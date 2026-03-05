"""Read all chats, generate structured recaps, write to Google Sheet."""
import asyncio
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.types import User, Channel, Chat
import anthropic
from google.oauth2 import service_account
from googleapiclient.discovery import build

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


async def read_all_chats() -> dict[str, list[str]]:
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
                    if not msg.text or msg.action is not None:
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
                print(f"{len(msgs)} msgs")
            except Exception as e:
                print(f"Error {chat_id}: {e}")

    return all_chats


def generate_structured_recap(chat_title: str, messages: list[str]) -> list[list[str]]:
    """Generate recap as structured rows for the sheet."""
    messages_text = "\n".join(messages)
    if len(messages_text) > 80000:
        messages_text = messages_text[-80000:]

    client = anthropic.Anthropic()

    SYSTEM = (
        "Ты помощник директора по международному развитию beauty-бренда The Act Perfumes (Dubai). "
        "Отвечай ТОЛЬКО валидным JSON массивом, без markdown, без ```json, без пояснений."
    )

    PROMPT = f"""Проанализируй переписку и верни JSON массив тем.

Каждая тема — объект:
{{
  "contact": "имя контакта",
  "role": "роль (если понятна)",
  "topic": "название темы",
  "status": "Решено / В процессе / Открыто",
  "summary": "суть обсуждения (1-2 предложения)",
  "result": "к чему пришли",
  "next_step": "что нужно сделать",
  "responsible": "кто отвечает"
}}

Если переписка формальная — верни 1 элемент с topic "Общение" и кратким summary.

Переписка:
=== {chat_title} ===
{messages_text}"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=SYSTEM,
        messages=[{"role": "user", "content": PROMPT}],
    )

    text = response.content[0].text.strip()
    # Clean up potential markdown wrapping
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        items = json.loads(text)
    except json.JSONDecodeError:
        print(f"  JSON parse error for {chat_title}, raw: {text[:200]}")
        items = [{"contact": chat_title, "role": "?", "topic": "Ошибка парсинга",
                  "status": "?", "summary": text[:200], "result": "", "next_step": "", "responsible": ""}]

    rows = []
    for item in items:
        rows.append([
            item.get("contact", ""),
            item.get("role", ""),
            item.get("topic", ""),
            item.get("status", ""),
            item.get("summary", ""),
            item.get("result", ""),
            item.get("next_step", ""),
            item.get("responsible", ""),
        ])
    return rows


def create_sheet_and_write(all_rows: list[list[str]]) -> str:
    creds = service_account.Credentials.from_service_account_file(
        "sa.json", scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
    )
    sheets = build("sheets", "v4", credentials=creds)
    drive = build("drive", "v3", credentials=creds)

    today = datetime.now(TZ).strftime("%d.%m.%Y")

    # Create spreadsheet
    spreadsheet = sheets.spreadsheets().create(body={
        "properties": {"title": f"The Act — Рекап переписок ({today})"},
        "sheets": [{"properties": {"title": "Рекап"}}],
    }).execute()
    sheet_id = spreadsheet["spreadsheetId"]
    print(f"Created sheet: {sheet_id}")

    # Share with user
    drive.permissions().create(
        fileId=sheet_id,
        body={"type": "anyone", "role": "writer"},
    ).execute()

    # Header
    header = ["Контакт", "Роль", "Тема", "Статус", "Суть", "Итог", "Следующий шаг", "Ответственный"]
    values = [header] + all_rows

    sheets.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range="Рекап!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()

    # Format header (bold, freeze)
    sheet_props_id = spreadsheet["sheets"][0]["properties"]["sheetId"]
    sheets.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": [
        {"repeatCell": {
            "range": {"sheetId": sheet_props_id, "startRowIndex": 0, "endRowIndex": 1},
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True},
                     "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9}}},
            "fields": "userEnteredFormat(textFormat,backgroundColor)",
        }},
        {"updateSheetProperties": {
            "properties": {"sheetId": sheet_props_id, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount",
        }},
        {"autoResizeDimensions": {
            "dimensions": {"sheetId": sheet_props_id, "dimension": "COLUMNS",
                          "startIndex": 0, "endIndex": 8},
        }},
    ]}).execute()

    print(f"Written {len(all_rows)} rows")
    return sheet_id


async def main():
    cache_file = "recap_rows_cache.json"

    # Try loading from cache first
    if os.path.exists(cache_file):
        print(f"=== Loading cached data from {cache_file} ===\n")
        with open(cache_file) as f:
            all_rows = json.load(f)
    else:
        print("=== Reading all chats ===\n")
        all_chats = await read_all_chats()

        print(f"\n=== Generating recaps for {len(all_chats)} chats ===\n")
        all_rows = []
        for chat_title, msgs in all_chats.items():
            print(f"Processing: {chat_title}...", flush=True)
            rows = generate_structured_recap(chat_title, msgs)
            all_rows.extend(rows)
            print(f"  {len(rows)} topics")

        # Cache results
        with open(cache_file, "w") as f:
            json.dump(all_rows, f, ensure_ascii=False)
        print(f"Cached {len(all_rows)} rows to {cache_file}")

    print(f"\n=== Writing to Google Sheet ({len(all_rows)} rows) ===\n")
    sheet_id = create_sheet_and_write(all_rows)
    print(f"\nhttps://docs.google.com/spreadsheets/d/{sheet_id}/edit")


asyncio.run(main())
