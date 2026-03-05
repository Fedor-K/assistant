"""One-time script to list all your Telegram chats with their IDs."""
import asyncio
import os
from dotenv import load_dotenv
from telethon import TelegramClient

load_dotenv()

async def main():
    client = TelegramClient(
        os.getenv("TG_SESSION_NAME", "theact_session"),
        int(os.getenv("TG_API_ID", "0")),
        os.getenv("TG_API_HASH", ""),
    )
    async with client:
        print("\n=== Your Telegram chats ===\n")
        async for dialog in client.iter_dialogs():
            chat_id = dialog.entity.id
            # For supergroups/channels, prepend -100
            if hasattr(dialog.entity, 'megagroup') or hasattr(dialog.entity, 'broadcast'):
                chat_id = int(f"-100{dialog.entity.id}")
            elif hasattr(dialog.entity, 'chat_photo') and not hasattr(dialog.entity, 'phone'):
                chat_id = -dialog.entity.id
            print(f"{chat_id:>16}  {dialog.name}")

asyncio.run(main())
