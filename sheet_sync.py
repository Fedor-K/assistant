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
HEADER = ["Контакт", "Роль", "Тема", "Статус", "Суть", "Итог", "Следующий шаг", "Ответственный", "Создано", "Обновлено", "Готово"]


def _get_sheets():
    creds = service_account.Credentials.from_service_account_file(
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "sa.json"),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return build("sheets", "v4", credentials=creds)


def _read_existing(sheets) -> list[list[str]]:
    result = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range="Все данные!A:K"
    ).execute()
    rows = result.get("values", [])
    return rows[1:] if rows else []  # skip header


def sync_rows(new_rows: list[dict]):
    """
    new_rows: list of dicts with keys matching HEADER (without dates).
    Compares by (contact, topic). Updates existing, adds new.
    """
    sheets = _get_sheets()
    today = datetime.now(TZ).strftime("%d.%m.%Y")

    existing = _read_existing(sheets)

    # Index existing by (contact, topic)
    existing_map = {}
    for i, row in enumerate(existing):
        if len(row) >= 3:
            key = (row[0].strip(), row[2].strip())
            existing_map[key] = (i, row)

    updated_rows = list(existing)
    new_additions = []

    for nr in new_rows:
        key = (nr["contact"].strip(), nr["topic"].strip())
        row_data = [
            nr.get("contact", ""),
            nr.get("role", ""),
            nr.get("topic", ""),
            nr.get("status", ""),
            nr.get("summary", ""),
            nr.get("result", ""),
            nr.get("next_step", ""),
            nr.get("responsible", ""),
        ]

        if key in existing_map:
            idx, old_row = existing_map[key]
            created = old_row[8] if len(old_row) > 8 else today
            done = old_row[10] if len(old_row) > 10 else "FALSE"

            # Check if anything changed
            old_comparable = old_row[:8] if len(old_row) >= 8 else old_row + [""] * (8 - len(old_row))
            if row_data != old_comparable:
                updated_rows[idx] = row_data + [created, today, done]
            # else: no change, keep as is (preserves done flag)
        else:
            new_additions.append(row_data + [today, today, "FALSE"])

    all_rows = updated_rows + new_additions
    values = [HEADER] + all_rows

    # Clear and rewrite
    sheets.spreadsheets().values().clear(
        spreadsheetId=SHEET_ID, range="Все данные!A:K"
    ).execute()
    sheets.spreadsheets().values().update(
        spreadsheetId=SHEET_ID, range="Все данные!A1", valueInputOption="RAW",
        body={"values": values},
    ).execute()

    # Rebuild dashboard
    _rebuild_dashboard(sheets, all_rows)
    _rebuild_by_contact(sheets, all_rows)

    print(f"[sheet_sync] Updated: {len(existing)} existing, +{len(new_additions)} new")


def _rebuild_dashboard(sheets, all_rows):
    """Rebuild dashboard. Reads existing checkboxes from dashboard first to preserve them."""
    # Read existing dashboard to preserve checkbox state
    existing_dash = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range="Дашборд!A:H"
    ).execute().get("values", [])

    # Map existing dashboard checkboxes by (contact, topic)
    done_map = {}
    for row in existing_dash[1:]:  # skip header
        if len(row) >= 2:
            key = (row[0].strip(), row[1].strip())
            done_map[key] = row[7] if len(row) > 7 else "FALSE"

    header = ["Контакт", "Тема", "Статус", "Что нужно сделать", "Ответственный", "Создано", "Обновлено", "Готово"]
    rows = []
    for r in all_rows:
        r_padded = r + [""] * (11 - len(r))
        status = r_padded[3]
        if status in ("В процессе", "Открыто") or r_padded[6].strip():
            key = (r_padded[0].strip(), r_padded[2].strip())
            done = done_map.get(key, "FALSE")
            rows.append([r_padded[0], r_padded[2], r_padded[3],
                        r_padded[6] if r_padded[6].strip() else r_padded[5],
                        r_padded[7], r_padded[8], r_padded[9], done])

    # Sort: unchecked first, then by status
    def sort_key(x):
        is_done = 1 if x[7] == "TRUE" else 0
        status_order = 0 if x[2] == "Открыто" else (1 if x[2] == "В процессе" else 2)
        return (is_done, status_order)
    rows.sort(key=sort_key)

    sheets.spreadsheets().values().clear(spreadsheetId=SHEET_ID, range="Дашборд!A:Z").execute()
    sheets.spreadsheets().values().update(
        spreadsheetId=SHEET_ID, range="Дашборд!A1", valueInputOption="RAW",
        body={"values": [header] + rows},
    ).execute()


def _rebuild_by_contact(sheets, all_rows):
    header = ["Контакт", "Роль", "Тема", "Статус", "Суть", "Итог", "Создано", "Обновлено"]
    sorted_rows = sorted(all_rows, key=lambda r: r[0] if r else "")
    contact_rows = []
    current = None
    for r in sorted_rows:
        r_padded = r + [""] * (10 - len(r))
        if r_padded[0] != current:
            if current is not None:
                contact_rows.append([""] * 8)
            current = r_padded[0]
        contact_rows.append([r_padded[0], r_padded[1], r_padded[2], r_padded[3],
                            r_padded[4], r_padded[5], r_padded[8], r_padded[9]])

    sheets.spreadsheets().values().clear(spreadsheetId=SHEET_ID, range="По контактам!A:Z").execute()
    sheets.spreadsheets().values().update(
        spreadsheetId=SHEET_ID, range="По контактам!A1", valueInputOption="RAW",
        body={"values": [header] + contact_rows},
    ).execute()
