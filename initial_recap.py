"""One-time: read full history from all chats and generate comprehensive recap."""
import asyncio
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.types import User, Channel, Chat
import anthropic

load_dotenv()

TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Dubai"))


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


async def read_all_chats():
    chat_ids_raw = os.getenv("TG_CHAT_IDS", "")
    chat_ids = [int(cid.strip()) for cid in chat_ids_raw.split(",") if cid.strip()]

    client = TelegramClient(
        os.getenv("TG_SESSION_NAME", "theact_session"),
        int(os.getenv("TG_API_ID", "0")),
        os.getenv("TG_API_HASH", ""),
    )

    all_chats = {}

    async with client:
        for chat_id in chat_ids:
            try:
                entity = await client.get_entity(chat_id)
                chat_title = getattr(entity, "title", None) or _sender_name(entity)
                print(f"Reading: {chat_title}...", end=" ", flush=True)

                msgs = []
                async for msg in client.iter_messages(entity, limit=None):
                    if not msg.text:
                        continue
                    if msg.action is not None:
                        continue
                    sender = await msg.get_sender()
                    if sender and isinstance(sender, User) and sender.bot:
                        continue

                    date_str = msg.date.astimezone(TZ).strftime("%d.%m.%Y")
                    time_str = msg.date.astimezone(TZ).strftime("%H:%M")
                    name = _sender_name(sender)
                    msgs.append(f"[{date_str} {time_str}] {name}: {msg.text}")

                msgs.reverse()
                if msgs:
                    all_chats[chat_title] = msgs
                print(f"{len(msgs)} messages")

            except Exception as e:
                print(f"Error {chat_id}: {e}")

    return all_chats


def generate_full_recap(all_chats: dict[str, list[str]]) -> str:
    """Generate recap per chat, then combine."""
    client = anthropic.Anthropic()
    all_recaps = []

    SYSTEM = (
        "Ты помощник директора по международному развитию beauty-бренда The Act Perfumes (Dubai). "
        "Рынки: MENA, Африка, США (в разработке). "
        "Твоя задача — делать деловые рекапы переписок. Только факты, конкретика, без воды."
    )

    PROMPT_TEMPLATE = """Проанализируй полную переписку с контактом и составь структурированный рекап.

Для каждой темы/вопроса, который обсуждался, укажи:

**👤 Контакт:** имя и роль (если понятна из контекста)

**📌 Темы и решения:**
Для каждой темы:
- Тема
- Статус: ✅ Решено / ⏳ В процессе / ❓ Открыто
- Суть: что обсуждали
- Итог: к чему пришли

**⚠️ Открытые вопросы** (что требует действий)

**➡️ Следующие шаги** (конкретно кто и что должен сделать)

Если переписка формальная или пустая — напиши одной строкой.

Переписка:
=== {chat_title} ===
{messages}"""

    for chat_title, msgs in all_chats.items():
        print(f"Generating recap for: {chat_title}...", flush=True)
        messages_text = "\n".join(msgs)

        # Truncate if too long (Claude context limit)
        if len(messages_text) > 80000:
            messages_text = messages_text[-80000:]

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=SYSTEM,
            messages=[{"role": "user", "content": PROMPT_TEMPLATE.format(
                chat_title=chat_title, messages=messages_text
            )}],
        )
        recap = response.content[0].text
        all_recaps.append(recap)
        print(f"  Done ({len(recap)} chars)")

    return "\n\n---\n\n".join(all_recaps)


def write_to_doc(text: str):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    sa_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "sa.json")
    creds = service_account.Credentials.from_service_account_file(
        sa_path, scopes=["https://www.googleapis.com/auth/documents"]
    )
    docs = build("docs", "v1", credentials=creds)
    doc_id = os.getenv("RECAP_DOC_ID")

    # Get current doc length
    doc = docs.documents().get(documentId=doc_id).execute()
    end_index = doc["body"]["content"][-1]["endIndex"]

    # Clear existing content
    requests = []
    if end_index > 2:
        requests.append({"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end_index - 1}}})

    today = datetime.now(TZ).strftime("%d.%m.%Y")
    full_text = f"ПОЛНЫЙ РЕКАП ВСЕХ ПЕРЕПИСОК (по состоянию на {today})\n\n{text}\n"
    requests.append({"insertText": {"location": {"index": 1}, "text": full_text}})

    docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
    print(f"\nWritten to Google Doc: {doc_id}")


async def main():
    print("=== Reading all chats ===\n")
    all_chats = await read_all_chats()

    print(f"\n=== Generating recaps for {len(all_chats)} chats ===\n")
    full_recap = generate_full_recap(all_chats)

    print(f"\n=== Writing to Google Doc ===")
    write_to_doc(full_recap)

    # Also save locally
    with open("full_recap.txt", "w") as f:
        f.write(full_recap)
    print("Also saved to full_recap.txt")


asyncio.run(main())
