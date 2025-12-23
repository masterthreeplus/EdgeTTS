import os
import logging
import asyncio
import uuid
from flask import Flask
from threading import Thread
import edge_tts
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import Forbidden

# MongoDB အတွက် Import လုပ်ခြင်း
import pymongo
import certifi

# 1. Flask App (Keep-Alive)
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running with MongoDB!"

def run_flask():
    port = int(os.environ.get("PORT", 5000)) 
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask, daemon=True)
    t.start()

# 2. Configuration
TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URI = os.environ.get("MONGO_URI") # Database URL
ADMIN_ID = int(os.environ.get("ADMIN_ID")) 

if not TOKEN or not MONGO_URI or not ADMIN_ID:
    raise ValueError("Missing BOT_TOKEN, MONGO_URI or ADMIN_ID!")

VOICE = "my-MM-ThihaNeural"
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- MongoDB Functions ---

# Database ချိတ်ဆက်ခြင်း
# tlsCAFile=certifi.where() သည် Render တွင် SSL Error မတက်စေရန် အရေးကြီးသည်
client = pymongo.MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = client["telegram_bot_db"] # Database နာမည်
users_col = db["users"] # Collection (Table) နာမည်

def add_user(user_id, username):
    """User ကို Database ထဲ ထည့်ခြင်း (ရှိပြီးသားဆိုရင် update လုပ်မယ်)"""
    try:
        users_col.update_one(
            {"_id": user_id}, # ID တူရင်
            {"$set": {"username": username, "status": "active"}}, # Update လုပ်မယ်
            upsert=True # မရှိရင် အသစ်ထည့်မယ်
        )
    except Exception as e:
        logging.error(f"MongoDB Error: {e}")

def get_all_users():
    """User ID အားလုံးကို ဆွဲထုတ်ခြင်း"""
    # _id ဆိုတာ user_id ပါပဲ
    users = users_col.find({}, {"_id": 1})
    return [user["_id"] for user in users]

def get_user_count():
    """လူဦးရေ ရေတွက်ခြင်း"""
    return users_col.count_documents({})

# --- Bot Commands ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username) # Save to MongoDB
    
    await update.message.reply_text(f"မင်္ဂလာပါ {user.first_name}! (Powered by MongoDB) 🍃")

# Admin Dashboard
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    try:
        count = get_user_count()
        await update.message.reply_text(f"📊 Total Users in MongoDB: {count}")
    except Exception as e:
        await update.message.reply_text(f"Error checking stats: {e}")

# Broadcast Logic (Same as before)
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text("အသုံးပြုပုံ: /broadcast [စာသား]")
        return

    message_text = " ".join(context.args)
    users = get_all_users() # Getting List from MongoDB
    
    await update.message.reply_text(f"📣 Broadcasting to {len(users)} users...")
    
    success_count = 0
    blocked_count = 0
    
    for user_id in users:
        try:
            await context.bot.send_message(chat_id=user_id, text=message_text)
            success_count += 1
            await asyncio.sleep(0.05)
        except Forbidden:
            blocked_count += 1
            # Block ထားရင် Database မှာ status update လုပ်ထားလို့ရပါတယ် (Optional)
            users_col.update_one({"_id": user_id}, {"$set": {"status": "blocked"}})
        except Exception as e:
            logging.error(f"Failed to send to {user_id}: {e}")

    await update.message.reply_text(
        f"✅ Broadcast Complete!\nSuccess: {success_count}\nBlocked: {blocked_count}"
    )

async def text_to_speech(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username) # Save active user

    text = update.message.text
    if not text:
        await update.message.reply_text("စာသား (Text) သီးသန့် ပို့ပေးပါခင်ဗျာ။")
        return

    chat_id = update.message.chat_id
    await update.message.reply_text("Processing...")

    output_file = f"{uuid.uuid4()}.mp3"
    
    try:
        communicate = edge_tts.Communicate(text, VOICE)
        await communicate.save(output_file)
        
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            with open(output_file, 'rb') as audio:
                await update.message.reply_voice(voice=audio)
            os.remove(output_file)
        else:
            await update.message.reply_text("Error: Audio file creation failed.")

    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def main():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_to_speech))

    await application.run_polling()

if __name__ == "__main__":
    keep_alive()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
