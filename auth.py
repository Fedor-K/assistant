"""Manual Telethon auth with explicit code request."""
import asyncio
import os
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import FloodWaitError, SessionPasswordNeededError

load_dotenv()

async def main():
    client = TelegramClient(
        os.getenv("TG_SESSION_NAME", "theact_session"),
        int(os.getenv("TG_API_ID", "0")),
        os.getenv("TG_API_HASH", ""),
    )
    await client.connect()

    phone = "+79882515556"

    if not await client.is_user_authorized():
        try:
            result = await client.send_code_request(phone)
            print(f"Code sent! Type: {result.type}")
            print("Check Telegram app or SMS")
        except FloodWaitError as e:
            print(f"Flood wait: need to wait {e.seconds} seconds")
            await client.disconnect()
            return
        except Exception as e:
            print(f"Error sending code: {e}")
            await client.disconnect()
            return

        code = input("Enter code: ")
        try:
            await client.sign_in(phone, code)
        except Exception as e:
            if "2FA" in str(type(e).__name__) or "password" in str(e).lower() or "SessionPasswordNeeded" in str(type(e).__name__):
                password = input("Enter your 2FA cloud password: ")
                await client.sign_in(password=password)
            else:
                raise
        print("Authorized!")
    else:
        print("Already authorized!")

    # List chats
    print("\n=== Your Telegram chats ===\n")
    async for dialog in client.iter_dialogs():
        chat_id = dialog.entity.id
        if hasattr(dialog.entity, 'megagroup') or hasattr(dialog.entity, 'broadcast'):
            chat_id = int(f"-100{dialog.entity.id}")
        elif hasattr(dialog.entity, 'chat_photo') and not hasattr(dialog.entity, 'phone'):
            chat_id = -dialog.entity.id
        print(f"{chat_id:>16}  {dialog.name}")

    await client.disconnect()

asyncio.run(main())
