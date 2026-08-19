"""Grafik rasmidan darajalarni o'qish (caption yozilmaganda).

Natija HAR DOIM adminga tasdiqlash uchun ko'rsatiladi — to'g'ridan-to'g'ri bazaga tushmaydi.
"""
import base64
import logging

import config

log = logging.getLogger(__name__)

try:
    from anthropic import AsyncAnthropic
    _client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY) if config.ANTHROPIC_API_KEY else None
except ImportError:  # anthropic o'rnatilmagan bo'lsa bot baribir ishlaydi
    _client = None

TOOL = {
    "name": "record_signal",
    "description": "Grafikdan o'qilgan trading signal darajalari.",
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "Juftlik, masalan BTCUSDT"},
            "side": {"type": "string", "enum": ["LONG", "SHORT"]},
            "entry": {"type": "number"},
            "sl": {"type": "number"},
            "tps": {"type": "array", "items": {"type": "number"},
                    "description": "Take profit darajalari, entrydan uzoqlashish tartibida"},
            "confidence": {"type": "number", "description": "0..1 oraliqda ishonch"},
            "reasoning": {"type": "string", "description": "Qisqacha: qaysi belgilar asos bo'ldi"},
        },
        "required": ["symbol", "side", "entry", "sl", "tps", "confidence"],
    },
}

PROMPT = """Bu trading grafik skrinshoti. Undan signal darajalarini o'qi.

Qoidalar:
- Long/Short pozitsiya asbobi (yashil/qizil zonalar) bo'lsa, undagi entry, stop va target
  darajalarini o'qi. Yashil zona odatda foyda, qizil zona zarar tomonini bildiradi.
- Matnli belgilar (TP, SL, Entry, Target) bo'lsa ularga ustunlik ber.
- Narx o'qidagi (o'ng tomondagi) qiymatlarga qarab darajalarni aniqla.
- Juftlik nomini grafikning yuqori chap burchagidan o'qi.
- Agar biror daraja aniq ko'rinmasa, taxmin QILMA — confidence ni pasaytir va reasoning da yoz.
- Faqat record_signal asbobini chaqir."""


async def read_chart(image_bytes: bytes, media_type: str = "image/jpeg") -> dict | None:
    if _client is None:
        return None
    b64 = base64.standard_b64encode(image_bytes).decode()
    try:
        msg = await _client.messages.create(
            model=config.VISION_MODEL,
            max_tokens=1024,
            tools=[TOOL],
            tool_choice={"type": "tool", "name": "record_signal"},
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image",
                     "source": {"type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": PROMPT},
                ],
            }],
        )
    except Exception as e:
        log.exception("Vision xato: %s", e)
        return None

    for block in msg.content:
        if block.type == "tool_use":
            d = dict(block.input)
            d["tps"] = [float(x) for x in d.get("tps", [])]
            d["entry"] = float(d["entry"])
            d["sl"] = float(d["sl"])
            return d
    return None
