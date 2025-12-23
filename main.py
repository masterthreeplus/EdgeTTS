import os
import logging
import asyncio
import nest_asyncio
from flask import Flask
from threading import Thread
import edge_tts
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# 1. Flask App for Keep-Alive
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 5000)) 
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# 2. Configuration
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise ValueError("No BOT_TOKEN found in environment variables!")

# Voice Constants
VOICE_MALE = "my-MM-ThihaNeural"
VOICE_FEMALE = "my-MM-NularNeural"

# User Settings (Memory)
user_preferences = {}

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- Bot Functions ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # အောက်ဆုံးမှာ အမြဲပေါ်နေမယ့် Menu ခလုတ်များ
    keyboard = [
        ["👨 Male Voice (Thiha)", "👩 Female Voice (Nular)"],
        ["ℹ️ Current Settings"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "မင်္ဂလာပါ! စာပို့လိုက်ရင် အသံဖိုင် ပြောင်းပေးပါမယ်။\n\n"
        "အောက်က ခလုတ်တွေနဲ့ အသံပြောင်းလို့ရပါတယ် 👇", 
        reply_markup=reply_markup
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.message.chat_id
    
    # ၁။ ခလုတ်နှိပ်တာလား စစ်မယ်
    if text == "👨 Male Voice (Thiha)":
        user_preferences[chat_id] = VOICE_MALE
        await update.message.reply_text("✅ အသံကို **Thiha (Male)** သို့ ပြောင်းလိုက်ပါပြီ။")
        return
        
    elif text == "👩 Female Voice (Nular)":
        user_preferences[chat_id] = VOICE_FEMALE
        await update.message.reply_text("✅ အသံကို **Nular (Female)** သို့ ပြောင်းလိုက်ပါပြီ။")
        return

    elif text == "ℹ️ Current Settings":
        current_voice = user_preferences.get(chat_id, VOICE_MALE)
        voice_name = "Thiha (Male)" if current_voice == VOICE_MALE else "Nular (Female)"
        await update.message.reply_text(f"လက်ရှိသုံးထားသော အသံ: **{voice_name}**")
        return

    # ၂။ ခလုတ်မဟုတ်ရင် TTS လုပ်မယ်
    # Default Voice ယူမယ်
    voice = user_preferences.get(chat_id, VOICE_MALE)
    
    await update.message.reply_text(f"Processing... ({'Male' if voice == VOICE_MALE else 'Female'})")

    output_file = f"{chat_id}.mp3"
    
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_file)
        
        # File Size စစ်မယ်
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            await update.message.reply_voice(voice=open(output_file, 'rb'))
            os.remove(output_file)
        else:
            await update.message.reply_text("Error: Audio file creation failed (0 bytes).")

    except Exception as e:
        error_msg = str(e)
        if "No audio was received" in error_msg and voice == VOICE_FEMALE:
             await update.message.reply_text(
                 "⚠️ Female Voice Error:\n"
                 "Microsoft Server မှ အမျိုးသမီးအသံကို ယာယီပိတ်ထားပုံရပါသည်။\n"
                 "ကျေးဇူးပြု၍ Male Voice ကို ပြောင်းသုံးပေးပါ။"
             )
        else:
            await update.message.reply_text(f"Error: {e}")
            logging.error(f"TTS Error: {e}")

async def main():
    nest_asyncio.apply()
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    # MessageHandler တစ်ခုတည်းက စာကော Button ကော ကိုင်တွယ်မယ်
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await application.run_polling()

if __name__ == "__main__":
    keep_alive()
    asyncio.run(main())
