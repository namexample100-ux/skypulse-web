"""Сервис работы с OpenWeatherMap API."""

import logging
import aiohttp
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)
from config import (
    OWM_API_KEY, OWM_CURRENT_URL, OWM_FORECAST_URL,
    OWM_AIR_URL, DEFAULT_UNITS, DEFAULT_LANG,
)

# ── Эмодзи по коду погоды ──────────────────────────────────────────────

WEATHER_EMOJI = {
    2: "⛈", 3: "🌧", 5: "🌧", 6: "❄️",
    7: "🌫", 800: "☀️", 801: "🌤", 802: "⛅",
    803: "🌥", 804: "☁️",
}

AQI_LABELS = {
    1: (" Отличное", "Воздух чистый, идеально для прогулок"),
    2: (" Хорошее", "Допустимый уровень загрязнения"),
    3: (" Умеренное", "Чувствительным людям лучше ограничить прогулки"),
    4: (" Плохое", "Рекомендуется оставаться в помещении"),
    5: (" Опасное", "Серьёзная угроза здоровью!"),
}

WIND_DIRECTIONS = [
    "С", "ССВ", "СВ", "ВСВ", "В", "ВЮВ", "ЮВ", "ЮЮВ",
    "Ю", "ЮЮЗ", "ЮЗ", "ЗЮЗ", "З", "ЗСЗ", "СЗ", "ССЗ",
]


def _weather_emoji(code: int) -> str:
    """Эмодзи по weather condition code."""
    if code == 800:
        return WEATHER_EMOJI[800]
    if 800 < code <= 804:
        return WEATHER_EMOJI.get(code, "☁️")
    group = code // 100
    return WEATHER_EMOJI.get(group, "🌈")


def _wind_dir(deg: float) -> str:
    """Направление ветра по градусам."""
    idx = round(deg / 22.5) % 16
    return WIND_DIRECTIONS[idx]


def _ts_to_time(ts: int, tz_offset: int = 0) -> str:
    """Unix timestamp → HH:MM с учётом часового пояса."""
    dt = datetime.fromtimestamp(ts, tz=timezone(timedelta(seconds=tz_offset)))
    return dt.strftime("%H:%M")


def _default_params(units: str = None, lang: str = None, **extra) -> dict:
    """Стандартные параметры запроса."""
    params = {
        "appid": OWM_API_KEY, 
        "units": units or DEFAULT_UNITS, 
        "lang": lang or DEFAULT_LANG
    }
    params.update(extra)
    return params


# ── Класс-сервис ────────────────────────────────────────────────────────

class WeatherService:
    """Асинхронный клиент для OpenWeatherMap API."""

    def __init__(self):
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ── API-запросы ──────────────────────────────────────────────────

    async def _fetch(self, url: str, params: dict) -> dict | None:
        session = await self._get_session()
        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                body = await resp.text()
                if resp.status != 200:
                    log.warning("OWM API error: status=%s url=%s body=%s", resp.status, url, body)
                    return None
                return await resp.json(content_type=None)
        except Exception as e:
            log.exception("OWM API request failed: %s", e)
            return None

    async def get_current(self, city: str, units: str = None, lang: str = None) -> dict | None:
        return await self._fetch(OWM_CURRENT_URL, _default_params(units=units, lang=lang, q=city))

    async def get_current_by_coords(self, lat: float, lon: float, units: str = None, lang: str = None) -> dict | None:
        return await self._fetch(OWM_CURRENT_URL, _default_params(units=units, lang=lang, lat=lat, lon=lon))

    async def get_forecast(self, city: str, units: str = None, lang: str = None) -> dict | None:
        return await self._fetch(OWM_FORECAST_URL, _default_params(units=units, lang=lang, q=city))

    async def get_forecast_by_coords(self, lat: float, lon: float, units: str = None, lang: str = None) -> dict | None:
        return await self._fetch(OWM_FORECAST_URL, _default_params(units=units, lang=lang, lat=lat, lon=lon))

    async def get_air_quality(self, lat: float, lon: float, lang: str = None) -> dict | None:
        return await self._fetch(OWM_AIR_URL, _default_params(lang=lang, lat=lat, lon=lon))

    # ── Open-Meteo (Backup) ──────────────────────────────────────────

    async def get_current_backup(self, lat: float, lon: float) -> dict | None:
        """Получить текущую погоду через Open-Meteo (без API ключа)."""
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "current_weather": "true",
            "timezone": "auto"
        }
        session = await self._get_session()
        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
        except Exception as e:
            log.error(f"Open-Meteo error: {e}")
            return None

    # ── RainViewer (Radar) ───────────────────────────────────────────

    def get_radar_url(self, lat: float, lon: float) -> str:
        """Ссылка на живую карту осадков RainViewer."""
        # Уровень зума 6 обычно оптимален для города
        return f"https://www.rainviewer.com/map.html#{lat}_{lon}_6"

    # ── Форматирование ───────────────────────────────────────────────

    def format_current(self, data: dict, units: str = "metric") -> str:
        """Красивая карточка текущей погоды."""
        w = data["weather"][0]
        m = data["main"]
        wind = data.get("wind", {})
        tz = data.get("timezone", 0)
        sys = data.get("sys", {})

        emoji = _weather_emoji(w["id"])
        
        # Поддержка единиц
        temp_unit = "°C" if units == "metric" else "°F"
        speed_unit = "м/с" if units == "metric" else "mph"
        
        wind_speed = wind.get("speed", 0)
        wind_str = f'{wind_speed:.0f} {speed_unit}'
        if "gust" in wind:
            wind_str += f' (порывы {wind["gust"]:.0f})'
        if "deg" in wind:
            wind_str = f'{_wind_dir(wind["deg"])} {wind_str}'

        sunrise = _ts_to_time(sys["sunrise"], tz) if "sunrise" in sys else "—"
        sunset = _ts_to_time(sys["sunset"], tz) if "sunset" in sys else "—"

        lines = [
            f'{emoji} {data["name"]}, {sys.get("country", "")}',
            f'{w["description"].capitalize()}',
            "",
            f'🌡 Температура: {m["temp"]:.0f}{temp_unit}',
            f'🤔 Ощущается: {m["feels_like"]:.0f}{temp_unit}',
            f'📊 Мин / Макс: {m["temp_min"]:.0f}° / {m["temp_max"]:.0f}°',
            f'💧 Влажность: {m["humidity"]}%',
            f'🔵 Давление: {m["pressure"] * 0.75006:.0f} мм.рт.ст',
            f'💨 Ветер: {wind_str}',
            f'☁️ Облачность: {data.get("clouds", {}).get("all", 0)}%',
            f'👁 Видимость: {data.get("visibility", 0) / 1000:.0f} км',
            "",
            f'🌅 Восход: {sunrise}  🌇 Закат: {sunset}',
        ]
        return "\n".join(lines)

    def format_forecast(self, data: dict, units: str = "metric") -> str:
        """Прогноз на 5 дней, сгруппированный по датам."""
        city = data.get("city", {})
        tz = city.get("timezone", 0)
        items = data.get("list", [])

        # Группировка по дате
        days: dict[str, list] = {}
        for item in items:
            dt = datetime.fromtimestamp(item["dt"], tz=timezone(timedelta(seconds=tz)))
            day_key = dt.strftime("%d.%m (%a)")
            days.setdefault(day_key, []).append(item)

        lines = [f'📊 Прогноз — {city.get("name", "")}', ""]
        
        # Поддержка единиц
        temp_unit = "°"
        speed_unit = "м/с" if units == "metric" else "mph"

        day_names = {"Mon": "Пн", "Tue": "Вт", "Wed": "Ср", "Thu": "Чт",
                     "Fri": "Пт", "Sat": "Сб", "Sun": "Вс"}

        for day_key, entries in list(days.items())[:5]:
            for en, ru in day_names.items():
                day_key = day_key.replace(en, ru)

            temps = [e["main"]["temp"] for e in entries]
            t_min, t_max = min(temps), max(temps)
            # Самое частое описание погоды
            desc_counts: dict[str, int] = {}
            emoji_for_day = "🌈"
            for e in entries:
                d = e["weather"][0]["description"]
                desc_counts[d] = desc_counts.get(d, 0) + 1
                emoji_for_day = _weather_emoji(e["weather"][0]["id"])
            main_desc = max(desc_counts, key=desc_counts.get)  # type: ignore

            lines.append(
                f'{emoji_for_day} {day_key}  '
                f'{t_min:.0f}{temp_unit}…{t_max:.0f}{temp_unit}  '
                f'{main_desc}'
            )

            # Подробности по 3 часа (макс. 4 записи на день для краткости)
            for e in entries[:4]:
                dt = datetime.fromtimestamp(e["dt"], tz=timezone(timedelta(seconds=tz)))
                t = e["main"]["temp"]
                wd = e["weather"][0]["description"]
                wind_speed = e.get("wind", {}).get("speed", 0)
                lines.append(f'    {dt.strftime("%H:%M")}  {t:.0f}{temp_unit}  {wd}  💨{wind_speed:.0f}{speed_unit}')

            lines.append("")

        return "\n".join(lines)

    def format_air_quality(self, data: dict, city_name: str = "") -> str:
        """Индекс качества воздуха + загрязнители."""
        if not data or "list" not in data or not data["list"]:
            return "❌ Данные о качестве воздуха недоступны"

        entry = data["list"][0]
        aqi = entry["main"]["aqi"]
        comp = entry.get("components", {})

        label, advice = AQI_LABELS.get(aqi, ("⚪ Нет данных", ""))

        title = f"🌬 Качество воздуха — {city_name}" if city_name else "🌬 Качество воздуха"
        lines = [
            title,
            f"Индекс AQI: {aqi}/5 — {label}",
            f"{advice}",
            "",
            "📋 Загрязнители (мкг/м³):",
            f'  PM2.5: {comp.get("pm2_5", 0):.0f}',
            f'  PM10:  {comp.get("pm10", 0):.0f}',
            f'  CO:    {comp.get("co", 0):.0f}',
            f'  NO₂:   {comp.get("no2", 0):.0f}',
            f'  O₃:    {comp.get("o3", 0):.0f}',
            f'  SO₂:   {comp.get("so2", 0):.0f}',
        ]
        return "\n".join(lines)

    def format_clothing(self, data: dict) -> str:
        """Рекомендация одежды на основе погоды."""
        m = data["main"]
        wind = data.get("wind", {})
        weather_id = data["weather"][0]["id"]
        temp = m["temp"]
        wind_speed = wind.get("speed", 0)

        # Учёт ветра (wind chill)
        feels = m["feels_like"]

        # Определяем осадки
        has_rain = 200 <= weather_id < 600
        has_snow = 600 <= weather_id < 700

        lines = [f'👗 Что надеть — {data["name"]}', ""]

        # Верхняя одежда по температуре
        if feels <= -20:
            lines.append("🧥 Пуховик / шуба")
            lines.append("   Термобельё, тёплые штаны, валенки")
            lines.append("   🧣 Шарф + 🧤 варежки + 🎿 шапка-ушанка")
        elif feels <= -10:
            lines.append("🧥 Тёплая куртка / пуховик")
            lines.append("   Свитер, тёплые брюки, зимние ботинки")
            lines.append("   🧣 Шарф + 🧤 перчатки + 🧢 тёплая шапка")
        elif feels <= 0:
            lines.append("🧥 Зимняя куртка")
            lines.append("   Кофта/свитер, джинсы, ботинки")
            lines.append("   🧤 Перчатки + 🧢 шапка")
        elif feels <= 10:
            lines.append("🧥 Демисезонная куртка")
            lines.append("   Лёгкий свитер, брюки, кроссовки")
        elif feels <= 18:
            lines.append("🧥 Лёгкая куртка / ветровка")
            lines.append("   Рубашка/лонгслив, джинсы")
        elif feels <= 25:
            lines.append("👕 Футболка / рубашка")
            lines.append("   Лёгкие брюки / джинсы, кеды")
        else:
            lines.append("👕 Лёгкая футболка / майка")
            lines.append("   Шорты, сандалии, 🕶 очки")
            lines.append("   🧴 Солнцезащитный крем!")

        lines.append("")

        # Дождь / снег
        if has_rain:
            lines.append("☔ Возьмите зонт! Ожидаются осадки")
        if has_snow:
            lines.append("❄️ Снег! Утеплитесь и наденьте нескользящую обувь")

        # Сильный ветер
        if wind_speed >= 10:
            lines.append(f"💨 Сильный ветер ({wind_speed:.0f} м/с) — наденьте ветрозащиту")
        elif wind_speed >= 6:
            lines.append(f"💨 Ветрено ({wind_speed:.0f} м/с) — учтите при выборе одежды")

        return "\n".join(lines)

    def format_uv_estimate(self, data: dict) -> str:
        """Оценка UV-индекса по координатам, облачности и времени суток."""
        import math

        coord = data.get("coord", {})
        lat = abs(coord.get("lat", 50))
        clouds = data.get("clouds", {}).get("all", 0)
        tz = data.get("timezone", 0)
        dt_now = datetime.now(timezone.utc) + timedelta(seconds=tz)
        sys = data.get("sys", {})

        # Оценка высоты солнца
        hour = dt_now.hour + dt_now.minute / 60
        solar_noon_dist = abs(hour - 12)

        # Базовый UV по широте (экватор=12, полюса=2)
        base_uv = max(1, 12 - lat / 7.5)

        # Коррекция по времени суток
        if solar_noon_dist > 6:
            time_factor = 0.0
        else:
            time_factor = max(0, 1 - (solar_noon_dist / 6) ** 1.5)

        # Коррекция по облачности
        cloud_factor = 1 - (clouds / 100) * 0.7

        # Ночь — UV = 0
        sunrise = sys.get("sunrise", 0)
        sunset = sys.get("sunset", 0)
        if sunrise and sunset and (data["dt"] < sunrise or data["dt"] > sunset):
            uv = 0.0
        else:
            uv = base_uv * time_factor * cloud_factor

        uv = round(uv, 1)
        uv_int = int(round(uv))

        # Определяем уровень
        if uv_int <= 2:
            level = " Низкий"
            advice = "Защита не требуется. Наслаждайтесь прогулкой!"
            bar = "▓░░░░"
        elif uv_int <= 5:
            level = " Умеренный"
            advice = "Носите очки, используйте крем SPF 30+"
            bar = "▓▓░░░"
        elif uv_int <= 7:
            level = " Высокий"
            advice = "Головной убор + крем SPF 50. Избегайте солнца 11-16ч"
            bar = "▓▓▓░░"
        elif uv_int <= 10:
            level = " Очень высокий"
            advice = "Избегайте солнца! Крем SPF 50+, закрытая одежда"
            bar = "▓▓▓▓░"
        else:
            level = " Экстремальный"
            advice = "Оставайтесь в помещении! Максимальная защита"
            bar = "▓▓▓▓▓"

        lines = [
            f'🌡 UV-индекс — {data["name"]}',
            "",
            f'[{bar}]  {uv_int} из 11+',
            f'{level}',
            "",
            f'💡 {advice}',
            "",
            f'☁️ Облачность: {clouds}%  (снижает UV на {int(clouds * 0.7)}%)',
            f'🕐 Местное время: {dt_now.strftime("%H:%M")}',
        ]
        return "\n".join(lines)

    def format_temp_chart(self, data: dict, units: str = "metric") -> str:
        """Текстовый мини-график температуры на 24ч."""
        city = data.get("city", {})
        tz = city.get("timezone", 0)
        items = data.get("list", [])[:8]  # 8 × 3ч = 24ч

        if not items:
            return "❌ Нет данных для графика"

        temps = [e["main"]["temp"] for e in items]
        t_min, t_max = min(temps), max(temps)
        t_range = t_max - t_min if t_max != t_min else 1

        bars = "▁▂▃▄▅▆▇█"
        chart = ""
        for t in temps:
            idx = int((t - t_min) / t_range * 7)
            chart += bars[idx]

        # Метки времени
        times = []
        for e in items:
            dt = datetime.fromtimestamp(e["dt"], tz=timezone(timedelta(seconds=tz)))
            times.append(dt.strftime("%H"))

        temp_unit = "°" if units == "metric" else "°F"

        lines = [
            f'📈 Температура 24ч — {city.get("name", "")}',
            "",
            f'{chart}',
            f'{"".join(t.ljust(1) for t in times)}  ч',
            "",
            f'🔺 Макс: {t_max:.0f}{temp_unit}  🔻 Мин: {t_min:.0f}{temp_unit}',
            "",
        ]

        # Детали по точкам
        for e in items:
            dt = datetime.fromtimestamp(e["dt"], tz=timezone(timedelta(seconds=tz)))
            t = e["main"]["temp"]
            desc = e["weather"][0]["description"]
            emoji = _weather_emoji(e["weather"][0]["id"])
            lines.append(f'  {dt.strftime("%H:%M")}  {emoji} {t:.0f}{temp_unit}  {desc}')

        return "\n".join(lines)

    def format_comparison(self, d1: dict, d2: dict, units: str = "metric") -> str:
        """Сравнение двух городов."""
        m1, m2 = d1["main"], d2["main"]
        w1, w2 = d1["weather"][0], d2["weather"][0]
        
        emoji1 = _weather_emoji(w1["id"])
        emoji2 = _weather_emoji(w2["id"])
        
        temp_unit = "°C" if units == "metric" else "°F"
        speed_unit = "м/с" if units == "metric" else "mph"

        diff = m1["temp"] - m2["temp"]
        if abs(diff) < 0.5:
            diff_str = "одинаково"
        else:
            diff_str = f'на {abs(diff):.0f}{temp_unit} ' + ("теплее" if diff > 0 else "холоднее")
            
        lines = [
            f'🏙 Сравнение: {d1["name"]} vs {d2["name"]}',
            "",
            f'📍 {d1["name"]}:',
            f'   {emoji1} {m1["temp"]:.0f}{temp_unit}, {w1["description"]}',
            f'   🌬 {d1.get("wind", {}).get("speed", 0):.0f} {speed_unit}',
            "",
            f'📍 {d2["name"]}:',
            f'   {emoji2} {m2["temp"]:.0f}{temp_unit}, {w2["description"]}',
            f'   🌬 {d2.get("wind", {}).get("speed", 0):.0f} {speed_unit}',
            "",
            f'⚖️ В {d1["name"]} {diff_str}, чем в {d2["name"]}.',
        ]
        return "\n".join(lines)

    def format_date_weather(self, data: dict, target_date: str, units: str = "metric") -> str:
        """Погода на конкретную дату (из прогноза 5 дней). target_date: 'DD.MM'."""
        city = data.get("city", {})
        tz = city.get("timezone", 0)
        items = data.get("list", [])
        
        temp_unit = "°C" if units == "metric" else "°F"
        speed_unit = "м/с" if units == "metric" else "mph"

        day_entries = []
        for item in items:
            dt = datetime.fromtimestamp(item["dt"], tz=timezone(timedelta(seconds=tz)))
            if dt.strftime("%d.%m") == target_date:
                day_entries.append(item)
                
        if not day_entries:
            return f"❌ К сожалению, данных на {target_date} пока нет. Доступен прогноз на 5 дней."

        temps = [e["main"]["temp"] for e in day_entries]
        t_min, t_max = min(temps), max(temps)
        
        # Общая сводка (берем дневную погоду или первую доступную)
        mid_day = day_entries[len(day_entries)//2]
        for e in day_entries:
            hour = datetime.fromtimestamp(e["dt"], tz=timezone(timedelta(seconds=tz))).hour
            if 12 <= hour <= 15:
                mid_day = e
                break
        
        main_w = mid_day["weather"][0]
        emoji = _weather_emoji(main_w["id"])
        
        lines = [
            f'📅 Погода на {target_date} — {city.get("name", "")}',
            f'{main_w["description"].capitalize()}',
            "",
            f'{emoji} Температура: {t_min:.0f}°…{t_max:.0f}{temp_unit}',
            f'🌬 Ветер: {mid_day.get("wind", {}).get("speed", 0):.0f} {speed_unit}',
            f'💧 Влажность: {mid_day["main"]["humidity"]}%',
            "",
            "Подробно по часам:"
        ]
        
        for e in day_entries:
            dt = datetime.fromtimestamp(e["dt"], tz=timezone(timedelta(seconds=tz)))
            t = e["main"]["temp"]
            w = e["weather"][0]["description"]
            ico = _weather_emoji(e["weather"][0]["id"])
            lines.append(f'  {dt.strftime("%H:%M")}  {ico} {t:.0f}°  {w}')
            
        return "\n".join(lines)


    def format_alerts(self, data: dict) -> str:
        """Анализ прогноза на предмет опасных погодных явлений (ближайшие 48ч)."""
        city = data.get("city", {})
        tz = city.get("timezone", 0)
        items = data.get("list", [])[:16]  # Ближайшие 48 часов (16 * 3ч)
        
        alerts = []
        prev_temp = None
        
        for i, item in enumerate(items):
            dt = datetime.fromtimestamp(item["dt"], tz=timezone(timedelta(seconds=tz)))
            time_str = dt.strftime("%d.%m %H:%M")
            
            # 1. Ветер
            wind_speed = item.get("wind", {}).get("speed", 0)
            if wind_speed >= 15:
                alerts.append(f"⚠️ Штормовой ветер!\n   {time_str}: {wind_speed:.0f} м/с. Опасно!")
            elif wind_speed >= 10:
                alerts.append(f"💨 Сильный ветер\n   {time_str}: {wind_speed:.0f} м/с.")

            # 2. Осадки
            w = item["weather"][0]
            w_id = w["id"]
            if w_id in [502, 503, 504, 522]: # Сильный дождь
                alerts.append(f"🌊 Сильный ливень\n   {time_str}: {w['description']}")
            elif w_id in [602, 622]: # Сильный снег
                alerts.append(f"❄️ Сильный снегопад\n   {time_str}: {w['description']}")
            elif w_id in [201, 202, 211, 212]: # Гроза
                alerts.append(f"⛈ Гроза\n   {time_str}: {w['description']}")

            # 3. Резкие перепады температуры
            curr_temp = item["main"]["temp"]
            if prev_temp is not None:
                diff = curr_temp - prev_temp
                if diff <= -7:
                    alerts.append(f"📉 Резкое похолодание!\n   К {dt.strftime('%H:%M')} температура упадет на {abs(diff):.0f}° за 3 часа.")
                elif diff >= 7:
                    alerts.append(f"📈 Резкое потепление\n   К {dt.strftime('%H:%M')} температура вырастет на {diff:.0f}° за 3 часа.")
            
            prev_temp = curr_temp

        # Убираем дубликаты типов алертов (оставляем только первый/самый ранний)
        # Но для простоты сейчас просто объединим уникальные по тексту или оставим всё
        
        if not alerts:
            return f"✅ Опасных погодных явлений в ближайшие 48ч не ожидается.\nГород: {city.get('name', '')}"

        # Ограничим количество алертов, чтобы не спамить
        unique_alerts = []
        seen = set()
        for a in alerts:
            alert_type = a.split('\n')[0]
            if alert_type not in seen:
                unique_alerts.append(a)
                seen.add(alert_type)

        lines = [
            f"⚠️ Внимание! Прогноз алертов — {city.get('name', '')}",
            "",
            "\n\n".join(unique_alerts[:5]), # Топ 5 самых важных
            "",
            "Будьте осторожны на улице!"
        ]
        return "\n".join(lines)


    def format_current_backup(self, data: dict, city_name: str = "Локация") -> str:
        """Форматирование данных от Open-Meteo."""
        curr = data.get("current_weather", {})
        temp = curr.get("temperature", 0)
        wind = curr.get("windspeed", 0)
        code = curr.get("weathercode", 0)
        
        # Маппинг WMO кодов Open-Meteo в эмодзи (упрощенно)
        # https://open-meteo.com/en/docs
        wmo_emoji = {
            0: "☀️", 1: "🌤", 2: "⛅", 3: "☁️",
            45: "🌫", 48: "🌫",
            51: "🌧", 53: "🌧", 55: "🌧",
            61: "🌧", 63: "🌧", 65: "🌧",
            71: "❄️", 73: "❄️", 75: "❄️",
            95: "⛈",
        }
        emoji = wmo_emoji.get(code, "🌈")
        
        lines = [
            f"🛡 {city_name} (Резервный источник)",
            "Данные получены через Open-Meteo",
            "",
            f"🌡 Температура: {temp:.1f}°C",
            f"💨 Ветер: {wind:.1f} км/ч",
            f"Состояние: {emoji}",
            "",
            "⚠️ Этот источник используется как временная замена OpenWeatherMap."
        ]
        return "\n".join(lines)
