import threading
from flask import Flask
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from supabase import create_client

BOT_TOKEN = "এখানে তোমার Telegram Token বসাও"
SUPABASE_URL = "https://udnchnjweynrsosjicwh.supabase.co"
SUPABASE_KEY = "এখানে তোমার sb_publishable_ Key বসাও"
ADMIN_ID = 123456789

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Render কে বাঁচায় রাখার জন্য Flask
app_flask = Flask(__name__)
@app_flask.route('/')
def home():
    return "SL Global Tasks Bot is Running!"

def run_flask():
    import os
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

def get_settings():
    try:
        res = supabase.table("settings").select("*").execute()
        return {r['key']: r['value'] for r in res.data}
    except:
        return {'mining_hours':'1','mining_reward':'0.005','min_withdraw':'5'}

def get_user(user_id, username="", first_name=""):
    res = supabase.table("users").select("*").eq("id", user_id).execute()
    if res.data:
        return res.data[0]
    data = {"id": user_id, "username": username, "first_name": first_name, "balance": 0, "referral_code": f"SL{user_id}"}
    supabase.table("users").insert(data).execute()
    return data

def main_menu():
    kb = [
        [InlineKeyboardButton("⛏️ Mining", callback_data="mining"), InlineKeyboardButton("📋 Tasks", callback_data="tasks")],
        [InlineKeyboardButton("👥 Team", callback_data="team"), InlineKeyboardButton("💰 Wallet", callback_data="wallet")],
        [InlineKeyboardButton("🏆 Challenge", callback_data="challenge"), InlineKeyboardButton("🏅 Leaderboard", callback_data="leader")],
    ]
    return InlineKeyboardMarkup(kb)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    u = get_user(user.id, user.username or "", user.first_name or "")
    if args and args[0].startswith("SL"):
        try:
            ref_id = int(args[0][2:])
            if ref_id != user.id and not u.get("referred_by"):
                supabase.table("users").update({"referred_by": ref_id}).eq("id", user.id).execute()
        except: pass
    await update.message.reply_text(
        f"👋 আসসালামু আলাইকুম {user.first_name}!\n\n**SL Global Tasks** এ স্বাগতম 🔥\n\n💰 ব্যালেন্স: ${float(u.get('balance',0)):.4f}\n⛏️ Mining: ১ ঘণ্টা পর পর Claim\n👥 Referral: 10% / 10% / 5%",
        reply_markup=main_menu(), parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user = q.from_user
    u = get_user(user.id)
    settings = get_settings()
    mining_hours = float(settings.get('mining_hours','1'))
    mining_reward = float(settings.get('mining_reward','0.005'))
    if q.data == "mining":
        now = datetime.now(timezone.utc)
        last = u.get("mining_start")
        if last:
            last_dt = datetime.fromisoformat(last.replace("Z","+00:00"))
            diff = (now - last_dt).total_seconds() / 3600
            if diff < mining_hours:
                left = int((mining_hours - diff)*60)
                await q.edit_message_text(f"⏳ Mining চলতেছে!\n\n{left} মিনিট পর Claim করতে পারবা।", reply_markup=main_menu())
                return
        new_bal = float(u.get('balance',0)) + mining_reward
        supabase.table("users").update({"balance": new_bal, "mining_start": now.isoformat()}).eq("id", user.id).execute()
        await q.edit_message_text(f"✅ Mining Claim সফল!\n\n+${mining_reward} পাইছো!\n💰 নতুন ব্যালেন্স: ${new_bal:.4f}", reply_markup=main_menu())
    elif q.data == "tasks":
        res = supabase.table("tasks").select("*").eq("is_active", True).execute()
        if not res.data:
            await q.edit_message_text("📋 এখন কোনো Task নাই। Admin Panel থেকে Task যোগ করো।", reply_markup=main_menu())
            return
        text = "📋 **Tasks:**\n\n"
        for t in res.data:
            text += f"• {t['title']} - ${t['reward']} - [লিংক]({t['url']})\n"
        await q.edit_message_text(text, reply_markup=main_menu(), parse_mode="Markdown", disable_web_page_preview=True)
    elif q.data == "wallet":
        await q.edit_message_text(f"💰 **Wallet**\n\nব্যালেন্স: ${float(u.get('balance',0)):.4f}\nMin Withdraw: ${settings.get('min_withdraw','5')}", reply_markup=main_menu(), parse_mode="Markdown")
    elif q.data == "team":
        link = f"https://t.me/{context.bot.username}?start=SL{user.id}"
        await q.edit_message_text(f"👥 **Team**\n\nতোমার লিংক:\n`{link}`\n\nকমিশন: Level 1: 10% / Level 2: 10% / Level 3: 5%\nমোট Invite: {u.get('total_invites',0)}", reply_markup=main_menu(), parse_mode="Markdown")
    elif q.data == "challenge":
        await q.edit_message_text(f"🏆 **Challenge**\n\n🥉 3 Invite = ${settings.get('challenge_1_price','0.50')}\n🥈 10 Invite = ${settings.get('challenge_2_price','2.00')}\n🥇 30 Invite = ${settings.get('challenge_3_price','7.00')}\n\nতোমার Invite: {u.get('total_invites',0)}", reply_markup=main_menu(), parse_mode="Markdown")
    elif q.data == "leader":
        res = supabase.table("users").select("first_name,balance").order("balance", desc=True).limit(10).execute()
        text = "🏅 **Leaderboard Top 10:**\n\n"
        for i, r in enumerate(res.data, 1):
            text += f"{i}. {r.get('first_name','User')} - ${float(r.get('balance',0)):.4f}\n"
        await q.edit_message_text(text, reply_markup=main_menu(), parse_mode="Markdown")

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("Bot চলতেছে মামা...")
    app.run_polling()

if __name__ == "__main__":
    main()
