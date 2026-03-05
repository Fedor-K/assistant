import json
import os
import anthropic

SYSTEM_PROMPT = (
    "Ты помощник директора по международному развитию beauty-бренда The Act Perfumes (Dubai). "
    "Рынки: MENA, Африка, США (в разработке). "
    "Твоя задача — делать деловые рекапы переписок. Только факты, конкретика, без воды."
)

DAILY_PROMPT = """Проанализируй переписки за сегодня и составь структурированный рекап по каждому контакту.

Для каждого контакта/чата отдельный блок:

**👤 Контакт:** имя и роль (если понятна из контекста)

**📌 Темы и решения:**
Для каждой темы:
- Тема
- Статус: ✅ Решено / ⏳ В процессе / ❓ Открыто
- Суть: что обсуждали
- Итог: к чему пришли

**⚠️ Открытые вопросы** (что требует действий)

**➡️ Следующие шаги** (конкретно кто и что должен сделать)

---

Если сообщений мало или они формальные (приветствия, "спасибо") — просто кратко отметь суть контакта, не раздувай.

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


STRUCTURED_PROMPT = """Проанализируй переписки и верни JSON массив тем.

Каждая тема — объект:
{{
  "contact": "имя контакта",
  "role": "роль (если понятна)",
  "topic": "название темы",
  "status": "Решено / В процессе / Открыто",
  "summary": "суть обсуждения (1-2 предложения)",
  "result": "к чему пришли",
  "next_step": "что нужно сделать",
  "responsible": "кто отвечает"
}}

Если переписка формальная — верни 1 элемент с topic "Общение" и кратким summary.

Переписка:
{messages}"""


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


def generate_structured_recap(messages_by_chat: dict[str, list[str]]) -> list[dict]:
    """Generate structured recap as list of dicts for sheet sync."""
    if not messages_by_chat:
        return []

    formatted = _format_messages(messages_by_chat)
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=(
            "Ты помощник директора по международному развитию beauty-бренда The Act Perfumes (Dubai). "
            "Отвечай ТОЛЬКО валидным JSON массивом, без markdown, без ```json, без пояснений."
        ),
        messages=[
            {"role": "user", "content": STRUCTURED_PROMPT.format(messages=formatted)}
        ],
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print(f"[recap] JSON parse error: {text[:200]}")
        return []


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
