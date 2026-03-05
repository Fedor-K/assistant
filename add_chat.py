"""Add or remove chats. Usage: python add_chat.py"""
import asyncio
import os
from dotenv import load_dotenv, set_key
from telethon import TelegramClient
from telethon.tl.types import User, Channel, Chat

load_dotenv()

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")


def _sender_name(entity) -> str:
    if isinstance(entity, User):
        parts = [entity.first_name or "", entity.last_name or ""]
        return " ".join(p for p in parts if p) or entity.username or "Unknown"
    if isinstance(entity, (Channel, Chat)):
        return entity.title or "Unknown"
    return "Unknown"


def _get_current_ids() -> list[int]:
    raw = os.getenv("TG_CHAT_IDS", "")
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def _save_ids(ids: list[int]):
    value = ",".join(str(i) for i in ids)
    set_key(ENV_PATH, "TG_CHAT_IDS", value)
    print(f"\nСохранено: {len(ids)} чатов")


async def main():
    current_ids = _get_current_ids()

    client = TelegramClient(
        os.getenv("TG_SESSION_NAME", "theact_session"),
        int(os.getenv("TG_API_ID", "0")),
        os.getenv("TG_API_HASH", ""),
    )

    async with client:
        dialogs = []
        async for d in client.iter_dialogs():
            entity = d.entity
            if hasattr(entity, "megagroup") or hasattr(entity, "broadcast"):
                chat_id = int(f"-100{entity.id}")
            elif isinstance(entity, Chat):
                chat_id = -entity.id
            else:
                chat_id = entity.id
            dialogs.append((chat_id, d.name))

    # Show current
    print("\n=== Текущие чаты для рекапа ===\n")
    for cid in current_ids:
        name = next((n for i, n in dialogs if i == cid), "???")
        print(f"  ✅ {cid}  {name}")

    print("\n=== Все ваши чаты ===\n")
    for i, (cid, name) in enumerate(dialogs, 1):
        marker = "✅" if cid in current_ids else "  "
        print(f"  {marker} {i:>3}. {name}")

    print("\nВведите номера через запятую чтобы добавить (например: 3,5,12)")
    print("Или '-номер' чтобы убрать (например: -2)")
    print("Enter — выйти без изменений\n")

    choice = input("> ").strip()
    if not choice:
        print("Без изменений.")
        return

    for part in choice.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("-"):
            idx = int(part[1:]) - 1
            cid = dialogs[idx][0]
            if cid in current_ids:
                current_ids.remove(cid)
                print(f"  ❌ Убран: {dialogs[idx][1]}")
        else:
            idx = int(part) - 1
            cid = dialogs[idx][0]
            if cid not in current_ids:
                current_ids.append(cid)
                print(f"  ✅ Добавлен: {dialogs[idx][1]}")

    _save_ids(current_ids)


asyncio.run(main())
