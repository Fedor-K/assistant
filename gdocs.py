import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/documents"]
TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Dubai"))


def _get_service():
    sa_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "sa.json")
    creds = service_account.Credentials.from_service_account_file(sa_path, scopes=SCOPES)
    return build("docs", "v1", credentials=creds)


def _get_doc_text(service, doc_id: str) -> str:
    doc = service.documents().get(documentId=doc_id).execute()
    text = ""
    for element in doc.get("body", {}).get("content", []):
        if "paragraph" in element:
            for run in element["paragraph"].get("elements", []):
                text += run.get("textRun", {}).get("content", "")
    return text


def _get_doc_length(service, doc_id: str) -> int:
    doc = service.documents().get(documentId=doc_id).execute()
    content = doc.get("body", {}).get("content", [])
    if content:
        return content[-1]["endIndex"]
    return 1


def append_recap(doc_id: str, date_str: str, recap_text: str):
    """Append daily recap with date header to the recap doc."""
    service = _get_service()

    header = f"\n\n## {date_str}\n\n"
    full_text = header + recap_text + "\n"

    end_index = _get_doc_length(service, doc_id)

    requests = [
        {
            "insertText": {
                "location": {"index": end_index - 1},
                "text": full_text,
            }
        }
    ]

    service.documents().batchUpdate(
        documentId=doc_id, body={"requests": requests}
    ).execute()
    print(f"[gdocs] Appended recap for {date_str}")


def remove_old_recaps(doc_id: str, days: int = 28):
    """Remove recap sections older than `days` from the document."""
    service = _get_service()
    text = _get_doc_text(service, doc_id)

    cutoff = datetime.now(TZ) - timedelta(days=days)
    cutoff_str = cutoff.strftime("%d.%m.%Y")

    # Find all ## DD.MM.YYYY headers
    pattern = r"## (\d{2}\.\d{2}\.\d{4})"
    sections = list(re.finditer(pattern, text))

    if not sections:
        return

    # Find the earliest position of old content to remove
    remove_end = None
    for i, match in enumerate(sections):
        section_date_str = match.group(1)
        try:
            section_date = datetime.strptime(section_date_str, "%d.%m.%Y").replace(
                tzinfo=TZ
            )
        except ValueError:
            continue

        if section_date < cutoff:
            # This section is old — mark end as the start of next section or end of text
            if i + 1 < len(sections):
                remove_end = sections[i + 1].start()
            else:
                remove_end = len(text)

    if remove_end is None:
        return

    # Find the start of the first old section
    remove_start = None
    for match in sections:
        section_date_str = match.group(1)
        try:
            section_date = datetime.strptime(section_date_str, "%d.%m.%Y").replace(
                tzinfo=TZ
            )
        except ValueError:
            continue
        if section_date < cutoff:
            remove_start = match.start()
            break

    if remove_start is None or remove_start >= remove_end:
        return

    # Account for the document's structural offset (body starts at index 1)
    # We need to map text positions to document indices
    doc = service.documents().get(documentId=doc_id).execute()
    body_content = doc.get("body", {}).get("content", [])

    # Build a text-to-index mapping
    text_pos = 0
    doc_start_index = None
    doc_end_index = None

    for element in body_content:
        if "paragraph" in element:
            for run in element["paragraph"].get("elements", []):
                tr = run.get("textRun", {})
                content = tr.get("content", "")
                start_idx = run["startIndex"]

                for j, ch in enumerate(content):
                    if text_pos == remove_start and doc_start_index is None:
                        doc_start_index = start_idx + j
                    if text_pos == remove_end:
                        doc_end_index = start_idx + j
                    text_pos += 1

                if doc_end_index is None and text_pos >= remove_end:
                    doc_end_index = run["endIndex"]

    if doc_start_index is None or doc_end_index is None:
        return

    requests = [
        {
            "deleteContentRange": {
                "range": {
                    "startIndex": doc_start_index,
                    "endIndex": doc_end_index,
                }
            }
        }
    ]

    service.documents().batchUpdate(
        documentId=doc_id, body={"requests": requests}
    ).execute()
    print(f"[gdocs] Removed recaps older than {cutoff_str}")


def overwrite_status_doc(doc_id: str, status_text: str):
    """Replace the entire content of the status doc."""
    service = _get_service()
    end_index = _get_doc_length(service, doc_id)

    requests = []
    # Delete existing content (keep index 1 — required by API)
    if end_index > 2:
        requests.append(
            {
                "deleteContentRange": {
                    "range": {"startIndex": 1, "endIndex": end_index - 1}
                }
            }
        )

    requests.append(
        {"insertText": {"location": {"index": 1}, "text": status_text}}
    )

    service.documents().batchUpdate(
        documentId=doc_id, body={"requests": requests}
    ).execute()
    print("[gdocs] Status doc updated")


def read_recap_doc(doc_id: str) -> str:
    """Read the full text of the recap document (for weekly status generation)."""
    service = _get_service()
    return _get_doc_text(service, doc_id)
