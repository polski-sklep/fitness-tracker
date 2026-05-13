import logging

from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from app.config import settings
from bot.handlers import handle_callback, handle_help, handle_summary, handle_text, handle_undo, handle_photo

logger = logging.getLogger(__name__)


async def error_handler(update, context) -> None:
    logger.exception("Bot handler error", exc_info=context.error)
    if update and update.effective_message:
        await update.effective_message.reply_text(
            f"Internal error: {type(context.error).__name__}: {str(context.error)[:200]}"
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", handle_help))
    application.add_handler(CommandHandler("help", handle_help))
    application.add_handler(CommandHandler("undo", handle_undo))
    application.add_handler(CommandHandler("summary", handle_summary))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_error_handler(error_handler)
    application.run_polling()


if __name__ == "__main__":
    main()
