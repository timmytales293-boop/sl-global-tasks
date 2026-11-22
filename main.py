import os
import html
import logging
import threading
from datetime import datetime, timezone

from flask import Flask
from supabase import create_client
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("slbot")

# ---------- CONFIG (set these as environment variables on Render) ----------
BOT_TOKEN = os.environ.get(9260808399:AAEJWd0VvQAqnljG66k3DO4LYh4f2IFtDlY)
SUPABASE_URL = os.environ.get("https://udnchnjweynrsosjicwh.supabase.co/")
SUPABASE_KEY = os.environ.get("sb_publishable_fOD7ZcqobFe0dFQbDEoaYg__3YKgU0Y")  # use the service_role key (server only!)
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

missing = [n for n, v in [("BOT_TOKEN", BOT_TOKEN),
                          ("SUPABASE_URL", SUPABASE_URL),
                          ("SUPABASE_KEY", SUPABASE_KEY)] if not v]
if missing:
    raise SystemExit(f"Missing environment variables: {', '.join(missing)}")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------- Flask keep-alive (for Render) ----------
app_flask = Flask(__name__)


@app_flask.route("/")
def home():
    return "SL Global Tasks Bot is Running!"


def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)


# ---------- Helpers ----------
DEFAULT_SETTINGS = {
    "mining_hours": "1",
    "mining_reward": "0.005",
    "min_withdraw": "5",
    "challenge_1_price": "0.50",
    "challenge_2_price": "2.00",
    "challenge_3_price": "7.00",
}


def esc(text) -> str:
    """Escape user-controlled text for Telegram HTML mode."""
    return html.escape(str(text or ""))


def get_settings():
    settings = dict(DEFAULT_SETTINGS)
    try:
        res = supabase.table("settings").select("*").execute()
        settings.update({r["key"]: r["value"] for r in res.data})
    except Exception as e:
        log.warning("Could not load settings, using defaults: %s", e)
    return settings


def get_user(user_id, username="", first_name=""):
    res = supabase.table("users").select("*").eq("id", user_id).execute()
    if res.data:
        return res.data[0]
    data = {
        "id": user_id,
        "username": username,
        "first_name": first_name,
        "balance": 0,
        "referral_code": f"SL{user_id}",
        "total_invites": 0,
    }
    supabase.table("users").insert(data).execute()
    return data


def credit_referral_chain(user_id, base_amount):
    """Distribute 10% / 10% / 5% of base_amount up the referral chain."""
    pct = [0.10, 0.10, 0.05]
    current = user_id
    for p in pct:
        res = supabase.table("users").select("referred_by").eq("id", current).execute()
        if not res.data:
            break
        parent = res.data[0].get("referred_by")
        if not parent:
            break
        p_res = supabase.table("users").select("balance").eq("id", parent).execute()
        if p_res.data:
            new_bal = float(p_res.data[0].get("balance") or 0) + base_amount * p
            supabase.table("users").update({"balance": round(new_bal, 6)}).eq("id", parent).execute()
        current = parent


def main_menu():
    kb = [
        [InlineKeyboardButton("⛏️ Mining", callback_data="mining"),
         InlineKeyboardButton("📋 Tasks", callback_data="tasks")],
        [InlineKeyboardButton("👥 Team", callback_data="team"),
         InlineKeyboardButton("💰 Wallet", callback_data="wallet")],
        [InlineKeyboardButton("🏆 Challenge", callback_data="challenge"),
         InlineKeyboardButton("🏅 Leaderboard", callback_data="leader")],
    ]
    return InlineKeyboardMarkup(kb)


async def safe_edit(q, text, **kwargs):
    """Edit a message, ignoring Telegram's 'message is not modified' error."""
    try:
        await q.edit_message_text(text, **kwargs)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    settings = get_settings()

    existing = supabase.table("users").select("id").eq("id", user.id).execute().data
    is_new = not existing
    u = get_user(user.id, user.username or "", user.first_name or "")

    if args and args[0].startswith("SL") and is_new:
        try:
            ref_id = int(args[0][2:])
            if ref_id != user.id:
                r = supabase.table("users").select("total_invites").eq("id", ref_id).execute()
                if r.data:  # only count the referral if the referrer really exists
                    supabase.table("users").update({"referred_by": ref_id}).eq("id", user.id).execute()
                    supabase.table("users").update({
                        "total_invites": int(r.data[0].get("total_invites") or 0) + 1
                    }).eq("id", ref_id).execute()
        except (ValueError, TypeError):
            pass

    await update.message.reply_text(
        f"👋 Welcome, {esc(user.first_name)}!\n\n"
        f"<b>SL Global Tasks</b> 🔥\n\n"
        f"💰 Balance: ${float(u.get('balance') or 0):.4f}\n"
        f"⛏️ Mining: Claim once every {esc(settings['mining_hours'])} hour(s)\n"
        f"👥 Referral: 10% / 10% / 5%",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user = q.from_user
    u = get_user(user.id, user.username or "", user.first_name or "")
    settings = get_settings()
    mining_hours = float(settings["mining_hours"])
    mining_reward = float(settings["mining_reward"])

    if q.data == "mining":
        now = datetime.now(timezone.utc)
        last = u.get("mining_start")
        if last:
            try:
                last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                diff = (now - last_dt).total_seconds() / 3600
                if diff < mining_hours:
                    left = max(1, int(round((mining_hours - diff) * 60)))
                    await safe_edit(
                        q,
                        f"⏳ Mining in progress!\n\n"
                        f"Please wait {left} more minute(s) before claiming again.",
                        reply_markup=main_menu(),
                    )
                    return
            except Exception as e:
                log.warning("Could not parse mining_start %r: %s", last, e)

        new_bal = round(float(u.get("balance") or 0) + mining_reward, 6)

        # Only succeeds if mining_start is still what we read -> blocks double-claims
        upd = supabase.table("users").update({
            "balance": new_bal,
            "mining_start": now.isoformat(),
        }).eq("id", user.id)
        upd = upd.eq("mining_start", last) if last else upd.is_("mining_start", "null")
        result = upd.execute()

        if not result.data:
            await safe_edit(q, "⏳ Already claimed. Please try again later.",
                            reply_markup=main_menu())
            return

        credit_referral_chain(user.id, mining_reward)

        await safe_edit(
            q,
            f"✅ Mining claimed successfully!\n\n"
            f"+${mining_reward} added to your balance.\n"
            f"💰 New balance: ${new_bal:.4f}",
            reply_markup=main_menu(),
        )

    elif q.data == "tasks":
        res = supabase.table("tasks").select("*").eq("is_active", True).execute()
        if not res.data:
            await safe_edit(
                q,
                "📋 No tasks available right now. Please check back later.",
                reply_markup=main_menu(),
            )
            return
        text = "📋 <b>Available Tasks:</b>\n\n"
        for t in res.data:
            text += (f"• {esc(t.get('title'))} — ${esc(t.get('reward'))} — "
                     f"<a href=\"{html.escape(str(t.get('url') or ''), quote=True)}\">Open Link</a>\n")
        await safe_edit(
            q,
            text,
            reply_markup=main_menu(),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    elif q.data == "wallet":
        await safe_edit(
            q,
            f"💰 <b>Wallet</b>\n\n"
            f"Balance: ${float(u.get('balance') or 0):.4f}\n"
            f"Minimum Withdraw: ${esc(settings['min_withdraw'])}",
            reply_markup=main_menu(),
            parse_mode="HTML",
        )

    elif q.data == "team":
        link = f"https://t.me/{context.bot.username}?start=SL{user.id}"
        await safe_edit(
            q,
            f"👥 <b>Team</b>\n\n"
            f"Your referral link:\n<code>{esc(link)}</code>\n\n"
            f"Commission: Level 1: 10% | Level 2: 10% | Level 3: 5%\n"
            f"Total Invites: {u.get('total_invites') or 0}",
            reply_markup=main_menu(),
            parse_mode="HTML",
        )

    elif q.data == "challenge":
        await safe_edit(
            q,
            f"🏆 <b>Challenge</b>\n\n"
            f"🥉 3 Invites  → ${esc(settings['challenge_1_price'])}\n"
            f"🥈 10 Invites → ${esc(settings['challenge_2_price'])}\n"
            f"🥇 30 Invites → ${esc(settings['challenge_3_price'])}\n\n"
            f"Your Invites: {u.get('total_invites') or 0}",
            reply_markup=main_menu(),
            parse_mode="HTML",
        )

    elif q.data == "leader":
        res = (
            supabase.table("users")
            .select("first_name,balance")
            .order("balance", desc=True)
            .limit(10)
            .execute()
        )
        text = "🏅 <b>Leaderboard — Top 10:</b>\n\n"
        for i, r in enumerate(res.data, 1):
            text += f"{i}. {esc(r.get('first_name') or 'User')} — ${float(r.get('balance') or 0):.4f}\n"
        await safe_edit(
            q,
            text,
            reply_markup=main_menu(),
            parse_mode="HTML",
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Unhandled error", exc_info=context.error)


# ---------- Main ----------
def main():
    threading.Thread(target=run_flask, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_error_handler(error_handler)
    print("SL Global Tasks Bot started ✅")
    app.run_polling()


if __name__ == "__main__":
    main()
