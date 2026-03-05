"""Telethon auth via QR code — no SMS/code needed."""
import asyncio
import os
import qrcode
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.functions.auth import ExportLoginTokenRequest, AcceptLoginTokenRequest
from telethon.tl.types.auth import LoginTokenSuccess, LoginToken, LoginTokenMigrateTo
from telethon.errors import SessionPasswordNeededError

load_dotenv()

async def main():
    client = TelegramClient(
        os.getenv("TG_SESSION_NAME", "theact_session"),
        int(os.getenv("TG_API_ID", "0")),
        os.getenv("TG_API_HASH", ""),
    )
    await client.connect()

    if await client.is_user_authorized():
        print("Already authorized!")
    else:
        try:
            while True:
                result = await client(ExportLoginTokenRequest(
                    api_id=int(os.getenv("TG_API_ID")),
                    api_hash=os.getenv("TG_API_HASH"),
                    except_ids=[]
                ))

                if isinstance(result, LoginTokenSuccess):
                    break

                if isinstance(result, LoginTokenMigrateTo):
                    await client._switch_dc(result.dc_id)
                    result = await client(ExportLoginTokenRequest(
                        api_id=int(os.getenv("TG_API_ID")),
                        api_hash=os.getenv("TG_API_HASH"),
                        except_ids=[]
                    ))
                    if isinstance(result, LoginTokenSuccess):
                        break

                # Generate QR code
                import base64
                token = base64.urlsafe_b64encode(result.token).decode('utf-8')
                url = f"tg://login?token={token}"

                qr = qrcode.QRCode(box_size=1, border=1)
                qr.add_data(url)
                qr.make()
                qr.print_ascii(invert=True)

                print("\nОткрой Telegram на телефоне:")
                print("Настройки → Устройства → Подключить устройство")
                print("Сканируй QR-код выше")
                print("Ожидаю...\n")

                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    break

        except SessionPasswordNeededError:
            password = input("Введи облачный пароль (2FA): ")
            await client.sign_in(password=password)

        print("Authorized!")

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
