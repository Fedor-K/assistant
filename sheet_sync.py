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
HEADER = ["Контакт", "Роль", "Готово", "Тема", "Статус", "Суть", "Итог", "Следующий шаг", "Ответственный", "Создано", "Обновлено", "Контекст"]


def _get_sheets():
    creds = service_account.Credentials.from_service_account_file(
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "sa.json"),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return build("sheets", "v4", credentials=creds)


def _read_existing(sheets) -> list[list[str]]:
    result = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range="Все данные!A:L"
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
    # Sheet layout: 0=Контакт, 1=Роль, 2=Готово, 3=Тема, 4=Статус, 5=Суть, 6=Итог, 7=Следующий шаг, 8=Ответственный, 9=Создано, 10=Обновлено, 11=Контекст
    existing_map = {}
    for i, row in enumerate(existing):
        if len(row) >= 4:
            key = (row[0].strip(), row[3].strip())
            existing_map[key] = (i, row)

    updated_rows = list(existing)
    new_additions = []

    for nr in new_rows:
        key = (nr["contact"].strip(), nr["topic"].strip())
        # Data fields (without Готово, dates, context)
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

        if key in existing_map:
            idx, old_row = existing_map[key]
            pad = old_row + [""] * (12 - len(old_row))
            created = pad[9] or today
            done = pad[2] or "FALSE"
            old_context = pad[11]

            # Append new context to existing (keep history)
            if context and context not in old_context:
                combined_context = f"{old_context}\n---\n{context}" if old_context else context
            else:
                combined_context = old_context

            # Extract old data fields (skip Готово at index 2)
            old_data = [pad[0], pad[1], pad[3], pad[4], pad[5], pad[6], pad[7], pad[8]]
            if data_fields != old_data:
                updated_rows[idx] = [data_fields[0], data_fields[1], done] + data_fields[2:] + [created, today, combined_context]
            elif context and context not in old_context:
                updated_rows[idx] = [pad[0], pad[1], done, pad[3], pad[4], pad[5], pad[6], pad[7], pad[8], created, today, combined_context]
            # else: no change, keep as is
        else:
            new_additions.append([data_fields[0], data_fields[1], "FALSE"] + data_fields[2:] + [today, today, context])

    all_rows = updated_rows + new_additions
    values = [HEADER] + all_rows

    # Clear and rewrite
    sheets.spreadsheets().values().clear(
        spreadsheetId=SHEET_ID, range="Все данные!A:L"
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
