"""Сервис для получения новостей о космосе через Spaceflight News API."""
import aiohttp
import logging
from datetime import datetime

log = logging.getLogger(__name__)

class SpaceService:
    def __init__(self):
        self.base_url = "https://api.spaceflightnewsapi.net/v4/articles/"
        self.session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def get_latest_news(self, limit: int = 5) -> list[dict] | None:
        """Получить список последних новостей о космосе."""
        try:
            session = await self._get_session()
            params = {"limit": limit}
            async with session.get(self.base_url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("results", [])
                log.error(f"Ошибка SpaceAPI: {response.status}")
                return None
        except Exception as e:
            log.error(f"Ошибка при запросе SpaceAPI: {e}")
            return None

    def format_news(self, articles: list[dict]) -> str:
        """Форматирование списка новостей в текст для Telegram."""
        if not articles:
            return "🚀 Пока нет свежих новостей из глубин космоса."

        text = "🚀 Космический Пульс: Последние события\n\n"
        for art in articles:
            title = art.get("title", "Без названия")
            url = art.get("url", "#")
            summary = art.get("summary", "")
            source = art.get("news_site", "Unknown")
            
            # Обрезаем длинное саммари
            if len(summary) > 150:
                summary = summary[:147] + "..."
            
            text += f"🔹 {title}\n"
            text += f"Источник: {source}\n"
            text += f"🔗 <a href='{url}'>Читать полностью</a>\n\n"
        
        text += "Данные предоставлены Spaceflight News API"
        return text

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
