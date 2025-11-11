from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
import pytz

from news_fetcher import update_news_cache


def update_news_cache_limited():
    """Оновлення тільки між 7:00 і 20:00 за данським часом."""
    tz = pytz.timezone("Europe/Copenhagen")
    now = datetime.now(tz)
    if 7 <= now.hour < 20:
        update_news_cache()
    else:
        print(f"⏸ Пропуск оновлення ({now.strftime('%H:%M')} — поза робочим часом)")


def start_scheduler():
    scheduler = BackgroundScheduler(timezone="Europe/Copenhagen")
    
    # Запускаємо кожні 30 хвилин, але всередині функції перевіряємо час
    scheduler.add_job(
        update_news_cache_limited,
        trigger=IntervalTrigger(minutes=30),
        id="news_update_job",
        replace_existing=True,
    )
    
    # Перше оновлення одразу при старті, якщо зараз у дозволений час
    update_news_cache_limited()
    
    scheduler.start()
    print("✅ Scheduler started (Europe/Copenhagen, 07:00–20:00)")


if __name__ == "__main__":
    start_scheduler()
