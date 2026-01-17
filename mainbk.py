import os
import logging
import uuid
import csv
import time
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
    return "Bot is running with Advanced Logic!"

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
COOLDOWN_SECONDS = 30 

# Queue System (Semaphore)
CONCURRENT_LIMIT = asyncio.Semaphore(2) 

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
                "$setOnInsert": {
                    "joined_at": datetime.now(), 
                    "generated_count": 0,
                    "last_generated": datetime.min # Cooldown အတွက် Initial Value
                },
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
        logging.exception("MongoDB Update Error")

def check_cooldown(user_id):
    """Database ထဲက last_generated ကို စစ်ဆေးခြင်း"""
    user = users_col.find_one({"_id": user_id}, {"last_generated": 1})
    if not user: return True # User မရှိသေးရင် Allow
    
    last_gen = user.get("last_generated", datetime.min)
    
    # အချိန်ကွာခြားချက် တွက်ချက်ခြင်း
    if (datetime.now() - last_gen).total_seconds() < COOLDOWN_SECONDS:
        remaining = int(COOLDOWN_SECONDS - (datetime.now() - last_gen).total_seconds())
        return remaining # စောင့်ရမည့် စက္ကန့် ပြန်ပို့
    
    return 0 # 0 ဆိုရင် Allow

def update_usage_stats(user_id):
    """အောင်မြင်သွားရင် Count တိုးပြီး Time မှတ်မယ်"""
    try:
        users_col.update_one(
            {"_id": user_id},
            {
                "$inc": {"generated_count": 1},
                "$set": {"last_generated": datetime.now()} # Database Cooldown Storage
            }
        )
    except Exception as e:
        logging.exception("DB Stats Update Error")

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
    # Filename Conflict မဖြစ်အောင် Timestamp သုံးမယ်
    filename = f"users_{int(time.time())}.csv"
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

# --- Admin Handlers (Admin Only) ---
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total, active, blocked, total_gen = get_stats()
    msg = (
        f"📈 **Bot Statistics**\n\n"
        f"👥 Total Users: {total}\n"
        f"✅ Active Users: {active}\n"
        f"🚫 Blocked Users: {blocked}\n"
        f"🔊 Total Generated: {total_gen}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def admin_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("⏳ Generating CSV...")
    file_path = None
    try:
        file_path = generate_csv_file()
        await update.message.reply_document(document=open(file_path, 'rb'), caption="User Data")
    except Exception as e:
        logging.exception("Export Error")
        await status_msg.edit_text(f"Error: {e}")
    finally:
        # File Cleanup (သေချာပေါက် ဖျက်မယ့်နေရာ)
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            await status_msg.delete()

async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Reply to a message with `/broadcast` to send to all users.")

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
        except Exception: 
            logging.exception(f"Broadcast error for {user_id}")
        
        # Broadcast Safe Limit (0.15s)
        await asyncio.sleep(0.15) 

    await status_msg.edit_text(f"✅ Broadcast Done!\nSent: {success}, Blocked: {blocked}")

# --- Text Handler (General Users) ---
async def text_to_speech(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_or_update_user(user)
    text = update.message.text
    
    # စာမရှိရင် Return
    if not text: return 

    # 1. Check Character Limit
    if len(text) > MAX_CHARS:
        await update.message.reply_text(f"❌ စာလုံးရေများလွန်းသည် ({len(text)}/{MAX_CHARS})")
        return

    # 2. Check Cooldown from DB
    remaining_time = check_cooldown(user.id)
    if remaining_time > 0:
        await update.message.reply_text(f"⏳ Fair Usage: ကျေးဇူးပြု၍ {remaining_time} စက္ကန့် စောင့်ပေးပါ။")
        return

    status_msg = await update.message.reply_text("Processing... (Queue ဝင်နေပါသည်)")
    output_file = f"{uuid.uuid4()}.mp3"

    try:
        # 3. Queue System
        async with CONCURRENT_LIMIT:
            await status_msg.edit_text("Generating Audio... 🎵")
            
            communicate = edge_tts.Communicate(text, VOICE)
            await communicate.save(output_file)
            
            if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                with open(output_file, 'rb') as audio:
                    await update.message.reply_audio(
                        audio=audio, 
                        title=f"Voice-{datetime.now().strftime('%H%M%S')}",
                        performer="Bot AI"
                    )
                
                # Success: Update stats & cooldown in DB
                update_usage_stats(user.id)
            else:
                await status_msg.edit_text("Error: Audio file empty.")

    except Exception as e:
        logging.exception("TTS Generation Error")
        await status_msg.edit_text("Sorry, an error occurred during generation.")
    
    finally:
        # 4. File Cleanup (အရေးအကြီးဆုံး ပြင်ဆင်ချက်)
        # Error တက်တက်၊ မတက်တက် ဖိုင်ကျန်နေရင် ဖျက်မယ်
        if os.path.exists(output_file):
            os.remove(output_file)
        
        # Processing message ကို ဖျက်မယ် (Optional)
        try:
            await status_msg.delete()
        except:
            pass

def main():
    application = Application.builder().token(TOKEN).build()
    
    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("broadcast", broadcast_reply))
    
    # Admin Handlers (Admin ID စစ်ပြီးမှ အလုပ်လုပ်မည် - Conflict မဖြစ်တော့ပါ)
    # Filter: Text Match AND User is Admin
    application.add_handler(MessageHandler(filters.Regex("^📊 Dashboard Stats$") & filters.User(ADMIN_ID), admin_stats))
    application.add_handler(MessageHandler(filters.Regex("^📂 Export User Data$") & filters.User(ADMIN_ID), admin_export))
    application.add_handler(MessageHandler(filters.Regex("^📢 Broadcast Help$") & filters.User(ADMIN_ID), admin_help))

    # General Text Handler (Admin Command တွေ မပါတော့ပါ)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_to_speech))

    application.run_polling()

if __name__ == "__main__":
    keep_alive()
    main()
