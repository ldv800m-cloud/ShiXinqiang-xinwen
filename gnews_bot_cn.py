import requests
import telegram
import asyncio
import os
import logging
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
from telegram.constants import ParseMode
from playwright.async_api import async_playwright, Browser, Page
from datetime import datetime, timezone, timedelta

# --- Настройка логирования ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Загрузка переменных окружения ---
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY")

if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GNEWS_API_KEY]):
    logger.error("❌ Ошибка: не все переменные окружения загружены")
    exit()

# --- Функция получения новостей ---
def get_news() -> List[Dict[str, Any]]:
    """Получает новости по простому запросу 'спорт'"""
    url = f"https://gnews.io/api/v4/search?q=спорт&lang=ru&max=5&apikey={GNEWS_API_KEY}"
    
    logger.info("📰 Запрос к GNews API...")
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        articles = data.get('articles', [])
        logger.info(f"✅ Найдено {len(articles)} статей")
        return articles
    except Exception as e:
        logger.error(f"❌ Ошибка при запросе к GNews: {e}")
        return []

# --- Функция отправки в Telegram ---
async def send_article(bot, article: Dict[str, Any]) -> bool:
    """Отправляет одну статью в Telegram"""
    title = article.get('title', 'Без заголовка')
    url = article.get('url', '')
    image_url = article.get('image')
    source = article.get('source', {}).get('name', 'Неизвестный источник')
    published = article.get('publishedAt', '')
    
    if not url:
        return False
    
    # Форматируем время
    try:
        if published.endswith('Z'):
            published = published[:-1] + '+00:00'
        dt = datetime.fromisoformat(published)
        dt_moscow = dt.astimezone(timezone(timedelta(hours=3)))
        time_str = dt_moscow.strftime('%d.%m.%Y %H:%M')
    except:
        time_str = 'Неизвестно'
    
    # Формируем сообщение
    caption = (
        f"🏆 <b>{title}</b>\n\n"
        f"📰 Источник: {source}\n"
        f"📅 Опубликовано: {time_str} МСК\n\n"
        f"🔗 <a href='{url}'>Читать полностью</a>"
    )
    
    try:
        if image_url:
            await bot.send_photo(
                chat_id=TELEGRAM_CHAT_ID,
                photo=image_url,
                caption=caption,
                parse_mode=ParseMode.HTML
            )
        else:
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=caption,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
        logger.info(f"✅ Отправлено: {title[:50]}...")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        return False

# --- Основная функция ---
async def main():
    logger.info("🚀 Запуск бота")
    
    bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
    
    # Получаем новости
    articles = get_news()
    if not articles:
        logger.info("❌ Новостей нет")
        return
    
    # Отправляем первые 3 статьи
    sent = 0
    for article in articles[:3]:
        if await send_article(bot, article):
            sent += 1
            await asyncio.sleep(2)  # Пауза между отправками
    
    logger.info(f"✅ Отправлено {sent} статей")
    logger.info("🏁 Работа завершена")

if __name__ == '__main__':
    asyncio.run(main())
