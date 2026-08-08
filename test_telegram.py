"""
Prueba rápida: solo verifica que las notificaciones de Telegram funcionen,
sin tocar la parte de scraping del SEACE. Si esto funciona, el .env está bien
configurado para Telegram.

Uso:
    python test_telegram.py
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

print("Token leído:", TELEGRAM_BOT_TOKEN[:10] + "..." if TELEGRAM_BOT_TOKEN else "(vacío)")
print("Chat ID leído:", TELEGRAM_CHAT_ID or "(vacío)")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    print("\n❌ Falta configurar TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en el archivo .env")
    raise SystemExit(1)

url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
resp = requests.post(
    url,
    data={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": "✅ Prueba exitosa: el monitor de SEACE ya puede avisarte por Telegram.",
    },
    timeout=15,
)

if resp.status_code == 200:
    print("\n✅ ¡Mensaje enviado! Revisa tu Telegram, debería haberte llegado ya.")
else:
    print(f"\n❌ Error {resp.status_code}: {resp.text}")
