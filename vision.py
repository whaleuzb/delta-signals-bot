"""Grafik rasmidan signal darajalarini o'qish (caption yozilmaganda).

Natija HAR DOIM adminga tasdiqlash uchun ko'rsatiladi — to'g'ridan-to'g'ri
bazaga tushmaydi. Shu sabab bu yerdagi maqsad "hech qachon xato qilmaslik"
emas, "iloji boricha ko'proq rasmni to'g'ri o'qish, o'qib bo'lmasa esa buni
aniq tan olish".
"""
import base64
import json
import logging

import config

log = logging.getLogger(__name__)

try:
    from anthropic import AsyncAnthropic
    _client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY) if config.ANTHROPIC_API_KEY else None
except ImportError:  # anthropic o'rnatilmagan bo'lsa bot baribir ishlaydi
    _client = None

# Javob shakli TALAB qilinadi (structured outputs): model boshqa hech narsa
# emas, aynan shu JSON'ni qaytaradi. Avval "asbob chaqirish" (tool_use)
# ishlatilardi — majburiy asbob tanlash esa fikrlash bilan yaxshi
# birlashmaydi, fikrlash aynan grafik o'qishda (narx o'qini solishtirish,
# darajalarni taqqoslash) eng ko'p yordam beradigan narsa.
SCHEMA = {
    "type": "object",
    "properties": {
        "is_chart": {
            "type": "boolean",
            "description": "Rasm haqiqatan trading grafigimi",
        },
        "symbol": {
            "type": ["string", "null"],
            "description": "Grafikdagi juftlik nomi — qanday yozilgan bo'lsa "
                           "shundayligicha, masalan BTCUSDT yoki BINANCE:BTCUSDT.P",
        },
        "side": {"type": ["string", "null"], "enum": ["LONG", "SHORT", None]},
        "entry": {"type": ["number", "null"], "description": "Kirish narxi"},
        "sl": {"type": ["number", "null"], "description": "Stop-loss narxi"},
        "tps": {
            "type": "array",
            "items": {"type": "number"},
            "description": "Take-profit darajalari, kirishdan uzoqlashish tartibida",
        },
        "confidence": {"type": "number", "description": "0..1 — o'z javobiga ishonch"},
        "reasoning": {
            "type": "string",
            "description": "Bir-ikki jumla: nimadan o'qiding, nima noaniq qoldi. "
                           "O'zbek tilida.",
        },
    },
    "required": ["is_chart", "symbol", "side", "entry", "sl", "tps",
                 "confidence", "reasoning"],
    "additionalProperties": False,
}

PROMPT = """Bu trading grafik skrinshoti bo'lishi kerak. Undan signal
darajalarini o'qi.

QAYERGA QARASH KERAK
1. Long/Short pozitsiya asbobi (TradingView'dagi yashil-qizil to'rtburchaklar):
   yashil zona — foyda tomoni (take profit), qizil zona — zarar tomoni (stop).
   Ularning chegaralaridagi raqamlarni o'qi.
2. Matnli yozuvlar: "Entry", "TP1", "TP2", "SL", "Target", "Stop", "Buy", "Sell".
   Ular bo'lsa ularga ustunlik ber — chizmani o'lchashdan aniqroq.
3. Gorizontal chiziqlar va ularning yorliqlari.
4. Juftlik nomi — odatda yuqori chap burchakda.

RAQAMLARNI O'QISH
- Narx o'qi (o'ng tomon) bo'yicha tekshir: o'qigan raqamlaring grafikdagi narx
  oralig'iga mos kelishi shart.
- Ming ajratgichiga e'tibor ber: "65 000" va "65.000" bir xil sonni bildirishi
  mumkin. Grafikdagi boshqa narxlar bilan solishtirib qaror qil.
- Mayda yoki xira raqamni TAXMIN QILMA.

MANTIQIY TEKSHIRUV (javob berishdan oldin o'zingni tekshir)
- LONG bo'lsa: stop kirishdan PAST, take profitlar kirishdan YUQORI.
- SHORT bo'lsa: teskarisi.
- O'qiganing bu qoidaga zid bo'lsa — demak tomonni yoki darajani
  chalkashtirgansan. Qaytadan qara.

JAVOB
- Hammasi aniq bo'lsa: confidence 0.8 dan yuqori.
- Bir daraja noaniq bo'lsa: uni o'qi, lekin confidence ni pasaytir va
  reasoning da AYNAN qaysi biri noaniqligini yoz.
- Rasm grafik bo'lmasa yoki darajalarni umuman o'qib bo'lmasa: is_chart=false
  yoki confidence=0 qo'y, maydonlarni null qoldir. Bu xato emas — noto'g'ri
  raqam berishdan ko'ra shunisi yaxshi."""


def media_type(data: bytes) -> str:
    """Rasm turini baytlardan aniqlaydi.

    Avval har doim "image/jpeg" deb yuborilardi: Telegram siqilgan rasmlari
    JPEG bo'lgani uchun bu ko'pincha to'g'ri kelardi, lekin fayl sifatida
    yuborilgan PNG'da API xato qaytarardi."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"GIF":
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _clean(raw: dict) -> dict | None:
    """Model javobini tekshirib, ishlatishga yaroqli holga keltiradi.

    Bu bosqich muhim: model darajalarni to'g'ri o'qib, ammo stop bilan take
    profitni ALMASHTIRIB qo'yishi mumkin (ayniqsa SHORT'da). Bunday javobni
    butunlay tashlash o'rniga, darajalarni kirish narxiga nisbatan joylashuvi
    bo'yicha qayta taqsimlaymiz — geometriya yolg'on gapirmaydi."""
    if not raw.get("is_chart"):
        return None
    try:
        entry = float(raw["entry"])
        sl = float(raw["sl"])
        tps = [float(x) for x in (raw.get("tps") or [])]
    except (TypeError, ValueError, KeyError):
        return None
    side = raw.get("side")
    if side not in ("LONG", "SHORT") or not tps or entry <= 0 or sl <= 0:
        return None

    levels = [x for x in [sl, *tps] if x > 0]
    below = sorted({x for x in levels if x < entry}, reverse=True)   # kirishga yaqindan
    above = sorted({x for x in levels if x > entry})
    want_sl, want_tps = (below, above) if side == "LONG" else (above, below)

    if not want_sl or not want_tps:
        # Bir tomonda umuman daraja yo'q — bunday o'qishga ishonib bo'lmaydi.
        log.info("Vision: darajalar geometriyasi mos kelmadi (%s, entry=%s, "
                 "sl=%s, tps=%s)", side, entry, sl, tps)
        return None

    out = dict(raw)
    out["side"] = side
    out["entry"] = entry
    out["sl"] = want_sl[0]        # kirishga eng yaqin qarama-qarshi daraja
    out["tps"] = want_tps
    out["confidence"] = float(raw.get("confidence") or 0)
    if out["sl"] != sl or out["tps"] != tps:
        log.info("Vision: darajalar qayta taqsimlandi (sl %s -> %s, tps %s -> %s)",
                 sl, out["sl"], tps, out["tps"])
        # Qayta taqsimlash — bu modelning o'qishida chalkashlik bo'lgani
        # demak, shuning uchun ishonch pasaytiriladi va admin diqqat bilan
        # qaraydi.
        out["confidence"] = min(out["confidence"], 0.6)
    return out


async def _ask(image_b64: str, mtype: str, hint: str, note: str = "") -> dict | None:
    text = PROMPT
    if hint:
        # Rasm ostidagi yozuv — tekin va juda qimmatli maslahat: ko'pincha
        # juftlik nomi yoki tomon aynan shu yerda yozilgan bo'ladi.
        text += (f"\n\nFOYDALANUVCHI YOZUVI (rasm ostida): {hint}\n"
                 "Rasmdagi bilan mos kelsa ishonchni oshir; zid bo'lsa "
                 "RASMDAGIGA ishon.")
    if note:
        text += f"\n\n{note}"

    msg = await _client.messages.create(
        model=config.VISION_MODEL,
        max_tokens=4096,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": mtype, "data": image_b64}},
                {"type": "text", "text": text},
            ],
        }],
    )
    for block in msg.content:
        if block.type == "text":
            return json.loads(block.text)
    return None


async def read_chart(image_bytes: bytes, hint: str = "") -> dict | None:
    """Rasmni o'qiydi. Bo'lmasa None — chaqiruvchi matn so'rashga qaytadi.

    `hint` — rasm ostidagi yozuv (bo'lsa).

    Bir marta QAYTA urinish bor: birinchi javob geometriyaga mos kelmasa,
    modelga aynan shu xato aytilib qayta so'raladi. Bu tekin emas, lekin
    signalni qo'lda qayta yozishdan ko'ra arzon."""
    if _client is None:
        return None
    b64 = base64.standard_b64encode(image_bytes).decode()
    mtype = media_type(image_bytes)

    try:
        raw = await _ask(b64, mtype, hint)
    except Exception:
        log.exception("Vision xato (birinchi urinish)")
        return None
    if raw is None:
        return None

    out = _clean(raw)
    if out is not None:
        return out
    if not raw.get("is_chart"):
        return None          # grafik emas — qayta so'rashning ma'nosi yo'q

    try:
        raw2 = await _ask(
            b64, mtype, hint,
            "AVVALGI JAVOBING XATO EDI: stop va take profit darajalari kirish "
            "narxiga nisbatan noto'g'ri tomonda chiqdi. Narx o'qini qaytadan "
            "o'qi va har bir darajani kirish narxi bilan solishtirib tekshir.")
    except Exception:
        log.exception("Vision xato (qayta urinish)")
        return None
    return _clean(raw2) if raw2 else None
