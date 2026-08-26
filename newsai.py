"""Yangilik matnini tahlil qilish — o'zbekchaga tarjima, qisqa xulosa,
"bu bozorni haqiqatan qimirlatadimi" filtri va qaysi tiker nazarda
tutilganini taxmin qilish.

`vision.py`ning aynan o'zi andozasi (Claude client, structured output),
lekin matn uchun — rasm yo'q."""
import json
import logging

import config

log = logging.getLogger("newsai")

try:
    from anthropic import AsyncAnthropic
    _client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY) if config.ANTHROPIC_API_KEY else None
except ImportError:  # anthropic o'rnatilmagan bo'lsa bot baribir ishlaydi
    _client = None

SCHEMA = {
    "type": "object",
    "properties": {
        "is_market_moving": {
            "type": "boolean",
            "description": "Bu yangilik narxga sezilarli ta'sir qilish "
                           "ehtimoli yuqorimi? Oddiy, kundalik hujjat "
                           "(masalan har chorakdagi rutin hisobot) bo'lsa false.",
        },
        "translation_uz": {
            "type": "string",
            "description": "Sarlavha va asosiy mazmunning o'zbekcha tarjimasi, "
                           "1-2 jumla.",
        },
        "insight_uz": {
            "type": "string",
            "description": "Juda qisqa (5-8 so'z) o'zbekcha xulosa/sarlavha, "
                           "diqqatni tortadigan uslubda. Masalan: "
                           "\"SEC yirik tergov boshladi\".",
        },
        "symbol_hint": {
            "type": ["string", "null"],
            "description": "Matnda tilga olingan kompaniya/tokenning birja "
                           "tikeri, agar aniq bo'lsa (masalan MSTR, BTC). "
                           "Aniq bo'lmasa null.",
        },
    },
    "required": ["is_market_moving", "translation_uz", "insight_uz", "symbol_hint"],
    "additionalProperties": False,
}

PROMPT = """Quyida moliyaviy/kripto yangilik matni berilgan (SEC hujjati,
birja e'loni yoki shunga o'xshash rasmiy manba).

Vazifang:
1. Bu yangilik bozorga (aktiv narxiga) SEZILARLI ta'sir qilish ehtimoli
   bormi, yoki bu oddiy/rutin hujjatmi? Rutin bo'lsa is_market_moving=false.
2. Sarlavha va matnni O'ZBEK tiliga tarjima qil (1-2 jumla, aniq va qisqa).
3. Diqqatni tortadigan juda qisqa xulosa yoz (5-8 so'z, o'zbekcha).
4. Matnda qaysi kompaniya/token nazarda tutilganini top va uning ODATDA
   ishlatiladigan birja tikerini yoz (masalan "MicroStrategy" -> "MSTR",
   "Bitcoin" -> "BTC"). Ishonchli bo'lmasa null qoldir — taxmin qilib
   noto'g'ri tiker yozishdan ko'ra shunisi yaxshi."""


async def analyze(headline_en: str, body_en: str) -> dict | None:
    """`None` — Claude ulanmagan yoki xato bo'lsa (chaqiruvchi shunda hech
    narsa postlamasligi kerak, aks holda tarjimasiz/tahlilsiz xabar ketardi)."""
    if _client is None:
        return None
    text = f"{PROMPT}\n\nSARLAVHA: {headline_en}\n\nMATN: {body_en}"
    try:
        msg = await _client.messages.create(
            model=config.NEWS_MODEL,
            max_tokens=1024,
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": [{"type": "text", "text": text}]}],
        )
    except Exception:
        log.exception("Yangilik tahlili xato")
        return None
    for block in msg.content:
        if block.type == "text":
            try:
                return json.loads(block.text)
            except (json.JSONDecodeError, TypeError):
                log.warning("Yangilik tahlili javobi JSON emas: %r", block.text)
                return None
    return None
