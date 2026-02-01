import os
import re
import json
import sqlite3
import asyncio
from datetime import datetime, timedelta, timezone, time as dtime
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from telegram import Update, ChatJoinRequest
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    ChatJoinRequestHandler,
    filters,
)

# =========================
# CONFIG (ENV VARS)
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

TREASURY_WALLET = os.getenv("TREASURY_WALLET", "").strip()
RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com").strip()

VIP_PRICE_SOL = float(os.getenv("VIP_PRICE_SOL", "1.5"))
VIP_DAYS = int(os.getenv("VIP_DAYS", "30"))

# Admins: comma-separated Telegram user ids, e.g. "123,456"
ADMIN_IDS = set()
if os.getenv("ADMIN_IDS"):
    ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS").split(",") if x.strip().isdigit()}

# VIP group (private)
VIP_CHAT_ID = os.getenv("VIP_CHAT_ID", "").strip()

# Public group (private group used for public marketing feed)
PUBLIC_CHAT_ID = os.getenv("PUBLIC_CHAT_ID", "").strip()

# Trending config
POST_TRENDING_ENABLED = os.getenv("POST_TRENDING_ENABLED", "1").strip() == "1"
POST_TRENDING_TIME = os.getenv("POST_TRENDING_TIME", "09:00").strip()  # in TZ
TZ_NAME = os.getenv("TZ", "Europe/Berlin").strip()
APP_TZ = ZoneInfo(TZ_NAME)

DB_PATH = "vip.db"


# =========================
# I18N
# =========================
TXT = {
    "de": {
        "welcome": (
            "👋 Willkommen!\n\n"
            "Hier kannst du VIP-Zugang kaufen und danach Trading-Signale erhalten.\n"
            "⚠️ Hinweis: Keine Finanzberatung. Trading & Memecoins sind extrem riskant.\n\n"
            "➡️ VIP kaufen: /buy\n"
            "➡️ Zahlung prüfen: /verify <TX-ID>\n"
            "➡️ VIP Status: /vip\n"
            "➡️ Hilfe: Schreib mir z.B. „Preis?“, „Wie bezahlen?“, „Verify?“\n"
        ),
        "buy": (
            "💎 VIP Zugang\n"
            "Dauer: {days} Tage\n"
            "Preis: {price} SOL\n\n"
            "✅ Sende den Betrag an diese Solana-Adresse:\n"
            "{wallet}\n\n"
            "📌 Danach sende mir die Transaction-Signature (Tx-ID) so:\n"
            "/verify <TX-ID>\n\n"
            "Tipp: Die Tx-ID findest du in Phantom/Solflare bei der Transaktion → Details."
        ),
        "verify_usage": "Bitte so: /verify <TX-ID>",
        "verify_checking": "🔎 Prüfe Zahlung on-chain …",
        "verify_ok": (
            "✅ Zahlung bestätigt!\n"
            "Du bist jetzt VIP freigeschaltet bis: {until}\n\n"
            "➡️ VIP Status: /vip"
        ),
        "verify_fail": (
            "❌ Konnte keine passende Zahlung finden.\n\n"
            "Bitte prüfe:\n"
            "1) Tx-ID korrekt kopiert?\n"
            "2) Zahlung ging an die richtige Adresse?\n"
            "3) Mindestens {price} SOL gesendet?\n\n"
            "Wenn es weiterhin nicht klappt: sende die Tx-ID nochmal."
        ),
        "verify_used": "⚠️ Diese Tx-ID wurde bereits verwendet. Bitte kontaktiere Support, falls das ein Fehler ist.",
        "vip_active": "✅ VIP aktiv bis: {until}",
        "vip_inactive": "❌ Kein aktiver VIP. VIP kaufen: /buy",
        "admin_only": "⛔ Kein Zugriff.",
        "grant_usage": "Usage: /grant <user_id> <days>",
        "grant_done": "✅ User {uid} freigeschaltet bis: {until}",
        "revoke_usage": "Usage: /revoke <user_id>",
        "revoke_done": "✅ VIP entzogen für User {uid}",
        "broadcast_usage": "Usage: /broadcast <nachricht>",
        "broadcast_done": "✅ Broadcast an {n} VIPs gesendet.",
        "chatid": "CHAT_ID: {id}",
        "where": "CHAT_ID: {id}\nTYPE: {type}\nTITLE: {title}",
        "faq_unknown": "Schreib bitte kurz: „Preis?“, „Wie bezahlen?“, „Verify?“",
        "faq_price": "💎 VIP kostet {price} SOL für {days} Tage. Kaufen: /buy",
        "faq_pay": "Sende {price} SOL an die Wallet aus /buy, dann /verify <TX-ID>.",
        "faq_verify": "Sende /verify <TX-ID> (Tx-ID kommt aus Phantom/Solflare bei der Transaktion).",
        "faq_vip": "VIP-Status prüfen: /vip — Kaufen: /buy",
    },
    "en": {
        "welcome": (
            "👋 Welcome!\n\n"
            "Here you can buy VIP access and receive trading signals.\n"
            "⚠️ Not financial advice. Trading & memecoins are extremely risky.\n\n"
            "➡️ Buy VIP: /buy\n"
            "➡️ Verify payment: /verify <TXID>\n"
            "➡️ VIP status: /vip\n"
            "➡️ Help: ask “price?”, “how to pay?”, “verify?”\n"
        ),
        "buy": (
            "💎 VIP Access\n"
            "Duration: {days} days\n"
            "Price: {price} SOL\n\n"
            "✅ Send the amount to this Solana address:\n"
            "{wallet}\n\n"
            "📌 Then send the transaction signature (TXID):\n"
            "/verify <TXID>\n\n"
            "Tip: TXID is in Phantom/Solflare → transaction details."
        ),
        "verify_usage": "Use: /verify <TXID>",
        "verify_checking": "🔎 Checking on-chain payment …",
        "verify_ok": (
            "✅ Payment confirmed!\n"
            "VIP active until: {until}\n\n"
            "➡️ Check status: /vip"
        ),
        "verify_fail": (
            "❌ I couldn't find a matching payment.\n\n"
            "Please check:\n"
            "1) TXID copied correctly?\n"
            "2) Payment sent to the correct address?\n"
            "3) At least {price} SOL sent?\n\n"
            "If it still fails: send the TXID again."
        ),
        "verify_used": "⚠️ This TXID was already used. Please contact support if this is a mistake.",
        "vip_active": "✅ VIP active until: {until}",
        "vip_inactive": "❌ No active VIP. Buy VIP: /buy",
        "admin_only": "⛔ Access denied.",
        "grant_usage": "Usage: /grant <user_id> <days>",
        "grant_done": "✅ User {uid} granted until: {until}",
        "revoke_usage": "Usage: /revoke <user_id>",
        "revoke_done": "✅ VIP revoked for user {uid}",
        "broadcast_usage": "Usage: /broadcast <message>",
        "broadcast_done": "✅ Broadcast sent to {n} VIPs.",
        "chatid": "CHAT_ID: {id}",
        "where": "CHAT_ID: {id}\nTYPE: {type}\nTITLE: {title}",
        "faq_unknown": "Please ask briefly: “price?”, “how to pay?”, “verify?”",
        "faq_price": "💎 VIP is {price} SOL for {days} days. Buy: /buy",
        "faq_pay": "Send {price} SOL to the wallet in /buy, then /verify <TXID>.",
        "faq_verify": "Send /verify <TXID> (TXID is in Phantom/Solflare transaction details).",
        "faq_vip": "Check VIP: /vip — Buy: /buy",
    }
}


def lang(update: Update) -> str:
    code = (update.effective_user.language_code or "").lower()
    return "de" if code.startswith("de") else "en"


# =========================
# DB helpers
# =========================
def db():
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL;")
    return con


def init_db():
    con = db()
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vip_users (
            user_id INTEGER PRIMARY KEY,
            paid_until TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS used_txs (
            txsig TEXT PRIMARY KEY,
            used_at TEXT NOT NULL
        )
    """)
    con.commit()
    con.close()


def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def vip_until(user_id: int):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT paid_until FROM vip_users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    con.close()
    if not row:
        return None
    try:
        return datetime.fromisoformat(row[0])
    except Exception:
        return None


def set_vip(user_id: int, days: int):
    until = datetime.now(timezone.utc) + timedelta(days=days)
    con = db()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO vip_users(user_id, paid_until)
        VALUES(?, ?)
        ON CONFLICT(user_id) DO UPDATE SET paid_until=excluded.paid_until
    """, (user_id, until.isoformat()))
    con.commit()
    con.close()
    return until


def revoke_vip(user_id: int):
    con = db()
    cur = con.cursor()
    cur.execute("DELETE FROM vip_users WHERE user_id=?", (user_id,))
    con.commit()
    con.close()


def mark_tx_used(txsig: str):
    con = db()
    cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO used_txs(txsig, used_at) VALUES(?, ?)",
                (txsig, datetime.now(timezone.utc).isoformat()))
    con.commit()
    con.close()


def is_tx_used(txsig: str) -> bool:
    con = db()
    cur = con.cursor()
    cur.execute("SELECT 1 FROM used_txs WHERE txsig=?", (txsig,))
    row = cur.fetchone()
    con.close()
    return bool(row)


def all_active_vips() -> list[int]:
    now = datetime.now(timezone.utc)
    con = db()
    cur = con.cursor()
    cur.execute("SELECT user_id, paid_until FROM vip_users")
    rows = cur.fetchall()
    con.close()
    res = []
    for uid, until_str in rows:
        try:
            until = datetime.fromisoformat(until_str)
            if until > now:
                res.append(int(uid))
        except Exception:
            pass
    return res


# =========================
# Solana RPC verification
# =========================
def rpc_call(method: str, params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    data = json.dumps(payload).encode("utf-8")
    req = Request(RPC_URL, data=data, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def sol_to_lamports(sol: float) -> int:
    return int(sol * 1_000_000_000)


def verify_payment_tx(txsig: str) -> bool:
    """
    Verifies: tx contains a SystemProgram transfer to TREASURY_WALLET with amount >= VIP_PRICE_SOL
    """
    txsig = (txsig or "").strip()
    if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{80,90}", txsig):
        return False

    r = rpc_call("getTransaction", [txsig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
    result = r.get("result")
    if not result:
        return False

    tx = result.get("transaction", {})
    message = tx.get("message", {})
    instructions = message.get("instructions", [])

    required = sol_to_lamports(VIP_PRICE_SOL)

    for ix in instructions:
        parsed = ix.get("parsed")
        if not parsed:
            continue
        if parsed.get("type") != "transfer":
            continue
        info = parsed.get("info", {})
        dest = info.get("destination")
        lamports = info.get("lamports", 0)
        if dest == TREASURY_WALLET and int(lamports) >= required:
            return True

    return False


# =========================
# DexScreener trending (free)
# Uses token boosts top + token-pairs endpoints
# =========================
def http_get_json(url: str) -> dict | list | None:
    req = Request(url, headers={"accept": "application/json"})
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def dexscreener_boosts_top_solana(limit: int = 3) -> list[str]:
    """
    Pulls tokens with most active boosts, then filters chainId == solana.
    Endpoint: https://api.dexscreener.com/token-boosts/top/v1
    """
    data = http_get_json("https://api.dexscreener.com/token-boosts/top/v1")
    if not data or not isinstance(data, dict):
        return []
    items = data.get("pairs") or data.get("data") or data.get("results") or []
    if not isinstance(items, list):
        items = []

    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if (it.get("chainId") or "").lower().strip() != "solana":
            continue
        token_addr = it.get("tokenAddress") or it.get("baseTokenAddress") or ""
        token_addr = str(token_addr).strip()
        if token_addr and token_addr not in out:
            out.append(token_addr)
        if len(out) >= limit:
            break
    return out


def dexscreener_token_pairs(chain_id: str, token_address: str) -> list[dict]:
    """
    Endpoint: https://api.dexscreener.com/token-pairs/v1/{chainId}/{tokenAddress}
    """
    url = f"https://api.dexscreener.com/token-pairs/v1/{chain_id}/{token_address}"
    data = http_get_json(url)
    if not data or not isinstance(data, list):
        return []
    return data


def pick_best_pair(pairs: list[dict]) -> dict | None:
    """
    Choose a "best" pair by highest liquidity if available.
    """
    best = None
    best_liq = -1.0
    for p in pairs:
        liq = 0.0
        try:
            liq = float((p.get("liquidity") or {}).get("usd") or 0)
        except Exception:
            liq = 0.0
        if liq > best_liq:
            best_liq = liq
            best = p
    return best


# =========================
# FAQ Auto replies (private chat only)
# =========================
def detect_intent(text: str, l: str) -> str | None:
    t = (text or "").lower()

    if l == "de":
        if any(x in t for x in ["preis", "kosten", "wie viel", "vip preis", "1.5"]):
            return "price"
        if any(x in t for x in ["zahlen", "bezahlen", "zahlung", "wallet", "adresse", "solana"]):
            return "pay"
        if any(x in t for x in ["verify", "tx", "txid", "signatur", "transaktion"]):
            return "verify"
        if "vip" in t or "status" in t:
            return "vip"
        return None

    # EN
    if any(x in t for x in ["price", "cost", "how much", "vip price", "1.5"]):
        return "price"
    if any(x in t for x in ["pay", "payment", "wallet", "address", "solana"]):
        return "pay"
    if any(x in t for x in ["verify", "tx", "txid", "signature", "transaction"]):
        return "verify"
    if "vip" in t or "status" in t:
        return "vip"
    return None


async def faq_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    if update.effective_chat.type != "private":
        return

    l = lang(update)
    intent = detect_intent(update.message.text, l)

    if intent == "price":
        await update.message.reply_text(TXT[l]["faq_price"].format(price=VIP_PRICE_SOL, days=VIP_DAYS))
    elif intent == "pay":
        await update.message.reply_text(TXT[l]["faq_pay"].format(price=VIP_PRICE_SOL))
    elif intent == "verify":
        await update.message.reply_text(TXT[l]["faq_verify"])
    elif intent == "vip":
        await update.message.reply_text(TXT[l]["faq_vip"])
    else:
        await update.message.reply_text(TXT[l]["faq_unknown"])


# =========================
# Bot commands
# =========================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    l = lang(update)
    await update.message.reply_text(TXT[l]["welcome"])


async def buy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    l = lang(update)
    if not TREASURY_WALLET:
        await update.message.reply_text("Admin config error: TREASURY_WALLET not set.")
        return
    await update.message.reply_text(
        TXT[l]["buy"].format(days=VIP_DAYS, price=VIP_PRICE_SOL, wallet=TREASURY_WALLET)
    )


async def vip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    l = lang(update)
    until = vip_until(update.effective_user.id)
    now = datetime.now(timezone.utc)
    if until and until > now:
        await update.message.reply_text(
            TXT[l]["vip_active"].format(until=until.strftime("%Y-%m-%d %H:%M UTC"))
        )
    else:
        await update.message.reply_text(TXT[l]["vip_inactive"])


async def verify_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    l = lang(update)
    if len(context.args) != 1:
        await update.message.reply_text(TXT[l]["verify_usage"])
        return

    txsig = context.args[0].strip()

    if is_tx_used(txsig):
        await update.message.reply_text(TXT[l]["verify_used"])
        return

    await update.message.reply_text(TXT[l]["verify_checking"])

    ok = False
    try:
        ok = await asyncio.to_thread(verify_payment_tx, txsig)
    except Exception:
        ok = False

    if not ok:
        await update.message.reply_text(TXT[l]["verify_fail"].format(price=VIP_PRICE_SOL))
        return

    mark_tx_used(txsig)
    until = set_vip(update.effective_user.id, VIP_DAYS)

    await update.message.reply_text(
        TXT[l]["verify_ok"].format(until=until.strftime("%Y-%m-%d %H:%M UTC"))
    )

    # Send VIP invite link (optional)
    if VIP_CHAT_ID:
        try:
            chat_id_int = int(VIP_CHAT_ID)
            invite = await context.bot.create_chat_invite_link(
                chat_id=chat_id_int,
                member_limit=1,
                expire_date=int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
            )
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text=("🔗 VIP Zugang (Link gültig 1 Stunde / 1x nutzbar):\n" + invite.invite_link)
            )
        except Exception:
            pass


# Admin helpers
async def chatid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    l = lang(update)
    if not is_admin(uid):
        await update.message.reply_text(TXT[l]["admin_only"])
        return
    await update.message.reply_text(TXT[l]["chatid"].format(id=update.effective_chat.id))


async def where_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    l = lang(update)
    if not is_admin(uid):
        await update.message.reply_text(TXT[l]["admin_only"])
        return
    chat = update.effective_chat
    await update.message.reply_text(
        TXT[l]["where"].format(id=chat.id, type=chat.type, title=(chat.title or "-"))
    )


async def grant_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    l = lang(update)
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text(TXT[l]["admin_only"])
        return
    if len(context.args) != 2 or not context.args[0].isdigit() or not context.args[1].isdigit():
        await update.message.reply_text(TXT[l]["grant_usage"])
        return
    target = int(context.args[0])
    days = int(context.args[1])
    until = set_vip(target, days)
    await update.message.reply_text(
        TXT[l]["grant_done"].format(uid=target, until=until.strftime("%Y-%m-%d %H:%M UTC"))
    )


async def revoke_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    l = lang(update)
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text(TXT[l]["admin_only"])
        return
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text(TXT[l]["revoke_usage"])
        return
    target = int(context.args[0])
    revoke_vip(target)
    await update.message.reply_text(TXT[l]["revoke_done"].format(uid=target))


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    l = lang(update)
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text(TXT[l]["admin_only"])
        return
    if not context.args:
        await update.message.reply_text(TXT[l]["broadcast_usage"])
        return
    msg = update.message.text.split(" ", 1)[1].strip()
    vips = all_active_vips()
    sent = 0
    for vid in vips:
        try:
            await context.bot.send_message(chat_id=vid, text=msg)
            sent += 1
        except Exception:
            pass
    await update.message.reply_text(TXT[l]["broadcast_done"].format(n=sent))


# Join requests: auto-approve VIP, decline others (only VIP group)
async def join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    req: ChatJoinRequest = update.chat_join_request
    user_id = req.from_user.id

    if VIP_CHAT_ID and str(req.chat.id) != str(VIP_CHAT_ID):
        return

    until = vip_until(user_id)
    now = datetime.now(timezone.utc)

    try:
        if until and until > now:
            await context.bot.approve_chat_join_request(chat_id=req.chat.id, user_id=user_id)
        else:
            await context.bot.decline_chat_join_request(chat_id=req.chat.id, user_id=user_id)
    except Exception:
        pass


# Cleanup expired VIPs: remove from DB + kick from VIP group
async def cleanup_expired(context: ContextTypes.DEFAULT_TYPE):
    if not VIP_CHAT_ID:
        return
    chat_id_int = int(VIP_CHAT_ID)
    now = datetime.now(timezone.utc)

    con = db()
    cur = con.cursor()
    cur.execute("SELECT user_id, paid_until FROM vip_users")
    rows = cur.fetchall()
    con.close()

    for uid, until_str in rows:
        try:
            until = datetime.fromisoformat(until_str)
        except Exception:
            continue

        if until <= now:
            revoke_vip(int(uid))
            try:
                await context.bot.ban_chat_member(chat_id=chat_id_int, user_id=int(uid))
                await context.bot.unban_chat_member(chat_id=chat_id_int, user_id=int(uid))
            except Exception:
                pass


# Daily trending post to PUBLIC group (info-only)
async def post_daily_trending(context: ContextTypes.DEFAULT_TYPE):
    if not (POST_TRENDING_ENABLED and PUBLIC_CHAT_ID):
        return

    # Get top boosted tokens on solana (best-effort)
    try:
        token_addrs = await asyncio.to_thread(dexscreener_boosts_top_solana, 3)
    except Exception:
        token_addrs = []

    if not token_addrs:
        return

    lines = [
        "🔥 Daily Solana Trending (Info-only)",
        "⚠️ No financial advice. High risk.",
        "",
    ]

    for addr in token_addrs[:3]:
        # Fetch pairs to get name/symbol/liquidity/volume if possible
        name = "Unknown"
        sym = ""
        liq_usd = None
        vol24 = None

        try:
            pairs = await asyncio.to_thread(dexscreener_token_pairs, "solana", addr)
            best = pick_best_pair(pairs) if pairs else None
            if best:
                base = best.get("baseToken") or {}
                name = base.get("name") or name
                sym = base.get("symbol") or sym
                try:
                    liq_usd = float((best.get("liquidity") or {}).get("usd") or 0)
                except Exception:
                    liq_usd = None
                try:
                    vol24 = float((best.get("volume") or {}).get("h24") or 0)
                except Exception:
                    vol24 = None
        except Exception:
            pass

        title = f"{name} ({sym})" if sym else name
        lines.append(f"• {title}")
        if liq_usd is not None:
            lines.append(f"  Liquidity: ${liq_usd:,.0f}")
        if vol24 is not None:
            lines.append(f"  24h Volume: ${vol24:,.0f}")

        lines.append(f"  Solscan: https://solscan.io/token/{addr}")
        lines.append(f"  DexScreener: https://dexscreener.com/solana/{addr}")
        lines.append("")

    lines.append("VIP signals are posted separately in the VIP group.")

    try:
        await context.bot.send_message(chat_id=int(PUBLIC_CHAT_ID), text="\n".join(lines))
    except Exception:
        pass


def parse_time_hhmm(value: str) -> dtime:
    m = re.fullmatch(r"(\d{2}):(\d{2})", value.strip())
    if not m:
        return dtime(9, 0)
    hh = int(m.group(1))
    mm = int(m.group(2))
    hh = max(0, min(23, hh))
    mm = max(0, min(59, mm))
    return dtime(hh, mm)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN not set")
    if not TREASURY_WALLET:
        raise RuntimeError("TREASURY_WALLET not set")
    if not ADMIN_IDS:
        raise RuntimeError("ADMIN_IDS not set (your Telegram user id)")

    init_db()

    app = Application.builder().token(BOT_TOKEN).timezone(APP_TZ).build()

    # Commands
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("buy", buy_cmd))
    app.add_handler(CommandHandler("verify", verify_cmd))
    app.add_handler(CommandHandler("vip", vip_cmd))

    # Admin commands
    app.add_handler(CommandHandler("chatid", chatid_cmd))
    app.add_handler(CommandHandler("where", where_cmd))
    app.add_handler(CommandHandler("grant", grant_cmd))
    app.add_handler(CommandHandler("revoke", revoke_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))

    # Join requests (VIP group)
    app.add_handler(ChatJoinRequestHandler(join_request_handler))

    # FAQ auto replies (private only)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, faq_reply))

    # Jobs
    # Remove expired VIPs every 6 hours
    app.job_queue.run_repeating(cleanup_expired, interval=6 * 60 * 60, first=60)

    # Daily trending post (public group)
    t = parse_time_hhmm(POST_TRENDING_TIME)
    app.job_queue.run_daily(post_daily_trending, time=t)

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
