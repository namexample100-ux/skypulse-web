"""Сервис для получения курсов валют через ExchangeRate-API."""
import aiohttp
import logging
import time

log = logging.getLogger(__name__)

class FinanceService:
    def __init__(self):
        self.base_url = "https://open.er-api.com/v6/latest/USD"
        self.session: aiohttp.ClientSession | None = None
        self._cache = {}
        self._cache_time = 0
        self._ttl = 3600  # 1 час кэша

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def get_rates(self) -> dict | None:
        """Получить актуальные курсы валют с кэшированием."""
        now = time.time()
        if self._cache and (now - self._cache_time < self._ttl):
            return self._cache

        try:
            session = await self._get_session()
            async with session.get(self.base_url) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("result") == "success":
                        self._cache = data.get("rates", {})
                        self._cache_time = now
                        return self._cache
                log.error(f"Ошибка FinanceAPI: {response.status}")
                return None
        except Exception as e:
            log.error(f"Ошибка при запросе FinanceAPI: {e}")
            return None

    def format_rates(self, rates: dict) -> str:
        """Форматирование курсов валют в текст для Telegram."""
        if not rates:
            return "📈 Не удалось получить свежие котировки."

        rub_rate = rates.get("RUB")
        if not rub_rate:
            return "📈 Ошибка: курс рубля не найден."

        # Рассчитываем курсы к рублю
        # ExchangeRate-API по умолчанию дает базу в USD
        usd_rub = rub_rate
        eur_usd = rates.get("EUR", 0)
        cny_usd = rates.get("CNY", 0)
        
        eur_rub = usd_rub / eur_usd if eur_usd else 0
        cny_rub = usd_rub / cny_usd if cny_usd else 0

        text = "📈 Финансовый Пульс: Курсы валют\n\n"
        text += f"💵 USD: {usd_rub:.2f} ₽\n"
        text += f"💶 EUR: {eur_rub:.2f} ₽\n"
        text += f"🇨🇳 CNY: {cny_rub:.2f} ₽\n\n"
        
        text += f"Обновлено: {datetime.now().strftime('%H:%M')}\n"
        text += "Данные предоставлены ExchangeRate-API"
        return text

    async def get_history(self, currency: str = "USD") -> list | None:
        """Получить исторические курсы за последние 7 дней (данные ЦБ РФ)."""
        import xml.etree.ElementTree as ET
        from datetime import timedelta
        
        val_codes = {
            "USD": "R01235",
            "EUR": "R01239",
            "CNY": "R01375"
        }
        val_nm_rq = val_codes.get(currency.upper(), "R01235")
        
        now = datetime.now()
        date1 = (now - timedelta(days=9)).strftime("%d/%m/%Y") # Берём запас в 9 дней на случай выходных
        date2 = now.strftime("%d/%m/%Y")
        url = f"https://www.cbr.ru/scripts/XML_dynamic.asp?date_req1={date1}&date_req2={date2}&VAL_NM_RQ={val_nm_rq}"
        
        try:
            session = await self._get_session()
            headers = {"User-Agent": "Mozilla/5.0"}
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    text = await response.text()
                    root = ET.fromstring(text)
                    
                    history = []
                    for record in root.findall('Record'):
                        date_str = record.attrib.get('Date', '')
                        value_str = record.find('Value').text.replace(',', '.')
                        history.append({
                            "date": date_str,
                            "value": float(value_str)
                        })
                    # Берем только последние 7 дней из доступных записей
                    return history[-7:]
                else:
                    log.error(f"CBR API Error: {response.status}")
                    return None
        except Exception as e:
            log.error(f"Ошибка получения истории ЦБ РФ: {e}")
            return None

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

from datetime import datetime
