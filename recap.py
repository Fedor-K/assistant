import json
import os
import anthropic

SYSTEM_PROMPT = (
    "Ты помощник директора по международному развитию beauty-бренда The Act Perfumes (Dubai). "
    "Рынки: MENA, Африка, США (в разработке). "
    "Твоя задача — делать деловые рекапы переписок. Только факты, конкретика, без воды."
)

DAILY_PROMPT = """На основе переписок составь отчёт о проделанной работе за день.

Формат — деловой отчёт, как для акта выполненных работ. Без эмодзи, без пересказа чатов.

Структура:

1. ВЫПОЛНЕННЫЕ ЗАДАЧИ
Что было сделано/согласовано/решено сегодня. Конкретные результаты.

2. ЗАДАЧИ В РАБОТЕ
Что находится в процессе. По каждой: текущий статус и что ожидается.

3. НОВЫЕ ЗАДАЧИ И ВОПРОСЫ
Что возникло сегодня и требует внимания.

4. СЛЕДУЮЩИЕ ШАГИ
Конкретные действия: кто, что, когда.

Правила:
- Только факты и конкретика
- Если переписка формальная (ок, спасибо) — не упоминай
- Группируй по темам, а не по контактам
- Указывай ответственных

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
  "responsible": "кто отвечает",
  "context": "ключевые сообщения по теме, дословно из переписки (3-10 самых важных строк, каждая с датой и автором)"
}}

Если переписка формальная (приветствия, "ок", "спасибо") — НЕ создавай для неё тему, просто пропусти.

Переписка:
{messages}"""

STRUCTURED_PROMPT_WITH_IDS = """Проанализируй переписки и верни JSON массив тем.

ВАЖНО: Вот список существующих тем из таблицы. Если сообщение относится к одной из них — используй её ID.
Если тема реально новая и не относится ни к одной существующей — поставь "id": "new".

Существующие темы:
{existing_topics}

Каждая тема — объект:
{{
  "id": ID существующей темы (число) или "new" для новой темы,
  "contact": "имя контакта",
  "role": "роль (если понятна)",
  "topic": "название темы",
  "status": "Решено / В процессе / Открыто",
  "summary": "суть обсуждения (1-2 предложения)",
  "result": "к чему пришли",
  "next_step": "что нужно сделать",
  "responsible": "кто отвечает",
  "context": "ключевые сообщения по теме, дословно из переписки (3-10 самых важных строк, каждая с датой и автором)"
}}

Если переписка формальная (приветствия, "ок", "спасибо") — НЕ создавай для неё тему, просто пропусти.

Переписка:
{messages}"""

DEDUP_PROMPT = """Ты проверяешь, не являются ли новые темы дубликатами существующих.

Новые темы:
{new_topics}

Существующие темы того же контакта:
{existing_topics}

Для каждой новой темы ответь JSON массивом:
[
  {{"new_topic": "название новой темы", "is_duplicate": true/false, "existing_id": ID_существующей_или_null}}
]

is_duplicate = true, если это по сути та же тема, просто названная другими словами.
Отвечай ТОЛЬКО валидным JSON массивом, без пояснений."""


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


def generate_structured_recap(messages_by_chat: dict[str, list[str]], existing_topics: list[dict] = None) -> list[dict]:
    """Generate structured recap as list of dicts for sheet sync.
    existing_topics: list of {"id": int, "contact": str, "topic": str} from the sheet.
    """
    if not messages_by_chat:
        return []

    formatted = _format_messages(messages_by_chat)
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    if existing_topics:
        topics_text = "\n".join(
            f"- ID {t['id']}: {t['contact']} — {t['topic']}"
            for t in existing_topics if t.get("id") is not None
        )
        prompt = STRUCTURED_PROMPT_WITH_IDS.format(existing_topics=topics_text, messages=formatted)
    else:
        prompt = STRUCTURED_PROMPT.format(messages=formatted)

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
        system=(
            "Ты помощник директора по международному развитию beauty-бренда The Act Perfumes (Dubai). "
            "Отвечай ТОЛЬКО валидным JSON массивом, без markdown, без ```json, без пояснений."
        ),
        messages=[
            {"role": "user", "content": prompt}
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


def check_duplicates(items: list[dict], existing_topics: list[dict]) -> list[dict]:
    """Check if items with id='new' are duplicates of existing topics. Fix IDs if so."""
    new_items = [it for it in items if it.get("id") == "new"]
    if not new_items or not existing_topics:
        return items

    # Group existing by contact
    existing_by_contact = {}
    for t in existing_topics:
        if t.get("id") is not None:
            existing_by_contact.setdefault(t["contact"].strip().lower(), []).append(t)

    # Only check items whose contact already has existing topics
    to_check = []
    for it in new_items:
        contact = it["contact"].strip().lower()
        if contact in existing_by_contact:
            to_check.append(it)

    if not to_check:
        return items

    new_topics_text = "\n".join(f"- {it['contact']}: {it['topic']}" for it in to_check)

    # Collect relevant existing topics
    relevant = []
    seen = set()
    for it in to_check:
        for t in existing_by_contact.get(it["contact"].strip().lower(), []):
            if t["id"] not in seen:
                relevant.append(t)
                seen.add(t["id"])

    existing_text = "\n".join(f"- ID {t['id']}: {t['contact']} — {t['topic']}" for t in relevant)

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system="Отвечай ТОЛЬКО валидным JSON массивом, без markdown, без пояснений.",
        messages=[
            {"role": "user", "content": DEDUP_PROMPT.format(new_topics=new_topics_text, existing_topics=existing_text)}
        ],
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        dedup_results = json.loads(text)
    except json.JSONDecodeError:
        print(f"[recap] Dedup JSON parse error: {text[:200]}")
        return items

    # Build map: new_topic -> existing_id
    dedup_map = {}
    for d in dedup_results:
        if d.get("is_duplicate") and d.get("existing_id"):
            dedup_map[d["new_topic"].strip().lower()] = d["existing_id"]

    # Apply: change id from "new" to existing ID where duplicate found
    merged = 0
    for it in items:
        if it.get("id") == "new":
            topic_key = it["topic"].strip().lower()
            if topic_key in dedup_map:
                it["id"] = dedup_map[topic_key]
                merged += 1

    if merged:
        print(f"[recap] Dedup: merged {merged} duplicate(s) into existing topics")

    return items


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
