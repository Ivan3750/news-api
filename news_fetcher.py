# --- Fix for feedparser on Python 3.13 (cgi removed) ---
import sys, types
if "cgi" not in sys.modules:
    cgi = types.ModuleType("cgi")
    cgi.parse_header = lambda value: (value, {})
    sys.modules["cgi"] = cgi
# -------------------------------------------------------

import feedparser
import os
import time
import random
import threading
from datetime import datetime
import trafilatura
import google.generativeai as genai
from dotenv import load_dotenv
from db import get_connection
from sources import RSS_SOURCES

# -------------------------------
# ⚙️ CONFIG
# -------------------------------
load_dotenv()

GEMINI_KEYS = [
    os.getenv("GOOGLE_API_KEY_MAIN"),
    os.getenv("GOOGLE_API_KEY_BACKUP"),
]
MODEL = "gemini-2.5-flash"

active_key_index = 0
genai.configure(api_key=GEMINI_KEYS[active_key_index])
model = genai.GenerativeModel(MODEL)

# -------------------------------
# ⏳ Rate limit control (Gemini safety)
# -------------------------------
REQUEST_HISTORY = []
MAX_RPM = 10  # 10 запитів за хвилину — нижче ліміту
LOCK = threading.Lock()

def rate_limit_guard():
    """Ensure we don't exceed Gemini RPM limits."""
    with LOCK:
        now = time.time()
        REQUEST_HISTORY.append(now)

        # Залишаємо історію лише за останню хвилину
        while REQUEST_HISTORY and now - REQUEST_HISTORY[0] > 60:
            REQUEST_HISTORY.pop(0)

        if len(REQUEST_HISTORY) >= MAX_RPM:
            sleep_time = 60 - (now - REQUEST_HISTORY[0]) + 1
            print(f"🕒 Rate limit reached — sleeping for {sleep_time:.1f}s...")
            time.sleep(sleep_time)

# -------------------------------
# 🔄 Перемикання ключа
# -------------------------------
def switch_key():
    global active_key_index, model
    active_key_index = 1 - active_key_index
    new_key = GEMINI_KEYS[active_key_index]
    genai.configure(api_key=new_key)
    model = genai.GenerativeModel(MODEL)
    print(f"🔑 Switched to API key {active_key_index + 1}")

# -------------------------------
# 📅 Безпечний парсер дати
# -------------------------------
def parse_pubdate(pubdate_str):
    if not pubdate_str:
        return None
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            return datetime.strptime(pubdate_str, fmt)
        except ValueError:
            continue
    return None

# -------------------------------
# 📰 Завантаження RSS
# -------------------------------
def fetch_rss_entries(source_name, rss_url, limit=5):
    print(f"🔍 Henter nyheder fra {source_name}...")
    feed = feedparser.parse(rss_url)
    for entry in feed.entries[:limit]:
        yield {
            "title": entry.title,
            "link": entry.link,
            "published": getattr(entry, "published", None),
            "source": source_name,
        }

# -------------------------------
# 📜 Завантаження повного тексту
# -------------------------------
def get_full_text(url):
    downloaded = trafilatura.fetch_url(url)
    if downloaded:
        return trafilatura.extract(downloaded)
    return None

# -------------------------------
# 🤖 Підсумок через Gemini (з fallback)
# -------------------------------
def summarize_text_danish(text):
    global model
    prompt = (
        "Lav et kort nyhedsresumé på dansk i 2-3 sætninger. "
        "Behold fakta og skriv i neutral journalistisk stil:\n\n"
        f"{text}"
    )

    for attempt in range(2):
        try:
            rate_limit_guard()  # ✅ контролюємо RPM
            response = model.generate_content(prompt)
            if response and response.text:
                return response.text.strip()
            else:
                raise ValueError("Empty response from Gemini")
        except Exception as e:
            print(f"⚠️ AI fejl (attempt {attempt+1}) med key {active_key_index+1}: {e}")
            if attempt == 0:
                switch_key()
                time.sleep(1)
            else:
                print("❌ Both keys failed — skipping this news item.")
                return "Kunne ikke generere resumé."
    return "Kunne ikke generere resumé."

# -------------------------------
# 🏷️ Визначення категорії
# -------------------------------
def classify_category_danish(text):
    global model
    categories = ["Alle", "Politik", "Økonomi", "Sport", "Miljø", "Teknologi"]

    prompt = (
        "Læs denne danske nyhedsartikel og bestem, hvilken kategori den tilhører. "
        "Vælg KUN én af følgende kategorier:\n\n"
        "Politik, Økonomi, Sport, Miljø, Teknologi.\n\n"
        "Svar KUN med navnet på kategorien uden forklaring.\n\n"
        f"Artikel:\n{text}"
    )

    for attempt in range(2):
        try:
            rate_limit_guard()  # ✅ контролюємо RPM
            response = model.generate_content(prompt)
            if not response or not response.text:
                raise ValueError("Empty response")

            cat = response.text.strip()
            cat = cat.replace('"', '').replace("'", "").strip()

            for c in categories:
                if c.lower() in cat.lower():
                    return c
            return "Alle"
        except Exception as e:
            print(f"⚠️ Category AI fejl (attempt {attempt+1}) med key {active_key_index+1}: {e}")
            if attempt == 0:
                switch_key()
                time.sleep(1)
            else:
                print("❌ Both keys failed for category — fallback to 'Alle'.")
                return "Alle"
    return "Alle"

# -------------------------------
# 💾 Збереження у базу даних
# -------------------------------
def save_to_db(news_list):
    if not news_list:
        return
    conn = get_connection()
    cur = conn.cursor()

    for news in news_list:
        cur.execute("SELECT id FROM news WHERE link = %s", (news["link"],))
        if cur.fetchone():
            continue

        cur.execute("""
            INSERT INTO news (title, link, pubDate, source, shortText, category)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            news["title"],
            news["link"],
            news.get("pubDate"),
            news["source"],
            news["summary"],
            news["category"],
        ))

    conn.commit()
    cur.close()
    conn.close()
    print(f"🗄️ {len(news_list)} news items saved to DB.")

# -------------------------------
# 🔁 Оновлення всіх джерел
# -------------------------------
def fetch_all_news(limit=5):
    all_news = []
    total_processed = 0
    for source_name, rss_url in RSS_SOURCES.items():
        for entry in fetch_rss_entries(source_name, rss_url, limit):
            full_text = get_full_text(entry["link"])
            if not full_text:
                continue

            summary = summarize_text_danish(full_text)
            category = classify_category_danish(summary)
            pub_date = parse_pubdate(entry.get("published"))

            news_item = {
                "title": entry["title"],
                "link": entry["link"],
                "pubDate": pub_date,
                "source": entry["source"],
                "summary": summary,
                "category": category,
            }
            all_news.append(news_item)
            total_processed += 1
            print(f"✅ Processed {total_processed} news so far...")
            time.sleep(random.uniform(0.8, 1.6))  # трохи більша пауза для безпеки
    return all_news

# -------------------------------
# 🧠 Головна функція
# -------------------------------
def update_news_cache():
    try:
        new_data = fetch_all_news(limit=3)
        save_to_db(new_data)
        print(f"✅ News fetched and saved ({len(new_data)} items).")
    except Exception as e:
        print(f"❌ Error updating news cache: {e}")
