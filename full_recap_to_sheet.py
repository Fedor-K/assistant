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
  "responsible": "кто отвечает",
  "first_date": "дата первого сообщения по этой теме в формате DD.MM.YYYY",
  "last_date": "дата последнего сообщения по этой теме в формате DD.MM.YYYY"
}}

Если переписка формальная — верни 1 элемент с topic "Общение" и кратким summary.

Переписка:
=== {chat_title} ===
{messages_text}"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
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
            item.get("first_date", ""),
            item.get("last_date", ""),
        ])
    return rows


def write_to_existing_sheet(all_rows: list[list[str]]):
    creds = service_account.Credentials.from_service_account_file(
        "sa.json", scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    sheets = build("sheets", "v4", credentials=creds)
    sheet_id = os.getenv("SHEET_ID", "12WTHHM_0JXu1wJuLYM3M_-Sb3gZvJqxUSd51801Ulsc")
    today = datetime.now(TZ).strftime("%d.%m.%Y")

    header = ["Контакт", "Роль", "Готово", "Тема", "Статус", "Суть", "Итог", "Следующий шаг", "Ответственный", "Создано", "Обновлено"]

    final_rows = []
    for r in all_rows:
        # r[0:8] = contact, role, topic, status, summary, result, next_step, responsible, r[8] = first_date, r[9] = last_date
        padded = r + [""] * (10 - len(r)) if len(r) < 10 else r[:10]
        first_date = padded[8] or today
        last_date = padded[9] or today
        # Insert Готово at index 2 (after Роль)
        final_rows.append([padded[0], padded[1], "FALSE", padded[2], padded[3], padded[4], padded[5], padded[6], padded[7], first_date, last_date])

    values = [header] + final_rows

    # Clear ALL tabs
    for tab in ["Все данные", "Дашборд", "По контактам"]:
        sheets.spreadsheets().values().clear(spreadsheetId=sheet_id, range=f"{tab}!A:Z").execute()

    # Write Все данные
    sheets.spreadsheets().values().update(
        spreadsheetId=sheet_id, range="Все данные!A1", valueInputOption="RAW",
        body={"values": values},
    ).execute()

    # Дашборд — layout: Контакт, Тема, Готово, Статус, Что нужно сделать, Ответственный, Создано, Обновлено
    # final_rows layout: 0=Контакт, 1=Роль, 2=Готово, 3=Тема, 4=Статус, 5=Суть, 6=Итог, 7=Следующий шаг, 8=Ответственный, 9=Создано, 10=Обновлено
    dash_header = ["Контакт", "Тема", "Готово", "Статус", "Что нужно сделать", "Ответственный", "Создано", "Обновлено"]
    dash_rows = []
    for r in final_rows:
        if r[4] in ("В процессе", "Открыто") or r[7].strip():
            dash_rows.append([r[0], r[3], r[2], r[4],
                            r[7] if r[7].strip() else r[5],
                            r[8], r[9], r[10]])
    dash_rows.sort(key=lambda x: 0 if x[3] == "Открыто" else (1 if x[3] == "В процессе" else 2))

    sheets.spreadsheets().values().update(
        spreadsheetId=sheet_id, range="Дашборд!A1", valueInputOption="RAW",
        body={"values": [dash_header] + dash_rows},
    ).execute()

    # По контактам
    # final_rows layout: 0=Контакт, 1=Роль, 2=Готово, 3=Тема, 4=Статус, 5=Суть, 6=Итог, 9=Создано, 10=Обновлено
    ct_header = ["Контакт", "Роль", "Тема", "Статус", "Суть", "Итог", "Создано", "Обновлено"]
    sorted_rows = sorted(final_rows, key=lambda r: r[0])
    ct_rows = []
    current = None
    for r in sorted_rows:
        if r[0] != current:
            if current is not None:
                ct_rows.append([""] * 8)
            current = r[0]
        ct_rows.append([r[0], r[1], r[3], r[4], r[5], r[6], r[9], r[10]])

    sheets.spreadsheets().values().update(
        spreadsheetId=sheet_id, range="По контактам!A1", valueInputOption="RAW",
        body={"values": [ct_header] + ct_rows},
    ).execute()

    # Formatting
    sp = sheets.spreadsheets().get(spreadsheetId=sheet_id).execute()
    sid = {s["properties"]["title"]: s["properties"]["sheetId"] for s in sp["sheets"]}

    # Remove old conditional formats
    fmt_del = []
    for s in sp["sheets"]:
        for _ in s.get("conditionalFormats", []):
            fmt_del.append({"deleteConditionalFormatRule": {"sheetId": s["properties"]["sheetId"], "index": 0}})
    if fmt_del:
        sheets.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": fmt_del}).execute()

    dash_rows_count = len(dash_rows) + 1
    all_rows_count = len(final_rows) + 1

    fmt = [
        # Bold headers + freeze (Все данные now has 11 cols with Готово at C)
        *[item for tab, ncols in [("Дашборд", 8), ("Все данные", 11), ("По контактам", 8)] for item in [
            {"repeatCell": {
                "range": {"sheetId": sid[tab], "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": ncols},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.85, "green": 0.85, "blue": 0.85}}},
                "fields": "userEnteredFormat(textFormat,backgroundColor)",
            }},
            {"updateSheetProperties": {
                "properties": {"sheetId": sid[tab], "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }},
        ]],
        # Дашборд checkboxes col C (2)
        {"setDataValidation": {
            "range": {"sheetId": sid["Дашборд"], "startRowIndex": 1, "endRowIndex": dash_rows_count, "startColumnIndex": 2, "endColumnIndex": 3},
            "rule": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}
        }},
        # Все данные checkboxes col C (2)
        {"setDataValidation": {
            "range": {"sheetId": sid["Все данные"], "startRowIndex": 1, "endRowIndex": all_rows_count, "startColumnIndex": 2, "endColumnIndex": 3},
            "rule": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}
        }},
        # Дашборд strikethrough on C
        {"addConditionalFormatRule": {"rule": {
            "ranges": [{"sheetId": sid["Дашборд"], "startRowIndex": 1, "endRowIndex": dash_rows_count, "startColumnIndex": 0, "endColumnIndex": 8}],
            "booleanRule": {
                "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": "=$C2=TRUE"}]},
                "format": {"textFormat": {"strikethrough": True, "foregroundColor": {"red": 0.6, "green": 0.6, "blue": 0.6}}}
            }
        }, "index": 0}},
        # Все данные strikethrough on C
        {"addConditionalFormatRule": {"rule": {
            "ranges": [{"sheetId": sid["Все данные"], "startRowIndex": 1, "endRowIndex": all_rows_count, "startColumnIndex": 0, "endColumnIndex": 11}],
            "booleanRule": {
                "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": "=$C2=TRUE"}]},
                "format": {"textFormat": {"strikethrough": True, "foregroundColor": {"red": 0.6, "green": 0.6, "blue": 0.6}}}
            }
        }, "index": 0}},
        # Status colors Дашборд col D (3) — Статус
        {"addConditionalFormatRule": {"rule": {
            "ranges": [{"sheetId": sid["Дашборд"], "startRowIndex": 1, "startColumnIndex": 3, "endColumnIndex": 4}],
            "booleanRule": {"condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": "Открыто"}]}, "format": {"backgroundColor": {"red": 1, "green": 0.8, "blue": 0.8}}}
        }, "index": 1}},
        {"addConditionalFormatRule": {"rule": {
            "ranges": [{"sheetId": sid["Дашборд"], "startRowIndex": 1, "startColumnIndex": 3, "endColumnIndex": 4}],
            "booleanRule": {"condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": "В процессе"}]}, "format": {"backgroundColor": {"red": 1, "green": 0.95, "blue": 0.7}}}
        }, "index": 2}},
        {"addConditionalFormatRule": {"rule": {
            "ranges": [{"sheetId": sid["Дашборд"], "startRowIndex": 1, "startColumnIndex": 3, "endColumnIndex": 4}],
            "booleanRule": {"condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": "Решено"}]}, "format": {"backgroundColor": {"red": 0.8, "green": 1, "blue": 0.8}}}
        }, "index": 3}},
    ]

    sheets.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": fmt}).execute()
    print(f"Written {len(final_rows)} rows with formatting")


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
    write_to_existing_sheet(all_rows)


asyncio.run(main())
