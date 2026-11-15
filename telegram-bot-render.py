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

import json
import os
import threading
import time
from datetime import date

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

# ---- Thong ke tin nhan (luu vao stats.json) ----
STATS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stats.json")
stats = {"total_messages": 0, "total_replies": 0, "users": {}, "days": {}, "chats": {}}


def load_stats():
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            stats.update(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        pass


def save_stats():
    tmp = STATS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False)
    os.replace(tmp, STATS_FILE)


def record_message(m):
    stats["total_messages"] += 1
    today = date.today().isoformat()
    stats["days"][today] = stats["days"].get(today, 0) + 1
    uid = str(m.from_user.id)
    name = m.from_user.first_name or m.from_user.username or uid
    u = stats["users"].setdefault(uid, {"name": name, "count": 0})
    u["name"] = name
    u["count"] += 1
    if m.chat.type != "private":
        cid = str(m.chat.id)
        c = stats.setdefault("chats", {}).setdefault(
            cid, {"title": m.chat.title or cid, "total": 0, "users": {}}
        )
        c["title"] = m.chat.title or cid
        c["total"] += 1
        cu = c["users"].setdefault(uid, {"name": name, "count": 0})
        cu["name"] = name
        cu["count"] += 1
    save_stats()


def record_reply():
    stats["total_replies"] += 1
    save_stats()


load_stats()


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
        "Lenh: /reset (xoa lich su chat), /model (xem model dang dung), "
        "/stats (thong ke tin nhan), /members (thong ke thanh vien nhom).",
    )


@bot.message_handler(commands=["reset"])
def reset(m):
    histories.pop(m.from_user.id, None)
    group_sessions.pop((m.chat.id, m.from_user.id), None)
    bot.reply_to(m, "Da xoa lich su tro chuyen.")


@bot.message_handler(commands=["model"])
def model(m):
    bot.reply_to(m, f"Model dang dung: {MODEL}")


@bot.message_handler(commands=["stats"])
def stats_cmd(m):
    users = stats["users"]
    today = stats["days"].get(date.today().isoformat(), 0)
    uid = str(m.from_user.id)
    mine = users.get(uid, {}).get("count", 0)
    top = sorted(users.values(), key=lambda u: u["count"], reverse=True)[:5]
    lines = [
        "Thong ke bot",
        f"Tong tin nhan: {stats['total_messages']}",
        f"Bot da tra loi: {stats['total_replies']}",
        f"Bot bo qua: {stats['total_messages'] - stats['total_replies']}",
        f"Hom nay: {today}",
        f"So nguoi dung: {len(users)}",
        f"Tin nhan cua ban: {mine}",
        "",
        "Top 5 nguoi chat nhieu nhat:",
    ]
    for i, u in enumerate(top, 1):
        lines.append(f"{i}. {u['name']}: {u['count']}")
    bot.reply_to(m, "\n".join(lines))


@bot.message_handler(commands=["members"])
def members_cmd(m):
    if m.chat.type == "private":
        bot.reply_to(m, "Lenh nay chi dung trong nhom.")
        return
    try:
        total = bot.get_chat_member_count(m.chat.id)
    except Exception:
        total = None
    c = stats.get("chats", {}).get(str(m.chat.id), {"total": 0, "users": {}})
    active = c["users"]
    lines = [
        f"Tong thanh vien nhom: {total}" if total is not None else "Tong thanh vien nhom: ?",
        f"Da nhan tin (tu khi bat dau thong ke): {len(active)}",
        f"Tong tin nhan trong nhom: {c['total']}",
        "",
        "Thanh vien da nhan tin:",
    ]
    for i, u in enumerate(
        sorted(active.values(), key=lambda x: x["count"], reverse=True), 1
    ):
        lines.append(f"{i}. {u['name']}: {u['count']}")
    bot.reply_to(m, "\n".join(lines))


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
    record_message(m)
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
    record_reply()


print("Bot dang chay...")
bot.infinity_polling()
