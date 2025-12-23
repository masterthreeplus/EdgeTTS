import os
import logging
import asyncio
import uuid
from flask import Flask
from threading import Thread
import edge_tts
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# 1. Flask App for Keep-Alive (Render မအိပ်အောင်)
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 5000)) 
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask, daemon=True)
    t.start()

# 2. Configuration
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise ValueError("No BOT_TOKEN found in environment variables!")

# အသံကို Thiha (Male) တစ်ခုတည်း အသေထားပါမယ်
VOICE = "my-MM-ThihaNeural"

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("မင်္ဂလာပါ! စာပို့လိုက်ရင် အသံဖိုင် (Thiha) ပြောင်းပေးပါမယ်။")

async def text_to_speech(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    # စာမပါရင် ဘာမှမလုပ်ပါ
    if not text:
        await update.message.reply_text("စာသား (Text) သီးသန့် ပို့ပေးပါခင်ဗျာ။")
        return

    chat_id = update.message.chat_id
    await update.message.reply_text("Processing...")

    # Unique Filename ဖန်တီးခြင်း
    output_file = f"{uuid.uuid4()}.mp3"
    
    try:
        # TTS ဖန်တီးခြင်း
        communicate = edge_tts.Communicate(text, VOICE)
        await communicate.save(output_file)
        
        # ဖိုင်ရှိမရှိ စစ်ဆေးပြီး ပို့ခြင်း
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            with open(output_file, 'rb') as audio:
                await update.message.reply_voice(voice=audio)
            
            # ပို့ပြီးရင် ဖျက်မယ်
            os.remove(output_file)
        else:
            await update.message.reply_text("Error: Audio file creation failed.")

    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        logging.error(f"TTS Error: {e}")

async def main():
    application = Application.builder().token(TOKEN).build()

    # Commands
    application.add_handler(CommandHandler("start", start))
    
    # Message Handler (စာဝင်လာသမျှ အသံပြောင်းမယ်)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_to_speech))

    await application.run_polling()

if __name__ == "__main__":
    keep_alive()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
