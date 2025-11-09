from apscheduler.schedulers.background import BackgroundScheduler
from news_fetcher import update_news_cache

def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(update_news_cache, "interval", minutes=30)
    update_news_cache()  # перше оновлення одразу
    scheduler.start()
