import os
import logging
import uuid
import csv  # Excel ဖိုင်ထုတ်ရန်
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
    return "Bot is running with Export System!"

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
    user_id = user.id
    try:
        users_col.update_one(
            {"_id": user_id},
            {
                "$setOnInsert": {"joined_at": datetime.now()},
                "$set": {
                    "name": user.first_name,
                    "username": user.username or "None",
                    "status": "active",
                    "last_active": datetime.now()
                }
            },
            upsert=True
        )
    except Exception as e:
        logging.error(f"MongoDB Error: {e}")

def get_all_active_users():
    users = users_col.find({"status": "active"}, {"_id": 1})
    return [user["_id"] for user in users]

def get_stats():
    total = users_col.count_documents({})
    active = users_col.count_documents({"status": "active"})
    blocked = users_col.count_documents({"status": "blocked"})
    return total, active, blocked

def mark_user_blocked(user_id):
    users_col.update_one({"_id": user_id}, {"$set": {"status": "blocked"}})

# --- New Feature: Export to CSV ---
def generate_csv_file():
    filename = "users_list.csv"
    # Database မှ User အားလုံးဆွဲထုတ်ခြင်း
    users = users_col.find({})
    
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        # ခေါင်းစဉ်များ
        writer.writerow(["User ID", "Name", "Username", "Status", "Joined Date", "Last Active"])
        
        for user in users:
            writer.writerow([
                user["_id"],
                user.get("name", "N/A"),
                user.get("username", "None"),
                user.get("status", "unknown"),
                user.get("joined_at", "N/A"),
                user.get("last_active", "N/A")
            ])
    return filename

# --- Bot Commands ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_or_update_user(user)

    if user.id == ADMIN_ID:
        # Admin Menu ခလုတ် ၃ ခု
        admin_keyboard = [
            [KeyboardButton("📊 Dashboard Stats"), KeyboardButton("📂 Export User Data")],
            [KeyboardButton("📢 Broadcast Help")]
        ]
        reply_markup = ReplyKeyboardMarkup(admin_keyboard, resize_keyboard=True)
        await update.message.reply_text(f"Welcome Admin {user.first_name}!", reply_markup=reply_markup)
    else:
        await update.message.reply_text(f"မင်္ဂလာပါ {user.first_name}! စာပို့လိုက်ရင် အသံဖိုင် ပြောင်းပေးပါမယ်။")

async def admin_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text

    if user.id != ADMIN_ID:
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
        
    elif text == "📂 Export User Data":
        status_msg = await update.message.reply_text("⏳ Generating CSV file...")
        try:
            file_path = generate_csv_file()
            await update.message.reply_document(
                document=open(file_path, 'rb'),
                caption="📄 User Data List\n(User ID, Name, Status, Date)"
            )
            await status_msg.delete()
            os.remove(file_path) # ပို့ပြီးရင် Server ပေါ်ကဖျက်မယ်
        except Exception as e:
            await status_msg.edit_text(f"Error exporting: {e}")

    elif text == "📢 Broadcast Help":
        msg = (
            "📢 **Broadcast လုပ်နည်း**\n\n"
            "1. Bot ဆီသို့ ပုံ (သို့) စာ ပို့လိုက်ပါ။\n"
            "2. ထိုစာကို Reply ပြန်ပြီး `/broadcast` လို့ ရိုက်ပါ။\n"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
    
    else:
        await text_to_speech(update, context)

async def broadcast_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

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
            if original_msg.photo:
                await context.bot.send_photo(
                    chat_id=user_id, 
                    photo=original_msg.photo[-1].file_id,
                    caption=original_msg.caption
                )
            elif original_msg.text:
                await context.bot.send_message(
                    chat_id=user_id, 
                    text=original_msg.text
                )
            success += 1
        except Forbidden:
            mark_user_blocked(user_id)
            blocked += 1
        except Exception as e:
            logging.error(f"Broadcast Fail: {user_id} - {e}")

    await status_msg.edit_text(
        f"✅ **Broadcast Finished!**\n\n"
        f"Sent: {success}\n"
        f"Blocked: {blocked} (Updated in DB)"
    , parse_mode="Markdown")

async def text_to_speech(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_or_update_user(user)

    text = update.message.text
    if not text: return

    # Admin Command စာသားတွေဆိုရင် TTS မလုပ်ဘူး
    if text in ["📊 Dashboard Stats", "📢 Broadcast Help", "📂 Export User Data"]:
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
            await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"Error: {e}")

def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("broadcast", broadcast_reply))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_panel_handler))
    application.run_polling()

if __name__ == "__main__":
    keep_alive()
    main()
