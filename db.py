import aiosqlite
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "recap.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                chat_title TEXT,
                sender_name TEXT,
                message_text TEXT NOT NULL,
                message_time TEXT NOT NULL,
                date TEXT NOT NULL,
                processed INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.commit()


async def save_messages(chat_id: int, chat_title: str, messages: list[dict]):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.executemany(
            """INSERT INTO messages (chat_id, chat_title, sender_name, message_text, message_time, date)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (
                    chat_id,
                    chat_title,
                    m["sender_name"],
                    m["text"],
                    m["time"],
                    m["date"],
                )
                for m in messages
            ],
        )
        await conn.commit()


async def get_unprocessed_messages(date: str) -> dict[str, list[str]]:
    """Returns {chat_title: [formatted messages]} for the given date."""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT chat_title, sender_name, message_text, message_time "
            "FROM messages WHERE date = ? AND processed = 0 ORDER BY chat_id, message_time",
            (date,),
        )
        rows = await cursor.fetchall()

    by_chat: dict[str, list[str]] = {}
    for row in rows:
        title = row["chat_title"] or str(row["chat_id"])
        line = f"[{row['message_time']}] {row['sender_name']}: {row['message_text']}"
        by_chat.setdefault(title, []).append(line)
    return by_chat


async def get_all_messages(date: str) -> dict[str, list[str]]:
    """Returns ALL messages for the date (processed + unprocessed)."""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT chat_title, sender_name, message_text, message_time "
            "FROM messages WHERE date = ? ORDER BY chat_id, message_time",
            (date,),
        )
        rows = await cursor.fetchall()

    by_chat: dict[str, list[str]] = {}
    for row in rows:
        title = row["chat_title"] or "Unknown"
        line = f"[{row['message_time']}] {row['sender_name']}: {row['message_text']}"
        by_chat.setdefault(title, []).append(line)
    return by_chat


async def mark_processed(date: str):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "UPDATE messages SET processed = 1 WHERE date = ?", (date,)
        )
        await conn.commit()


async def get_messages_for_period(start_date: str, end_date: str) -> dict[str, list[str]]:
    """Returns messages for a date range (for weekly status)."""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT chat_title, sender_name, message_text, message_time, date "
            "FROM messages WHERE date >= ? AND date <= ? ORDER BY date, chat_id, message_time",
            (start_date, end_date),
        )
        rows = await cursor.fetchall()

    by_chat: dict[str, list[str]] = {}
    for row in rows:
        title = row["chat_title"] or "Unknown"
        line = f"[{row['date']} {row['message_time']}] {row['sender_name']}: {row['message_text']}"
        by_chat.setdefault(title, []).append(line)
    return by_chat


async def cleanup_old_messages(before_date: str):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("DELETE FROM messages WHERE date < ?", (before_date,))
        await conn.commit()
