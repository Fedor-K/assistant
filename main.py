import asyncio
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

load_dotenv()

from db import init_db, get_unprocessed_messages, get_all_messages, mark_processed, cleanup_old_messages
from tg_reader import read_chats_today
from recap import generate_daily_recap, generate_structured_recap, generate_status_snapshot, generate_done_report, check_duplicates
from gdocs import append_recap, remove_old_recaps, overwrite_status_doc, read_recap_doc
from sheet_sync import sync_rows, get_existing_topics, get_done_tasks
from email_reader import read_emails_today, format_emails_for_recap
from docx_export import save_recap_docx

TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Dubai"))


async def daily_recap_job():
    """Read today's chats, generate recap, write to Google Doc."""
    print(f"\n[main] Starting daily recap at {datetime.now(TZ).isoformat()}")

    try:
        count = await read_chats_today()
        print(f"[main] Read {count} messages total")

        today = datetime.now(TZ).strftime("%Y-%m-%d")
        new_messages = await get_unprocessed_messages(today)

        if not new_messages:
            print("[main] No new messages to recap")
            return

        date_header = datetime.now(TZ).strftime("%d.%m.%Y")

        # Generate work report from completed tasks
        done_tasks = get_done_tasks()
        if done_tasks:
            report_text = generate_done_report(done_tasks)
            print(f"[main] Done report generated ({len(report_text)} chars)")

            docx_path = save_recap_docx(report_text, date_header)
            print(f"[main] DOCX saved: {docx_path}")

            status_doc_id = os.getenv("STATUS_DOC_ID", "")
            if status_doc_id:
                overwrite_status_doc(status_doc_id, report_text)
        else:
            print("[main] No completed tasks for report")

        # Read emails and merge with TG messages
        emails = read_emails_today()
        email_text = format_emails_for_recap(emails)

        # Merge: add email text as a virtual "chat"
        all_sources = dict(new_messages)
        if email_text:
            all_sources["Почта (Email)"] = [email_text]

        # Sync structured data to Google Sheet
        existing_topics = get_existing_topics()
        structured = generate_structured_recap(all_sources, existing_topics=existing_topics)
        if structured:
            # Check new items for duplicates
            structured = check_duplicates(structured, existing_topics)
            sync_rows(structured)
            print(f"[main] Sheet synced ({len(structured)} topics)")

        await mark_processed(today)

        # Cleanup SQLite — remove messages older than 35 days
        cutoff = (datetime.now(TZ) - timedelta(days=35)).strftime("%Y-%m-%d")
        await cleanup_old_messages(cutoff)

        print("[main] Daily recap done")

    except Exception as e:
        print(f"[main] Error in daily recap: {e}", file=sys.stderr)
        raise


async def weekly_status_job():
    """Generate weekly status snapshot from last 4 weeks of recaps."""
    print(f"\n[main] Starting weekly status at {datetime.now(TZ).isoformat()}")

    try:
        doc_id = os.getenv("RECAP_DOC_ID", "")
        status_doc_id = os.getenv("STATUS_DOC_ID", "")

        if not doc_id or not status_doc_id:
            print("[main] RECAP_DOC_ID or STATUS_DOC_ID not set, skipping status")
            return

        recaps_text = read_recap_doc(doc_id)

        if not recaps_text.strip():
            print("[main] Recap doc is empty, skipping status")
            return

        status_text = generate_status_snapshot(recaps_text)
        print(f"[main] Status snapshot generated ({len(status_text)} chars)")

        overwrite_status_doc(status_doc_id, status_text)
        print("[main] Weekly status done")

    except Exception as e:
        print(f"[main] Error in weekly status: {e}", file=sys.stderr)
        raise


async def sunday_combined_job():
    """On Sundays: daily recap first, then status snapshot."""
    await daily_recap_job()
    await weekly_status_job()


async def main():
    await init_db()
    print(f"[main] DB initialized")

    # One-off run mode
    if len(sys.argv) > 1:
        if sys.argv[1] == "recap":
            await daily_recap_job()
            return
        elif sys.argv[1] == "status":
            await weekly_status_job()
            return
        elif sys.argv[1] == "both":
            await sunday_combined_job()
            return
        else:
            print(f"Unknown command: {sys.argv[1]}")
            print("Usage: python main.py [recap|status|both]")
            return

    recap_hour = int(os.getenv("RECAP_HOUR", "19"))
    recap_minute = int(os.getenv("RECAP_MINUTE", "0"))

    scheduler = AsyncIOScheduler(timezone=TZ)

    # Daily recap at 19:00 (Mon-Sat)
    scheduler.add_job(
        daily_recap_job,
        "cron",
        hour=recap_hour,
        minute=recap_minute,
        day_of_week="mon-sat",
        id="daily_recap",
    )

    # Sunday: recap at 18:00, then status
    scheduler.add_job(
        sunday_combined_job,
        "cron",
        hour=18,
        minute=0,
        day_of_week="sun",
        id="sunday_combined",
    )

    scheduler.start()
    print(f"[main] Scheduler started. Daily recap at {recap_hour:02d}:{recap_minute:02d}, Sunday status at 18:00")
    print(f"[main] Timezone: {TZ}")

    # Keep running
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        print("[main] Shutdown")


if __name__ == "__main__":
    asyncio.run(main())
