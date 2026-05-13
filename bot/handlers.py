import re
from datetime import date, datetime, timedelta
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from app.config import settings
from app.db import SessionLocal
from app.models import RawInput, RawInputKind, Session
from app.services.claude_extractor import ExtractionError, extract_image, extract_text_sessions
from app.services.claude_summary import generate_weekly_summary
from app.services.persistence import create_session_from_payload
from bot.confirm_flow import PENDING, confirmation_keyboard, render_summary


def _authorized(update: Update) -> bool:
    return bool(
        update.effective_user
        and settings.telegram_allowed_user_id
        and update.effective_user.id == settings.telegram_allowed_user_id
    )


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await update.effective_message.reply_text(
        "Send a workout as text or a screenshot. I’ll parse it, show a confirmation, then save it.\n"
        "Commands: /undo deletes the last session, /summary generates a weekly review."
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return

    text = update.effective_message.text or ""
    db = SessionLocal()
    raw_input = RawInput(
        telegram_msg_id=update.effective_message.message_id,
        kind=RawInputKind.text,
        raw_text=text,
        claude_model=settings.claude_model,
    )
    db.add(raw_input)
    db.commit()
    db.refresh(raw_input)
    db.close()

    parsing_message = await update.effective_message.reply_text("Parsing…")
    try:
        parsed = await extract_text_sessions(text)
    except ExtractionError as exc:
        await parsing_message.edit_text(str(exc)[:3500])
        return

    PENDING[parsing_message.message_id] = parsed
    await parsing_message.edit_text(render_summary(parsed), reply_markup=confirmation_keyboard())


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return

    photo = update.effective_message.photo[-1]
    telegram_file = await context.bot.get_file(photo.file_id)
    upload_dir = Path("data/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    image_path = upload_dir / f"{update.effective_message.message_id}_{photo.file_unique_id}.jpg"
    await telegram_file.download_to_drive(image_path)

    db = SessionLocal()
    raw_input = RawInput(
        telegram_msg_id=update.effective_message.message_id,
        kind=RawInputKind.image,
        image_path=str(image_path),
        claude_model=settings.claude_model,
    )
    db.add(raw_input)
    db.commit()
    db.close()

    parsing_message = await update.effective_message.reply_text("Parsing screenshot…")
    try:
        parsed = await extract_image(image_path, "image/jpeg")
    except ExtractionError as exc:
        await parsing_message.edit_text(str(exc)[:3500])
        return

    PENDING[parsing_message.message_id] = [parsed]
    await parsing_message.edit_text(render_summary(parsed), reply_markup=confirmation_keyboard())


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    query = update.callback_query
    await query.answer()

    parsed_sessions = PENDING.pop(query.message.message_id, None)
    if query.data == "discard":
        await query.edit_message_text("Discarded.")
        return
    if query.data == "edit":
        await query.edit_message_text("Send a corrected workout message and I’ll parse that instead.")
        return
    if query.data != "save" or not parsed_sessions:
        await query.edit_message_text("Nothing pending to save.")
        return

    db = SessionLocal()
    try:
        saved = []
        prs = []
        for parsed in parsed_sessions:
            session, session_prs = create_session_from_payload(db, parsed)
            saved.append(session)
            prs.extend(session_prs)
        db.commit()
        for session in saved:
            db.refresh(session)
    except Exception as exc:
        db.rollback()
        await query.edit_message_text(f"Save failed: {exc}")
        raise
    finally:
        db.close()

    pr_line = f"\nPR: {prs[0]}" if prs else ""
    if len(saved) > 1:
        total_power = sum(float(session.total_power or 0) for session in saved)
        await query.edit_message_text(f"Saved {len(saved)} sessions.\nCombined Total Power: {total_power:,.0f}{pr_line}")
        return
    session = saved[0]
    await query.edit_message_text(
        f"Saved.\nTotal Power: {float(session.total_power or 0):,.0f} "
        f"(Index {float(session.index_vs_median or 0):.0f}){pr_line}"
    )


async def handle_undo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    db = SessionLocal()
    try:
        session = db.query(Session).filter(Session.deleted_at.is_(None)).order_by(Session.started_at.desc()).first()
        if not session:
            await update.effective_message.reply_text("No session to undo.")
            return
        session.deleted_at = datetime.now()
        db.commit()
        await update.effective_message.reply_text(f"Undid session {session.id}. Run recompute_all if needed.")
    finally:
        db.close()


async def handle_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    db = SessionLocal()
    try:
        end = date.today() + timedelta(days=1)
        start = end - timedelta(days=7)
        summary = await generate_weekly_summary(db, start, end)
        await update.effective_message.reply_text(_telegram_markdown(summary.body_md), parse_mode="Markdown")
    finally:
        db.close()


def _telegram_markdown(text: str) -> str:
    text = text.replace("_", "\\_")
    return re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
