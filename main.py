import os
import logging
import asyncio
import nest_asyncio
from flask import Flask
from threading import Thread
import edge_tts
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

# 2. Get Token from Environment Variable
# ဒီနေရာမှာ တိုက်ရိုက်မထည့်ဘဲ os.environ နဲ့ လှမ်းယူပါမယ်
TOKEN = os.environ.get("BOT_TOKEN")

# Token မရှိရင် Error ပြပြီး ရပ်သွားအောင် စစ်ဆေးခြင်း
if not TOKEN:
    raise ValueError("No BOT_TOKEN found in environment variables!")

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Mingalarpar! စာပို့လိုက်ရင် အသံဖိုင် ပြောင်းပေးပါမယ်။")

async def text_to_speech(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.message.chat_id
    
    await update.message.reply_text("အသံဖိုင် ပြောင်းနေပါပြီ... ခဏစောင့်ပါ...")

    output_file = f"{chat_id}.mp3"
    voice = "en-US-ChristopherNeural"  # မြန်မာလိုဆို "my-MM-ThihaNeural"
    
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_file)
        
        await update.message.reply_voice(voice=open(output_file, 'rb'))
        
        os.remove(output_file)
        
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def main():
    nest_asyncio.apply()
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_to_speech))

    await application.run_polling()

if __name__ == "__main__":
    keep_alive()
    asyncio.run(main())
