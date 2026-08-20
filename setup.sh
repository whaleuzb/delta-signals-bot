#!/usr/bin/env bash
# Lokal muhitni tayyorlash (Mac Mini)
set -e
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
echo ""
echo "Tayyor. Endi:"
echo "  1) .env faylini to'ldiring (BOT_TOKEN, DATABASE_URL)"
echo "  2) python test_tracker.py   — dvigatel testi"
echo "  3) python bot.py            — ishga tushirish"
