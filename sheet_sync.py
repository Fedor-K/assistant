"""Sync daily recaps to Google Sheet — update existing rows, add new ones."""
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build

load_dotenv()

TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Dubai"))
SHEET_ID = os.getenv("SHEET_ID", "12WTHHM_0JXu1wJuLYM3M_-Sb3gZvJqxUSd51801Ulsc")
HEADER = ["Контакт", "Роль", "Готово", "Тема", "Статус", "Суть", "Итог", "Следующий шаг", "Ответственный", "Создано", "Обновлено", "Контекст", "ID"]


def _get_sheets():
    creds = service_account.Credentials.from_service_account_file(
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "sa.json"),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return build("sheets", "v4", credentials=creds)


def _read_existing(sheets) -> list[list[str]]:
    result = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range="Все данные!A:M"
    ).execute()
    rows = result.get("values", [])
    return rows[1:] if rows else []  # skip header


def _next_id(existing: list[list[str]]) -> int:
    """Find max ID in existing rows and return next one."""
    max_id = 0
    for row in existing:
        pad = row + [""] * (13 - len(row))
        try:
            rid = int(pad[12])
            if rid > max_id:
                max_id = rid
        except (ValueError, IndexError):
            pass
    return max_id + 1


def _ensure_ids(rows: list[list[str]]) -> list[list[str]]:
    """Assign IDs to rows that don't have one (migration)."""
    next_id = _next_id(rows)
    result = []
    for row in rows:
        pad = row + [""] * (13 - len(row))
        if not pad[12]:
            pad[12] = str(next_id)
            next_id += 1
        result.append(pad[:13])
    return result


def get_existing_topics() -> list[dict]:
    """Read existing topics from sheet for prompt building (active + done)."""
    sheets = _get_sheets()
    existing = _read_existing(sheets)
    topics = []
    for row in existing:
        pad = row + [""] * (13 - len(row))
        topic_id = pad[12]
        contact = pad[0]
        topic = pad[3]
        if contact and topic:
            topics.append({
                "id": int(topic_id) if topic_id else None,
                "contact": contact,
                "topic": topic,
            })

    # Also read completed topics so Claude doesn't recreate them
    try:
        result = sheets.spreadsheets().values().get(
            spreadsheetId=SHEET_ID, range="Завершённые!A:L"
        ).execute()
        done_rows = result.get("values", [])[1:]  # skip header
        for row in done_rows:
            pad = row + [""] * (12 - len(row))
            topic_id = pad[11]
            contact = pad[0]
            topic = pad[2]  # done tab: col C = Тема
            if contact and topic and topic_id:
                topics.append({
                    "id": int(topic_id),
                    "contact": contact,
                    "topic": topic,
                })
    except Exception:
        pass  # tab might not exist yet

    return topics


def sync_rows(new_rows: list[dict]):
    """
    new_rows: list of dicts with "id" (int or "new"), contact, topic, etc.
    Matches by ID. Updates existing, adds new with auto-incremented IDs.
    """
    sheets = _get_sheets()
    today = datetime.now(TZ).strftime("%d.%m.%Y")

    existing = _read_existing(sheets)
    # Migrate: assign IDs to old rows that don't have them
    existing = _ensure_ids(existing)

    # Sheet layout: 0=Контакт, 1=Роль, 2=Готово, 3=Тема, 4=Статус, 5=Суть, 6=Итог, 7=Следующий шаг, 8=Ответственный, 9=Создано, 10=Обновлено, 11=Контекст, 12=ID
    existing_by_id = {}
    for i, row in enumerate(existing):
        pad = row + [""] * (13 - len(row))
        try:
            row_id = int(pad[12])
            existing_by_id[row_id] = (i, pad)
        except (ValueError, IndexError):
            pass

    next_id = _next_id(existing)
    updated_rows = list(existing)
    new_additions = []

    for nr in new_rows:
        row_id = nr.get("id")
        data_fields = [
            nr.get("contact", ""),
            nr.get("role", ""),
            nr.get("topic", ""),
            nr.get("status", ""),
            nr.get("summary", ""),
            nr.get("result", ""),
            nr.get("next_step", ""),
            nr.get("responsible", ""),
        ]

        context = nr.get("context", "")
        if isinstance(context, list):
            context = "\n".join(str(c) for c in context)

        if isinstance(row_id, int) and row_id in existing_by_id:
            # Update existing row by ID
            idx, pad = existing_by_id[row_id]
            created = pad[9] or today
            done = pad[2] or "FALSE"
            old_context = pad[11]

            if context and context not in old_context:
                combined_context = f"{old_context}\n---\n{context}" if old_context else context
            else:
                combined_context = old_context

            updated_rows[idx] = [data_fields[0], data_fields[1], done] + data_fields[2:] + [created, today, combined_context, str(row_id)]
        else:
            # New row — assign next ID
            new_additions.append([data_fields[0], data_fields[1], "FALSE"] + data_fields[2:] + [today, today, context, str(next_id)])
            next_id += 1

    all_rows = updated_rows + new_additions

    # Separate done rows → "Завершённые" tab
    active_rows = []
    done_rows = []
    for r in all_rows:
        pad = r + [""] * (13 - len(r))
        if str(pad[2]).upper() == "TRUE":
            done_rows.append(pad)
        else:
            active_rows.append(pad)

    values = [HEADER] + active_rows

    # Clear and rewrite active data
    sheets.spreadsheets().values().clear(
        spreadsheetId=SHEET_ID, range="Все данные!A:M"
    ).execute()
    sheets.spreadsheets().values().update(
        spreadsheetId=SHEET_ID, range="Все данные!A1", valueInputOption="RAW",
        body={"values": values},
    ).execute()

    # Move done rows to "Завершённые"
    _move_to_done(sheets, done_rows)

    # Rebuild dashboard (only active rows)
    dash_done = _rebuild_dashboard(sheets, active_rows)
    _rebuild_by_contact(sheets, active_rows)

    # Apply real checkboxes
    all_data_done = [False] * len(active_rows)  # all active = unchecked
    _apply_checkbox_formatting(sheets, all_data_done, dash_done)

    print(f"[sheet_sync] Updated: {len(existing)} existing, +{len(new_additions)} new, {len(done_rows)} done")


def _ensure_tab_exists(sheets, tab_name: str):
    """Create tab if it doesn't exist."""
    sp = sheets.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    existing_tabs = [s["properties"]["title"] for s in sp["sheets"]]
    if tab_name not in existing_tabs:
        sheets.spreadsheets().batchUpdate(spreadsheetId=SHEET_ID, body={
            "requests": [{"addSheet": {"properties": {"title": tab_name}}}]
        }).execute()


DONE_HEADER = ["Контакт", "Роль", "Тема", "Статус", "Суть", "Итог", "Следующий шаг", "Ответственный", "Создано", "Обновлено", "Завершено", "ID"]


def _move_to_done(sheets, done_rows: list[list[str]]):
    """Append done rows to 'Завершённые' tab (no duplicates by ID)."""
    if not done_rows:
        return

    _ensure_tab_exists(sheets, "Завершённые")

    # Read existing done rows to avoid duplicates
    result = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range="Завершённые!A:L"
    ).execute()
    existing_done = result.get("values", [])

    # Collect existing IDs
    existing_ids = set()
    for row in existing_done[1:] if existing_done else []:
        pad = row + [""] * (12 - len(row))
        if pad[11]:
            existing_ids.add(pad[11])

    today = datetime.now(TZ).strftime("%d.%m.%Y")
    new_done = []
    for r in done_rows:
        pad = r + [""] * (13 - len(r))
        row_id = pad[12]
        if row_id in existing_ids:
            continue  # already in done tab
        # Format: contact, role, topic, status, summary, result, next_step, responsible, created, updated, done_date, id
        new_done.append([pad[0], pad[1], pad[3], pad[4], pad[5], pad[6], pad[7], pad[8], pad[9], pad[10], today, pad[12]])

    if not existing_done:
        # Write header + rows
        sheets.spreadsheets().values().update(
            spreadsheetId=SHEET_ID, range="Завершённые!A1", valueInputOption="RAW",
            body={"values": [DONE_HEADER] + new_done},
        ).execute()
    elif new_done:
        # Append rows
        sheets.spreadsheets().values().append(
            spreadsheetId=SHEET_ID, range="Завершённые!A1", valueInputOption="RAW",
            body={"values": new_done},
        ).execute()


def _apply_checkbox_formatting(sheets, all_data_done: list[bool], dash_done: list[bool]):
    """Apply real checkboxes to Готово column (C) in both tabs with correct True/False values."""
    sp = sheets.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    sid = {s["properties"]["title"]: s["properties"]["sheetId"] for s in sp["sheets"]}

    requests = []
    for tab, done_values in [("Все данные", all_data_done), ("Дашборд", dash_done)]:
        sheet_id = sid[tab]
        # Write each cell as boolean checkbox
        rows_data = []
        for val in done_values:
            rows_data.append({"values": [{"userEnteredValue": {"boolValue": val},
                                          "dataValidation": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}}]})
        if rows_data:
            requests.append({"updateCells": {
                "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": len(done_values) + 1,
                           "startColumnIndex": 2, "endColumnIndex": 3},
                "rows": rows_data,
                "fields": "userEnteredValue,dataValidation",
            }})

    if requests:
        sheets.spreadsheets().batchUpdate(spreadsheetId=SHEET_ID, body={"requests": requests}).execute()


def _rebuild_dashboard(sheets, all_rows) -> list[bool]:
    """Rebuild dashboard. Returns list of done booleans for checkbox formatting."""
    # Read existing dashboard to preserve checkbox state
    # Dashboard layout: Контакт(A), Тема(B), Готово(C), Статус(D), Что нужно сделать(E), Ответственный(F), Создано(G), Обновлено(H)
    existing_dash = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range="Дашборд!A:H"
    ).execute().get("values", [])

    # Map existing dashboard checkboxes by (contact, topic) — Готово is col C (index 2)
    done_map = {}
    for row in existing_dash[1:]:  # skip header
        if len(row) >= 2:
            key = (row[0].strip(), row[1].strip())
            done_map[key] = row[2] if len(row) > 2 else "FALSE"

    header = ["Контакт", "Тема", "Готово", "Статус", "Что нужно сделать", "Ответственный", "Создано", "Обновлено"]
    rows = []
    # all_rows layout: 0=Контакт, 1=Роль, 2=Готово, 3=Тема, 4=Статус, 5=Суть, 6=Итог, 7=Следующий шаг, 8=Ответственный, 9=Создано, 10=Обновлено
    for r in all_rows:
        r_padded = r + [""] * (12 - len(r))
        status = r_padded[4]
        if status in ("В процессе", "Открыто") or r_padded[7].strip():
            key = (r_padded[0].strip(), r_padded[3].strip())
            done = done_map.get(key, r_padded[2] or "FALSE")
            rows.append([r_padded[0], r_padded[3], done, r_padded[4],
                        r_padded[7] if r_padded[7].strip() else r_padded[5],
                        r_padded[8], r_padded[9], r_padded[10]])

    # Sort: unchecked first, then by status
    def sort_key(x):
        is_done = 1 if x[2] == "TRUE" else 0
        status_order = 0 if x[3] == "Открыто" else (1 if x[3] == "В процессе" else 2)
        return (is_done, status_order)
    rows.sort(key=sort_key)

    sheets.spreadsheets().values().clear(spreadsheetId=SHEET_ID, range="Дашборд!A:Z").execute()
    sheets.spreadsheets().values().update(
        spreadsheetId=SHEET_ID, range="Дашборд!A1", valueInputOption="RAW",
        body={"values": [header] + rows},
    ).execute()

    return [str(r[2]).upper() == "TRUE" for r in rows]


def _rebuild_by_contact(sheets, all_rows):
    header = ["Контакт", "Роль", "Тема", "Статус", "Суть", "Итог", "Создано", "Обновлено"]
    sorted_rows = sorted(all_rows, key=lambda r: r[0] if r else "")
    contact_rows = []
    current = None
    # all_rows layout: 0=Контакт, 1=Роль, 2=Готово, 3=Тема, 4=Статус, 5=Суть, 6=Итог, 9=Создано, 10=Обновлено
    for r in sorted_rows:
        r_padded = r + [""] * (12 - len(r))
        if r_padded[0] != current:
            if current is not None:
                contact_rows.append([""] * 8)
            current = r_padded[0]
        contact_rows.append([r_padded[0], r_padded[1], r_padded[3], r_padded[4],
                            r_padded[5], r_padded[6], r_padded[9], r_padded[10]])

    sheets.spreadsheets().values().clear(spreadsheetId=SHEET_ID, range="По контактам!A:Z").execute()
    sheets.spreadsheets().values().update(
        spreadsheetId=SHEET_ID, range="По контактам!A1", valueInputOption="RAW",
        body={"values": [header] + contact_rows},
    ).execute()
