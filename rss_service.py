"""Сервис для работы с RSS-лентами."""
import asyncio
import aiohttp
import feedparser
import logging
from typing import List, Dict, Optional

log = logging.getLogger(__name__)

class RSSService:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def fetch_feed(self, url: str) -> Optional[List[Dict]]:
        """Получить последние 5 записей из RSS-ленты."""
        try:
            session = await self._get_session()
            async with session.get(url, timeout=10) as response:
                if response.status != 200:
                    log.error(f"Ошибка RSS: {response.status} для {url}")
                    return None
                
                content = await response.text()
                # feedparser работает синхронно, поэтому запускаем его в потоке
                feed = await asyncio.to_thread(feedparser.parse, content)
                
                if feed.get("bozo"):
                    log.warning(f"Возможная ошибка в формате RSS для {url}: {feed.bozo_exception}")
                
                entries = []
                # Берем больше записей (10), чтобы при смешивании было из чего выбрать
                for entry in feed.entries[:10]:
                    # Пытаемся достать timestamp для сортировки
                    import time
                    published_parsed = entry.get("published_parsed")
                    timestamp = time.mktime(published_parsed) if published_parsed else 0
                    
                    entries.append({
                        "title": entry.get("title", "Без названия"),
                        "link": entry.get("link", "#"),
                        "published": entry.get("published", "Неизвестно"),
                        "timestamp": timestamp
                    })
                return entries
        except Exception as e:
            log.error(f"Сбой при получении RSS {url}: {e}")
            return None

    def format_feed(self, title: str, entries: List[Dict]) -> str:
        """Форматирование новостей из ленты в текст."""
        if not entries:
            return f"📡 {title}\n\nНичего не найдено или лента пуста."

        text = f"📡 RSS: {title}\n\n"
        for i, entry in enumerate(entries, 1):
            text += f"{i}. <a href='{entry['link']}'>{entry['title']}</a>\n"
            text += f"   {entry['published']}\n\n"
        
        return text

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
