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
import time

import requests
import telebot
from flask import Flask

XINGCHI_BASE_URL = "https://api.xingchiapi.com/v1"
MODEL = "gpt-6-astra"
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
ME = bot.get_me()
BOT_USERNAME = ME.username
BOT_ID = ME.id
histories = {}  # user_id -> [{"role": ..., "content": ...}]
GROUP_SESSION_TIMEOUT = 5 * 60  # 5 phut: sau khi @bot, user co 5 phut
# noi chuyen tiep ma khong can @ lai; moi tin nhan lam moi lai 5 phut.
group_sessions = {}  # (chat_id, user_id) -> thoi gian tin nhan cuoi


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


def send_long(chat_id, text, reply_to=None):
    for i in range(0, len(text), 4000):
        bot.send_message(chat_id, text[i : i + 4000], reply_to_message_id=reply_to)
        reply_to = None  # chi reply tin dau tien


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
    group_sessions.pop((m.chat.id, m.from_user.id), None)
    bot.reply_to(m, "Da xoa lich su tro chuyen.")


@bot.message_handler(commands=["model"])
def model(m):
    bot.reply_to(m, f"Model dang dung: {MODEL}")


def is_for_bot(m):
    """Chat rieng: tra loi moi tin.
    Trong nhom: tra loi khi duoc @, khi duoc reply, hoac khi user dang
    trong phien tro chuyen (da @bot trong 5 phut gan nhat)."""
    if m.chat.type == "private":
        return True
    if m.reply_to_message and m.reply_to_message.from_user.id == BOT_ID:
        group_sessions[(m.chat.id, m.from_user.id)] = time.monotonic()
        return True
    if m.entities:
        for e in m.entities:
            if e.type == "mention":
                mentioned = m.text[e.offset : e.offset + e.length]
                if mentioned.lower() == f"@{BOT_USERNAME}".lower():
                    group_sessions[(m.chat.id, m.from_user.id)] = time.monotonic()
                    return True
    last = group_sessions.get((m.chat.id, m.from_user.id))
    if last is not None and time.monotonic() - last < GROUP_SESSION_TIMEOUT:
        group_sessions[(m.chat.id, m.from_user.id)] = time.monotonic()
        return True
    return False


@bot.message_handler(func=lambda m: True, content_types=["text"])
def chat(m):
    if not is_for_bot(m):
        return
    bot.send_chat_action(m.chat.id, "typing")
    try:
        reply = ask_xingchi(m.from_user.id, m.text)
    except Exception as e:
        bot.reply_to(m, f"Xin loi, goi AI bi loi: {e}")
        return
    reply_to = m.message_id if m.chat.type != "private" else None
    send_long(m.chat.id, reply, reply_to=reply_to)


print("Bot dang chay...")
bot.infinity_polling()
