# TG Recap Bot

Бот читает историю Telegram-чатов, генерирует деловые рекапы через Claude API и записывает в Google Docs + Google Sheets.

## Быстрый старт

```bash
cd ~/tg-recap-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Заполни .env (см. ниже)
```

## Первый запуск — авторизация Telegram

```bash
python auth_qr.py
```
Сканируй QR-код из Telegram (Настройки → Устройства → Подключить устройство), затем введи облачный пароль (2FA).

## Команды

### Ежедневный рекап
```bash
python main.py recap
```
Читает сообщения за сегодня → генерирует рекап → пишет в Google Doc и Google Sheet.

### Еженедельный статус-снапшот
```bash
python main.py status
```

### Рекап + статус
```bash
python main.py both
```

### Запуск по расписанию (daemon)
```bash
python main.py
```
- Пн-Сб 19:00 Dubai → дневной рекап
- Вс 18:00 Dubai → рекап + статус-снапшот

### Управление чатами
```bash
python add_chat.py
```
Показывает все чаты, отмечает текущие. Вводишь номера через запятую — добавляет, с минусом — убирает.

### Список всех чатов
```bash
python list_chats.py
```

### Полный рекап всех чатов (первоначальный)
```bash
python full_recap_to_sheet.py
```
Читает ВСЮ историю всех чатов и заполняет Google Sheet с нуля.

## Настройка .env

| Переменная | Описание |
|---|---|
| `TG_API_ID` | Telegram API ID (https://my.telegram.org) |
| `TG_API_HASH` | Telegram API Hash |
| `TG_SESSION_NAME` | Имя файла сессии Telethon |
| `ANTHROPIC_API_KEY` | Ключ Claude API |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Путь к JSON ключу сервисного аккаунта Google |
| `RECAP_DOC_ID` | ID Google Doc для дневных рекапов |
| `STATUS_DOC_ID` | ID Google Doc для статус-снапшота |
| `SHEET_ID` | ID Google Sheet для структурированных данных |
| `TIMEZONE` | Часовой пояс (Asia/Dubai) |
| `RECAP_HOUR` / `RECAP_MINUTE` | Время запуска рекапа |
| `TG_CHAT_IDS` | ID чатов через запятую |

## Google Sheet

Три вкладки:
- **Дашборд** — открытые задачи с галочками и цветами статусов
- **По контактам** — все темы сгруппированы по людям
- **Все данные** — полная таблица

## Деплой (systemd)

```ini
[Unit]
Description=TG Recap Bot
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/tg-recap-bot
ExecStart=/path/to/tg-recap-bot/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable tg-recap-bot
sudo systemctl start tg-recap-bot
journalctl -u tg-recap-bot -f
```
