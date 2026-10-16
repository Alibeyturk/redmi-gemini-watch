import os
import sys
import uuid
import socket
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from dotenv import load_dotenv

import memory_manager as mm

# .env dosyasını yükle
load_dotenv()

# Proje dizinleri
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)

# FastAPI uygulaması
app = FastAPI(title="Redmi Watch - Akıllı Gemini Asistanı (Canlı, Hatırlatıcılı, Namaz Vakitli)")

# CORS ayarları
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Statik ses dosyaları klasörü
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def get_local_ip() -> str:
    """Bilgisayarın yerel ağdaki IP adresini bulur."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


LOCAL_IP = get_local_ip()
SERVER_PORT = 8000

# Gemini istemcisi
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request

global_gemini_client = None

def get_gemini_client():
    global global_gemini_client
    if global_gemini_client is None:
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            return None
        try:
            from google import genai
            global_gemini_client = genai.Client(api_key=api_key)
        except Exception as e:
            print(f"[UYARI] Google GenAI başlatılamadı: {e}")
            return None
    return global_gemini_client


def get_base_url(request: Request) -> str:
    """Render veya yerel ağdaki doğru HTTPS/HTTP adresini döner."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", f"{LOCAL_IP}:{SERVER_PORT}"))
    return f"{proto}://{host}"


# ==========================================
# GEMINI İÇİN ÖZEL ARAÇLAR (TOOLS / FUNCTION CALLING)
# ==========================================

def hatirlatici_kur(mesaj: str, dakika_sonra: Optional[int] = None, saat_dakika: Optional[str] = None) -> str:
    """Kullanıcı için ileri bir zamana hatırlatıcı kurar.
    Örnek: dakika_sonra=3 veya saat_dakika='12:45'
    """
    r = mm.add_reminder(mesaj, delay_minutes=dakika_sonra, target_time_str=saat_dakika)
    return f"Hatırlatıcı başarıyla kuruldu: '{mesaj}' - Planlanan zaman: {r['target_time_str']}."


def namaz_vakti_ogren_ve_hatirlat(vakit_adi: str, sehir: Optional[str] = None, hatirlatici_olsun_mu: bool = True) -> str:
    """Namaz vaktini Diyanet verilerinden öğrenir ve istenirse o saate otomatik hatırlatıcı kurar.
    Eğer kullanıcının şehri henüz bilinmiyorsa şehir sorulmalıdır.
    """
    if sehir:
        mm.set_current_city(sehir)

    target_city = mm.get_current_city()
    if not target_city:
        return "Şu an hangi şehirde olduğunuz bilinmiyor. Lütfen kullanıcıya 'Şu an hangi şehirdesiniz?' diye sorun."

    vakit_saati = mm.get_specific_prayer_time(target_city, vakit_adi)
    if not vakit_saati:
        return f"{target_city} şehri için {vakit_adi} vakti bulunamadı."

    if hatirlatici_olsun_mu:
        mm.add_reminder(f"{vakit_adi.capitalize()} Namazı Vakti ({target_city})", target_time_str=vakit_saati)
        return f"{target_city} için {vakit_adi} vakti saat {vakit_saati}. Vakit girdiğinde size haber vermek üzere hatırlatıcı kurdum."

    return f"{target_city} için {vakit_adi} vakti saat {vakit_saati}."


def sehir_guncelle(sehir_adi: str) -> str:
    """Kullanıcının bulunduğu yeni şehri kaydeder ve hafızaya alır."""
    c = mm.set_current_city(sehir_adi)
    return f"Mevcut şehir '{c}' olarak güncellendi ve hafızaya kaydedildi."


def kullanici_bilgisi_kaydet(konu: str, detay: str) -> str:
    """Kullanıcı hakkında unutulmaması gereken kalıcı bir bilgi kaydeder (örn: isim, sevdiği şeyler, işi vb.)."""
    mm.save_user_fact(konu, detay)
    return f"Bilgi kalıcı olarak hafızaya alındı: {konu} = {detay}."


AVAILABLE_TOOLS = [
    hatirlatici_kur,
    namaz_vakti_ogren_ve_hatirlat,
    sehir_guncelle,
    kullanici_bilgisi_kaydet
]


def build_system_prompt() -> str:
    city = mm.get_current_city()
    facts = mm.get_all_user_facts()
    facts_str = ", ".join([f"{k}: {v}" for k, v in facts.items()]) if facts else "Henüz özel bilgi yok."

    return (
        "Sen bir akıllı saatte çalışan, arkadaş canlısı, samimi ve çok doğal Türkçe konuşan bir sesli asistansın. "
        "Kullanıcıyla kesintisiz, akıcı bir sesli sohbet yürütüyorsun.\n"
        f"KULLANICI BİLGİLERİ (Hafıza): Bulunduğu Şehir: {city or 'Bilinmiyor (Gerekirse sor)'}. Bilinenler: {facts_str}\n"
        "ÖNEMLİ KURALLAR:\n"
        "1. Kullanıcı namaz vakti sorduğunda veya namazda haber ver dediğinde, eğer bulunduğu şehir bilinmiyorsa nazikçe hangi şehirde olduğunu sor.\n"
        "2. Hatırlatıcı istendiğinde (örn '3 dakika sonra haber ver' veya 'öğle namazında haber ver') ilgili araçları kullanarak hatırlatıcı kur.\n"
        "3. Yanıtın saat hoparlöründen seslendirileceği için ASLA madde işareti, yıldız (*), tire (-) veya karmaşık markdown sembolleri kullanma.\n"
        "4. Kısa, samimi, net ve doğrudan konuş (genelde 1-2 cümle)."
    )


# Çoklu turlu canlı sohbet oturumu
active_chat = None


def get_or_create_chat(reset=False):
    global active_chat
    if reset or active_chat is None:
        client = get_gemini_client()
        if not client:
            return None
        from google.genai import types
        model_name = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
        active_chat = client.chats.create(
            model=model_name,
            config=types.GenerateContentConfig(
                max_output_tokens=85,
                temperature=0.5,
                system_instruction=build_system_prompt(),
                tools=AVAILABLE_TOOLS
            )
        )
        print("[SOHBET]: Yeni akıllı sohbet oturumu başlatıldı.")
    return active_chat


def clean_text_for_tts(text: str) -> str:
    """TTS motorunun duraksamasına neden olan işaretleri temizler."""
    import re
    text = re.sub(r'[*_#`~]', '', text)
    text = re.sub(r'^\s*[-•*]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\.{2,}', '.', text)
    text = re.sub(r'!{2,}', '!', text)
    text = re.sub(r'\?{2,}', '?', text)
    return text.strip()


async def text_to_speech(text: str, output_path: Path, voice: Optional[str] = None, rate: Optional[str] = None) -> bool:
    """Doğal, akıcı ve duraklamasız Türkçe ses üretir."""
    clean_text = clean_text_for_tts(text)
    if not clean_text:
        return False

    selected_voice = voice or os.getenv("TTS_VOICE", "tr-TR-EmelNeural")
    selected_rate = rate or os.getenv("TTS_RATE", "+18%")

    try:
        import edge_tts
        communicate = edge_tts.Communicate(clean_text, selected_voice, rate=selected_rate)
        await communicate.save(str(output_path))
        return True
    except Exception as e:
        print(f"[UYARI] Edge-TTS hatası: {e}")

    # Fallback to Emel if other failed
    if selected_voice != "tr-TR-EmelNeural":
        try:
            import edge_tts
            communicate = edge_tts.Communicate(clean_text, "tr-TR-EmelNeural", rate=selected_rate)
            await communicate.save(str(output_path))
            return True
        except Exception:
            pass

    # Fallback to gTTS
    try:
        from gtts import gTTS
        tts = gTTS(text=clean_text, lang="tr", slow=False)
        tts.save(str(output_path))
        return True
    except Exception as e2:
        print(f"[HATA] gTTS başarısız: {e2}")
        return False


# ==========================================
# ARKA PLAN HATIRLATICI KONTROL MOTORU
# ==========================================

pending_alerts: List[Dict[str, Any]] = []


async def reminder_monitor_loop():
    """Her 2 saniyede bir süresi dolan hatırlatıcıları kontrol eder ve sesli uyarı hazırlar."""
    while True:
        try:
            due_reminders = mm.check_and_get_due_reminders()
            for r in due_reminders:
                alert_text = f"Hatırlatıcı zamanı geldi: {r['title']}!"
                audio_id = uuid.uuid4().hex[:8]
                audio_path = STATIC_DIR / f"alert_{audio_id}.mp3"
                await text_to_speech(alert_text, audio_path)
                audio_url = f"http://{LOCAL_IP}:{SERVER_PORT}/static/alert_{audio_id}.mp3"

                alert_obj = {
                    "id": r["id"],
                    "title": r["title"],
                    "text": alert_text,
                    "audio_url": audio_url
                }
                pending_alerts.append(alert_obj)
                print(f"🔔 [ALARM TETİKLENDİ]: {alert_text}")
        except Exception as e:
            print(f"[HATA] Hatırlatıcı motorunda hata: {e}")
        await asyncio.sleep(2)


@app.on_event("startup")
async def on_startup():
    asyncio.create_task(reminder_monitor_loop())


@app.get("/api/pending-alerts")
async def get_pending_alerts():
    """İstemcilerin (Web veya Saat) zamanı gelmiş alarmları çekmesi için endpoint."""
    global pending_alerts
    alerts_to_send = list(pending_alerts)
    pending_alerts.clear()
    return {"alerts": alerts_to_send}


@app.get("/api/active-reminders")
async def get_active_reminders_api():
    """Aktif hatırlatıcıların ve kayıtlı şehrin listesi."""
    return {
        "city": mm.get_current_city() or "Belirlenmedi",
        "reminders": mm.get_active_reminders()
    }


@app.get("/", response_class=HTMLResponse)
async def index():
    api_status_badge = (
        '<span style="color:#22c55e;">● Gemini AI Aktif</span>'
        if GEMINI_API_KEY
        else '<span style="color:#ef4444;">● API Anahtarı Eksik (.env doldurun)</span>'
    )
    current_city_text = mm.get_current_city() or "Henüz Sorulmadı / Belirlenmedi"

    return f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Gemini Akıllı Asistan - Canlı Sohbet & Hatırlatıcılar</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                background: #090d16;
                color: #f8fafc;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                min-height: 100vh;
                margin: 0;
                padding: 16px;
                box-sizing: border-box;
            }}
            .card {{
                background: #131b2e;
                border-radius: 24px;
                padding: 24px;
                max-width: 540px;
                width: 100%;
                box-shadow: 0 12px 40px rgba(0,0,0,0.6);
                border: 1px solid #1e293b;
            }}
            h1 {{
                font-size: 22px;
                margin: 0 0 8px 0;
                color: #38bdf8;
                display: flex;
                align-items: center;
                gap: 8px;
            }}
            .badge {{
                font-size: 13px;
                margin-bottom: 14px;
            }}
            .info-grid {{
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 10px;
                margin-bottom: 16px;
            }}
            .info-box {{
                background: #0a0f1d;
                border: 1px solid #1e293b;
                border-radius: 12px;
                padding: 10px 14px;
            }}
            .info-box p {{
                margin: 0 0 4px 0;
                font-size: 11px;
                color: #94a3b8;
            }}
            .info-box .val {{
                color: #f59e0b;
                font-size: 14px;
                font-weight: bold;
            }}
            .live-btn {{
                background: linear-gradient(135deg, #10b981, #059669);
                color: white;
                border: none;
                border-radius: 16px;
                padding: 16px 20px;
                font-size: 17px;
                font-weight: bold;
                cursor: pointer;
                width: 100%;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 10px;
                box-shadow: 0 4px 15px rgba(16, 185, 129, 0.3);
                transition: all 0.2s;
            }}
            .live-active {{
                background: linear-gradient(135deg, #ef4444, #dc2626) !important;
                box-shadow: 0 0 25px rgba(239, 68, 68, 0.6) !important;
                animation: pulse 1.4s infinite;
            }}
            @keyframes pulse {{
                0% {{ transform: scale(1); opacity: 1; }}
                50% {{ transform: scale(1.02); opacity: 0.85; }}
                100% {{ transform: scale(1); opacity: 1; }}
            }}
            .status-banner {{
                margin-top: 12px;
                background: #0a0f1d;
                border-radius: 12px;
                padding: 10px 14px;
                font-size: 14px;
                color: #38bdf8;
                text-align: center;
                min-height: 20px;
                border: 1px solid #1e293b;
            }}
            .alarm-banner {{
                margin-top: 10px;
                background: #7f1d1d;
                color: #fecaca;
                border-radius: 12px;
                padding: 10px 14px;
                font-size: 14px;
                font-weight: bold;
                display: none;
                animation: pulse 1s infinite;
                border: 1px solid #ef4444;
            }}
            .chat-container {{
                margin-top: 12px;
                max-height: 200px;
                overflow-y: auto;
                background: #0a0f1d;
                border-radius: 12px;
                padding: 12px;
                display: flex;
                flex-direction: column;
                gap: 8px;
                border: 1px solid #1e293b;
            }}
            .msg {{
                padding: 8px 12px;
                border-radius: 10px;
                font-size: 14px;
                line-height: 1.4;
            }}
            .msg-user {{
                background: #0284c7;
                align-self: flex-end;
                color: white;
                border-bottom-right-radius: 2px;
            }}
            .msg-gemini {{
                background: #1e293b;
                align-self: flex-start;
                color: #e2e8f0;
                border-bottom-left-radius: 2px;
                border-left: 3px solid #38bdf8;
            }}
            .reminders-list {{
                margin-top: 12px;
                background: #0a0f1d;
                border-radius: 12px;
                padding: 10px 14px;
                font-size: 13px;
                border: 1px solid #1e293b;
            }}
            .reminders-title {{
                color: #94a3b8;
                font-weight: bold;
                margin-bottom: 6px;
                font-size: 12px;
            }}
            .reminder-item {{
                color: #38bdf8;
                padding: 3px 0;
            }}
            .controls {{
                display: flex;
                gap: 10px;
                margin-top: 12px;
            }}
            .btn-secondary {{
                background: #1e293b;
                color: #94a3b8;
                border: 1px solid #334155;
                border-radius: 10px;
                padding: 8px 12px;
                font-size: 13px;
                cursor: pointer;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>✨ Gemini Live & Hatırlatıcı Asistanı</h1>
            <div class="badge">{api_status_badge}</div>

            <div class="info-grid">
                <div class="info-box">
                    <p>📍 Kayıtlı Şehir:</p>
                    <div id="cityDisplay" class="val">{current_city_text}</div>
                </div>
                <div class="info-box">
                    <p>⌚ Saat Sunucu Adresi:</p>
                    <div class="val" style="font-family:monospace; font-size:12px;">http://{LOCAL_IP}:{SERVER_PORT}</div>
                </div>
            </div>

            <!-- Ses Ayarı -->
            <div style="display:flex; gap:10px; margin-bottom:12px;">
                <select id="voiceSelect" style="flex:1; background:#0a0f1d; color:#fff; border:1px solid #1e293b; border-radius:8px; padding:8px; font-size:13px;">
                    <option value="tr-TR-EmelNeural" selected>👩 Emel (Doğal Türkçe Kadın)</option>
                    <option value="tr-TR-AhmetNeural">👨 Ahmet (Türkçe Erkek)</option>
                </select>
                <select id="rateSelect" style="flex:1; background:#0a0f1d; color:#fff; border:1px solid #1e293b; border-radius:8px; padding:8px; font-size:13px;">
                    <option value="+18%" selected>⚡ Doğal & Akıcı (+18%)</option>
                    <option value="+0%">Sakin (+0%)</option>
                    <option value="+28%">Hızlı (+28%)</option>
                </select>
            </div>

            <button id="liveBtn" class="live-btn" onclick="toggleLiveChat()">
                <span>🟢 Canlı Sohbeti Başlat (Hands-Free)</span>
            </button>

            <div id="statusBanner" class="status-banner">"3 dakika sonra haber ver" veya "Öğle namazında haber ver" diyebilirsiniz.</div>
            <div id="alarmBanner" class="alarm-banner">🔔 ALARM ÇALIYOR!</div>

            <!-- Aktif Hatırlatıcılar Listesi -->
            <div class="reminders-list">
                <div class="reminders-title">⏰ Aktif Hatırlatıcılar:</div>
                <div id="remindersContent" style="color:#64748b;">Kayıtlı aktif hatırlatıcı yok.</div>
            </div>

            <div id="chatHistory" class="chat-container">
                <div class="msg msg-gemini">Selam! Şehrinizi bilmediğimde size sorarım ve hatırlatıcılarınızı tam vaktinde çalarım. Dinliyorum!</div>
            </div>

            <div class="controls">
                <button class="btn-secondary" onclick="resetChat()">🗑️ Sohbeti Sıfırla</button>
            </div>

            <audio id="audioPlayer" style="display:none;" autoplay></audio>
            <audio id="alarmPlayer" style="display:none;" autoplay></audio>
        </div>

        <script>
            let isLive = false;
            let recognition = null;
            let silenceTimer = null;
            let lastSpeechText = "";
            let isProcessing = false;

            const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
            const liveBtn = document.getElementById('liveBtn');
            const statusBanner = document.getElementById('statusBanner');
            const alarmBanner = document.getElementById('alarmBanner');
            const chatHistory = document.getElementById('chatHistory');
            const audioPlayer = document.getElementById('audioPlayer');
            const alarmPlayer = document.getElementById('alarmPlayer');
            const cityDisplay = document.getElementById('cityDisplay');
            const remindersContent = document.getElementById('remindersContent');

            // Ses bittiğinde otomatik dinlemeye geri dön (Hands-free loop)
            audioPlayer.onended = () => {{
                if (isLive) {{
                    statusBanner.innerText = "🎙️ Sizi dinliyorum, buyrun...";
                    startListening();
                }}
            }};

            function appendMessage(sender, text) {{
                const msg = document.createElement('div');
                msg.className = 'msg ' + (sender === 'user' ? 'msg-user' : 'msg-gemini');
                msg.innerText = (sender === 'user' ? 'Sen: ' : 'Gemini: ') + text;
                chatHistory.appendChild(msg);
                chatHistory.scrollTop = chatHistory.scrollHeight;
            }}

            function toggleLiveChat() {{
                if (!isLive) {{
                    startLiveMode();
                }} else {{
                    stopLiveMode();
                }}
            }}

            function startLiveMode() {{
                if (!SpeechRec) {{
                    alert("Tarayıcınız Web Speech API desteklemiyor. Lütfen Google Chrome veya Edge kullanın.");
                    return;
                }}
                isLive = true;
                liveBtn.classList.add('live-active');
                liveBtn.innerHTML = "<span>🔴 Canlı Sohbeti Bitir</span>";
                statusBanner.innerText = "🎙️ Bağlandı! Doğrudan konuşabilirsiniz...";
                startListening();
            }}

            function stopLiveMode() {{
                isLive = false;
                liveBtn.classList.remove('live-active');
                liveBtn.innerHTML = "<span>🟢 Canlı Sohbeti Başlat (Hands-Free)</span>";
                statusBanner.innerText = "Canlı sohbet durduruldu.";
                if (recognition) {{
                    try {{ recognition.stop(); }} catch(e) {{}}
                }}
                if (silenceTimer) clearTimeout(silenceTimer);
                audioPlayer.pause();
            }}

            function startListening() {{
                if (!isLive || isProcessing) return;

                if (recognition) {{
                    try {{ recognition.stop(); }} catch(e) {{}}
                }}

                recognition = new SpeechRec();
                recognition.lang = 'tr-TR';
                recognition.continuous = true;
                recognition.interimResults = true;

                recognition.onresult = (event) => {{
                    let currentText = "";
                    for (let i = event.resultIndex; i < event.results.length; ++i) {{
                        currentText += event.results[i][0].transcript;
                    }}

                    if (currentText.trim().length > 0) {{
                        lastSpeechText = currentText.trim();
                        statusBanner.innerText = "🗣️ " + lastSpeechText;

                        if (silenceTimer) clearTimeout(silenceTimer);
                        silenceTimer = setTimeout(() => {{
                            if (lastSpeechText.length > 0 && isLive && !isProcessing) {{
                                sendToGemini(lastSpeechText);
                                lastSpeechText = "";
                            }}
                        }}, 800);
                    }}
                }};

                recognition.onerror = () => {{
                    if (isLive && !isProcessing) {{
                        setTimeout(() => startListening(), 500);
                    }}
                }};

                recognition.onend = () => {{
                    if (isLive && !isProcessing) {{
                        startListening();
                    }}
                }};

                try {{
                    recognition.start();
                }} catch (e) {{}}
            }}

            async function sendToGemini(text) {{
                isProcessing = true;
                if (recognition) {{
                    try {{ recognition.stop(); }} catch(e) {{}}
                }}

                appendMessage('user', text);
                statusBanner.innerText = "⚡ Gemini düşünüyor ve işliyor...";

                const voice = document.getElementById('voiceSelect').value;
                const rate = document.getElementById('rateSelect').value;

                const formData = new FormData();
                formData.append('text', text);
                formData.append('voice', voice);
                formData.append('rate', rate);

                try {{
                    const res = await fetch('/api/ask-text', {{
                        method: 'POST',
                        body: formData
                    }});
                    const data = await res.json();

                    if (data.success) {{
                        appendMessage('gemini', data.text);
                        statusBanner.innerText = "🔊 Gemini cevap veriyor...";
                        if (data.audio_url) {{
                            audioPlayer.src = data.audio_url;
                            audioPlayer.play();
                        }} else {{
                            isProcessing = false;
                            if (isLive) startListening();
                        }}
                    }} else {{
                        appendMessage('gemini', 'Hata: ' + data.error);
                        isProcessing = false;
                        if (isLive) startListening();
                    }}
                }} catch (err) {{
                    statusBanner.innerText = "❌ Bağlantı hatası: " + err;
                    isProcessing = false;
                    if (isLive) setTimeout(() => startListening(), 1000);
                }} finally {{
                    isProcessing = false;
                    updateRemindersUI();
                }}
            }}

            async function updateRemindersUI() {{
                try {{
                    const res = await fetch('/api/active-reminders');
                    const data = await res.json();
                    cityDisplay.innerText = data.city;
                    if (data.reminders && data.reminders.length > 0) {{
                        remindersContent.innerHTML = data.reminders.map(r => 
                            `<div class="reminder-item">🔔 <strong>${{r.title}}</strong> (${{r.target_time_str}})</div>`
                        ).join('');
                    }} else {{
                        remindersContent.innerHTML = '<span style="color:#64748b;">Kayıtlı aktif hatırlatıcı yok.</span>';
                    }}
                }} catch(e) {{}}
            }}

            // Arka planda süresi dolan alarmları dinle (her 2 saniyede bir)
            setInterval(async () => {{
                try {{
                    const res = await fetch('/api/pending-alerts');
                    const data = await res.json();
                    if (data.alerts && data.alerts.length > 0) {{
                        for (const alert of data.alerts) {{
                            alarmBanner.style.display = 'block';
                            alarmBanner.innerText = '🔔 ' + alert.text;
                            appendMessage('gemini', '🔔 ' + alert.text);
                            alarmPlayer.src = alert.audio_url;
                            alarmPlayer.play();
                            setTimeout(() => {{ alarmBanner.style.display = 'none'; }}, 8000);
                        }}
                        updateRemindersUI();
                    }}
                }} catch(e) {{}}
            }}, 2000);

            // Başlangıçta hatırlatıcıları çek
            updateRemindersUI();

            async function resetChat() {{
                try {{
                    await fetch('/api/reset-chat', {{ method: 'POST' }});
                    chatHistory.innerHTML = '<div class="msg msg-gemini">Sohbet hafızası sıfırlandı. Yeni konuya başlayabilirsiniz!</div>';
                    statusBanner.innerText = "Hafıza sıfırlandı.";
                }} catch(e) {{}}
            }}
        </script>
    </body>
    </html>
    """


@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "has_api_key": bool(GEMINI_API_KEY),
        "local_ip": LOCAL_IP,
        "port": SERVER_PORT,
    }


@app.post("/api/reset-chat")
async def reset_chat():
    """Çoklu turlu sohbet hafızasını sıfırlar."""
    get_or_create_chat(reset=True)
    return {"success": True, "message": "Sohbet hafızası sıfırlandı."}


@app.post("/api/ask-text")
async def ask_text(
    request: Request,
    text: str = Form(...),
    voice: Optional[str] = Form(None),
    rate: Optional[str] = Form(None),
):
    """Canlı sohbet için çok turlu (hafızalı & araç destekli) metin API'si."""
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return {"success": False, "error": "GEMINI_API_KEY tanımlanmamış."}

    try:
        audio_id = uuid.uuid4().hex[:8]
        temp_output_path = STATIC_DIR / f"reply_{audio_id}.mp3"

        chat = get_or_create_chat()
        if not chat:
            raise HTTPException(status_code=500, detail="Gemini sohbeti başlatılamadı.")

        # Çok turlu hafızalı ve otomatik araç çağrılı mesaj gönder
        response = chat.send_message(text)

        reply_text = response.text.strip() if response and response.text else "Bir cevap veremedim."
        print(f"[GEMINI CEVAP]: {reply_text}")

        # Akıcı Türkçe sese çevir
        tts_ok = await text_to_speech(reply_text, temp_output_path, voice=voice, rate=rate)
        base_url = get_base_url(request)
        audio_url = f"{base_url}/static/reply_{audio_id}.mp3" if tts_ok else None

        return {
            "success": True,
            "text": reply_text,
            "audio_url": audio_url,
        }
    except Exception as e:
        print(f"[HATA]: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/ask-audio")
async def ask_audio(
    request: Request,
    file: UploadFile = File(...),
    voice: Optional[str] = None,
    rate: Optional[str] = None,
):
    """Saatten gelen ses dosyasını alır, hafızalı sohbete iletir ve sesli yanıt döner."""
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "GEMINI_API_KEY eksik."},
        )

    try:
        audio_id = uuid.uuid4().hex[:8]
        temp_input_path = STATIC_DIR / f"input_{audio_id}.wav"
        temp_output_path = STATIC_DIR / f"reply_{audio_id}.mp3"

        audio_bytes = await file.read()
        with open(temp_input_path, "wb") as f:
            f.write(audio_bytes)

        chat = get_or_create_chat()
        if not chat:
            raise HTTPException(status_code=500, detail="Gemini istemcisi oluşturulamadı.")

        from google.genai import types

        response = chat.send_message(
            message=[types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav")]
        )

        reply_text = response.text.strip() if response and response.text else "Bir cevap üretemedim."
        print(f"[GEMINI SESLİ CEVAP]: {reply_text}")

        tts_ok = await text_to_speech(reply_text, temp_output_path, voice=voice, rate=rate)
        base_url = get_base_url(request)
        audio_url = f"{base_url}/static/reply_{audio_id}.mp3" if tts_ok else None

        return {
            "success": True,
            "text": reply_text,
            "audio_url": audio_url,
        }

    except Exception as e:
        print(f"[HATA]: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


if __name__ == "__main__":
    import uvicorn
    print("\n" + "=" * 60)
    print("🚀 GEMINI LIVE + HATIRLATICI + NAMAZ VAKİTLERİ BAŞLATILIYOR")
    print(f"📡 Saat İçin Yerel Ağ Adresi: http://{LOCAL_IP}:{SERVER_PORT}")
    print(f"🌐 Tarayıcıdan Canlı Panel   : http://localhost:{SERVER_PORT}")
    print("=" * 60 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=SERVER_PORT)
