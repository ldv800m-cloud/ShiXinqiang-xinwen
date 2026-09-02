import requests
import telegram
import time
import asyncio
import os
import re
from dotenv import load_dotenv
from telegram.constants import ParseMode
from telegram.error import BadRequest
from playwright.async_api import async_playwright, Playwright, Browser
import jieba
import jieba.analyse
from datetime import datetime, timezone, timedelta

# --- 配置加载 ---
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY")
if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GNEWS_API_KEY]):
    print("Ошибка: конфигурация не загружена. Проверьте переменные окружения.")
    exit()

# --- Стратегия и настройки ---
MAX_ARTICLES_TO_SEND = 3
SEND_INTERVAL_SECONDS = 20
SENT_ARTICLES_FILE = 'sent_articles.txt'
SENT_TITLES_FILE = 'sent_titles.txt'

# ★★★ ВСЕ ЗАГОЛОВКИ ТОЛЬКО НА РУССКОМ ★★★
CHANNEL_TOPIC_HEADER = "🏆 Новости детского спорта"
CONTACT_LINK_TEXT = "📩 Связаться с нами"
CONTACT_LINK_URL = "https://t.me/ваш_контакт"  # Замените!
GROUP_LINK_TEXT = "💬 Обсудить в чате"
GROUP_LINK_URL = "https://t.me/ваша_группа"    # Замените!

# --- Функция форматирования времени (русский язык) ---
def format_china_time(time_str: str) -> str:
    if not time_str:
        return "Неизвестно"
    try:
        if time_str.endswith('Z'):
            time_str = time_str[:-1] + '+00:00'
        dt_object = datetime.fromisoformat(time_str)
        moscow_tz = timezone(timedelta(hours=3))
        dt_object_moscow = dt_object.astimezone(moscow_tz)
        return dt_object_moscow.strftime('%d %B %Y, %H:%M')
    except (ValueError, TypeError):
        return time_str.split('T')[0]

# --- Вспомогательные функции ---
def load_sent_urls():
    if not os.path.exists(SENT_ARTICLES_FILE): return set()
    with open(SENT_ARTICLES_FILE, 'r', encoding='utf-8') as f: return set(line.strip() for line in f)

def save_sent_url(article_url):
    with open(SENT_ARTICLES_FILE, 'a', encoding='utf-8') as f: f.write(article_url + '\n')

def load_sent_titles():
    if not os.path.exists(SENT_TITLES_FILE): return set()
    with open(SENT_TITLES_FILE, 'r', encoding='utf-8') as f: return set(line.strip() for line in f)

def save_sent_title(article_title):
    with open(SENT_TITLES_FILE, 'a', encoding='utf-8') as f: f.write(article_title + '\n')

# ★★★ ПОИСКОВЫЙ ЗАПРОС — НОВОСТИ О ДЕТСКОМ ДЗЮДО ★★★
def get_gnews_news():
    print("Поиск новостей о детском дзюдо в России...")
    url = f"https://gnews.io/api/v4/search?q=детское дзюдо OR \"первенство России по дзюдо\" OR \"юные дзюдоисты\"&lang=ru&max=10&apikey={GNEWS_API_KEY}"
    try:
        response = requests.get(url, timeout=15)
        if response.status_code != 200:
            print(f"Ошибка API: {response.status_code}")
            return []
        return response.json().get("articles", [])
    except Exception as e:
        print(f"Ошибка при запросе к GNews: {e}")
        return []

async def scrape_article_details(page, url: str) -> tuple[str, str]:
    pub_time, summary = "", ""
    try:
        await page.goto(url, timeout=30000, wait_until='domcontentloaded')
        time_selectors = ['meta[property="article:published_time"]','meta[name="publish-date"]','time','.pub_date','.post-time','.time-source .time']
        for selector in time_selectors:
            element = await page.query_selector(selector)
            if element:
                content = await element.get_attribute('content') or await element.get_attribute('datetime') or await element.inner_text()
                if content: pub_time = content.strip(); break
        content_selectors = ['article','.article-content','.post-body','.content','#article_content','#Content','.art-text','#main_content','div[class*="content-main"]','div[class*="article-body"]']
        for selector in content_selectors:
            content_element = await page.query_selector(selector)
            if content_element:
                paragraphs = await content_element.query_selector_all('p')
                summary_parts = [await p.inner_text() for p in paragraphs[:5] if await p.inner_text()]
                if summary_parts:
                    summary = "\n\n".join(summary_parts)
                    if len(paragraphs) > 5: summary += "..."
                    break
        return pub_time, summary
    except Exception as e:
        print(f"Ошибка при загрузке статьи: {url}, ошибка: {e}")
        return pub_time, summary

# --- Функция отправки (все на русском) ---
async def send_single_article(bot, article, pub_time: str, summary: str):
    title, url, image_url = article.get('title'), article.get('url'), article.get('image')
    source_name = article.get('source', {}).get('name', 'Неизвестный источник')
    if not title or not url: return False
    
    display_time = format_china_time(pub_time) if pub_time else format_china_time(article.get('publishedAt'))
    
    tags = jieba.analyse.extract_tags(title, topK=3)
    filtered_tags = [tag for tag in tags if not tag.isdigit()]
    hashtags = " ".join([f"#{tag}" for tag in filtered_tags]) if filtered_tags else ""
    
    summary_text = summary if summary else article.get('description', '')
    if summary_text and title in summary_text: 
        summary_text = ""
    if not summary_text:
        summary_text = f"📖 Полный текст доступен по <a href='{url}'>ссылке</a>."

    caption_parts = [
        f"{CHANNEL_TOPIC_HEADER} {hashtags}\n",
        f"<b>{title}</b>\n",
        summary_text,
        "",
        f"🔗 Подробнее: <a href='{url}'>Читать полностью</a>",
        f"📅 Опубликовано: {display_time}",
        f"📰 Источник: <a href='{url}'>{source_name}</a>",
        f"{CONTACT_LINK_TEXT}: <a href='{CONTACT_LINK_URL}'>Написать</a>",
        f"{GROUP_LINK_TEXT}: <a href='{GROUP_LINK_URL}'>Присоединиться</a>"
    ]
    caption = "\n".join(part for part in caption_parts if part.strip() or part == "")

    if len(caption) > 1024:
        oversize = len(caption) - 1024
        if "ссылке" not in summary_text:
            summary_text = summary_text[:-(oversize + 5)] + "..."
            caption_parts[2] = summary_text
            caption = "\n".join(part for part in caption_parts if part.strip() or part == "")
        else:
            caption = caption[:1020] + "..."

    try:
        if image_url:
            await bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=image_url, caption=caption, parse_mode=ParseMode.HTML)
        else:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=caption, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        return True
    except Exception as e:
        print(f"Ошибка отправки: {e}")
        try:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=caption, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            return True
        except Exception as fallback_e:
            print(f"Ошибка отправки в текстовом формате: {fallback_e}")
            return False

# --- Главная функция ---
async def main():
    bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
    print("Запуск бота для новостей детского спорта...")
    
    browser: Browser | None = None
    try:
        print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] --- Проверка новых статей ---")
        sent_urls = load_sent_urls()
        sent_titles = load_sent_titles()
        news_articles = get_gnews_news()

        if not news_articles:
            print("Новости не получены от API.")
        else:
            new_articles_found = [article for article in reversed(news_articles) if article.get('url') not in sent_urls and article.get('title') not in sent_titles]
            if not new_articles_found:
                print("Новых статей нет.")
            else:
                print(f"Найдено {len(new_articles_found)} новых статей...")
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    page = await browser.new_page()
                    
                    articles_sent_count, sent_titles_this_run = 0, set()
                    for article in new_articles_found:
                        if articles_sent_count >= MAX_ARTICLES_TO_SEND:
                            print(f"Достигнут лимит отправки ({MAX_ARTICLES_TO_SEND}).")
                            break
                        
                        current_title = article.get('title')
                        if current_title in sent_titles_this_run:
                            print(f"Дубликат в этом запуске, пропускаем: {current_title}")
                            save_sent_url(article.get('url'))
                            continue
                        
                        print(f"Обработка: {current_title}")
                        publication_time, summary = await scrape_article_details(page, article.get('url'))
                        
                        if await send_single_article(bot, article, publication_time, summary):
                            save_sent_url(article.get('url'))
                            save_sent_title(article.get('title'))
                            sent_titles_this_run.add(current_title)
                            articles_sent_count += 1
                            print(f"Отправлено ({articles_sent_count}/{MAX_ARTICLES_TO_SEND})")
                            if articles_sent_count < MAX_ARTICLES_TO_SEND and articles_sent_count < len(new_articles_found):
                                await asyncio.sleep(SEND_INTERVAL_SECONDS)
                        else:
                            print(f"Не удалось отправить: {current_title}")
        
        print("--- Задача выполнена ---")

    except Exception as e:
        print(f"!!! Критическая ошибка: {e} !!!")
    
    finally:
        if browser:
            print("Закрытие браузера...")
            await browser.close()
            print("Браузер закрыт.")
        print("Скрипт завершен.")

if __name__ == '__main__':
    jieba.initialize()
    asyncio.run(main())
