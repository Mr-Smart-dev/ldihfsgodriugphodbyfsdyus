# -*- coding: utf-8 -*-
"""
Kurdistan Today Smart Map 2026 - Sorani Fast Clean Edition v7
===========================================================
- Dark mode map by default + no city/street labels by default
- Optional label toggle
- Telegram verification code + quick-login button
- Quick-login button opens the map directly without typing the code
- Cleaner Sorani Kurdish UI
- No vehicle/car tracking
- Better tools, loading progress, filters, popups, and database checks
- SQLite data.db support with flexible subscribers columns
"""

from flask import Flask, jsonify, request, render_template_string, session, redirect
import sqlite3
import os
import sys
import random
import secrets
import threading
import subprocess
import shutil
import time
import socket
import requests
import json
from datetime import datetime
from functools import wraps

# =====================================================
# CONFIGURATION
# =====================================================

APP_NAME = "Kurdistan Today Smart Map 2026"
APP_VERSION = "8.0.0-10DB"
APP_HOST = "0.0.0.0"
DEFAULT_PORT = 5000

# گرنگ: تۆکنەکەت پێشتر لە چاتدا دەرکەوتووە. لە BotFather تۆکنێکی نوێ دروست بکە.
BOT_TOKEN = "8558608114:AAEh7p0n88CmgIOjkZEZoTzS31bZYxY6uqc"
GROUP_ID = "-1003665219783"

VERIFY_CODE = str(random.randint(100000, 999999))
QUICK_LOGIN_TOKEN = secrets.token_urlsafe(32)

# =====================================================
# PATHS / APP
# =====================================================

def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = app_dir()
# Supports either one database (data.db) or 10 split databases (data1.db ... data10.db)
DB_FILE = os.path.join(BASE_DIR, "data.db")
DB_FILES_10 = [os.path.join(BASE_DIR, f"data{i}.db") for i in range(1, 11)]


def get_lan_ip():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return "127.0.0.1"


def find_free_port(start=DEFAULT_PORT):
    for port in range(start, start + 80):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((APP_HOST, port))
                return port
            except OSError:
                continue
    return start

APP_PORT = find_free_port()
LAN_IP = get_lan_ip()
APP_URL = f"http://127.0.0.1:{APP_PORT}"
MOBILE_URL = f"http://{LAN_IP}:{APP_PORT}"
QUICK_LOGIN_URL = f"{MOBILE_URL}/quick-login/{QUICK_LOGIN_TOKEN}"

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
app.config["PERMANENT_SESSION_LIFETIME"] = 86400

# =====================================================
# HELPERS
# =====================================================

def verified_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("verified"):
            return jsonify({"ok": False, "error": "not_verified"}), 403
        return f(*args, **kwargs)
    return decorated_function


def safe_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def get_db_files():
    """Return available database files. Prefer split data1.db..data10.db, fallback to data.db."""
    split_files = [db for db in DB_FILES_10 if os.path.exists(db)]
    if split_files:
        return split_files
    if os.path.exists(DB_FILE):
        return [DB_FILE]
    return []


def db_exists():
    return len(get_db_files()) > 0


def get_conn(db_file=None):
    conn = sqlite3.connect(db_file or DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def has_table(cur, table):
    try:
        row = cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        return row is not None
    except Exception:
        return False


def table_columns(cur, table):
    try:
        return [str(r[1]) for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]
    except Exception:
        return []


def has_column(cur, table, column):
    return any(c.lower() == column.lower() for c in table_columns(cur, table))


def choose_column(cur, candidates, fallback=None):
    cols = table_columns(cur, "subscribers")
    low = {c.lower(): c for c in cols}
    for c in candidates:
        if c.lower() in low:
            return low[c.lower()]
    return fallback


def db_stats():
    data = {
        "exists": db_exists(),
        "db_path": ", ".join(os.path.basename(x) for x in get_db_files()) or "data.db / data1.db تا data10.db نەدۆزرایەوە",
        "total": 0,
        "with_location": 0,
        "cities": 0,
        "active": 0,
        "inactive": 0,
        "files": len(get_db_files()),
        "error": None,
    }
    if not db_exists():
        data["error"] = "هیچ database نەدۆزرایەوە. data.db یان data1.db تا data10.db لە هەمان فۆڵدەر دابنێ."
        return data

    city_set = set()
    errors = []

    for db_file in get_db_files():
        try:
            conn = get_conn(db_file)
            cur = conn.cursor()
            if not has_table(cur, "subscribers"):
                errors.append(f"{os.path.basename(db_file)}: خشتەی subscribers نییە")
                conn.close()
                continue

            area_col = choose_column(cur, ["Area", "City", "Zone", "Region"], None)
            status_col = choose_column(cur, ["Status", "State"], None)
            lat_col = choose_column(cur, ["lat", "latitude", "Lat", "Latitude"], "lat")
            lng_col = choose_column(cur, ["lng", "lon", "longitude", "Lng", "Longitude"], "lng")
            area_expr = f"COALESCE({area_col}, 'نادیار')" if area_col else "'نادیار'"
            status_expr = f"COALESCE({status_col}, '')" if status_col else "''"

            data["total"] += cur.execute("SELECT COUNT(*) c FROM subscribers").fetchone()["c"]
            data["with_location"] += cur.execute(
                f"SELECT COUNT(*) c FROM subscribers WHERE {lat_col} IS NOT NULL AND {lng_col} IS NOT NULL"
            ).fetchone()["c"]
            data["active"] += cur.execute(
                f"SELECT COUNT(*) c FROM subscribers WHERE {status_expr} LIKE '%چالاک%' OR lower({status_expr}) LIKE '%active%'"
            ).fetchone()["c"]
            data["inactive"] += cur.execute(
                f"SELECT COUNT(*) c FROM subscribers WHERE {status_expr} LIKE '%ناچالاک%' OR lower({status_expr}) LIKE '%inactive%' OR lower({status_expr}) LIKE '%off%'"
            ).fetchone()["c"]
            for r in cur.execute(f"SELECT DISTINCT {area_expr} AS Area FROM subscribers"):
                city_set.add(r["Area"] or "نادیار")
            conn.close()
        except Exception as e:
            errors.append(f"{os.path.basename(db_file)}: {e}")
            print("Stats DB error", db_file, e)

    data["cities"] = len(city_set)
    if errors:
        data["error"] = " | ".join(errors[:5])
    return data

# =====================================================
# TELEGRAM
# =====================================================

def telegram_api(method, data=None):
    if not BOT_TOKEN or BOT_TOKEN == "PUT_YOUR_NEW_BOT_TOKEN_HERE":
        return False, "BOT_TOKEN دانەنراوە. لە BotFather تۆکنێکی نوێ دابنێ."
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
            data=data or {},
            timeout=15,
        )
        return r.ok, r.text
    except Exception as e:
        return False, str(e)


def get_updates_chat_ids():
    if not BOT_TOKEN or BOT_TOKEN == "PUT_YOUR_NEW_BOT_TOKEN_HERE":
        return []
    try:
        r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates", timeout=15)
        data = r.json()
        found = []
        for item in data.get("result", []):
            msg = item.get("message") or item.get("channel_post") or item.get("edited_message") or {}
            chat = msg.get("chat") or {}
            cid = chat.get("id")
            title = chat.get("title") or chat.get("username") or chat.get("first_name") or "unknown"
            ctype = chat.get("type") or "unknown"
            if cid:
                found.append({"id": str(cid), "title": title, "type": ctype})
        unique, seen = [], set()
        for x in found:
            if x["id"] not in seen:
                unique.append(x)
                seen.add(x["id"])
        return unique
    except Exception as e:
        print("getUpdates error:", e)
        return []


def send_telegram_message(chat_id, text):
    keyboard = {
        "inline_keyboard": [
            [{"text": "✅ پشتڕاستکردنەوە و کردنەوەی نەخشە", "url": QUICK_LOGIN_URL}],
            [{"text": f"🔐 کۆدی دەستی: {VERIFY_CODE}", "callback_data": "show_code"}],
            [{"text": "🗺️ کردنەوەی نەخشە بەبێ چوونەژوورەوە", "url": APP_URL}],
        ]
    }
    return telegram_api("sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": json.dumps(keyboard, ensure_ascii=False),
    })


def send_verify_code():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = f"""🟢 <b>Kurdistan Today Smart Map 2026</b>

✅ <b>کۆدی چوونەژوورەوە و دوگمەی راستەوخۆ ئامادەیە</b>

🔐 کۆدی دەستی: <code>{VERIFY_CODE}</code>
🕐 کات: <code>{now}</code>
💾 داتابەیس: <code>data.db</code>
🌐 ناونیشان: <code>{APP_URL}</code>

دوگمەی یەکەم دابگرە؛ راستەوخۆ دەچیتە ناو نەخشەکە بەبێ نووسینی کۆد.
"""
    if GROUP_ID and GROUP_ID != "PUT_YOUR_GROUP_ID_HERE":
        ok, resp = send_telegram_message(GROUP_ID, text)
        if ok:
            print("✅ Telegram code sent to GROUP_ID:", GROUP_ID)
            return True, f"sent to {GROUP_ID}"

    chats = get_updates_chat_ids()
    for c in chats:
        if c["type"] in ("group", "supergroup", "channel", "private"):
            ok, resp = send_telegram_message(c["id"], text)
            if ok:
                print("✅ Telegram code sent to detected chat:", c["id"])
                return True, f"sent to detected {c['id']}"
    return False, "نەتوانرا کۆد بنێردرێت. Bot زیاد بکە بۆ گرووپ، پاشان /start یان نامەیەک بۆ bot بنێرە."

# =====================================================
# DESKTOP WEBAPP
# =====================================================

def open_webapp_window():
    time.sleep(1.2)
    candidates = [
        shutil.which("msedge"), shutil.which("chrome"), shutil.which("google-chrome"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    browser = next((c for c in candidates if c and os.path.exists(c)), None)
    if not browser:
        print("⚠️ Browser نەدۆزرایەوە. بە دەست بکەرەوە:", APP_URL)
        return
    profile_dir = os.path.join(BASE_DIR, "webapp_profile")
    os.makedirs(profile_dir, exist_ok=True)
    try:
        subprocess.Popen([
            browser,
            f"--app={APP_URL}",
            "--window-size=1620,980",
            "--window-position=25,20",
            "--disable-infobars",
            "--disable-session-crashed-bubble",
            f"--user-data-dir={profile_dir}",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print("Browser open error:", e)

# =====================================================
# HTML TEMPLATE
# =====================================================

HTML_TEMPLATE = r'''
<!DOCTYPE html>
<html lang="ku" dir="rtl">
<head>
<meta charset="UTF-8">
<title>Kurdistan Today | Smart Map 2026</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<meta name="theme-color" content="#06130f">
<link href="https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.css" rel="stylesheet">
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/css/all.min.css" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Arabic:wght@400;500;700;800;900&family=Inter:wght@400;700;900&display=swap" rel="stylesheet">
<style>
 :root{
  --red:#ef233c;--red2:#7f0d1b;--red3:#ff4d5f;--blue:#38bdf8;--orange:#f97316;
  --bg:#030305;--panel:rgba(10,10,14,.74);--panel2:rgba(20,7,10,.82);
  --border:rgba(239,35,60,.34);--border2:rgba(255,255,255,.08);
  --text:#fff7f8;--muted:#a8a8b3;--shadow:0 34px 90px rgba(0,0,0,.72);--radius:30px;
}
*{box-sizing:border-box;margin:0;padding:0} html,body{height:100%} body{font-family:'Noto Sans Arabic','Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);overflow:hidden} button,input{font-family:inherit} button{user-select:none} ::-webkit-scrollbar{width:7px;height:7px}::-webkit-scrollbar-track{background:#020407}::-webkit-scrollbar-thumb{background:linear-gradient(var(--red),var(--red2));border-radius:99px}
.verify-screen{position:fixed;inset:0;z-index:99999;display:flex;align-items:center;justify-content:center;padding:22px;background:radial-gradient(circle at 12% 15%,rgba(239,35,60,.24),transparent 35%),radial-gradient(circle at 85% 72%,rgba(56,189,248,.18),transparent 42%),linear-gradient(145deg,#020407,#07100d 55%,#020407)}.verify-screen.hidden{display:none}.scan-lines:before{content:"";position:fixed;inset:0;pointer-events:none;background:linear-gradient(to bottom,transparent 0,rgba(255,255,255,.03) 50%,transparent 100%);background-size:100% 5px;opacity:.28;mix-blend-mode:overlay}.verify-card{width:min(650px,100%);border:1px solid var(--border);background:linear-gradient(145deg,rgba(10,18,25,.96),rgba(2,4,7,.98));border-radius:42px;padding:34px;box-shadow:var(--shadow),0 0 55px rgba(239,35,60,.14);position:relative;overflow:hidden}.verify-card:after{content:"";position:absolute;inset:-2px;border-radius:43px;background:linear-gradient(120deg,transparent,rgba(239,35,60,.2),transparent);z-index:-1}.lock-icon{width:95px;height:95px;margin:0 auto 18px;border-radius:32px;display:grid;place-items:center;background:linear-gradient(135deg,var(--red),var(--red2));box-shadow:0 0 42px rgba(239,35,60,.45)}.lock-icon i{font-size:44px}.verify-card h1{text-align:center;font-size:31px;font-weight:900;letter-spacing:-.5px}.verify-card p{text-align:center;color:var(--muted);margin-top:7px;font-size:13px}.code-input{width:100%;direction:ltr;text-align:center;margin-top:24px;padding:18px 14px;border:1px solid var(--border);border-radius:28px;background:rgba(0,0,0,.48);color:white;font-size:36px;font-weight:900;letter-spacing:12px;outline:none}.code-input:focus{border-color:#ffb3bc;box-shadow:0 0 0 5px rgba(239,35,60,.16)}.verify-actions{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px}.vbtn{border:0;border-radius:26px;padding:14px;color:white;font-weight:900;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:10px;transition:.2s}.vbtn:hover{transform:translateY(-2px);filter:brightness(1.08)}.vbtn-green{background:linear-gradient(135deg,var(--red),var(--red2));box-shadow:0 10px 28px rgba(239,35,60,.16)}.vbtn-dark{background:rgba(255,255,255,.07);border:1px solid var(--border)}.verify-error{display:none;margin-top:14px;padding:12px;border-radius:20px;background:rgba(239,68,68,.16);border:1px solid rgba(239,68,68,.45);color:#fecaca;text-align:center;font-weight:900}.verify-error.show{display:block}.hint{margin-top:16px;color:var(--muted);font-size:12px;text-align:center;line-height:1.9;background:rgba(0,0,0,.32);border:1px solid var(--border2);padding:12px;border-radius:22px}
.app{height:100vh;width:100vw;display:grid;grid-template-columns:455px 1fr;visibility:hidden}.app.unlocked{visibility:visible}.sidebar{height:100vh;overflow:auto;background:linear-gradient(180deg,rgba(8,14,20,.97),rgba(2,4,7,.98));border-left:1px solid var(--border);z-index:20}.hero{position:sticky;top:0;z-index:12;padding:18px;background:linear-gradient(135deg,rgba(239,35,60,.98),rgba(4,120,87,.98));box-shadow:0 18px 48px rgba(0,0,0,.35)}.brand{display:flex;align-items:center;justify-content:space-between;gap:12px}.brand-left{display:flex;align-items:center;gap:12px}.logo{width:58px;height:58px;border-radius:21px;display:grid;place-items:center;background:rgba(0,0,0,.28);border:1px solid rgba(255,255,255,.22)}.logo i{font-size:27px}.brand h1{font-size:19px;font-weight:900}.brand p{font-size:11px;opacity:.85;margin-top:2px;direction:ltr;text-align:right}.badge{display:flex;align-items:center;gap:8px;background:rgba(0,0,0,.28);border-radius:999px;padding:8px 12px;font-size:11px;font-weight:900}.pulse{width:9px;height:9px;border-radius:50%;background:#ffd4d9;box-shadow:0 0 14px #ffd4d9;animation:pulse 1.3s infinite}@keyframes pulse{50%{transform:scale(1.35);opacity:.55}}.mini{margin-top:12px;background:rgba(0,0,0,.28);border:1px solid rgba(255,255,255,.18);border-radius:18px;padding:10px 12px;display:flex;justify-content:space-between;align-items:center;font-size:12px}.mini b{direction:ltr;letter-spacing:2px;background:rgba(0,0,0,.28);border-radius:999px;padding:5px 10px}.block{padding:16px 18px;border-bottom:1px solid rgba(255,255,255,.06)}.title{font-size:14px;font-weight:900;display:flex;align-items:center;gap:9px;margin-bottom:12px}.title i{color:#ffb3bc}.search{position:relative}.search i{position:absolute;right:15px;top:50%;transform:translateY(-50%);color:var(--red)}.search input{width:100%;padding:13px 46px 13px 14px;border-radius:24px;background:rgba(0,0,0,.42);border:1px solid var(--border);color:white;outline:none;font-weight:700}.search input:focus{border-color:#ffb3bc;box-shadow:0 0 0 4px rgba(239,35,60,.12)}.btn-row{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}.btn{border:0;border-radius:23px;padding:12px;color:white;font-weight:900;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:8px;transition:.18s}.btn:hover{filter:brightness(1.08);transform:translateY(-2px)}.green{background:linear-gradient(135deg,var(--red),var(--red2))}.dark{background:rgba(255,255,255,.07);border:1px solid var(--border)}.blue{background:linear-gradient(135deg,var(--blue),#1d4ed8)}.red{background:linear-gradient(135deg,var(--red),#991b1b)}.wide{grid-column:1/-1}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:9px}.stat{background:linear-gradient(145deg,rgba(255,255,255,.08),rgba(0,0,0,.28));border:1px solid var(--border);border-radius:18px;padding:11px 6px;text-align:center;position:relative;overflow:hidden}.stat:before{content:"";position:absolute;top:0;right:20%;left:20%;height:2px;background:linear-gradient(90deg,transparent,#ffb3bc,transparent)}.stat strong{display:block;color:#ffb3bc;font-size:21px;font-weight:900;direction:ltr}.stat span{font-size:10px;color:var(--muted)}.chips{display:flex;flex-wrap:wrap;gap:9px}.chip{border:1px solid var(--border);background:rgba(255,255,255,.06);border-radius:999px;padding:8px 13px;cursor:pointer;font-size:12px;font-weight:800;display:flex;gap:6px;align-items:center;transition:.18s}.chip:hover,.chip.active{background:linear-gradient(135deg,rgba(239,35,60,.9),rgba(6,95,70,.9));border-color:#ffb3bc}.range{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:center}.range input{accent-color:var(--red);width:100%}.results{padding:0 18px 18px}.item{background:linear-gradient(145deg,rgba(255,255,255,.075),rgba(0,0,0,.28));border:1px solid rgba(255,255,255,.09);border-radius:19px;padding:13px;margin-bottom:10px;cursor:pointer;transition:.18s}.item:hover{border-color:#ffb3bc;transform:translateX(-5px);background:rgba(239,35,60,.1)}.name{font-weight:900;display:flex;gap:8px;align-items:center}.name i{color:#ffb3bc}.meta{display:flex;flex-wrap:wrap;gap:7px;margin-top:9px}.pill{font-size:10px;color:#cbd5e1;background:rgba(0,0,0,.34);border:1px solid rgba(255,255,255,.08);border-radius:999px;padding:4px 9px}.map-wrap{position:relative;height:100vh;background:#020407}#map{height:100%;width:100%}.topbar{display:none!important;position:absolute;top:18px;right:18px;left:18px;z-index:10;display:flex;justify-content:space-between;gap:12px;pointer-events:none}.glass{pointer-events:auto;background:var(--panel);backdrop-filter:blur(14px);border:1px solid var(--border);border-radius:23px;padding:11px 15px;box-shadow:0 10px 35px rgba(0,0,0,.22)}.glass b{font-size:12px}.glass div{font-size:10px;color:var(--muted);margin-top:3px;direction:ltr;text-align:right}.tools-panel{position:absolute;top:92px;left:18px;z-index:12;display:grid;gap:10px;transition:.2s}.tool-pill{min-width:190px;background:var(--panel);border:1px solid var(--border);backdrop-filter:blur(14px);border-radius:999px;padding:10px 13px;font-size:12px;font-weight:900;display:flex;align-items:center;gap:9px;justify-content:space-between}.tool-pill input{accent-color:var(--red)}.controls{position:absolute;bottom:24px;left:24px;z-index:10;display:flex;gap:10px}.ctrl{width:50px;height:50px;border-radius:18px;border:1px solid var(--border);background:var(--panel);backdrop-filter:blur(12px);color:white;display:grid;place-items:center;cursor:pointer;transition:.18s}.ctrl:hover{background:var(--red);transform:translateY(-2px)}.toast{position:fixed;bottom:28px;right:28px;z-index:99999;display:none;gap:10px;align-items:center;background:rgba(0,0,0,.9);border:1px solid var(--red);border-radius:18px;padding:13px 18px;font-weight:800;box-shadow:var(--shadow)}.toast.show{display:flex}.loading{position:fixed;inset:0;z-index:9998;background:rgba(0,0,0,.58);display:none;align-items:center;justify-content:center;backdrop-filter:blur(4px)}.loading.active{display:flex}.loader{width:min(380px,90%);background:linear-gradient(145deg,#07100d,#020407);border:1px solid var(--border);border-radius:26px;padding:22px 24px;box-shadow:var(--shadow);text-align:center}.bar{height:10px;margin-top:15px;background:rgba(255,255,255,.08);border-radius:999px;overflow:hidden}.bar span{display:block;height:100%;width:42%;background:linear-gradient(90deg,var(--red),#ffb3bc,var(--blue));border-radius:999px;animation:load 1s infinite alternate}@keyframes load{to{transform:translateX(-140%);width:90%}}.maplibregl-popup-content{background:transparent!important;padding:0!important;box-shadow:none!important}.maplibregl-popup-tip{border-top-color:rgba(239,35,60,.5)!important}.popup{width:375px;background:linear-gradient(145deg,#0b1119,#030507);border:1px solid var(--border);border-radius:26px;overflow:hidden;box-shadow:var(--shadow)}.pop-head{padding:16px;background:linear-gradient(135deg,var(--red),var(--red2))}.pop-head h3{font-size:17px;font-weight:900}.pop-head p{font-size:11px;margin-top:4px;opacity:.86;direction:ltr;text-align:right}.pop-body{padding:14px}.pop-img{width:100%;height:130px;object-fit:cover;border-radius:20px;margin-bottom:12px;filter:saturate(1.1) contrast(1.05)}.row{display:flex;justify-content:space-between;gap:14px;padding:9px 0;border-bottom:1px solid rgba(255,255,255,.07);font-size:12px}.row b{color:#ffb3bc}.pop-foot{display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:14px}.pop-foot a{text-align:center;text-decoration:none;border-radius:18px;padding:10px;color:white;font-weight:900;font-size:12px}.link-g{background:linear-gradient(135deg,var(--red),var(--red2))}.link-b{background:linear-gradient(135deg,var(--blue),#1d4ed8)}.maplibregl-ctrl-group{background:rgba(6,13,18,.82)!important;border:1px solid var(--border)!important;border-radius:14px!important;overflow:hidden}.maplibregl-ctrl button span{filter:invert(1)}.maplibregl-ctrl-attrib{display:none!important}
/* RED CINEMA V6 */
.map-wrap:after{content:"";position:absolute;inset:0;pointer-events:none;background:radial-gradient(circle at 50% 45%,transparent 0 45%,rgba(0,0,0,.30) 72%,rgba(0,0,0,.72) 100%),linear-gradient(90deg,rgba(239,35,60,.10),transparent 18%,transparent 82%,rgba(239,35,60,.10));mix-blend-mode:screen;opacity:.85}.map-wrap:before{content:"";position:absolute;inset:0;z-index:2;pointer-events:none;background:linear-gradient(to bottom,rgba(255,255,255,.025),transparent 8%,transparent 92%,rgba(0,0,0,.25)),repeating-linear-gradient(to bottom,rgba(255,255,255,.025) 0 1px,transparent 1px 6px);opacity:.22}.sidebar{box-shadow:-18px 0 60px rgba(0,0,0,.55), inset 1px 0 0 rgba(255,255,255,.05)}.hero{background:radial-gradient(circle at 18% 22%,rgba(255,255,255,.16),transparent 20%),linear-gradient(135deg,#ff2d45,#9f1024 55%,#050507)!important}.btn.red,.red{background:linear-gradient(135deg,#ff2d45,#86101d)!important}.btn.green,.green{background:linear-gradient(135deg,#ef233c,#7f0d1b)!important}.btn.blue,.blue{background:linear-gradient(135deg,#334155,#111827)!important;border:1px solid rgba(239,35,60,.25)}.tool-pill{box-shadow:0 14px 36px rgba(0,0,0,.34),0 0 0 1px rgba(255,255,255,.035) inset}.ctrl{box-shadow:0 16px 45px rgba(0,0,0,.45),0 0 22px rgba(239,35,60,.12)}.ctrl:hover{background:#ef233c!important}.stat strong,.title i,.name i,.row b{color:#ffb3bc!important}.stat:before{background:linear-gradient(90deg,transparent,#ef233c,#ffb3bc,transparent)}.item:hover{background:rgba(239,35,60,.12)!important;border-color:#ffb3bc!important}.maplibregl-ctrl-logo,.maplibregl-ctrl-attrib{display:none!important}.progress-label{display:flex;align-items:center;justify-content:space-between;font-size:12px;color:#ffd4d9;margin-top:12px}.bar span{background:linear-gradient(90deg,#7f0d1b,#ef233c,#ffb3bc,#ef233c)!important;box-shadow:0 0 24px rgba(239,35,60,.55)}
@media(max-width:920px){.app{grid-template-columns:1fr}.sidebar{position:absolute;right:0;width:88%;max-width:420px;transform:translateX(105%);transition:.25s;box-shadow:var(--shadow)}.sidebar.open{transform:translateX(0)}.stats{grid-template-columns:repeat(2,1fr)}.topbar{left:12px;right:12px}.tools-panel{top:106px;left:12px}.verify-actions,.btn-row{grid-template-columns:1fr}.controls{left:12px;bottom:16px;flex-wrap:wrap}}
</style>
</head>
<body class="scan-lines">
<div class="verify-screen" id="verifyScreen">
  <div class="verify-card">
    <div class="lock-icon"><i class="fa-solid fa-shield-halved"></i></div>
    <h1>چوونەژوورەوەی نەخشە</h1>
    <p>کۆدی ٦ ژمارەیی بنووسە، یان لە Telegram دوگمەی پشتڕاستکردنەوە دابگرە.</p>
    <input id="verifyInput" class="code-input" inputmode="numeric" maxlength="6" placeholder="000000" autocomplete="off">
    <div class="verify-actions">
      <button class="vbtn vbtn-green" onclick="checkVerify()"><i class="fa-solid fa-unlock-keyhole"></i> چوونەژوورەوە</button>
      <button class="vbtn vbtn-dark" onclick="sendVerifyAgain(true)"><i class="fa-brands fa-telegram"></i> ناردنی کۆد</button>
    </div>
    <div class="verify-error" id="verifyError">کۆدەکە هەڵەیە</div>
    <div class="hint"><i class="fa-solid fa-circle-info"></i> دوگمەی Telegram دەتباتە ناو نەخشەکە بەبێ نووسینی کۆد. ئەگەر نەکرا، کۆدی ٦ ژمارەیی بە دەست بنووسە.</div>
  </div>
</div>

<div class="loading" id="loading"><div class="loader"><b><i class="fa-solid fa-database"></i> داتاکان بار دەکرێن...</b><div class="progress-label"><span>بارکردنی داتا</span><b id="loadPercent">0%</b></div><div class="bar"><span></span></div></div></div>
<div class="toast" id="toast"><i class="fa-solid fa-circle-check" style="color:#ffb3bc"></i><span id="toastText"></span></div>

<div class="app" id="appShell">
  <aside class="sidebar" id="sidebar">
    <div class="hero">
      <div class="brand">
        <div class="brand-left"><div class="logo"><i class="fa-solid fa-map-location-dot"></i></div><div><h1>نەخشەی ڕاستەوخۆ</h1><p>SMART MAP ACTIVE // 2026</p></div></div>
        <div class="badge"><span class="pulse"></span> کارایە</div>
      </div>
      <div class="mini"><span><i class="fa-solid fa-check-square"></i> دڵنیایی کراوە</span><b>{{VERIFY_CODE}}</b></div>
    </div>

    <div class="block">
      <div class="title"><i class="fa-solid fa-magnifying-glass"></i> گەڕانی زیرەک</div>
      <div class="search"><i class="fa-solid fa-search"></i><input id="searchInput" placeholder="ناو / ژمارە / ناوچە / دۆخ" onkeydown="if(event.key==='Enter') loadData()"></div>
      <div class="btn-row"><button class="btn green" onclick="loadData()"><i class="fa-solid fa-bolt"></i> گەڕان</button><button class="btn dark" onclick="resetAll()"><i class="fa-solid fa-rotate-right"></i> نوێکردنەوە</button></div>
      <div class="btn-row"><button class="btn blue" onclick="myLocation()"><i class="fa-solid fa-location-crosshairs"></i> شوێنی من</button><button class="btn red" onclick="sendVerifyAgain(true)"><i class="fa-brands fa-telegram"></i> کۆد بنێرە</button></div>
    </div>

    <div class="block">
      <div class="title"><i class="fa-solid fa-chart-pie"></i> ئامارەکان</div>
      <div class="stats"><div class="stat"><strong id="totalCount">0</strong><span>هەموو</span></div><div class="stat"><strong id="pointCount">0</strong><span>لە نەخشە</span></div><div class="stat"><strong id="cityCount">0</strong><span>ناوچە</span></div><div class="stat"><strong id="activeCount">0</strong><span>چالاک</span></div></div>
    </div>

    <div class="block">
      <div class="title"><i class="fa-solid fa-circle-nodes"></i> قەبارەی خاڵەکان</div>
      <div class="range"><input id="pointSize" type="range" min="2" max="14" value="5" oninput="refreshLayer(currentData)"><span id="sizeText">5</span></div>
    </div>

    <div class="block"><div class="title"><i class="fa-solid fa-city"></i> فلتەر بە ناوچە</div><div class="chips" id="citiesContainer"></div></div>
    <div class="block" style="border-bottom:0"><div class="title"><i class="fa-solid fa-list"></i> ئەنجامەکان</div></div>
    <div class="results" id="resultsList"></div>
  </aside>

  <main class="map-wrap">
    <div id="map"></div>
    <div class="topbar"><div class="glass"><b><i class="fa-solid fa-satellite-dish"></i> نەخشەی تاریک</b><div>LABELS HIDDEN BY DEFAULT</div></div><div class="glass"><b id="dbStatus">داتابەیس</b><div id="dbPath">data.db</div></div></div>
    <div class="tools-panel" id="toolsPanel">
      <label class="tool-pill"><span><i class="fa-solid fa-moon"></i> Dark Map</span><input id="darkToggle" type="checkbox" checked onchange="switchMapStyle()"></label>
      <label class="tool-pill"><span><i class="fa-solid fa-tag"></i> ناوی شوێنەکان</span><input id="labelToggle" type="checkbox" onchange="toggleLabels()"></label>
      <label class="tool-pill"><span><i class="fa-solid fa-layer-group"></i> پانێڵی ئامراز</span><input type="checkbox" checked onchange="toggleToolsMini(this)"></label>
    </div>
    <div class="controls"><button class="ctrl" onclick="toggleSidebar()" title="لیست"><i class="fa-solid fa-bars"></i></button><button class="ctrl" onclick="myLocation()" title="شوێنی من"><i class="fa-solid fa-crosshairs"></i></button><button class="ctrl" onclick="fitKurdistan()" title="کوردستان"><i class="fa-solid fa-map"></i></button><button class="ctrl" onclick="toggleLabelsButton()" title="ناوی شوێن"><i class="fa-solid fa-eye-slash"></i></button><button class="ctrl" onclick="zoomIn()" title="نزیککردنەوە"><i class="fa-solid fa-plus"></i></button><button class="ctrl" onclick="zoomOut()" title="دوورخستنەوە"><i class="fa-solid fa-minus"></i></button><button class="ctrl" onclick="togglePitch()" title="3D"><i class="fa-solid fa-cube"></i></button><button class="ctrl" onclick="toggleFullscreen()" title="Fullscreen"><i class="fa-solid fa-expand"></i></button></div>
  </main>
</div>

<script src="https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.js"></script>
<script src="https://unpkg.com/deck.gl@8.9.35/dist.min.js"></script>
<script>
let map=null, deckOverlay=null, selectedCity='', userMarker=null, unlocked=false, isFullscreen=false, currentData=[];
let labelLayerId='labelLayer';
const darkTiles='https://basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png';
const darkLabelTiles='https://basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png';
const lightTiles='https://basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png';
const lightLabelTiles='https://basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png';
const cityImages={"هەولێر":"https://upload.wikimedia.org/wikipedia/commons/thumb/0/0b/Erbil_Citadel.jpg/800px-Erbil_Citadel.jpg","سلێمانی":"https://upload.wikimedia.org/wikipedia/commons/thumb/2/2f/Sulaymaniyah_Mountain.jpg/800px-Sulaymaniyah_Mountain.jpg","دهۆک":"https://upload.wikimedia.org/wikipedia/commons/thumb/3/3a/Duhok_dam.jpg/800px-Duhok_dam.jpg","کەرکووک":"https://upload.wikimedia.org/wikipedia/commons/thumb/6/6b/Kirkuk_Citadel.jpg/800px-Kirkuk_Citadel.jpg","هەڵەبجە":"https://upload.wikimedia.org/wikipedia/commons/thumb/7/7f/Halabja_waterfall.jpg/800px-Halabja_waterfall.jpg","زاخۆ":"https://upload.wikimedia.org/wikipedia/commons/thumb/8/8b/Zakho_bridge.jpg/800px-Zakho_bridge.jpg"};
function toast(m,err=false){const t=document.getElementById('toast'),s=document.getElementById('toastText'),i=t.querySelector('i');s.innerText=m;i.className=err?'fa-solid fa-circle-exclamation':'fa-solid fa-circle-check';i.style.color=err?'#ff8a8a':'#ffb3bc';t.style.borderColor=err?'#ef4444':'#22c55e';t.classList.add('show');setTimeout(()=>t.classList.remove('show'),3300)}
function safe(v){return (v===null||v===undefined||v==='')?'—':String(v)} function getName(x){return x.Name||x.SubscriberName||x.FullName||x.CustomerName||'بێ ناو'}
function makeStyle(){const dark=document.getElementById('darkToggle')?.checked!==false;return {version:8,sources:{base:{type:'raster',tiles:[dark?darkTiles:lightTiles],tileSize:256,attribution:'© OpenStreetMap © CARTO'},labels:{type:'raster',tiles:[dark?darkLabelTiles:lightLabelTiles],tileSize:256}},layers:[{id:'base',type:'raster',source:'base'},{id:labelLayerId,type:'raster',source:'labels',layout:{visibility:(document.getElementById('labelToggle')?.checked?'visible':'none')}}]};}
async function checkVerify(){const code=document.getElementById('verifyInput').value.trim(),er=document.getElementById('verifyError');er.classList.remove('show');if(code.length!==6){er.innerText='تکایە کۆدی ٦ ژمارەیی بنووسە';er.classList.add('show');return}try{const r=await fetch('/api/verify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code})});const d=await r.json();if(d.ok){unlockApp();toast('بە سەرکەوتوویی چوویتە ژوورەوە')}else{er.innerText='کۆدەکە هەڵەیە';er.classList.add('show')}}catch(e){er.innerText='هەڵەی پەیوەندی';er.classList.add('show')}}
function unlockApp(){unlocked=true;document.getElementById('verifyScreen').classList.add('hidden');document.getElementById('appShell').classList.add('unlocked');initMap()}
async function sendVerifyAgain(show){try{const r=await fetch('/api/send-verify',{method:'POST'});const d=await r.json();if(show)toast(d.ok?'کۆد و دوگمەی چوونەژوورەوە نێردرایەوە':(d.message||'ناردن شکستی هێنا'),!d.ok)}catch(e){if(show)toast('هەڵەی پەیوەندی Telegram',true)}}
function initMap(){if(map)return;map=new maplibregl.Map({container:'map',style:makeStyle(),center:[44.01,36.19],zoom:8,pitch:46,bearing:-6,maxPitch:80});map.addControl(new maplibregl.NavigationControl(),'top-right');map.addControl(new maplibregl.ScaleControl({maxWidth:120,unit:'metric'}),'bottom-right');deckOverlay=new deck.MapboxOverlay({interleaved:false,layers:[]});map.addControl(deckOverlay);map.on('load',async()=>{await loadStats();await loadCities();await loadData()});map.on('moveend',()=>loadData());map.on('zoomend',()=>loadData())}
function switchMapStyle(){if(!map)return;const center=map.getCenter(),zoom=map.getZoom(),pitch=map.getPitch(),bearing=map.getBearing();map.setStyle(makeStyle());map.once('styledata',()=>{map.jumpTo({center,zoom,pitch,bearing});toggleLabels();refreshLayer(currentData)});toast(document.getElementById('darkToggle').checked?'Dark map چالاک کرا':'Light map چالاک کرا')}
function toggleLabels(){if(!map||!map.getLayer(labelLayerId))return;const show=document.getElementById('labelToggle').checked;map.setLayoutProperty(labelLayerId,'visibility',show?'visible':'none');toast(show?'ناوی شوێنەکان نیشان دران':'ناوی شوێنەکان شاردراوە')}
function toggleLabelsButton(){const cb=document.getElementById('labelToggle');cb.checked=!cb.checked;toggleLabels()}
function toggleToolsMini(cb){const p=document.getElementById('toolsPanel');[...p.querySelectorAll('.tool-pill')].forEach((x,i)=>{if(i>0)x.style.display=cb.checked?'flex':'none'});toast(cb.checked?'ئامرازەکان نیشان دران':'ئامرازەکان کورت کران')}
function fitKurdistan(){if(map)map.flyTo({center:[44.01,36.19],zoom:8,pitch:46,bearing:-6,duration:900})}
function colorOf(x){const st=String(x.Status||'').toLowerCase();if(st.includes('ناچالاک')||st.includes('inactive')||st.includes('off'))return [239,68,68,230];if(st.includes('چالاک')||st.includes('active'))return [239,35,60,235];return [56,189,248,220]}
function refreshLayer(data){if(!deckOverlay)return;const size=Number(document.getElementById('pointSize')?.value||9);document.getElementById('sizeText').innerText=size;deckOverlay.setProps({layers:[new deck.ScatterplotLayer({id:'points-glow',data,pickable:false,radiusUnits:'pixels',radiusMinPixels:size+5,radiusMaxPixels:size+18,getPosition:d=>[Number(d.lng),Number(d.lat)],getFillColor:d=>{const c=colorOf(d);return [c[0],c[1],c[2],45]},stroked:false,filled:true,getRadius:size+6}),new deck.ScatterplotLayer({id:'points',data,pickable:true,radiusUnits:'pixels',radiusMinPixels:size,radiusMaxPixels:size+15,getPosition:d=>[Number(d.lng),Number(d.lat)],getFillColor:d=>colorOf(d),getLineColor:[255,255,255,220],lineWidthMinPixels:1.7,stroked:true,filled:true,getRadius:size,onClick:info=>{if(info.object)showPopup(info.object)}})]})}
async function loadStats(){try{const r=await fetch('/api/stats'),s=await r.json();document.getElementById('totalCount').innerText=s.total||0;document.getElementById('cityCount').innerText=s.cities||0;document.getElementById('activeCount').innerText=s.active||0;document.getElementById('dbPath').innerText=s.db_path||'data.db';document.getElementById('dbStatus').innerText=s.exists&&!s.error?'✅ داتابەیس کارایە':'❌ کێشەی داتابەیس';if(s.error)toast(s.error,true)}catch(e){document.getElementById('dbStatus').innerText='❌ هەڵەی داتابەیس'}}
async function loadCities(){try{const r=await fetch('/api/cities'),data=await r.json(),c=document.getElementById('citiesContainer');c.innerHTML='';const all=document.createElement('div');all.className='chip active';all.innerHTML='<i class="fa-solid fa-globe"></i> هەموو';all.onclick=()=>selectCity('',all);c.appendChild(all);data.forEach(city=>{const el=document.createElement('div');el.className='chip';el.innerHTML=`<i class="fa-solid fa-location-dot"></i> ${safe(city.Area)} <small>(${city.count})</small>`;el.onclick=()=>selectCity(city.Area,el);c.appendChild(el)})}catch(e){console.log(e)}}
function selectCity(city,el){selectedCity=city;document.querySelectorAll('.chip').forEach(x=>x.classList.remove('active'));el.classList.add('active');loadData()}
async function loadData(){if(!unlocked||!map||!map.getBounds)return;document.getElementById('loading').classList.add('active');try{const b=map.getBounds(),q=document.getElementById('searchInput').value.trim();const p=new URLSearchParams({west:b.getWest(),south:b.getSouth(),east:b.getEast(),north:b.getNorth(),q,city:selectedCity});const r=await fetch('/api/points?'+p.toString()),data=await r.json();currentData=Array.isArray(data)?data:[];document.getElementById('pointCount').innerText=currentData.length;refreshLayer(currentData);updateResults(currentData)}catch(e){toast('هەڵە لە بارکردنی داتا',true)}finally{document.getElementById('loading').classList.remove('active')}}
function updateResults(data){const c=document.getElementById('resultsList');c.innerHTML='';if(!data.length){c.innerHTML='<div class="item" style="text-align:center"><i class="fa-regular fa-circle-xmark"></i> هیچ ئەنجامێک نەدۆزرایەوە</div>';return}data.slice(0,220).forEach(x=>{const d=document.createElement('div');d.className='item';d.innerHTML=`<div class="name"><i class="fa-solid fa-user"></i>${safe(getName(x))}</div><div class="meta"><span class="pill">ژمارە: ${safe(x.AccountNo)}</span><span class="pill">ناوچە: ${safe(x.Area)}</span><span class="pill">دۆخ: ${safe(x.Status)}</span></div>`;d.onclick=()=>showPopup(x);c.appendChild(d)})}
function showPopup(x){const city=x.Area||'نادیار',img=cityImages[city]||'https://via.placeholder.com/800x400/07100d/ffffff?text=Kurdistan+Today';const lat=Number(x.lat),lng=Number(x.lng);if(!Number.isFinite(lat)||!Number.isFinite(lng)){toast('شوێنی ئەم داتایە دروست نییە',true);return}const h=`<div class="popup"><div class="pop-head"><h3><i class="fa-solid fa-user"></i> ${safe(getName(x))}</h3><p>${safe(x.AccountNo)}</p></div><div class="pop-body"><img class="pop-img" src="${img}" onerror="this.style.display='none'"><div class="row"><b>ناوچە</b><span>${safe(x.Area)}</span></div><div class="row"><b>دۆخ</b><span>${safe(x.Status)}</span></div><div class="row"><b>شوێن</b><span>${lat.toFixed(5)} / ${lng.toFixed(5)}</span></div></div><div class="pop-foot"><a class="link-g" href="https://www.google.com/maps?q=${lat},${lng}" target="_blank"><i class="fa-brands fa-google"></i> Google</a><a class="link-b" href="https://www.openstreetmap.org/?mlat=${lat}&mlon=${lng}" target="_blank"><i class="fa-solid fa-map"></i> OSM</a></div></div>`;new maplibregl.Popup().setLngLat([lng,lat]).setHTML(h).setMaxWidth('390px').addTo(map);map.flyTo({center:[lng,lat],zoom:14,duration:800})}
function resetAll(){selectedCity='';document.getElementById('searchInput').value='';document.querySelectorAll('.chip').forEach(x=>x.classList.remove('active'));const f=document.querySelector('.chip');if(f)f.classList.add('active');fitKurdistan();loadData()}
function myLocation(){if(!navigator.geolocation){toast('Geolocation پشتگیری ناکرێت',true);return}navigator.geolocation.getCurrentPosition(pos=>{const lng=pos.coords.longitude,lat=pos.coords.latitude;if(userMarker)userMarker.remove();userMarker=new maplibregl.Marker({color:'#22c55e'}).setLngLat([lng,lat]).setPopup(new maplibregl.Popup().setHTML('<b>شوێنی ئێستا</b>')).addTo(map);map.flyTo({center:[lng,lat],zoom:13,duration:900});toast('شوێنت دۆزرایەوە')},()=>toast('نەتوانرا شوێنت بدۆزرێتەوە',true),{enableHighAccuracy:true,timeout:10000})}
function toggleSidebar(){document.getElementById('sidebar').classList.toggle('open')}
function zoomIn(){ if(map) map.zoomIn({duration:350}); }
function zoomOut(){ if(map) map.zoomOut({duration:350}); }
let pitched=true;
function togglePitch(){ if(!map) return; pitched=!pitched; map.easeTo({pitch:pitched?58:0,bearing:pitched?-10:0,duration:700}); }
function setLoadPercent(v){ const el=document.getElementById('loadPercent'); if(el) el.innerText=v+'%'; }
function toggleFullscreen(){if(!isFullscreen){document.documentElement.requestFullscreen?.();isFullscreen=true}else{document.exitFullscreen?.();isFullscreen=false}}
document.getElementById('verifyInput').focus();
</script>
</body>
</html>
'''

# =====================================================
# ROUTES
# =====================================================

@app.route("/")
def home():
    already = bool(session.get("verified"))
    html = render_template_string(HTML_TEMPLATE, VERIFY_CODE=VERIFY_CODE)
    if already:
        html = html.replace("let map=null, deckOverlay=null, selectedCity='', userMarker=null, unlocked=false", "let map=null, deckOverlay=null, selectedCity='', userMarker=null, unlocked=true")
        html = html.replace("document.getElementById('verifyInput').focus();", "unlockApp();")
    return html


@app.route("/quick-login/<token>")
def quick_login(token):
    if token == QUICK_LOGIN_TOKEN:
        session["verified"] = True
        session.permanent = True
        return redirect("/")
    return "Invalid quick-login token", 403


@app.route("/api/verify", methods=["POST"])
def api_verify():
    data = request.get_json(silent=True) or {}
    code = str(data.get("code", "")).strip()
    if code == VERIFY_CODE:
        session["verified"] = True
        session.permanent = True
        return jsonify({"ok": True})
    return jsonify({"ok": False})


@app.route("/api/send-verify", methods=["POST"])
def api_send_verify():
    ok, msg = send_verify_code()
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/telegram-chats")
def api_telegram_chats():
    return jsonify(get_updates_chat_ids())


@app.route("/api/stats")
@verified_required
def api_stats():
    return jsonify(db_stats())


@app.route("/api/cities")
@verified_required
def api_cities():
    if not db_exists():
        return jsonify([])

    merged = {}
    for db_file in get_db_files():
        try:
            conn = get_conn(db_file)
            cur = conn.cursor()
            if not has_table(cur, "subscribers"):
                conn.close()
                continue
            area_col = choose_column(cur, ["Area", "City", "Zone", "Region"], None)
            lat_col = choose_column(cur, ["lat", "latitude", "Lat", "Latitude"], "lat")
            lng_col = choose_column(cur, ["lng", "lon", "longitude", "Lng", "Longitude"], "lng")
            area_expr = f"COALESCE({area_col}, 'نادیار')" if area_col else "'نادیار'"
            rows = cur.execute(f"""
                SELECT {area_expr} AS Area, COUNT(*) AS count
                FROM subscribers
                WHERE {lat_col} IS NOT NULL AND {lng_col} IS NOT NULL
                GROUP BY {area_expr}
            """).fetchall()
            conn.close()
            for r in rows:
                area = r["Area"] or "نادیار"
                merged[area] = merged.get(area, 0) + int(r["count"] or 0)
        except Exception as e:
            print("Cities API DB error", db_file, e)

    data = [{"Area": k, "count": v} for k, v in sorted(merged.items(), key=lambda x: x[1], reverse=True)[:120]]
    return jsonify(data)


@app.route("/api/points")
@verified_required
def api_points():
    if not db_exists():
        return jsonify([])

    west = safe_float(request.args.get("west"), 42.5)
    south = safe_float(request.args.get("south"), 34.5)
    east = safe_float(request.args.get("east"), 47.0)
    north = safe_float(request.args.get("north"), 38.3)
    q = request.args.get("q", "").strip()
    city = request.args.get("city", "").strip()
    max_total = 30000

    all_rows = []

    for db_file in get_db_files():
        if len(all_rows) >= max_total:
            break
        try:
            conn = get_conn(db_file)
            cur = conn.cursor()
            if not has_table(cur, "subscribers"):
                conn.close()
                continue

            name_col = choose_column(cur, ["SubscriberName", "Name", "FullName", "CustomerName", "FirstName"], "rowid")
            account_col = choose_column(cur, ["AccountNo", "Account", "Code", "ID", "SubscriberID"], "rowid")
            area_col = choose_column(cur, ["Area", "City", "Zone", "Region"], None)
            status_col = choose_column(cur, ["Status", "State"], None)
            lat_col = choose_column(cur, ["lat", "latitude", "Lat", "Latitude"], "lat")
            lng_col = choose_column(cur, ["lng", "lon", "longitude", "Lng", "Longitude"], "lng")

            area_expr = f"COALESCE({area_col}, 'نادیار')" if area_col else "'نادیار'"
            status_expr = f"COALESCE({status_col}, 'چالاک')" if status_col else "'چالاک'"

            sql = f"""
                SELECT
                    {account_col} AS AccountNo,
                    {name_col} AS Name,
                    {name_col} AS FullName,
                    {lat_col} AS lat,
                    {lng_col} AS lng,
                    {area_expr} AS Area,
                    {status_expr} AS Status
                FROM subscribers
                WHERE {lat_col} IS NOT NULL
                  AND {lng_col} IS NOT NULL
                  AND {lat_col} BETWEEN ? AND ?
                  AND {lng_col} BETWEEN ? AND ?
            """
            params = [south, north, west, east]

            if city and city not in ("هەموو", "ALL", "ALL SECTORS"):
                sql += f" AND {area_expr} = ? "
                params.append(city)

            if q:
                sql += f"""
                    AND (
                        CAST({account_col} AS TEXT) LIKE ?
                        OR CAST({name_col} AS TEXT) LIKE ?
                        OR CAST({area_expr} AS TEXT) LIKE ?
                        OR CAST({status_expr} AS TEXT) LIKE ?
                    )
                """
                like = f"%{q}%"
                params += [like, like, like, like]

            remaining = max_total - len(all_rows)
            sql += f" LIMIT {remaining}"
            rows = cur.execute(sql, params).fetchall()
            conn.close()
            for r in rows:
                item = dict(r)
                item["SourceDB"] = os.path.basename(db_file)
                all_rows.append(item)
        except Exception as e:
            print("Points API DB error", db_file, e)

    return jsonify(all_rows)

# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    print("=" * 76)
    print(f"🟢 {APP_NAME} - Sorani Pro Dark Edition v{APP_VERSION}")
    print("=" * 76)
    print(f"🔐 کۆدی دەستی: {VERIFY_CODE}")
    print(f"✅ Quick Login: {QUICK_LOGIN_URL}")
    print("💾 DATABASE FILES:", ", ".join(os.path.basename(x) for x in get_db_files()) or "No database found")
    print(f"📡 TELEGRAM GROUP: {GROUP_ID}")
    print(f"🌐 PC URL: {APP_URL}")
    print(f"📱 MOBILE/LAN URL: {MOBILE_URL}")
    print("=" * 76)

    ok, msg = send_verify_code()
    if ok:
        print("✅ Telegram: کۆد و دوگمەی راستەوخۆ نێردرا")
    else:
        print("⚠️ Telegram:", msg)
        print("💡 BOT_TOKEN و GROUP_ID نوێ دابنێ، bot بکە بە گرووپدا، /start یان نامە بنێرە.")

    threading.Thread(target=open_webapp_window, daemon=True).start()
    app.run(debug=False, host=APP_HOST, port=APP_PORT, use_reloader=False, threaded=True)
