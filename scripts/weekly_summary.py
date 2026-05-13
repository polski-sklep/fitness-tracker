import asyncio
from datetime import date, timedelta

from app.db import SessionLocal
from app.services.claude_summary import generate_weekly_summary


async def main() -> None:
    db = SessionLocal()
    try:
        end = date.today() + timedelta(days=1)
        start = end - timedelta(days=7)
        summary = await generate_weekly_summary(db, start, end)
        print(summary.body_md)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())

