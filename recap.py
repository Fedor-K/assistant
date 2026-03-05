import os
import anthropic

SYSTEM_PROMPT = (
    "Ты помощник директора по международному развитию beauty-бренда The Act Perfumes (Dubai). "
    "Рынки: MENA, Африка, США (в разработке)."
)

DAILY_PROMPT = """Сделай деловой рекап переписки за сегодня. Только факты, без воды.

Структура:
✅ Решения принятые
📋 Задачи поставлены (кто отвечает)
🤝 Статус переговоров
❓ Открытые вопросы
➡️ Приоритеты на завтра

Переписка:
{messages_by_chat}"""

STATUS_PROMPT = """На основе рекапов последних 4 недель создай актуальный снапшот.
Не история — текущее состояние дел.

Структура:
🎯 Активные переговоры и статус
📦 Каналы продаж
👥 Команда и зоны ответственности
⚠️ Критические открытые вопросы
🗓️ Ближайшие дедлайны

Рекапы:
{last_4_weeks}"""


def _format_messages(by_chat: dict[str, list[str]]) -> str:
    parts = []
    for chat_title, lines in by_chat.items():
        parts.append(f"=== {chat_title} ===")
        parts.extend(lines)
        parts.append("")
    return "\n".join(parts)


def generate_daily_recap(messages_by_chat: dict[str, list[str]]) -> str:
    if not messages_by_chat:
        return "Нет сообщений за сегодня."

    formatted = _format_messages(messages_by_chat)
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": DAILY_PROMPT.format(messages_by_chat=formatted)}
        ],
    )
    return response.content[0].text


def generate_status_snapshot(recaps_text: str) -> str:
    if not recaps_text.strip():
        return "Недостаточно данных для статус-снапшота."

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": STATUS_PROMPT.format(last_4_weeks=recaps_text)}
        ],
    )
    return response.content[0].text
