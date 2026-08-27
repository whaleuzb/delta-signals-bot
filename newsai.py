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


ECON_SCHEMA = {
    "type": "object",
    "properties": {
        "is_market_moving": {
            "type": "boolean",
            "description": "Bu ko'rsatkich(lar) narxga sezilarli ta'sir "
                           "qilish ehtimoli yuqori bo'lgan darajada "
                           "muhimmi? Arzimas/rutin bo'lsa false.",
        },
        "message_uz": {
            "type": "string",
            "description": "To'liq formatlangan o'zbekcha xabar matni, "
                           "quyidagi PROMPT'dagi ANIQ namunaga mos.",
        },
    },
    "required": ["is_market_moving", "message_uz"],
    "additionalProperties": False,
}

ECON_PROMPT = """Quyida AQSHning bir vaqtda (bitta relizda) e'lon qilingan
makroiqtisodiy ko'rsatkich(lar)i berilgan — har biri sarlavha, kutilgan
(forecast), oldingi (previous) va haqiqiy natija (actual) bilan. Ko'pincha
bitta hodisaning oylik va yillik versiyasi (yoki "core" varianti) bir vaqtda
chiqadi — ular BITTA xabarda birlashtiriladi.

Vazifang — quyidagi ANIQ FORMATDA (misoldagek, boshqa hech narsa qo'shmasdan)
o'zbekcha xabar matni yoz:

❗️🇺🇸 #сша #<mavzuga oid 1-2 ta teg, rus tilida kichik harf bilan> #экономика #отчетность
AQSh - <KATEGORIYA NOMI KATTA HARFLARDA, o'zbekcha> - <KO'RSATKICH NOMI KATTA HARFLARDA, o'zbekcha> (<hisobot davri oyi, event sanasidan bir oy oldin, o'zbekcha qisqa nom, masalan "iyul">):

<davr nomi kichik harf bilan, masalan "oylik" yoki "yil davomida"> = <ishora bilan foiz> (kutilgan <ishora bilan foiz> / oldingi ko'rsatkich <ishora bilan foiz>)

(har bir ko'rsatkich uchun yuqoridagi qatordan, orasida bo'sh qator bilan)

MISOL (aynan shu uslubda, lekin mazmuni har xil ko'rsatkich uchun moslashtiriladi):
❗️🇺🇸 #сша #инфляция #экономика #отчетность
AQSh - INFLYATSIYA - PCE NARX INDEKSASI (iyul):

oylik = +0.2% (kutilgan +0.1% / oldingi ko'rsatkich -0.1%)
yil davomida = +3.7% (kutilgan +3.6% / oldingi ko'rsatkich +3.7%)

asosiy PCE = +3.3% yil davomida (kutilgan +3.3% / oldingi ko'rsatkich +3.3%)

Qoidalar:
- Foiz/sondan oldin har doim ishora (+ yoki -) bo'lsin.
- `actual` bo'sh bo'lgan ko'rsatkichni butunlay tashlab ket.
- Barcha `actual` bo'sh bo'lsa — message_uz'ni bo'sh satr qoldir va
  is_market_moving=false qo'y.
- Teglarni ko'rsatkich mazmuniga qarab tanla (masalan инфляция, безработица,
  ставка, ввп, промышленность, розница, рынок труда).
- Bu odatiy/kam ta'sirli ko'rsatkich bo'lsa is_market_moving=false qo'y
  (lekin message_uz baribir to'g'ri formatlanган holda yoz)."""


async def econ_result(events: list[dict]) -> dict | None:
    """`events` — bir xil vaqtda (`when`) chiqqan, `actual`si to'ldirilgan
    iqtisodiy ko'rsatkichlar ro'yxati. `None` — Claude ulanmagan yoki xato
    bo'lsa (chaqiruvchi hech narsa postlamasligi kerak)."""
    if _client is None:
        return None
    lines = []
    for e in events:
        lines.append(f"- {e['title']}: forecast={e.get('forecast') or 'N/A'}, "
                     f"previous={e.get('previous') or 'N/A'}, "
                     f"actual={e.get('actual') or 'N/A'}")
    when = events[0]["when"] if events else None
    text = (f"{ECON_PROMPT}\n\nHODISA SANASI: {when}\n\nKO'RSATKICHLAR:\n" +
           "\n".join(lines))
    try:
        msg = await _client.messages.create(
            model=config.NEWS_MODEL,
            max_tokens=1024,
            output_config={"format": {"type": "json_schema", "schema": ECON_SCHEMA}},
            messages=[{"role": "user", "content": [{"type": "text", "text": text}]}],
        )
    except Exception:
        log.exception("Iqtisodiy natija tahlili xato")
        return None
    for block in msg.content:
        if block.type == "text":
            try:
                return json.loads(block.text)
            except (json.JSONDecodeError, TypeError):
                log.warning("Iqtisodiy natija javobi JSON emas: %r", block.text)
                return None
    return None


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
