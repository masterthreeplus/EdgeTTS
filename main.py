async def text_to_speech(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # စာသား ပါ/မပါ စစ်မယ်
    text = update.message.text
    if not text:
        await update.message.reply_text("စာသား (Text) သီးသန့်ပို့ပေးပါခင်ဗျာ။")
        return

    chat_id = update.message.chat_id
    await update.message.reply_text(f"Processing: {text[:20]}...") # Debugging အတွက် စာနည်းနည်းပြမယ်

    output_file = f"{chat_id}.mp3"
    
    # Voice ID အမှန်ဖြစ်ဖို့ သေချာပါစေ
    # မြန်မာစာအတွက်ဆိုရင်: "my-MM-ThihaNeural" (Male) or "my-MM-NularNeural" (Female)
    # အင်္ဂလိပ်စာအတွက်ဆိုရင်: "en-US-ChristopherNeural" or "en-US-AriaNeural"
    
    voice = "my-MM-ThihaNeural" # ဒီနေရာမှာ ကိုယ်သုံးချင်တဲ့ Voice ကို အသေအချာ ရွေးပါ

    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_file)
        
        # ဖိုင်အရွယ်အစား ၀ ဖြစ်နေလား စစ်မယ်
        if os.path.getsize(output_file) == 0:
            raise Exception("Received empty audio file from Edge TTS.")

        await update.message.reply_voice(voice=open(output_file, 'rb'))
        
        os.remove(output_file)
        
    except Exception as e:
        logging.error(f"Error details: {e}") # Log ထဲမှာ အပြည့်အစုံ ကြည့်မယ်
        await update.message.reply_text(f"Error: {e}\n(Try changing the voice ID or shorter text)")
