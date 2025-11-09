import os
import time
import random
from datetime import datetime

import feedparser
import trafilatura
import google.generativeai as genai
from dotenv import load_dotenv

from db import get_connection
from sources import RSS_SOURCES
# -------------------------------
# ⚙️ CONFIG
# -------------------------------
load_dotenv()

GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")
MODEL = "gemini-2.5-flash"

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(MODEL)

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
# 🤖 Підсумок через Gemini
# -------------------------------
def summarize_text_danish(text):
    prompt = (
        "Lav et kort nyhedsresumé på dansk i 2-3 sætninger. "
        "Behold fakta og skriv i neutral journalistisk stil:\n\n"
        f"{text}"
    )
    response = model.generate_content(prompt)
    return response.text.strip() if response and response.text else "Ingen resumé."

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
            continue  # уникаємо дублікатів

        cur.execute("""
            INSERT INTO news (title, link, pubDate, source, shortText)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            news["title"],
            news["link"],
            news.get("pubDate"),
            news["source"],
            news["summary"],
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
    for source_name, rss_url in RSS_SOURCES.items():
        for entry in fetch_rss_entries(source_name, rss_url, limit):
            full_text = get_full_text(entry["link"])
            if not full_text:
                continue

            try:
                summary = summarize_text_danish(full_text)
            except Exception as e:
                print(f"⚠️ AI fejl for '{entry['title']}': {e}")
                summary = "Kunne ikke generere resumé."

            pub_date = parse_pubdate(entry.get("published"))

            news_item = {
                "title": entry["title"],
                "link": entry["link"],
                "pubDate": pub_date,
                "source": entry["source"],
                "summary": summary,
            }
            all_news.append(news_item)
            time.sleep(random.uniform(0.3, 0.8))
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
