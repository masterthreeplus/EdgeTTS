import os
import logging
import uuid
from datetime import datetime
from flask import Flask
from threading import Thread
import edge_tts
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import Forbidden

# MongoDB Driver
import pymongo
import certifi

# 1. Flask App (Keep-Alive)
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running with Admin Panel!"

def run_flask():
    port = int(os.environ.get("PORT", 5000)) 
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask, daemon=True)
    t.start()

# 2. Configuration
TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URI = os.environ.get("MONGO_URI")
ADMIN_ID = os.environ.get("ADMIN_ID")

if not TOKEN or not MONGO_URI or not ADMIN_ID:
    raise ValueError("Missing Config Variables!")

ADMIN_ID = int(ADMIN_ID)
VOICE = "my-MM-ThihaNeural"
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- MongoDB Functions ---

client = pymongo.MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = client["telegram_bot_db"]
users_col = db["users"]

def add_or_update_user(user):
    """User အချက်အလက်စုံလင်စွာ သိမ်းဆည်းခြင်း"""
    user_id = user.id
    first_name = user.first_name
    username = user.username or "None"
    
    try:
        users_col.update_one(
            {"_id": user_id},
            {
                "$setOnInsert": {"joined_at": datetime.now()}, # အသစ်ဖြစ်မှ ရက်စွဲထည့်မယ်
                "$set": {
                    "name": first_name,
                    "username": username,
                    "status": "active", # Active ဖြစ်နေကြောင်း update မယ်
                    "last_active": datetime.now()
                }
            },
            upsert=True
        )
    except Exception as e:
        logging.error(f"MongoDB Error: {e}")

def get_all_active_users():
    """Active ဖြစ်သော user များကိုသာ ဆွဲထုတ်ခြင်း"""
    users = users_col.find({"status": "active"}, {"_id": 1})
    return [user["_id"] for user in users]

def get_stats():
    """Admin Dashboard အတွက် စာရင်းများ"""
    total = users_col.count_documents({})
    active = users_col.count_documents({"status": "active"})
    blocked = users_col.count_documents({"status": "blocked"})
    return total, active, blocked

def mark_user_blocked(user_id):
    """Block လုပ်သွားသူကို Database တွင် မှတ်တမ်းတင်ခြင်း"""
    users_col.update_one({"_id": user_id}, {"$set": {"status": "blocked"}})

# --- Bot Commands ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_or_update_user(user) # Database ထဲထည့်မယ်

    # အကယ်၍ Admin ဖြစ်ခဲ့ရင် Admin Panel ခလုတ်တွေ ပြမယ်
    if user.id == ADMIN_ID:
        admin_keyboard = [
            [KeyboardButton("📊 Dashboard Stats"), KeyboardButton("📢 Broadcast Help")]
        ]
        reply_markup = ReplyKeyboardMarkup(admin_keyboard, resize_keyboard=True)
        await update.message.reply_text(f"Welcome Admin {user.first_name}! Admin Panel Loaded.", reply_markup=reply_markup)
    else:
        # ရိုးရိုး User အတွက်
        await update.message.reply_text(f"မင်္ဂလာပါ {user.first_name}! စာပို့လိုက်ရင် အသံဖိုင် ပြောင်းပေးပါမယ်။")

async def admin_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin Menu ခလုတ်များကို ကိုင်တွယ်ခြင်း"""
    user = update.effective_user
    text = update.message.text

    if user.id != ADMIN_ID:
        # Admin မဟုတ်ရင် TTS လုပ်ဖို့လွှဲပေးလိုက်မယ်
        await text_to_speech(update, context) 
        return

    if text == "📊 Dashboard Stats":
        total, active, blocked = get_stats()
        msg = (
            f"📈 **Bot Statistics**\n\n"
            f"👥 Total Users: {total}\n"
            f"✅ Active Users: {active}\n"
            f"🚫 Blocked Users: {blocked}"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
        
    elif text == "📢 Broadcast Help":
        msg = (
            "📢 **Broadcast လုပ်နည်း**\n\n"
            "1. Bot ဆီသို့ ပုံ (သို့) စာ ပို့လိုက်ပါ။\n"
            "2. ထိုစာကို Reply ပြန်ပြီး `/broadcast` လို့ ရိုက်ထည့်လိုက်ပါ။\n\n"
            "Bot က Active user အားလုံးဆီ ထပ်ဆင့်ပို့ပေးပါလိမ့်မယ်။"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
    
    else:
        # Menu မဟုတ်ရင် TTS အလုပ်ဆက်လုပ်မယ်
        await text_to_speech(update, context)

async def broadcast_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reply Method ဖြင့် Broadcast လုပ်ခြင်း (ပုံရော စာရော ရသည်)"""
    if update.effective_user.id != ADMIN_ID:
        return

    # Reply လုပ်ထားသော Message မရှိရင်
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ တစ်ခုခုကို Reply ပြန်ပြီး `/broadcast` လို့ရိုက်ပါ။")
        return

    original_msg = update.message.reply_to_message
    users = get_all_active_users()
    
    status_msg = await update.message.reply_text(f"🚀 Broadcasting to {len(users)} active users...")
    
    success = 0
    blocked = 0
    
    for user_id in users:
        try:
            # Message Type ကို ခွဲခြားပြီး ပို့မယ်
            if original_msg.photo:
                # ပုံ + စာ (Caption)
                await context.bot.send_photo(
                    chat_id=user_id, 
                    photo=original_msg.photo[-1].file_id,
                    caption=original_msg.caption
                )
            elif original_msg.text:
                # စာ သက်သက်
                await context.bot.send_message(
                    chat_id=user_id, 
                    text=original_msg.text
                )
            # အခြား Type တွေ (Sticker/Video) လိုရင် ဒီမှာထပ်ဖြည့်နိုင်ပါတယ်

            success += 1
        except Forbidden:
            # Block မိနေရင် Database မှာ update လုပ်မယ်
            mark_user_blocked(user_id)
            blocked += 1
        except Exception as e:
            logging.error(f"Broadcast Fail: {user_id} - {e}")

    await status_msg.edit_text(
        f"✅ **Broadcast Finished!**\n\n"
        f"sent: {success}\n"
        f"blocked/failed: {blocked} (Updated in DB)"
    , parse_mode="Markdown")

async def text_to_speech(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_or_update_user(user) # User လှုပ်ရှားတိုင်း Update လုပ်မယ်

    text = update.message.text
    if not text: return # စာမဟုတ်ရင် မလုပ်ဘူး

    chat_id = update.message.chat_id
    
    # Admin Panel ခလုတ်စာသားတွေဆိုရင် TTS မလုပ်ဘူး
    if text in ["📊 Dashboard Stats", "📢 Broadcast Help"]:
        return

    status_msg = await update.message.reply_text("Processing...")
    output_file = f"{uuid.uuid4()}.mp3"
    
    try:
        communicate = edge_tts.Communicate(text, VOICE)
        await communicate.save(output_file)
        
        if os.path.exists(output_file):
            with open(output_file, 'rb') as audio:
                await update.message.reply_voice(voice=audio)
            os.remove(output_file)
            await status_msg.delete() # Processing စာကိုဖျက်မယ်
    except Exception as e:
        await status_msg.edit_text(f"Error: {e}")

# --- MAIN ---

def main():
    application = Application.builder().token(TOKEN).build()

    # Commands
    application.add_handler(CommandHandler("start", start))
    
    # Broadcast Command (Reply method)
    application.add_handler(CommandHandler("broadcast", broadcast_reply))
    
    # Message Handler (Admin Menu & TTS)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_panel_handler))

    application.run_polling()

if __name__ == "__main__":
    keep_alive()
    main()
