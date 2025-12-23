import os
import logging
import asyncio
import nest_asyncio
from flask import Flask
from threading import Thread
import edge_tts
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

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

# 2. Configuration & Variables
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise ValueError("No BOT_TOKEN found in environment variables!")

# User တွေရဲ့ Voice ရွေးချယ်မှုကို ဒီမှာ ယာယီသိမ်းပါမယ်
# Format: { chat_id: "voice_id" }
user_preferences = {}

# Voice Constants
VOICE_MALE = "my-MM-ThihaNeural"
VOICE_FEMALE = "my-MM-NularNeural"

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- Bot Functions ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "မင်္ဂလာပါ! စာပို့လိုက်ရင် အသံဖိုင် ပြောင်းပေးပါမယ်။\n\n"
        "အသံပြောင်းချင်ရင် /voice လို့ ရိုက်ပါ (သို့) Menu ကနေ ရွေးပါ။"
    )
    await update.message.reply_text(welcome_text)

# Voice ရွေးတဲ့ ခလုတ်ပြမယ့် Function
async def voice_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("👨 Thiha (Male)", callback_data=VOICE_MALE)],
        [InlineKeyboardButton("👩 Nular (Female)", callback_data=VOICE_FEMALE)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("အသံရွေးချယ်ပါ (Choose Voice):", reply_markup=reply_markup)

# ခလုတ်နှိပ်လိုက်ရင် အလုပ်လုပ်မယ့် Function
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # Button loading circle ပျောက်အောင်လုပ်ခြင်း

    selected_voice = query.data
    chat_id = query.message.chat.id
    
    # User ရွေးလိုက်တဲ့ အသံကို Dictionary ထဲမှာ သိမ်းမယ်
    user_preferences[chat_id] = selected_voice
    
    voice_name = "Thiha (Male)" if selected_voice == VOICE_MALE else "Nular (Female)"
    
    # Message ကို ပြင်ပြီး အသိပေးမယ်
    await query.edit_message_text(text=f"✅ အသံကို **{voice_name}** သို့ ပြောင်းလဲလိုက်ပါပြီ။")

async def text_to_speech(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text:
        await update.message.reply_text("စာသား (Text) သီးသန့် ပို့ပေးပါခင်ဗျာ။")
        return

    chat_id = update.message.chat_id
    
    # User က ဘာရွေးထားလဲ စစ်မယ်။ မရွေးရသေးရင် Default (Male) ယူမယ်
    voice = user_preferences.get(chat_id, VOICE_MALE)
    
    await update.message.reply_text(f"Processing... ({'Male' if voice == VOICE_MALE else 'Female'})")

    output_file = f"{chat_id}.mp3"
    
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_file)
        
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            await update.message.reply_voice(voice=open(output_file, 'rb'))
            os.remove(output_file)
        else:
            await update.message.reply_text("Error: Audio file creation failed.")

    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        logging.error(f"TTS Error: {e}")

async def main():
    nest_asyncio.apply()
    application = Application.builder().token(TOKEN).build()

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("voice", voice_menu)) # /voice command အသစ်
    application.add_handler(CallbackQueryHandler(button_callback)) # Button နှိပ်တာကို နားထောင်ဖို့
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_to_speech))

    await application.run_polling()

if __name__ == "__main__":
    keep_alive()
    asyncio.run(main())
