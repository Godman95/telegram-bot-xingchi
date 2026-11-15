#!/usr/bin/env python3
"""Telegram bot thong ke tin nhan — ban deploy Render (khong can API key AI).

Bot dem tin nhan trong nhom va tra loi cac lenh thong ke:
  /stats   - tong tin nhan, tin theo ngay, top nguoi chat nhieu nhat
  /members - so thanh vien nhom, thanh vien tich cuc
  /model   - xem AI dang bat hay tat
  /reset   - xoa lich su chat AI (neu co)

AI (Groq, mien phi) la TUY CHON: neu co bien moi truong GROQ_API_KEY
thi bot tra loi tin nhan bang AI; neu khong co, bot chi thong ke
tin nhan va khong can key nao ca. Chi can TELEGRAM_BOT_TOKEN.
Lay key Groq mien phi tai console.groq.com (API Keys).

Ban nay them mot web server nho (Flask) de Render giu service song
va UptimeRobot ping giu bot khong ngu (Render free tat service sau
15 phut khong co truy cap).

Cach deploy (xem huong dan day du trong chat):
  1. Upload 3 file (telegram-bot-render.py, requirements.txt,
     render.yaml) len mot repo GitHub.
  2. Tren render.com: New -> Web Service -> chon repo.
  3. Them bien moi truong TELEGRAM_BOT_TOKEN (bat buoc).
     Them GROQ_API_KEY neu muon bat AI (tuy chon).
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

MODEL = "openai/gpt-oss-120b"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
SYSTEM_PROMPT = (
    "Ban la mot tro ly AI than thien, tra loi bang tieng Viet, "
    "ngan gon va de hieu."
)
MAX_HISTORY = 10  # so cap tin nhan giu lai cho moi nguoi dung

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
# AI la tuy chon: khong co key thi bot chi thong ke tin nhan.
GROQ_KEY = os.environ.get("GROQ_API_KEY", "").strip()

if not TELEGRAM_TOKEN:
    raise SystemExit(
        "Thieu TELEGRAM_BOT_TOKEN. "
        "Them bien moi truong nay trong Render Dashboard."
    )

if GROQ_KEY:
    # Chi in do dai + 4 ky tu dau de kiem tra key (khong in key).
    print(
        f"GROQ_API_KEY loaded: len={len(GROQ_KEY)}, prefix={GROQ_KEY[:4]}",
        flush=True,
    )
    print("AI: bat (Groq)", flush=True)
else:
    print("AI: tat (che do thong ke, khong can API key)", flush=True)

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


def ask_groq(user_id, text):
    history = histories.setdefault(user_id, [])
    history.append({"role": "user", "content": text})
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history[
        -MAX_HISTORY * 2:
    ]
    r = requests.post(
        f"{GROQ_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_KEY}",
            "Content-Type": "application/json",
        },
        json={"model": MODEL, "messages": messages},
        timeout=120,
    )
    try:
        r.raise_for_status()
    except requests.exceptions.HTTPError:
        raise RuntimeError(f"Groq tra ve {r.status_code}: {r.text[:300]}")
    reply = r.json()["choices"][0]["message"]["content"]
    history.append({"role": "assistant", "content": reply})
    return reply


def send_long(chat_id, text, reply_to=None):
    for i in range(0, len(text), 4000):
        bot.send_message(chat_id, text[i : i + 4000], reply_to_message_id=reply_to)
        reply_to = None  # chi reply tin dau tien


@bot.message_handler(commands=["start"])
def start(m):
    record_message(m)
    if GROQ_KEY:
        bot.reply_to(
            m,
            "Xin chao! Toi la bot AI. Cu nhan tin, toi se tra loi.\n"
            "Lenh: /reset (xoa lich su chat), /model (xem model dang dung), "
            "/stats (thong ke tin nhan), /members (thong ke thanh vien nhom).",
        )
    else:
        bot.reply_to(
            m,
            "Xin chao! Toi la bot thong ke tin nhan (khong dung AI).\n"
            "Lenh: /stats (thong ke tin nhan), "
            "/members (thong ke thanh vien nhom), /model (xem AI dang bat hay tat).",
        )


@bot.message_handler(commands=["reset"])
def reset(m):
    record_message(m)
    histories.pop(m.from_user.id, None)
    group_sessions.pop((m.chat.id, m.from_user.id), None)
    bot.reply_to(m, "Da xoa lich su tro chuyen.")


@bot.message_handler(commands=["model"])
def model(m):
    record_message(m)
    if GROQ_KEY:
        bot.reply_to(m, f"Model dang dung: {MODEL}")
    else:
        bot.reply_to(
            m, "AI dang tat (chua co API key). Bot dang chay che do thong ke."
        )


@bot.message_handler(commands=["stats"])
def stats_cmd(m):
    record_message(m)
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
    bottom = sorted(users.values(), key=lambda u: u["count"])[:5]
    lines.append("")
    lines.append("Top 5 nguoi chat it nhat:")
    for i, u in enumerate(bottom, 1):
        lines.append(f"{i}. {u['name']}: {u['count']}")
    bot.reply_to(m, "\n".join(lines))


@bot.message_handler(commands=["members"])
def members_cmd(m):
    record_message(m)
    if m.chat.type == "private":
        bot.reply_to(m, "Lenh nay chi dung trong nhom.")
        return
    try:
        total = bot.get_chat_member_count(m.chat.id)
    except Exception:
        total = None
    try:
        admins = bot.get_chat_administrators(m.chat.id)
        admin_names = [
            a.user.first_name or a.user.username or str(a.user.id) for a in admins
        ]
    except Exception:
        admin_names = []
    c = stats.get("chats", {}).get(
        str(m.chat.id), {"total": 0, "users": {}, "joined": {}}
    )
    chatted = c.get("users", {})
    joined = c.get("joined", {})
    known = {}
    for uid, u in chatted.items():
        known[uid] = u["name"]
    for uid, u in joined.items():
        known.setdefault(uid, u["name"])
    lines = [
        f"Tong thanh vien nhom: {total}" if total is not None else "Tong thanh vien nhom: ?",
        f"Quan tri vien ({len(admin_names)}): "
        + (", ".join(admin_names) if admin_names else "?"),
        f"Thanh vien bot biet ({len(known)}): da nhan tin hoac vao nhom khi bot co mat",
        f"Tong tin nhan trong nhom: {c.get('total', 0)}",
        "",
        "Thanh vien:",
    ]
    for i, (uid, name) in enumerate(
        sorted(known.items(), key=lambda kv: -chatted.get(kv[0], {}).get("count", 0)),
        1,
    ):
        n = chatted.get(uid, {}).get("count", 0)
        lines.append(f"{i}. {name}: {n} tin" if n else f"{i}. {name}: chua nhan tin")
    least = sorted(
        known.items(), key=lambda kv: chatted.get(kv[0], {}).get("count", 0)
    )[:5]
    lines.append("")
    lines.append("Top 5 nguoi it hoat dong nhat:")
    for i, (uid, name) in enumerate(least, 1):
        n = chatted.get(uid, {}).get("count", 0)
        lines.append(f"{i}. {name}: {n} tin" if n else f"{i}. {name}: chua nhan tin")
    bot.reply_to(m, "\n".join(lines))


@bot.message_handler(content_types=["new_chat_members"])
def on_join(m):
    """Ghi lai thanh vien moi vao nhom (bot nhan duoc su kien nay
    ke ca khi Group Privacy dang bat)."""
    cid = str(m.chat.id)
    c = stats.setdefault("chats", {}).setdefault(
        cid,
        {"title": m.chat.title or cid, "total": 0, "users": {}, "joined": {}, "left": {}},
    )
    for u in m.new_chat_members:
        if u.id == BOT_ID:
            continue
        name = u.first_name or u.username or str(u.id)
        c.setdefault("joined", {})[str(u.id)] = {
            "name": name,
            "date": date.today().isoformat(),
        }
        c.setdefault("left", {}).pop(str(u.id), None)
    save_stats()


@bot.message_handler(content_types=["left_chat_member"])
def on_leave(m):
    """Ghi lai thanh vien roi nhom."""
    u = m.left_chat_member
    if u.id == BOT_ID:
        return
    cid = str(m.chat.id)
    c = stats.get("chats", {}).get(cid)
    if not c:
        return
    name = u.first_name or u.username or str(u.id)
    c.setdefault("joined", {}).pop(str(u.id), None)
    c.setdefault("left", {})[str(u.id)] = {
        "name": name,
        "date": date.today().isoformat(),
    }
    save_stats()


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
    if not GROQ_KEY:
        bot.reply_to(
            m,
            "AI dang tat — bot chi thong ke tin nhan.\n"
            "Dung /stats de xem thong ke, /members de xem thanh vien.",
        )
        record_reply()
        return
    bot.send_chat_action(m.chat.id, "typing")
    try:
        reply = ask_groq(m.from_user.id, m.text)
    except Exception as e:
        bot.reply_to(m, f"Xin loi, goi AI bi loi: {e}")
        return
    reply_to = m.message_id if m.chat.type != "private" else None
    send_long(m.chat.id, reply, reply_to=reply_to)
    record_reply()


print("Bot dang chay...")
bot.infinity_polling()
