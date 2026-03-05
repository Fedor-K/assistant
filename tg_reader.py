import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telethon import TelegramClient
from telethon.tl.types import User, Channel, Chat

from db import save_messages

TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Dubai"))


def _get_client() -> TelegramClient:
    return TelegramClient(
        os.getenv("TG_SESSION_NAME", "theact_session"),
        int(os.getenv("TG_API_ID", "0")),
        os.getenv("TG_API_HASH", ""),
    )


def _sender_name(sender) -> str:
    if sender is None:
        return "Unknown"
    if isinstance(sender, User):
        parts = [sender.first_name or "", sender.last_name or ""]
        name = " ".join(p for p in parts if p)
        return name or sender.username or "Unknown"
    if isinstance(sender, (Channel, Chat)):
        return sender.title or "Channel"
    return "Unknown"


async def read_chats_today() -> int:
    """Read today's messages from all configured chats. Returns total message count."""
    chat_ids_raw = os.getenv("TG_CHAT_IDS", "")
    if not chat_ids_raw:
        print("[tg_reader] TG_CHAT_IDS is empty, nothing to read")
        return 0

    chat_ids = [int(cid.strip()) for cid in chat_ids_raw.split(",") if cid.strip()]
    now = datetime.now(TZ)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    date_str = now.strftime("%Y-%m-%d")

    total = 0
    client = _get_client()

    async with client:
        for chat_id in chat_ids:
            try:
                entity = await client.get_entity(chat_id)
                chat_title = getattr(entity, "title", None) or str(chat_id)

                msgs = []
                async for msg in client.iter_messages(
                    entity,
                    offset_date=now + timedelta(seconds=1),
                    reverse=True,
                ):
                    if msg.date.astimezone(TZ) < start_of_day:
                        continue
                    if msg.date.astimezone(TZ) > now:
                        break

                    # Skip empty, service, and bot messages
                    if not msg.text:
                        continue
                    if msg.action is not None:
                        continue

                    sender = await msg.get_sender()
                    if sender and isinstance(sender, User) and sender.bot:
                        continue

                    msgs.append(
                        {
                            "sender_name": _sender_name(sender),
                            "text": msg.text,
                            "time": msg.date.astimezone(TZ).strftime("%H:%M"),
                            "date": date_str,
                        }
                    )

                if msgs:
                    await save_messages(chat_id, chat_title, msgs)
                    total += len(msgs)
                    print(f"[tg_reader] {chat_title}: {len(msgs)} messages")
                else:
                    print(f"[tg_reader] {chat_title}: no messages today")

            except Exception as e:
                print(f"[tg_reader] Error reading chat {chat_id}: {e}")

    return total
