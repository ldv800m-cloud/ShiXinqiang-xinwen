import requests
import telegram
import time
import asyncio
import os
import re
import logging
import random
from typing import Optional, Set, List, Tuple, Dict, Any
from dotenv import load_dotenv
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from playwright.async_api import async_playwright, Playwright, Browser, Page
import jieba
import jieba.analyse
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from urllib.parse import quote

# --- Настройка логирования ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# --- Конфигурация ---
@dataclass
class Config:
    telegram_bot_token: str
    telegram_chat_id: str
    gnews_api_key: str
    max_articles_to_send: int = 5
    send_interval_seconds: int = 15
    api_timeout: int = 30
    browser_timeout: int = 35000
    
    @classmethod
    def from_env(cls) -> 'Config':
        load_dotenv()
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        api_key = os.getenv("GNEWS_API_KEY")
        
        if not all([token, chat_id, api_key]):
            raise ValueError("❌ Не все переменные окружения загружены")
        
        return cls(
            telegram_bot_token=token,
            telegram_chat_id=chat_id,
            gnews_api_key=api_key,
            max_articles_to_send=int(os.getenv("MAX_ARTICLES_TO_SEND", "5")),
            send_interval_seconds=int(os.getenv("SEND_INTERVAL_SECONDS", "15"))
        )

# --- Мотивационные фразы для детей ---
class MotivationMessages:
    FOR_CHILDREN = [
        "🌟 Ты можешь всё! Каждый день — это новый шаг к победе!",
        "💪 Спорт делает нас сильнее и увереннее!",
        "🏆 Каждый спортсмен когда-то начинал с малого. Ты тоже сможешь!",
        "⭐ Мечты сбываются, если не бояться тренироваться!",
        "🎯 Поставь цель и иди к ней — у тебя получится!",
        "🌈 Спорт — это радость движения и новых друзей!",
        "🔥 Твой потенциал безграничен! Продолжай в том же духе!",
        "👏 Каждая тренировка — это победа над собой!",
        "⭐ Ты — будущая звезда российского спорта!",
        "💖 Спорт учит не сдаваться и верить в себя!"
    ]
    
    FOR_PARENTS = [
        "👨‍👩‍👦 Воспитывайте чемпионов через любовь к спорту!",
        "📚 Спорт развивает характер и дисциплину с детства",
        "💪 Поддерживайте детей на их спортивном пути",
        "🏆 Правильное питание и спорт — залог здоровья детей",
        "🧠 Спорт учит детей работать в команде и уважать соперников",
        "⏰ Режим и тренировки формируют сильную личность",
        "🌟 Инвестируйте в спорт — инвестируйте в будущее детей"
    ]
    
    @classmethod
    def get_random_child_motivation(cls) -> str:
        return random.choice(cls.FOR_CHILDREN)
    
    @classmethod
    def get_random_parent_motivation(cls) -> str:
        return random.choice(cls.FOR_PARENTS)

# --- Полезные советы ---
class SportsTips:
    TIPS = [
        "🥗 Спортсменам нужно есть 5-6 раз в день маленькими порциями",
        "💧 Пить воду нужно до, во время и после тренировки",
        "😴 Ребенку нужно спать минимум 8-9 часов для восстановления",
        "🏋️ Разминка перед тренировкой обязательна! 5-10 минут",
        "🧘 Растяжка после тренировки помогает избежать травм",
        "👟 Правильная обувь — половина успеха в спорте",
        "📈 Прогресс приходит постепенно, не торопитесь",
        "🤝 Спорт учит проигрывать с достоинством",
        "🎯 Ставьте реальные цели и радуйтесь маленьким победам",
        "👨‍👦 Тренируйтесь вместе с ребенком — это мотивирует"
    ]
    
    @classmethod
    def get_random_tip(cls) -> str:
        return random.choice(cls.TIPS)

# --- Тексты ---
class Messages:
    CHANNEL_TOPIC_HEADER = "🇷🇺 Спорт для детей и родителей"
    UNKNOWN_TIME = "Неизвестно"
    UNKNOWN_SOURCE = "Неизвестный источник"
    
    NO_SUMMARY = "📖 Полный текст доступен по <a href='{url}'>ссылке</a>"
    FULL_ARTICLE_LINK = "🔗 Подробнее: <a href='{url}'>Читать полностью</a>"
    PUBLISHED_AT = "📅 Опубликовано: {time} (МСК)"
    SOURCE_LINE = "📰 Источник: <a href='{url}'>{source}</a>"
    
    CONTACT_LINK_TEXT = "📩 Связаться с нами"
    CONTACT_LINK_URL = "https://t.me/School_of_sport"  # ЗАМЕНИТЕ
    GROUP_LINK_TEXT = "💬 Обсудить в чате с родителями"
    GROUP_LINK_URL = "https://t.me/OG_ZHUKOV_JUDO_TEAM"    # ЗАМЕНИТЕ
    
    SPORT_EMOJIS = {
        "дзюдо": "🥋",
        "футбол": "⚽",
        "гимнастика": "🤸",
        "хоккей": "🏒",
        "плавание": "🏊",
        "легкая атлетика": "🏃",
        "спорт": "🏆"
    }
    
    AGE_CATEGORIES = {
        "дошкольники": "👶 3-6 лет",
        "школьники": "🧒 7-13 лет",
        "подростки": "👦 14-18 лет"
    }
    
    @classmethod
    def get_sport_emoji(cls, title: str) -> str:
        title_lower = title.lower()
        for sport, emoji in cls.SPORT_EMOJIS.items():
            if sport in title_lower:
                return emoji
        return cls.SPORT_EMOJIS["спорт"]
    
    @classmethod
    def get_age_category(cls, title: str) -> str:
        title_lower = title.lower()
        if "дошколь" in title_lower or "3-" in title_lower:
            return cls.AGE_CATEGORIES["дошкольники"]
        elif "школьник" in title_lower or "7-" in title_lower or "8-" in title_lower or "9-" in title_lower or "10-" in title_lower or "11-" in title_lower or "12-" in title_lower or "13-" in title_lower:
            return cls.AGE_CATEGORIES["школьники"]
        elif "подрост" in title_lower or "14-" in title_lower or "15-" in title_lower or "16-" in title_lower or "17-" in title_lower or "18-" in title_lower:
            return cls.AGE_CATEGORIES["подростки"]
        return "👨‍👩‍👦 Для всех возрастов"

# --- Российские источники ---
class RussianSportsSources:
    SOURCES = [
        "sport-express.ru", "championat.com", "rsport.ria.ru",
        "matchtv.ru", "sports.ru", "tass.ru/sport",
        "sovsport.ru", "mk.ru/sport", "rg.ru/sport"
    ]
    
    @classmethod
    def is_russian_source(cls, url: str) -> bool:
        if not url:
            return False
        return any(source in url.lower() for source in cls.SOURCES)

# --- Функции времени ---
def get_moscow_time() -> timezone:
    return timezone(timedelta(hours=3))

def get_current_moscow_time() -> str:
    now = datetime.now(get_moscow_time())
    return now.strftime('%d %B %Y, %H:%M')

def format_russian_time(time_str: Optional[str]) -> str:
    if not time_str:
        return Messages.UNKNOWN_TIME
    try:
        if time_str.endswith('Z'):
            time_str = time_str[:-1] + '+00:00'
        dt = datetime.fromisoformat(time_str)
        dt_moscow = dt.astimezone(get_moscow_time())
        return dt_moscow.strftime('%d %B %Y, %H:%M')
    except (ValueError, TypeError):
        return time_str.split('T')[0] if time_str else Messages.UNKNOWN_TIME

# --- Генерация хештегов ---
def get_family_hashtags(title: str, max_tags: int = 6) -> str:
    try:
        tags = jieba.analyse.extract_tags(title, topK=4)
        filtered = [tag for tag in tags if len(tag) > 1 and not tag.isdigit()]
        
        base_tags = ["Россия", "Спорт", "Дети", "Родители"]
        
        if "дзюдо" in title.lower():
            base_tags.append("Дзюдо")
        if "футбол" in title.lower():
            base_tags.append("Футбол")
        if "гимнастика" in title.lower():
            base_tags.append("Гимнастика")
        if "мотивация" in title.lower():
            base_tags.append("Мотивация")
        if "питание" in title.lower():
            base_tags.append("ЗдоровоеПитание")
        if "психология" in title.lower():
            base_tags.append("ДетскаяПсихология")
        
        all_tags = list(set(filtered + base_tags))
        return " ".join([f"#{tag}" for tag in all_tags[:max_tags]])
    except Exception:
        return "#Спорт #Дети #Россия"

# --- Клиент GNews API ---
class GNewsClient:
    BASE_URL = "https://gnews.io/api/v4"
    
    def __init__(self, api_key: str, timeout: int = 30):
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'FamilySportsBot/1.0',
            'Accept-Language': 'ru-RU'
        })
    
    def _build_family_sports_query(self) -> str:
        queries = [
            '"первенство России" дзюдо дети',
            '"юные дзюдоисты" Россия',
            '"детская лига дзюдо"',
            '"соревнования по дзюдо" дети',
            '"детский футбол" Россия',
            '"юные футболисты"',
            '"детская художественная гимнастика"',
            '"мотивация для юных спортсменов"',
            '"правильное питание" юные спортсмены',
            '"родители и спорт" дети'
        ]
        return " OR ".join(queries)
    
    def search_family_sports(self, max_results: int = 25) -> List[Dict[str, Any]]:
        query = self._build_family_sports_query()
        params = {
            'q': query,
            'lang': 'ru',
            'max': max_results,
            'apikey': self.api_key,
            'country': 'ru'
        }
        
        logger.info("🏆 Поиск семейных спортивных новостей...")
        try:
            response = self.session.get(f"{self.BASE_URL}/search", params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            articles = data.get('articles', [])
            
            family_articles = []
            for article in articles:
                title = article.get('title', '').lower()
                content = title + " " + article.get('description', '').lower()
                url = article.get('url', '')
                
                family_keywords = ['дети', 'детский', 'родители', 'юный', 'школьник']
                sport_keywords = ['дзюдо', 'футбол', 'гимнастика', 'спорт']
                
                is_family = any(k in content for k in family_keywords)
                is_sport = any(k in content for k in sport_keywords)
                is_russian = RussianSportsSources.is_russian_source(url)
                
                if (is_family or is_sport) and is_russian:
                    family_articles.append(article)
            
            logger.info(f"📰 Найдено {len(family_articles)} статей")
            return family_articles
            
        except Exception as e:
            logger.error(f"Ошибка запроса: {e}")
            return []

# --- Хранилище ---
class SentArticlesStore:
    def __init__(self, articles_file: str = 'sent_articles.txt', 
                 titles_file: str = 'sent_titles.txt'):
        self.articles_file = articles_file
        self.titles_file = titles_file
    
    def load_urls(self) -> Set[str]:
        if not os.path.exists(self.articles_file):
            return set()
        with open(self.articles_file, 'r', encoding='utf-8') as f:
            return {line.strip() for line in f if line.strip()}
    
    def load_titles(self) -> Set[str]:
        if not os.path.exists(self.titles_file):
            return set()
        with open(self.titles_file, 'r', encoding='utf-8') as f:
            return {line.strip() for line in f if line.strip()}
    
    def save_url(self, url: str) -> None:
        with open(self.articles_file, 'a', encoding='utf-8') as f:
            f.write(url + '\n')
    
    def save_title(self, title: str) -> None:
        with open(self.titles_file, 'a', encoding='utf-8') as f:
            f.write(title + '\n')

# --- Парсер ---
class ArticleScraper:
    def __init__(self, timeout: int = 35000):
        self.timeout = timeout
    
    async def scrape(self, page: Page, url: str) -> Tuple[str, str]:
        pub_time, summary = "", ""
        try:
            await page.goto(url, timeout=self.timeout, wait_until='domcontentloaded')
            
            time_selectors = ['meta[property="article:published_time"]', 'time', '.pub_date']
            for selector in time_selectors:
                element = await page.query_selector(selector)
                if element:
                    content = await element.get_attribute('content') or await element.inner_text()
                    if content:
                        pub_time = content.strip()
                        break
            
            content_selectors = ['article', '.article-content', '.post-body', '.content']
            for selector in content_selectors:
                element = await page.query_selector(selector)
                if element:
                    paragraphs = await element.query_selector_all('p')
                    summary_parts = []
                    for p in paragraphs[:4]:
                        text = await p.inner_text()
                        if text and text.strip():
                            summary_parts.append(text.strip())
                    if summary_parts:
                        summary = "\n\n".join(summary_parts)
                        break
            
        except Exception as e:
            logger.error(f"Ошибка загрузки: {e}")
        return pub_time, summary

# --- Отправка ---
class TelegramSender:
    def __init__(self, bot: telegram.Bot, chat_id: str):
        self.bot = bot
        self.chat_id = chat_id
        self.max_caption_length = 1024
    
    async def send_article(self, article: Dict[str, Any], pub_time: str, summary: str) -> bool:
        title = article.get('title')
        url = article.get('url')
        image_url = article.get('image')
        source_name = article.get('source', {}).get('name', Messages.UNKNOWN_SOURCE)
        
        if not title or not url:
            return False
        
        emoji = Messages.get_sport_emoji(title)
        age_category = Messages.get_age_category(title)
        display_time = format_russian_time(pub_time) or format_russian_time(article.get('publishedAt'))
        hashtags = get_family_hashtags(title)
        
        child_motivation = MotivationMessages.get_random_child_motivation()
        parent_motivation = MotivationMessages.get_random_parent_motivation()
        sports_tip = SportsTips.get_random_tip()
        
        summary_text = summary if summary else article.get('description', '')
        if summary_text and len(summary_text) > 250:
            summary_text = summary_text[:250] + "..."
        if not summary_text:
            summary_text = Messages.NO_SUMMARY.format(url=url)
        
        parts = [
            f"{Messages.CHANNEL_TOPIC_HEADER}\n",
            f"{emoji} <b>{title}</b>\n",
            f"👨‍👩‍👦 <i>{age_category}</i>\n",
            "",
            "📖 <b>Краткое содержание:</b>",
            summary_text,
            "",
            "🌟 <b>Для детей:</b>",
            f"✨ {child_motivation}",
            "",
            "👨‍👩‍👦 <b>Для родителей:</b>",
            f"💡 {parent_motivation}",
            "",
            "🏥 <b>Полезный совет:</b>",
            f"⚠️ {sports_tip}",
            "",
            Messages.FULL_ARTICLE_LINK.format(url=url),
            Messages.PUBLISHED_AT.format(time=display_time),
            Messages.SOURCE_LINE.format(url=url, source=source_name),
            "",
            f"📌 {hashtags}",
            "",
            f"{Messages.CONTACT_LINK_TEXT}: <a href='{Messages.CONTACT_LINK_URL}'>Написать</a>",
            f"{Messages.GROUP_LINK_TEXT}: <a href='{Messages.GROUP_LINK_URL}'>Присоединиться</a>",
            "",
            f"🕐 Обновлено: {get_current_moscow_time()}"
        ]
        
        caption = "\n".join(part for part in parts if part.strip() or part == "")
        
        if len(caption) > self.max_caption_length:
            caption = caption[:self.max_caption_length - 100] + "\n...\n" + parts[-4] + "\n" + parts[-3]
        
        try:
            if image_url:
                await self.bot.send_photo(
                    chat_id=self.chat_id,
                    photo=image_url,
                    caption=caption,
                    parse_mode=ParseMode.HTML
                )
            else:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=caption,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )
            return True
        except Exception as e:
            logger.error(f"Ошибка отправки: {e}")
            try:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=caption,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )
                return True
            except Exception:
                return False

# --- Основной бот ---
class FamilySportsBot:
    def __init__(self, config: Config):
        self.config = config
        self.bot = telegram.Bot(token=config.telegram_bot_token)
        self.store = SentArticlesStore()
        self.gnews = GNewsClient(config.gnews_api_key, config.api_timeout)
        self.scraper = ArticleScraper(config.browser_timeout)
        self.sender = TelegramSender(self.bot, config.telegram_chat_id)
    
    async def run(self) -> None:
        logger.info("🏆 Запуск бота для семейного спорта в России")
        
        browser: Optional[Browser] = None
        try:
            articles = self.gnews.search_family_sports(self.config.max_search_results)
            if not articles:
                logger.info("❌ Новости не получены")
                return
            
            new_articles = self._filter_new_articles(articles)
            if not new_articles:
                logger.info("✅ Новых статей нет")
                return
            
            logger.info(f"📰 Найдено {len(new_articles)} новых статей")
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await self._send_articles(new_articles, page)
                
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
        finally:
            if browser:
                await browser.close()
                logger.info("🔒 Браузер закрыт")
    
    def _filter_new_articles(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        new_articles = []
        sent_titles = self.store.load_titles()
        sent_urls = self.store.load_urls()
        
        for article in articles:
            url = article.get('url')
            title = article.get('title')
            if url and title and url not in sent_urls and title not in sent_titles:
                new_articles.append(article)
                if len(new_articles) >= self.config.max_articles_to_send * 2:
                    break
        
        return new_articles[:self.config.max_articles_to_send]
    
    async def _send_articles(self, articles: List[Dict[str, Any]], page: Page) -> None:
        sent_count = 0
        sent_titles_this_run = set()
        
        for i, article in enumerate(articles):
            if sent_count >= self.config.max_articles_to_send:
                break
            
            title = article.get('title')
            url = article.get('url')
            
            if title in sent_titles_this_run:
                logger.info(f"🔄 Дубликат: {title[:50]}")
                self.store.save_url(url)
                continue
            
            logger.info(f"📝 Обработка: {title[:80]}...")
            pub_time, summary = await self.scraper.scrape(page, url)
            
            if await self.sender.send_article(article, pub_time, summary):
                self.store.save_url(url)
                self.store.save_title(title)
                sent_titles_this_run.add(title)
                sent_count += 1
                logger.info(f"✅ Отправлено ({sent_count}/{self.config.max_articles_to_send})")
                
                if sent_count < self.config.max_articles_to_send and i < len(articles) - 1:
                    await asyncio.sleep(self.config.send_interval_seconds)
            else:
                logger.warning(f"❌ Не удалось: {title[:50]}")

# --- Запуск ---
def main():
    try:
        config = Config.from_env()
        logger.info("✅ Конфигурация загружена")
        
        jieba.initialize()
        logger.info("🔧 Jieba инициализирован")
        
        bot = FamilySportsBot(config)
        asyncio.run(bot.run())
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")

if __name__ == '__main__':
    main()
