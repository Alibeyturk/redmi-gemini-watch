import json
import time
import uuid
import datetime
import requests
from pathlib import Path
from typing import Dict, List, Optional, Any

BASE_DIR = Path(__file__).resolve().parent
MEMORY_FILE = BASE_DIR / "memory.json"

DEFAULT_MEMORY = {
    "current_city": None,
    "user_facts": {},
    "reminders": []
}


def load_memory() -> Dict[str, Any]:
    """Kalıcı hafıza dosyasını yükler."""
    if not MEMORY_FILE.exists():
        save_memory(DEFAULT_MEMORY)
        return DEFAULT_MEMORY.copy()
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Eksik alanları tamamla
            for k, v in DEFAULT_MEMORY.items():
                if k not in data:
                    data[k] = v
            return data
    except Exception as e:
        print(f"[UYARI] Hafıza dosyası okunamadı: {e}, varsayılana dönülüyor.")
        return DEFAULT_MEMORY.copy()


def save_memory(data: Dict[str, Any]) -> None:
    """Hafıza dosyasını diske kaydeder."""
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[HATA] Hafıza kaydedilemedi: {e}")


def get_current_city() -> Optional[str]:
    """Kayıtlı mevcut şehri döner."""
    mem = load_memory()
    return mem.get("current_city")


def set_current_city(city: str) -> str:
    """Kullanıcının bulunduğu şehri günceller."""
    city_clean = city.strip().capitalize()
    mem = load_memory()
    mem["current_city"] = city_clean
    save_memory(mem)
    return city_clean


def save_user_fact(key: str, value: str) -> None:
    """Kullanıcı hakkında kalıcı bir bilgi kaydeder (örn: isim, meslek)."""
    mem = load_memory()
    mem["user_facts"][key] = value
    save_memory(mem)


def get_all_user_facts() -> Dict[str, str]:
    """Kayıtlı tüm kullanıcı bilgilerini döner."""
    mem = load_memory()
    return mem.get("user_facts", {})


def add_reminder(title: str, delay_minutes: Optional[float] = None, target_time_str: Optional[str] = None) -> Dict[str, Any]:
    """Yeni bir hatırlatıcı ekler."""
    now = time.time()
    now_dt = datetime.datetime.now()

    target_ts = None
    target_display = ""

    if delay_minutes is not None and delay_minutes > 0:
        target_ts = now + (delay_minutes * 60)
        target_dt = datetime.datetime.fromtimestamp(target_ts)
        target_display = target_dt.strftime("%H:%M")
    elif target_time_str:
        # Örn "12:45" veya "15:30"
        parts = target_time_str.strip().split(":")
        if len(parts) >= 2:
            hour = int(parts[0])
            minute = int(parts[1])
            target_dt = now_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target_dt < now_dt:
                # Zaman bugün geçtiyse yarına kur
                target_dt += datetime.timedelta(days=1)
            target_ts = target_dt.timestamp()
            target_display = target_dt.strftime("%H:%M")

    if target_ts is None:
        target_ts = now + 180  # Varsayılan 3 dk
        target_display = "3 dakika sonra"

    reminder = {
        "id": uuid.uuid4().hex[:8],
        "title": title.strip(),
        "target_timestamp": target_ts,
        "target_time_str": target_display,
        "created_at": now,
        "triggered": False,
        "notified": False
    }

    mem = load_memory()
    mem["reminders"].append(reminder)
    save_memory(mem)
    return reminder


def check_and_get_due_reminders() -> List[Dict[str, Any]]:
    """Zamanı gelen ve henüz bildirilmemiş hatırlatıcıları döner."""
    now = time.time()
    mem = load_memory()
    due = []

    for r in mem.get("reminders", []):
        if not r.get("triggered", False) and r.get("target_timestamp", 0) <= now:
            r["triggered"] = True
            due.append(r)

    if due:
        save_memory(mem)
    return due


def get_active_reminders() -> List[Dict[str, Any]]:
    """Henüz zamanı gelmemiş aktif hatırlatıcıları listeler."""
    now = time.time()
    mem = load_memory()
    return [r for r in mem.get("reminders", []) if not r.get("triggered", False) and r.get("target_timestamp", 0) > now]


# ==========================================
# NAMAZ VAKİTLERİ (DİYANET ENTEGRASYONU)
# ==========================================

VAKIT_MAP = {
    "sabah": "Fajr",
    "imsak": "Fajr",
    "güneş": "Sunrise",
    "gunes": "Sunrise",
    "öğle": "Dhuhr",
    "ogle": "Dhuhr",
    "ikindi": "Asr",
    "akşam": "Maghrib",
    "aksam": "Maghrib",
    "yatsı": "Isha",
    "yatsi": "Isha"
}


def get_prayer_times(city: str) -> Optional[Dict[str, str]]:
    """Diyanet İşleri Başkanlığı verileriyle şehir için namaz vakitlerini çeker."""
    try:
        url = f"http://api.aladhan.com/v1/timingsByCity?city={city}&country=Turkey&method=13"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data.get("code") == 200:
                return data["data"]["timings"]
    except Exception as e:
        print(f"[UYARI] Namaz vakitleri çekilemedi ({city}): {e}")
    return None


def get_specific_prayer_time(city: str, vakit_name: str) -> Optional[str]:
    """Belirli bir vakit için saat değerini döner (örn: '12:39')."""
    timings = get_prayer_times(city)
    if not timings:
        return None

    vakit_lower = vakit_name.lower().strip()
    api_key = VAKIT_MAP.get(vakit_lower, "Dhuhr")
    return timings.get(api_key)
