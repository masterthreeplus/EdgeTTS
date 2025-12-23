import os
import logging
import asyncio
import nest_asyncio
from flask import Flask
from threading import Thread
import edge_tts
# အောက်ပါ Import စာကြောင်းတွေ ကျန်ခဲ့လို့ Error တက်တာပါ
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# 1. Flask App for Render Keep-Alive
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

# 2. Telegram Bot Logic
# Token ကို Environment Variable ကနေ ယူမယ်
TOKEN = os.environ.get("BOT_TOKEN")

if not TOKEN:
    raise ValueError("No BOT_TOKEN found in environment variables!")

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Mingalarpar! စာပို့လိုက်ရင် အသံဖိုင် ပြောင်းပေးပါမယ်။")

async def text_to_speech(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    # စာမပါရင် (ဥပမာ - Sticker) ဘာမှ မလုပ်ဘူး
    if not text:
        await update.message.reply_text("ကျေးဇူးပြုပြီး စာသား (Text) သီးသန့် ပို့ပေးပါ။")
        return

    chat_id = update.message.chat_id
    await update.message.reply_text("Processing...")

    output_file = f"{chat_id}.mp3"
    
    # Voice ID (မြန်မာအသံ လိုချင်ရင် 'my-MM-ThihaNeural' လို့ ပြောင်းပါ)
    voice = "my-MM-ThihaNeural" 

    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_file)
        
        # Audio ဖိုင်ရမရ စစ်ဆေးခြင်း
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            await update.message.reply_voice(voice=open(output_file, 'rb'))
            os.remove(output_file) # ပြီးရင် ဖျက်မယ်
        else:
            await update.message.reply_text("Error: Audio file creation failed.")

    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        logging.error(f"TTS Error: {e}")

async def main():
    nest_asyncio.apply()
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_to_speech))

    await application.run_polling()

if __name__ == "__main__":
    keep_alive() # Start Flask server
    asyncio.run(main()) # Start Bot
