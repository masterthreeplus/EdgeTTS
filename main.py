import os
import logging
import uuid
import csv
import asyncio
from datetime import datetime, timedelta
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
    return "Bot is running with Queue & Cooldown System!"

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
MAX_CHARS = 3000
COOLDOWN_SECONDS = 30 # တစ်ခါသုံးပြီးရင် စက္ကန့် ၃၀ စောင့်ရမယ်

# Render Free Plan အတွက် တပြိုင်နက် ၂ ယောက်ပဲ လက်ခံမယ် (ကျန်လူ စောင့်ရမယ်)
CONCURRENT_LIMIT = asyncio.Semaphore(2) 

# User တွေရဲ့ Cooldown မှတ်ဖို့ Memory
user_cooldowns = {}

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
                "$setOnInsert": {"joined_at": datetime.now(), "generated_count": 0},
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

def increment_usage(user_id):
    try:
        users_col.update_one({"_id": user_id}, {"$inc": {"generated_count": 1}})
    except Exception as e:
        logging.error(f"DB Error: {e}")

def get_all_active_users():
    users = users_col.find({"status": "active"}, {"_id": 1})
    return [user["_id"] for user in users]

def get_stats():
    total = users_col.count_documents({})
    active = users_col.count_documents({"status": "active"})
    blocked = users_col.count_documents({"status": "blocked"})
    pipeline = [{"$group": {"_id": None, "total_generated": {"$sum": "$generated_count"}}}]
    result = list(users_col.aggregate(pipeline))
    total_generated = result[0]["total_generated"] if result else 0
    return total, active, blocked, total_generated

def mark_user_blocked(user_id):
    users_col.update_one({"_id": user_id}, {"$set": {"status": "blocked"}})

def generate_csv_file():
    filename = "users_list.csv"
    users = users_col.find({})
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["User ID", "Name", "Username", "Status", "Joined Date", "Last Active", "Generated Count"])
        for user in users:
            writer.writerow([
                user["_id"], user.get("name", "N/A"), user.get("username", "None"),
                user.get("status", "unknown"), user.get("joined_at", "N/A"),
                user.get("last_active", "N/A"), user.get("generated_count", 0)
            ])
    return filename

# --- Bot Commands ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_or_update_user(user)

    if user.id == ADMIN_ID:
        admin_keyboard = [
            [KeyboardButton("📊 Dashboard Stats"), KeyboardButton("📂 Export User Data")],
            [KeyboardButton("📢 Broadcast Help")]
        ]
        reply_markup = ReplyKeyboardMarkup(admin_keyboard, resize_keyboard=True)
        await update.message.reply_text(f"Welcome Admin {user.first_name}!", reply_markup=reply_markup)
    else:
        await update.message.reply_text(
            f"မင်္ဂလာပါ {user.first_name}!\n"
            f"စာလုံးရေ {MAX_CHARS} အထိ အသံဖိုင် (MP3) ပြောင်းပေးပါတယ်။\n"
            f"Fair Usage: တစ်ခါသုံးပြီးရင် {COOLDOWN_SECONDS} စက္ကန့် စောင့်ပေးပါ။"
        )

async def admin_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text

    if user.id != ADMIN_ID:
        await text_to_speech(update, context) 
        return

    if text == "📊 Dashboard Stats":
        total, active, blocked, total_gen = get_stats()
        msg = (
            f"📈 **Bot Statistics**\n\n"
            f"👥 Total Users: {total}\n"
            f"✅ Active Users: {active}\n"
            f"🚫 Blocked Users: {blocked}\n"
            f"🔊 Total Generated: {total_gen}"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
        
    elif text == "📂 Export User Data":
        status_msg = await update.message.reply_text("⏳ Generating CSV...")
        try:
            file_path = generate_csv_file()
            await update.message.reply_document(document=open(file_path, 'rb'), caption="User Data")
            await status_msg.delete()
            os.remove(file_path)
        except Exception as e:
            await status_msg.edit_text(f"Error: {e}")

    elif text == "📢 Broadcast Help":
        await update.message.reply_text("Reply to a message with `/broadcast` to send to all users.")
    else:
        await text_to_speech(update, context)

async def broadcast_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a message/photo with `/broadcast`.")
        return

    original_msg = update.message.reply_to_message
    users = get_all_active_users()
    status_msg = await update.message.reply_text(f"🚀 Broadcasting to {len(users)} users...")
    
    success, blocked = 0, 0
    for user_id in users:
        try:
            if original_msg.photo:
                await context.bot.send_photo(chat_id=user_id, photo=original_msg.photo[-1].file_id, caption=original_msg.caption)
            elif original_msg.text:
                await context.bot.send_message(chat_id=user_id, text=original_msg.text)
            success += 1
        except Forbidden:
            mark_user_blocked(user_id)
            blocked += 1
        except Exception: pass
        await asyncio.sleep(0.05) # Spam limit

    await status_msg.edit_text(f"✅ Broadcast Done!\nSent: {success}, Blocked: {blocked}")

async def text_to_speech(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_or_update_user(user)
    text = update.message.text
    if not text or text in ["📊 Dashboard Stats", "📢 Broadcast Help", "📂 Export User Data"]: return

    # 1. Check Character Limit
    if len(text) > MAX_CHARS:
        await update.message.reply_text(f"❌ စာလုံးရေများလွန်းသည် ({len(text)}/{MAX_CHARS})")
        return

    # 2. Check Cooldown (Fairness)
    last_used = user_cooldowns.get(user.id)
    if last_used:
        elapsed = (datetime.now() - last_used).total_seconds()
        if elapsed < COOLDOWN_SECONDS:
            wait_time = int(COOLDOWN_SECONDS - elapsed)
            await update.message.reply_text(f"⏳ Fair Usage: ကျေးဇူးပြု၍ {wait_time} စက္ကန့် စောင့်ပေးပါ။")
            return

    status_msg = await update.message.reply_text("Processing... (Queue ဝင်နေပါသည်)")
    
    # 3. Queue System (Semaphore) - တပြိုင်နက် ၂ ယောက်ပဲ လုပ်ခွင့်ပြုမည်
    async with CONCURRENT_LIMIT:
        await status_msg.edit_text("Generating Audio... 🎵")
        output_file = f"{uuid.uuid4()}.mp3"
        
        try:
            communicate = edge_tts.Communicate(text, VOICE)
            await communicate.save(output_file)
            
            if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                with open(output_file, 'rb') as audio:
                    await update.message.reply_audio(
                        audio=audio, 
                        title=f"Voice-{datetime.now().strftime('%H%M%S')}",
                        performer="Bot AI"
                    )
                
                # Update Cooldown & Stats
                user_cooldowns[user.id] = datetime.now()
                increment_usage(user.id)
                
                os.remove(output_file)
                await status_msg.delete()
            else:
                await status_msg.edit_text("Error: Audio file empty.")

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
