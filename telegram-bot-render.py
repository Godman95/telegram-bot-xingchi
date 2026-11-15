#!/usr/bin/env python3
"""Telegram AI bot chay bang Xingchi GPT (gpt-6.1-sol) — ban deploy Render.

Ban nay them mot web server nho (Flask) de Render giu service song
va UptimeRobot ping giu bot khong ngu (Render free tat service sau
15 phut khong co truy cap).

Cach deploy (xem huong dan day du trong chat):
  1. Upload 3 file (telegram-bot-render.py, requirements.txt,
     render.yaml) len mot repo GitHub.
  2. Tren render.com: New -> Web Service -> chon repo.
  3. Them bien moi truong TELEGRAM_BOT_TOKEN va XINGCHI_API_KEY.
  4. Deploy. Them monitor tren uptimerobot.com ping URL cua service
     moi 5 phut de bot chay 24/7.

KHONG gui token/key qua chat.
"""

import os
import threading

import requests
import telebot
from flask import Flask

XINGCHI_BASE_URL = "https://api.xingchiapi.com/v1"
MODEL = "gpt-6.1-sol"
SYSTEM_PROMPT = (
    "Ban la mot tro ly AI than thien, tra loi bang tieng Viet, "
    "ngan gon va de hieu."
)
MAX_HISTORY = 10  # so cap tin nhan giu lai cho moi nguoi dung

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
XINGCHI_KEY = os.environ.get("XINGCHI_API_KEY", "").strip()

if not TELEGRAM_TOKEN or not XINGCHI_KEY:
    raise SystemExit(
        "Thieu TELEGRAM_BOT_TOKEN hoac XINGCHI_API_KEY. "
        "Them 2 bien moi truong nay trong Render Dashboard."
    )

# ---- Web server nho de Render + UptimeRobot ping giu bot song ----
app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is running!"


def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


threading.Thread(target=run_flask, daemon=True).start()

# ---- Telegram bot ----
bot = telebot.TeleBot(TELEGRAM_TOKEN)
histories = {}  # user_id -> [{"role": ..., "content": ...}]


def ask_xingchi(user_id, text):
    history = histories.setdefault(user_id, [])
    history.append({"role": "user", "content": text})
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history[
        -MAX_HISTORY * 2:
    ]
    r = requests.post(
        f"{XINGCHI_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {XINGCHI_KEY}",
            "Content-Type": "application/json",
        },
        json={"model": MODEL, "messages": messages},
        timeout=120,
    )
    r.raise_for_status()
    reply = r.json()["choices"][0]["message"]["content"]
    history.append({"role": "assistant", "content": reply})
    return reply


def send_long(chat_id, text):
    for i in range(0, len(text), 4000):
        bot.send_message(chat_id, text[i : i + 4000])


@bot.message_handler(commands=["start"])
def start(m):
    bot.reply_to(
        m,
        "Xin chao! Toi la bot AI chay bang GPT. Cu nhan tin, toi se tra loi.\n"
        "Lenh: /reset (xoa lich su chat), /model (xem model dang dung).",
    )


@bot.message_handler(commands=["reset"])
def reset(m):
    histories.pop(m.from_user.id, None)
    bot.reply_to(m, "Da xoa lich su tro chuyen.")


@bot.message_handler(commands=["model"])
def model(m):
    bot.reply_to(m, f"Model dang dung: {MODEL}")


@bot.message_handler(func=lambda m: True, content_types=["text"])
def chat(m):
    bot.send_chat_action(m.chat.id, "typing")
    try:
        reply = ask_xingchi(m.from_user.id, m.text)
    except Exception as e:
        bot.reply_to(m, f"Xin loi, goi AI bi loi: {e}")
        return
    send_long(m.chat.id, reply)


print("Bot dang chay...")
bot.infinity_polling()
