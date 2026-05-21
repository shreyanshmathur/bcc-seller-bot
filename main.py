import os
import re
import json
import base64
import logging
import asyncio
from datetime import datetime
from io import BytesIO

from groq import AsyncGroq
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

groq_client = AsyncGroq(api_key=GROQ_API_KEY)

VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
TEXT_MODEL = "llama-3.3-70b-versatile"
MINIMUM_ITEMS = 10
MAX_LOG = 500

# ── Global state (shared between bot and dashboard) ───────────────────────────
sessions: dict[int, dict] = {}
chat_info: dict[int, dict] = {}
message_log: list[dict] = []

# ── Dashboard HTML ─────────────────────────────────────────────────────────────
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>BCC Seller Bot — Dashboard</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <style>
    * { font-family: 'Inter', sans-serif; }
    body { background: #030712; }
    .pulse { animation: pulse 2s cubic-bezier(0.4,0,0.6,1) infinite; }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.25} }
    .feed { overflow-y: auto; height: calc(100vh - 220px); }
    .sessions-list { overflow-y: auto; height: calc(100vh - 220px); }
    ::-webkit-scrollbar { width: 3px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: #1f2937; border-radius: 2px; }
    .msg-in  { border-left: 3px solid #3b82f6; }
    .msg-out { border-left: 3px solid #10b981; }
    .fade-in { animation: fadein 0.3s ease; }
    @keyframes fadein { from{opacity:0;transform:translateY(4px)} to{opacity:1;transform:translateY(0)} }
  </style>
</head>
<body class="text-gray-100 min-h-screen">

  <!-- Header -->
  <div class="border-b border-gray-800/60 px-6 py-3 flex items-center justify-between bg-gray-950/80 backdrop-blur sticky top-0 z-10">
    <div class="flex items-center gap-3">
      <div class="w-7 h-7 bg-emerald-500 rounded-md flex items-center justify-center text-xs font-bold text-white">B</div>
      <span class="font-semibold text-white text-sm">BCC Seller Bot</span>
      <span class="text-gray-600 text-xs">/ Dashboard</span>
    </div>
    <div class="flex items-center gap-2">
      <div class="w-1.5 h-1.5 bg-emerald-400 rounded-full pulse" id="live-dot"></div>
      <span class="text-xs text-gray-500" id="last-updated">Connecting…</span>
    </div>
  </div>

  <!-- Stats row -->
  <div class="grid grid-cols-4 gap-3 px-6 pt-4 pb-4">
    <div class="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4">
      <div class="text-2xl font-bold text-white tabular-nums" id="s-total">—</div>
      <div class="text-xs text-gray-500 mt-0.5">Total Sessions</div>
    </div>
    <div class="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4">
      <div class="text-2xl font-bold text-emerald-400 tabular-nums" id="s-active">—</div>
      <div class="text-xs text-gray-500 mt-0.5">Active Now</div>
    </div>
    <div class="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4">
      <div class="text-2xl font-bold text-blue-400 tabular-nums" id="s-photos">—</div>
      <div class="text-xs text-gray-500 mt-0.5">Photos Analysed</div>
    </div>
    <div class="bg-gray-900/60 border border-gray-800/50 rounded-xl p-4">
      <div class="text-2xl font-bold text-violet-400 tabular-nums" id="s-items">—</div>
      <div class="text-xs text-gray-500 mt-0.5">Items Declared</div>
    </div>
  </div>

  <!-- Main panels -->
  <div class="flex gap-0 px-0 border-t border-gray-800/50">

    <!-- Message feed (left, 62%) -->
    <div class="flex-1" style="min-width:0">
      <div class="px-6 py-2.5 border-b border-gray-800/50 flex items-center justify-between bg-gray-950/40">
        <span class="text-xs font-medium text-gray-400 uppercase tracking-wider">Live Message Feed</span>
        <span class="text-xs text-gray-600" id="msg-count">—</span>
      </div>
      <div class="feed px-6 py-3 space-y-2" id="feed">
        <div class="text-center text-gray-700 text-xs pt-10">Waiting for messages…</div>
      </div>
    </div>

    <!-- Sessions panel (right, 38%) -->
    <div class="w-80 xl:w-96 border-l border-gray-800/50 shrink-0">
      <div class="px-5 py-2.5 border-b border-gray-800/50 bg-gray-950/40">
        <span class="text-xs font-medium text-gray-400 uppercase tracking-wider">Sessions</span>
      </div>
      <div class="sessions-list" id="sessions">
        <div class="text-center text-gray-700 text-xs pt-10">No sessions yet</div>
      </div>
    </div>

  </div>

  <script>
    const STEP_META = {
      greeting:          { label: 'Greeting',    cls: 'bg-yellow-500/15 text-yellow-300 ring-1 ring-yellow-500/30' },
      collecting_photos: { label: 'Collecting',  cls: 'bg-blue-500/15 text-blue-300 ring-1 ring-blue-500/30' },
      confirming:        { label: 'Confirming',  cls: 'bg-orange-500/15 text-orange-300 ring-1 ring-orange-500/30' },
      done:              { label: 'Done',         cls: 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30' },
    };

    let prevMsgCount = -1;

    function esc(s) {
      return String(s ?? '')
        .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    function fmtTime(ts) {
      // ts is like "2026-05-21T14:32:07"
      const t = ts.split('T')[1] || ts;
      return t.slice(0,5);
    }

    function renderFeed(messages) {
      document.getElementById('msg-count').textContent = messages.length + ' messages';
      if (messages.length === prevMsgCount) return;
      prevMsgCount = messages.length;

      if (!messages.length) {
        document.getElementById('feed').innerHTML = '<div class="text-center text-gray-700 text-xs pt-10">Waiting for messages…</div>';
        return;
      }

      const html = messages.map((m, i) => {
        const isIn = m.direction === 'in';
        const isPhoto = m.type === 'photo';
        const panelCls = isIn ? 'msg-in bg-gray-900/50' : 'msg-out bg-gray-900/25';
        const nameCls  = isIn ? 'text-blue-400' : 'text-emerald-400';
        const sender   = isIn ? esc(m.chat_name) : '← Bot';
        const preview  = esc(m.content.slice(0, 400)) + (m.content.length > 400 ? '…' : '');
        const stepBadge = m.step
          ? '<span class="ml-1 text-gray-600 text-xs">' + esc(m.step) + '</span>'
          : '';
        const photoBadge = isPhoto
          ? '<span class="ml-1 text-xs bg-violet-500/20 text-violet-300 px-1.5 py-0.5 rounded">photo</span>'
          : '';

        return '<div class="' + panelCls + ' rounded-lg px-3 py-2' + (i === 0 ? ' fade-in' : '') + '">'
          + '<div class="flex items-center gap-1.5 mb-1">'
          + '<span class="font-semibold text-xs ' + nameCls + '">' + sender + '</span>'
          + stepBadge + photoBadge
          + '<span class="ml-auto text-gray-600 text-xs tabular-nums">' + fmtTime(m.ts) + '</span>'
          + '</div>'
          + '<pre class="text-gray-300 text-xs leading-relaxed whitespace-pre-wrap font-sans">' + preview + '</pre>'
          + '</div>';
      }).join('');

      const feed = document.getElementById('feed');
      const atBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 60;
      feed.innerHTML = html;
      if (atBottom) feed.scrollTop = feed.scrollHeight;
    }

    function renderSessions(sessions) {
      if (!sessions.length) {
        document.getElementById('sessions').innerHTML = '<div class="text-center text-gray-700 text-xs pt-10">No sessions yet</div>';
        return;
      }
      const html = sessions.map(s => {
        const meta  = STEP_META[s.step] || { label: s.step, cls: 'bg-gray-600/15 text-gray-400' };
        const pct   = s.total_items > 0 ? Math.round(s.photos_received / s.total_items * 100) : 0;
        const prog  = s.total_items > 0 ? s.photos_received + ' / ' + s.total_items : '—';

        return '<div class="px-5 py-4 border-b border-gray-800/40 hover:bg-gray-900/30 transition-colors">'
          + '<div class="flex items-center justify-between mb-2">'
          + '<span class="text-sm font-medium text-gray-200 truncate">' + esc(s.chat_name) + '</span>'
          + '<span class="text-xs px-2 py-0.5 rounded-full ' + meta.cls + '">' + meta.label + '</span>'
          + '</div>'
          + '<div class="text-xs text-gray-600 mb-2">ID: ' + s.chat_id + '</div>'
          + (s.total_items > 0
              ? '<div>'
                + '<div class="flex justify-between text-xs text-gray-500 mb-1.5">'
                + '<span>Photos</span><span class="tabular-nums">' + prog + '</span>'
                + '</div>'
                + '<div class="h-1 bg-gray-800 rounded-full overflow-hidden">'
                + '<div class="h-full bg-blue-500 rounded-full transition-all duration-700" style="width:' + pct + '%"></div>'
                + '</div>'
                + '</div>'
              : '<div class="text-xs text-gray-700">No items declared yet</div>')
          + '</div>';
      }).join('');
      document.getElementById('sessions').innerHTML = html;
    }

    async function refresh() {
      try {
        const res  = await fetch('/api/data');
        const data = await res.json();

        document.getElementById('s-total').textContent  = data.stats.total_sessions;
        document.getElementById('s-active').textContent = data.stats.active_sessions;
        document.getElementById('s-photos').textContent = data.stats.total_photos;
        document.getElementById('s-items').textContent  = data.stats.total_items;

        renderFeed(data.messages);
        renderSessions(data.sessions);

        document.getElementById('last-updated').textContent = 'Updated ' + new Date().toLocaleTimeString();
        document.getElementById('live-dot').style.opacity = '1';
      } catch {
        document.getElementById('last-updated').textContent = 'Connection lost';
        document.getElementById('live-dot').style.opacity  = '0.2';
      }
    }

    refresh();
    setInterval(refresh, 2000);
  </script>
</body>
</html>"""

# ── Dashboard API ─────────────────────────────────────────────────────────────
api = FastAPI(docs_url=None, redoc_url=None)


@api.get("/", response_class=HTMLResponse)
async def dashboard_index():
    return DASHBOARD_HTML


@api.get("/api/data")
async def dashboard_data():
    return {
        "stats": {
            "total_sessions":  len(sessions),
            "active_sessions": sum(1 for s in sessions.values() if s["step"] != "done"),
            "total_photos":    sum(s["photos_received"] for s in sessions.values()),
            "total_items":     sum(s["total_items"] for s in sessions.values()),
        },
        "sessions": [
            {
                "chat_id":        cid,
                "chat_name":      chat_info.get(cid, {}).get("display", str(cid)),
                "step":           s["step"],
                "total_items":    s["total_items"],
                "photos_received": s["photos_received"],
            }
            for cid, s in sessions.items()
        ],
        "messages": list(reversed(message_log[-150:])),
    }


# ── Message logging ────────────────────────────────────────────────────────────

def track_user(update: Update) -> None:
    user = update.effective_user
    if not user:
        return
    name = user.first_name or ""
    if user.last_name:
        name += f" {user.last_name}"
    if user.username:
        name += f" (@{user.username})"
    chat_info[update.effective_chat.id] = {"display": name.strip() or str(update.effective_chat.id)}


def _append_log(chat_id: int, direction: str, msg_type: str, content: str) -> None:
    message_log.append({
        "ts":        datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "chat_id":   chat_id,
        "chat_name": chat_info.get(chat_id, {}).get("display", str(chat_id)),
        "direction": direction,
        "type":      msg_type,
        "content":   content,
        "step":      sessions.get(chat_id, {}).get("step", ""),
    })
    if len(message_log) > MAX_LOG:
        message_log.pop(0)


def log_in(update: Update, msg_type: str, content: str) -> None:
    _append_log(update.effective_chat.id, "in", msg_type, content)


async def send(update: Update, text: str) -> None:
    """Reply to the user and log the outgoing message."""
    _append_log(update.effective_chat.id, "out", "text", text)
    await update.message.reply_text(text)


# ── Session management ────────────────────────────────────────────────────────

def get_session(chat_id: int) -> dict:
    if chat_id not in sessions:
        sessions[chat_id] = _new_session()
    return sessions[chat_id]


def reset_session(chat_id: int) -> dict:
    sessions[chat_id] = _new_session()
    return sessions[chat_id]


def _new_session() -> dict:
    return {
        "step":            "greeting",
        "total_items":     0,
        "photos_received": 0,
        "analyses":        [],
        "history":         [],
    }


# ── Formatting helpers ────────────────────────────────────────────────────────

def _inr(amount: int) -> str:
    return f"Rs {amount:,}"


def _ref() -> str:
    return f"BCC-{datetime.now().strftime('%Y%m%d-%H%M')}"


def _item_message(analysis: dict, num: int, total: int) -> str:
    remaining = total - num
    tail = f"{num} done. {remaining} more to go." if remaining > 0 else f"All {total} items analysed."
    return (
        f"Item {num} of {total}\n\n"
        f"Brand: {analysis['brand']}\n"
        f"Category: {analysis['category']}\n"
        f"Condition: {analysis['condition_score']} / 5 — {analysis['condition_notes']}\n\n"
        f"Estimated price: {_inr(analysis['price_low'])} — {_inr(analysis['price_high'])}\n\n"
        f"{tail}"
    )


def _summary_message(session: dict) -> str:
    analyses  = session["analyses"]
    total     = session["total_items"]
    total_low = sum(a["price_low"] for a in analyses)
    total_hi  = sum(a["price_high"] for a in analyses)

    lines = [f"Here's the summary for your {total}-item drop-off:", ""]
    for i, a in enumerate(analyses, 1):
        lines.append(f"{i}. {a['brand']} {a['category']} — {_inr(a['price_low'])} to {_inr(a['price_high'])}")
    lines += [
        "",
        f"Total estimated value: {_inr(total_low)} — {_inr(total_hi)}",
        "",
        "Would you like to confirm this drop-off?",
        "",
        "Reply Yes to proceed or No to cancel.",
    ]
    return "\n".join(lines)


def _confirmation_message(session: dict) -> str:
    analyses  = session["analyses"]
    total_low = sum(a["price_low"] for a in analyses)
    total_hi  = sum(a["price_high"] for a in analyses)
    ref       = _ref()
    return (
        f"Your drop-off is confirmed.\n\n"
        f"Reference: {ref}\n"
        f"Items declared: {len(analyses)}\n"
        f"Total estimated value: {_inr(total_low)} — {_inr(total_hi)}\n\n"
        f"Bring your items to:\n"
        f"Bombay Closet Cleanse, [store address]\n"
        f"Drop-off hours: 11am to 7pm, Tuesday to Sunday\n\n"
        f"Our team will review each item on arrival. The AI estimates are a guide — "
        f"final prices are confirmed by staff.\n\n"
        f"See you soon."
    )


# ── AI calls ──────────────────────────────────────────────────────────────────

VISION_SYSTEM_PROMPT = """You are a senior buying specialist at Bombay Closet Cleanse (BCC), a premium pre-loved fashion platform in India.

BCC's average resale price is Rs 500. Items are sourced from sellers at under Rs 50.

You know the Indian resale market: Vinted, Depop, OLX, Carousell India, Instagram thrift accounts.

High-desirability brands for Indian consumers: Zara, H&M, Mango, AND, W, Biba, FabIndia, Nike, Adidas, Levis, Tommy Hilfiger, Calvin Klein, vintage denim, Y2K silhouettes, handloom, block-print pieces, Bollywood-adjacent styles.

Analyse the clothing item in the image and respond ONLY with valid JSON using exactly these keys:
- brand: visible brand name, or "Unbranded" if not visible
- category: type of garment (e.g. Dress, T-shirt, Jeans, Kurta, Blazer, etc.)
- condition_score: integer 1-5 where 1=poor, 5=excellent
- condition_notes: one sentence describing visible condition
- price_low: integer, lower bound of estimated INR resale price BCC could charge
- price_high: integer, upper bound of estimated INR resale price BCC could charge
- confidence: "low", "medium", or "high"

If the image is not a clothing or fashion item, respond with:
{"error": "brief description of what was seen instead"}

Price conservatively for unknown brands. Use market rates for recognised brands.
Respond with JSON only. No preamble, no explanation."""

CONVERSATION_SYSTEM_PROMPT = """You are the intake assistant for Bombay Closet Cleanse (BCC), a premium pre-loved fashion platform in India.

You help sellers submit items for drop-off at BCC stores via Telegram.

Rules — non-negotiable:
- Be warm but efficient. Like a well-trained store associate on WhatsApp.
- Never more than 4 lines per response. White space matters.
- Never use filler phrases: "Great!", "Awesome!", "Sure thing!", "Of course!", "Certainly!", "Absolutely!"
- Always address the specific context of what the seller just said. No generic prompts.
- Use line breaks for readability."""


async def llm_reply(session: dict, user_msg: str, context_hint: str = "") -> str:
    system = CONVERSATION_SYSTEM_PROMPT
    if context_hint:
        system += f"\n\nContext: {context_hint}"

    messages = session["history"][-12:] + [{"role": "user", "content": user_msg}]
    resp = await groq_client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[{"role": "system", "content": system}] + messages,
        max_tokens=250,
        temperature=0.6,
    )
    reply = resp.choices[0].message.content.strip()
    session["history"].append({"role": "user", "content": user_msg})
    session["history"].append({"role": "assistant", "content": reply})
    return reply


async def analyse_item(image_bytes: bytes) -> dict:
    b64  = base64.b64encode(image_bytes).decode()
    resp = await groq_client.chat.completions.create(
        model=VISION_MODEL,
        messages=[
            {"role": "system", "content": VISION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    {"type": "text",      "text": "Analyse this item for BCC intake."},
                ],
            },
        ],
        max_tokens=400,
        temperature=0.1,
    )
    raw   = resp.choices[0].message.content.strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return {"error": "Response was not valid JSON"}
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return {"error": "Could not parse analysis result"}


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    track_user(update)
    log_in(update, "command", "/start")
    reset_session(update.effective_chat.id)
    await send(
        update,
        "Welcome to Bombay Closet Cleanse.\n\n"
        "I'm here to help you submit items for a drop-off at our store.\n\n"
        "How many items are you looking to drop off?",
    )


async def cmd_restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    track_user(update)
    log_in(update, "command", "/status")
    session = get_session(update.effective_chat.id)
    step    = session["step"]

    if step == "greeting":
        await send(update, "No session in progress. Send /start to begin.")
    elif step == "collecting_photos":
        received = session["photos_received"]
        total    = session["total_items"]
        await send(update, f"You have sent {received} of {total} photos. {total - received} remaining.")
    elif step == "confirming":
        await send(update, f"All {session['total_items']} photos received. Reply Yes or No to confirm your drop-off.")
    elif step == "done":
        await send(update, "Your drop-off is already confirmed. Send /start to begin a new session.")


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    track_user(update)
    log_in(update, "command", "/cancel")
    reset_session(update.effective_chat.id)
    await send(update, "Session cancelled.\n\nYou can start again anytime with /start.")


# ── Message handlers ──────────────────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    track_user(update)
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    text    = update.message.text.strip()
    step    = session["step"]

    log_in(update, "text", text)

    if step == "greeting":
        numbers = re.findall(r"\b(\d+)\b", text)
        if numbers:
            count = int(numbers[0])
            if count < MINIMUM_ITEMS:
                await send(
                    update,
                    f"We accept a minimum of {MINIMUM_ITEMS} items per drop-off.\n\n"
                    "You're welcome to come back when you have more pieces to clear out.",
                )
            else:
                session["total_items"] = count
                session["step"]        = "collecting_photos"
                await send(
                    update,
                    f"{count} items — you're all set.\n\n"
                    "Please send your photos one at a time. I'll assess each piece as it comes in.\n\n"
                    "Send your first photo whenever you're ready.",
                )
        else:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            reply = await llm_reply(
                session, text,
                context_hint="Seller has not provided item count. Ask how many items they want to drop off.",
            )
            await send(update, reply)

    elif step == "collecting_photos":
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        reply = await llm_reply(
            session, text,
            context_hint=(
                f"Seller is in photo submission. {session['photos_received']} of "
                f"{session['total_items']} photos received. They sent text instead of a photo. "
                "Acknowledge briefly and ask for the next photo."
            ),
        )
        await send(update, reply)

    elif step == "confirming":
        words    = set(text.lower().split())
        yes_set  = {"yes", "confirm", "proceed", "ok", "sure", "yeah", "yep", "haan", "ha", "y"}
        no_set   = {"no", "cancel", "nope", "nahi", "nah", "n"}

        if words & yes_set:
            session["step"] = "done"
            await send(update, _confirmation_message(session))
        elif words & no_set:
            reset_session(chat_id)
            await send(update, "No problem. Your session has been cleared.\n\nCome back whenever you're ready. /start to begin again.")
        else:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            reply = await llm_reply(
                session, text,
                context_hint="Seller has seen their summary. Ask them clearly to reply Yes or No.",
            )
            await send(update, reply)

    elif step == "done":
        await send(update, "Your drop-off is already confirmed.\n\nSend /start to begin a new session.")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    track_user(update)
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    step    = session["step"]

    log_in(update, "photo", "📷 Photo submitted")

    if step == "greeting":
        await send(update, "I haven't asked for photos yet.\n\nFirst, tell me how many items you'd like to drop off.")
        return
    if step == "confirming":
        await send(update, "All photos have been received.\n\nPlease reply Yes to confirm your drop-off or No to cancel.")
        return
    if step == "done":
        await send(update, "Your drop-off is already confirmed. Send /start to begin a new session.")
        return
    if step != "collecting_photos":
        await send(update, "Send /start to begin a new session.")
        return
    if session["photos_received"] >= session["total_items"]:
        await send(update, f"You've already sent all {session['total_items']} photos.\n\nCheck the summary above and reply Yes or No.")
        return

    await update.message.reply_text("Analysing...")
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        photo_file = await update.message.photo[-1].get_file()
        buf        = BytesIO()
        await photo_file.download_to_memory(buf)
        analysis   = await analyse_item(buf.getvalue())

        if "error" in analysis:
            await send(
                update,
                f"I couldn't analyse that image.\n{analysis['error']}\n\n"
                "Please send a clear photo of a clothing item.",
            )
            return

        session["photos_received"] += 1
        session["analyses"].append(analysis)
        num   = session["photos_received"]
        total = session["total_items"]

        msg = _item_message(analysis, num, total)
        await send(update, msg)

        if num >= total:
            session["step"] = "confirming"
            await asyncio.sleep(0.5)
            summary = _summary_message(session)
            await send(update, summary)

    except Exception as exc:
        logger.error("Photo processing error: %s", exc, exc_info=True)
        await send(update, "Something went wrong analysing that photo.\n\nPlease try sending it again.")


async def handle_unsupported(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    track_user(update)
    log_in(update, "unsupported", f"Unsupported message type: {update.message.effective_attachment.__class__.__name__}")
    await send(update, "I can only handle text messages and photos for now.\n\nPlease send a photo of your item or type your response.")


# ── App wiring ────────────────────────────────────────────────────────────────

def _add_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("restart", cmd_restart))
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(CommandHandler("cancel",  cmd_cancel))
    app.add_handler(MessageHandler(filters.PHOTO,                                   handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,                 handle_text))
    app.add_handler(MessageHandler(~filters.TEXT & ~filters.PHOTO & ~filters.COMMAND, handle_unsupported))


async def _run() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in .env")
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set in .env")

    bot_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    _add_handlers(bot_app)

    port = int(os.getenv("PORT", "8080"))
    uv_config = uvicorn.Config(api, host="0.0.0.0", port=port, log_level="warning")
    uv_server = uvicorn.Server(uv_config)

    async with bot_app:
        await bot_app.start()
        await bot_app.updater.start_polling(allowed_updates=Update.ALL_TYPES)

        logger.info("BCC Seller Bot is running.")
        logger.info("Dashboard → http://localhost:8080")

        try:
            await uv_server.serve()
        finally:
            await bot_app.updater.stop()
            await bot_app.stop()


if __name__ == "__main__":
    asyncio.run(_run())
