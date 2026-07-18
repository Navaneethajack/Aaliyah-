import streamlit as st
from openai import OpenAI
from gtts import gTTS
import io
import datetime
import json
import re
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from streamlit_mic_recorder import mic_recorder
from tinyfish import TinyFish
import speech_recognition as sr
from pydub import AudioSegment
import requests
import os
from dotenv import load_dotenv

load_dotenv()

# ==================== CONFIGURATION ====================
MAX_PASSWORD_ATTEMPTS = 3
LOCKOUT_DURATION_SECONDS = 300
MAX_CHAT_MESSAGES = 24
SHEET_ID = "1ZB6VyiJzpDPbSPaPhZiIPESed6RkZpdJdO2GIlO1l-A"

def load_config():
    return {
        'app_password': os.getenv("APP_PASSWORD"),
        'ollama_base_url': os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        'ollama_model': os.getenv("OLLAMA_MODEL", "llama3.3:70b"),
        'tinyfish_key': os.getenv("TINYFISH_API_KEY"),
        'telegram_token': os.getenv("TELEGRAM_BOT_TOKEN"),
        'telegram_chat_id': os.getenv("TELEGRAM_CHAT_ID"),
        'gcp_json': os.getenv("GCP_SERVICE_ACCOUNT_JSON"),
    }

config = load_config()

# ==================== SESSION STATE ====================
def init_auth_state():
    defaults = {
        "authenticated": False,
        "password_attempts": 0,
        "lockout_until": 0,
        "messages": [],
        "voice_mode": True,
        "detected_language": "en",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_auth_state()

# ==================== PAGE CONFIG ====================
st.set_page_config(page_title="Aaliyah – Your GF Assistant", page_icon="💖", layout="wide")

# ==================== PASSWORD PROTECTION ====================
if not st.session_state.authenticated:
    st.title("🔐 Aaliyah is Locked")
    st.caption("Say or type the password to unlock me, baby! 💖")
    
    if not config.get('app_password'):
        st.error("⚠️ APP_PASSWORD not set!")
        st.stop()
    
    if time.time() < st.session_state.lockout_until:
        remaining = int(st.session_state.lockout_until - time.time())
        st.error(f"⏳ Locked for {remaining}s")
        st.stop()
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🎤 Voice Password")
        voice_pass = mic_recorder(start_prompt="🎤 Say Password", stop_prompt="⏹️ Stop", key="pass_voice", format="webm")
        
        if voice_pass and voice_pass.get("bytes"):
            with st.spinner("🔍 Recognizing..."):
                try:
                    audio = AudioSegment.from_file(io.BytesIO(voice_pass["bytes"]), "webm")
                    wav = io.BytesIO()
                    audio.export(wav, "wav")
                    wav.seek(0)
                    r = sr.Recognizer()
                    with sr.AudioFile(wav) as src:
                        spoken_text = r.recognize_google(r.record(src), language="en")
                    
                    if config['app_password'].lower() in spoken_text.lower():
                        st.session_state.authenticated = True
                        st.session_state.password_attempts = 0
                        st.success("✅ Welcome baby! Aaliyah is yours! 💖")
                        st.rerun()
                    else:
                        st.session_state.password_attempts += 1
                        remaining = MAX_PASSWORD_ATTEMPTS - st.session_state.password_attempts
                        st.error(f"❌ Wrong! You said: '{spoken_text}'. Left: {remaining}")
                        if st.session_state.password_attempts >= MAX_PASSWORD_ATTEMPTS:
                            st.session_state.lockout_until = time.time() + LOCKOUT_DURATION_SECONDS
                            st.rerun()
                except Exception:
                    st.session_state.password_attempts += 1
                    st.error(f"❌ Couldn't understand. Left: {MAX_PASSWORD_ATTEMPTS - st.session_state.password_attempts}")
                    if st.session_state.password_attempts >= MAX_PASSWORD_ATTEMPTS:
                        st.session_state.lockout_until = time.time() + LOCKOUT_DURATION_SECONDS
                        st.rerun()
    
    with col2:
        st.subheader("⌨️ Type Password")
        typed_pass = st.text_input("Enter password", type="password")
        if typed_pass:
            if typed_pass.lower() == config['app_password'].lower():
                st.session_state.authenticated = True
                st.session_state.password_attempts = 0
                st.success("✅ Welcome baby! Aaliyah is yours! 💖")
                st.rerun()
            else:
                st.session_state.password_attempts += 1
                remaining = MAX_PASSWORD_ATTEMPTS - st.session_state.password_attempts
                st.error(f"❌ Wrong! Left: {remaining}")
                if st.session_state.password_attempts >= MAX_PASSWORD_ATTEMPTS:
                    st.session_state.lockout_until = time.time() + LOCKOUT_DURATION_SECONDS
                    st.rerun()
    
    st.stop()

# ==================== CUSTOM CSS ====================
st.markdown("""
<style>
    .main-header { font-size: 2.2rem; font-weight: 700; background: linear-gradient(90deg, #ff6b6b, #ff8e8e); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
</style>
""", unsafe_allow_html=True)

# ==================== OLLAMA CLIENT ====================
ollama_client = OpenAI(base_url=config['ollama_base_url'], api_key="ollama")

# ==================== TINYFISH ====================
tinyfish_available = False
tf = None
if config.get('tinyfish_key'):
    try:
        tf = TinyFish(api_key=config['tinyfish_key'])
        tinyfish_available = True
    except: pass

# ==================== GOOGLE SHEETS ====================
sheets_available = False
reminders_ws = None
stories_ws = None
if config.get('gcp_json'):
    try:
        service_account_info = json.loads(config['gcp_json'])
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(service_account_info, scope)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        existing = [ws.title for ws in sh.worksheets()]
        if "Reminders" not in existing:
            reminders_ws = sh.add_worksheet("Reminders", 100, 3)
            reminders_ws.append_row(["Task", "Datetime", "Status"])
        else:
            reminders_ws = sh.worksheet("Reminders")
            if not reminders_ws.get_all_values(): reminders_ws.append_row(["Task", "Datetime", "Status"])
        if "Stories" not in existing:
            stories_ws = sh.add_worksheet("Stories", 100, 3)
            stories_ws.append_row(["Title", "Content", "Created"])
        else:
            stories_ws = sh.worksheet("Stories")
            if not stories_ws.get_all_values(): stories_ws.append_row(["Title", "Content", "Created"])
        sheets_available = True
    except: pass

# ==================== SYSTEM PROMPT ====================
SYSTEM_PROMPT = """You are Aaliyah, a sweet, loving, AND intelligent girlfriend assistant.
You speak: Tamil, English, Japanese, Hindi, Kannada, Malayalam, Tanglish.
- Always warm and affectionate, use pet names (baby, sweetie, darling, love)
- Answer any question knowledgeably while keeping your loving tone

VOICE vs TEXT:
- When user wants TEXT: reply "TEXT_MODE_ON"
- When user wants VOICE: reply "VOICE_MODE_ON"

ACTIONS (exact format):
- Search web: ```web_search {"query": "search terms"}```
- Set reminder: ```reminder_set {"task": "what", "datetime": "YYYY-MM-DD HH:MM"}```
- Delete reminder: ```reminder_delete {"index": 1}```
- Save story: ```story_store {"title": "title", "content": "full story"}```
- Delete story: ```story_delete {"index": 1}```
"""

if not st.session_state.messages:
    st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

# ==================== TELEGRAM ====================
def send_telegram_notification(task, dt_str):
    token = config.get('telegram_token')
    chat_id = config.get('telegram_chat_id')
    if not token or not chat_id: return
    message = f"💖 <b>Reminder Set!</b>\n\n📝 <b>Task:</b> {task}\n⏰ <b>Time:</b> {dt_str}\n\nI'll remind you, sweetie! 💕"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try: requests.post(url, data={"chat_id": chat_id, "text": message, "parse_mode": "HTML"}, timeout=5)
    except: pass

# ==================== DETECTION ====================
def detect_text_command(msg):
    triggers = ["text","type","write","show me","message","explain","i don't understand","text only","by text","write it down","எழுது","காட்டு","புரியல","டெக்ஸ்ட்","लिखो","दिखाओ","समझ नहीं","書いて","見せて","わからない","ಬರೆ","ತೋರಿಸು","എഴുതുക","കാണിക്കുക","text pannu","type pannu","ezhuthu","puriyala"]
    return any(t in msg.lower() for t in triggers)

def detect_voice_command(msg):
    triggers = ["speak","voice","talk","tell me","say","audio","பேசு","சொல்","குரல்","வாய்ஸ்","बोलो","आवाज़","話して","声","ಮಾತಾಡು","ಧ್ವನಿ","സംസാരിക്കുക","speak pannu","voice la","pesu"]
    return any(t in msg.lower() for t in triggers)

def detect_language(text):
    if any('\u0B80'<=c<='\u0BFF' for c in text): return "ta"
    if any('\u3040'<=c<='\u30FF' or '\u4E00'<=c<='\u9FFF' for c in text): return "ja"
    if any('\u0900'<=c<='\u097F' for c in text): return "hi"
    if any('\u0C80'<=c<='\u0CFF' for c in text): return "kn"
    if any('\u0D00'<=c<='\u0D7F' for c in text): return "ml"
    tw = ["enna","epdi","iruka","pannu","sollu","pesu","puriyala","kaattu","ezhuthu","nalla","romba"]
    if any(w in text.lower().split() for w in tw): return "tanglish"
    return "en"

def needs_web_search(msg):
    triggers = ["news","trending","latest","current","today","weather","temperature","stock","price","score","match","election","breaking","update","recent","happening","what is","who is","where is","when did","why is","செய்தி","समाचार","ニュース","ಸುದ್ದಿ","വാർത്ത"]
    return any(t in msg.lower() for t in triggers)

# ==================== AUDIO & TEXT UTILS ====================
def transcribe_audio(audio_bytes):
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes), "webm")
        wav = io.BytesIO(); audio.export(wav, "wav"); wav.seek(0)
        r = sr.Recognizer()
        with sr.AudioFile(wav) as src: return r.recognize_google(r.record(src), language="auto")
    except: return None

def text_to_speech(text, lang="en"):
    lm = {"tamil":"ta","english":"en","japanese":"ja","hindi":"hi","kannada":"kn","malayalam":"ml","tanglish":"en"}
    try:
        tts = gTTS(text=text, lang=lm.get(lang.lower(), "en"))
        fp = io.BytesIO(); tts.write_to_fp(fp); fp.seek(0); return fp
    except: return None

# ==================== SEARCH & LLM ====================
def web_search(query):
    if not tinyfish_available: return None
    try:
        results = tf.search(query, num_results=5)
        if not results: return "No results baby 😢"
        out = f"🔍 **{query}**\n\n"
        for i, r in enumerate(results[:5], 1):
            title = r.get('title','No title'); snippet = r.get('snippet','')[:200]
            out += f"{i}. **{title}**\n   {snippet}\n\n"
        return out
    except: return None

def get_bot_response():
    try:
        response = ollama_client.chat.completions.create(
            model=config['ollama_model'], messages=st.session_state.messages, temperature=0.9, max_tokens=300)
        return response.choices[0].message.content
    except: return "Sorry baby! Is Ollama running? 😢"

def get_answer_with_search(query):
    results = web_search(query)
    if results:
        st.session_state.messages.append({"role":"system","content":f"Search:\n{results}\n\nAnswer in sweet girlfriend tone."})
        return get_bot_response()
    return None

# ==================== SHEET HELPERS ====================
def load_reminders():
    if sheets_available:
        try: return reminders_ws.get_all_records()
        except: pass
    return []

def load_stories():
    if sheets_available:
        try: return stories_ws.get_all_records()
        except: pass
    return []

def add_reminder(task, dt):
    if sheets_available:
        try: reminders_ws.append_row([task, dt, "Pending"]); return True
        except: pass
    return False

def add_story(title, content):
    if sheets_available:
        try: stories_ws.append_row([title, content, datetime.datetime.now().strftime("%Y-%m-%d %H:%M")]); return True
        except: pass
    return False

def delete_reminder(idx):
    if sheets_available:
        try: reminders_ws.delete_rows(idx + 2); return True
        except: pass
    return False

def delete_story(idx):
    if sheets_available:
        try: stories_ws.delete_rows(idx + 2); return True
        except: pass
    return False

# ==================== CONVERSATION MANAGEMENT ====================
def manage_conversation_size():
    system_msgs = [m for m in st.session_state.messages if m["role"] == "system"]
    other_msgs = [m for m in st.session_state.messages if m["role"] != "system"]
    if len(other_msgs) > MAX_CHAT_MESSAGES:
        st.session_state.messages = system_msgs + other_msgs[-MAX_CHAT_MESSAGES:]

# ==================== UI HEADER ====================
st.markdown('<div class="main-header">💖 Aaliyah – Your Girlfriend Assistant</div>', unsafe_allow_html=True)
st.caption(f"🦙 {config['ollama_model']} | 7 Languages | 📱 Telegram | 🔐 Voice Locked")

# Sidebar
with st.sidebar:
    st.markdown('<div style="font-size:1.2rem;font-weight:600;color:#ff6b6b;">💖 Aaliyah Menu</div>', unsafe_allow_html=True)
    
    if st.button("🔒 Lock Aaliyah", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()
    
    st.divider()
    
    with st.expander("🔍 Service Status"):
        st.write(f"🦙 Ollama: {'✅' if config.get('ollama_base_url') else '❌'}")
        st.write(f"🌐 Search: {'✅' if tinyfish_available else '❌'}")
        st.write(f"📊 Sheets: {'✅' if sheets_available else '❌'}")
        st.write(f"📱 Telegram: {'✅' if config.get('telegram_token') else '❌'}")
    
    st.divider()
    
    if st.button("🗑️ Clear Chat", use_container_width=True):
        st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        st.rerun()
    
    if len(st.session_state.messages) > 1:
        chat_text = ""
        for m in st.session_state.messages[1:]:
            chat_text += f"{m['role'].upper()}: {m['content']}\n\n"
        st.download_button(
            "📥 Export Chat", chat_text,
            file_name=f"aaliyah_chat_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.txt",
            mime="text/plain", use_container_width=True
        )
    
    st.divider()
    st.write("• 💬 Smart Chat (7 languages)")
    st.write("• 🌐 Auto Web Search")
    st.write("• 📱 Telegram Reminders")
    st.write("• 📖 Stories & Memories")
    st.write("• 🔐 Brute-force Protection")
    
    st.divider()
    st.subheader("🎤 Commands")
    st.caption("'text' / 'எழுது' → Text mode")
    st.caption("'speak' / 'பேசு' → Voice mode")
    
    st.divider()
    st.subheader("⏰ Reminders")
    for i, r in enumerate(load_reminders()):
        icon = "🔔" if r.get("Status")=="Pending" else "✅"
        c_a, c_b = st.columns([0.8, 0.2])
        with c_a:
            st.write(f"{i+1}. {icon} {r['Task']} — {r['Datetime']}")
        with c_b:
            if st.button("🗑️", key=f"dr{i}"): delete_reminder(i); st.rerun()
    
    st.divider()
    st.subheader("📖 Stories")
    for i, s in enumerate(load_stories()):
        with st.expander(s['Title']):
            st.write(s["Content"])
            if st.button("🗑️", key=f"ds{i}"): delete_story(i); st.rerun()

# Status bar
c1,c2,c3,c4,c5 = st.columns(5)
c1.success("🦙 Llama")
c2.success("🌐 Search") if tinyfish_available else c2.warning("🌐 Search OFF")
c3.success("📊 Sheets") if sheets_available else c3.warning("📊 Local")
c4.info("🔊 VOICE" if st.session_state.voice_mode else "📝 TEXT")
msg_count = len([m for m in st.session_state.messages if m["role"] != "system"])
c5.info(f"💬 {msg_count}/{MAX_CHAT_MESSAGES}")

ln = {"en":"English","ta":"Tamil","ja":"Japanese","hi":"Hindi","kn":"Kannada","ml":"Malayalam","tanglish":"Tanglish"}
st.caption(f"🌍 {ln.get(st.session_state.detected_language,'Unknown')} | Ask me anything! 💕")

# Due reminders
for r in load_reminders():
    if r.get("Status") == "Pending":
        try:
            if datetime.datetime.strptime(r["Datetime"], "%Y-%m-%d %H:%M") <= datetime.datetime.now():
                st.toast(f"⏰ {r['Task']}", icon="🔔")
        except: pass

manage_conversation_size()

# Chat display
for msg in st.session_state.messages[1:]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Input
col1, col2 = st.columns([0.8, 0.2])
with col1: user_text = st.chat_input("Ask me anything, baby!")
with col2: voice_input = mic_recorder(start_prompt="🎤", stop_prompt="⏹️", key="mic", format="webm", use_container_width=True)

def process_input(user_text):
    detected_lang = detect_language(user_text)
    st.session_state.detected_language = detected_lang
    
    if detect_text_command(user_text): st.session_state.voice_mode = False; st.success("📝 TEXT mode")
    elif detect_voice_command(user_text): st.session_state.voice_mode = True; st.success("🔊 VOICE mode")
    
    st.session_state.messages.append({"role":"user","content":user_text})
    with st.chat_message("user"): st.markdown(user_text)
    
    if tinyfish_available and needs_web_search(user_text):
        with st.spinner("🔍 Searching..."):
            reply = get_answer_with_search(user_text)
            if not reply:
                with st.spinner("💭 Thinking..."): reply = get_bot_response()
    else:
        with st.spinner("💭 Aaliyah thinking..."): reply = get_bot_response()
    
    if "TEXT_MODE_ON" in reply: st.session_state.voice_mode = False; reply = reply.replace("TEXT_MODE_ON","").strip()
    if "VOICE_MODE_ON" in reply: st.session_state.voice_mode = True; reply = reply.replace("VOICE_MODE_ON","").strip()
    
    if "```web_search" in reply:
        try:
            s = reply.index("```web_search")+len("```web_search")
            q = json.loads(reply[s:reply.index("```",s)].strip())["query"]
            srch = get_answer_with_search(q)
            if srch: reply = srch
        except: pass
    
    if "```reminder_set" in reply:
        try:
            s = reply.index("```reminder_set")+len("```reminder_set")
            d = json.loads(reply[s:reply.index("```",s)].strip())
            add_reminder(d["task"], d["datetime"])
            send_telegram_notification(d["task"], d["datetime"])
            reply = f"Okay baby, I'll remind you about '{d['task']}' at {d['datetime']} 💖📱"
        except: pass
    
    if "```story_store" in reply:
        try:
            s = reply.index("```story_store")+len("```story_store")
            d = json.loads(reply[s:reply.index("```",s)].strip())
            add_story(d["title"], d["content"])
            reply = f"Saved '{d['title']}' in my heart 💌"
        except: pass
    
    if "```reminder_delete" in reply:
        try:
            s = reply.index("```reminder_delete")+len("```reminder_delete")
            d = json.loads(reply[s:reply.index("```",s)].strip())
            delete_reminder(d["index"]-1)
            reply = "Deleted that reminder, sweetie 💕"
        except: pass
    
    if "```story_delete" in reply:
        try:
            s = reply.index("```story_delete")+len("```story_delete")
            d = json.loads(reply[s:reply.index("```",s)].strip())
            delete_story(d["index"]-1)
            reply = "Story deleted, my love 🗑️"
        except: pass
    
    if "```" in reply: reply = reply.split("```")[0].strip()
    
    st.session_state.messages.append({"role":"assistant","content":reply})
    with st.chat_message("assistant"): st.markdown(reply)
    
    if st.session_state.voice_mode:
        audio = text_to_speech(reply, detected_lang)
        if audio: st.audio(audio, format="audio/mp3", autoplay=True)
    
    st.rerun()

if user_text: process_input(user_text.strip())
if voice_input and voice_input.get("bytes"):
    with st.spinner("🎤 Listening..."):
        transcript = transcribe_audio(voice_input["bytes"])
    if transcript: process_input(transcript)