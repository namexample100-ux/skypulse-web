"""SkyPulse Web — FastAPI backend."""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pywebpush import webpush, WebPushException

# Импортируем все сервисы
from weather import WeatherService
from news import NewsService
from space_service import SpaceService
from finance_service import FinanceService
from calendar_service import CalendarService
from rss_service import RSSService

# ── Настройки и Логирование ─────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
log = logging.getLogger(__name__)

SUBS_FILE = "web_subs.json"
SETTINGS_FILE = "web_settings.json"
RSS_FILE = "web_rss.json"

VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_EMAIL = os.getenv("VAPID_EMAIL", "mailto:admin@skypulse.app")

# ── Глобальные объекты (Сервисы и Хранилище) ───────────────────────────
ws = WeatherService()
ns = NewsService()
ss = SpaceService()
fs = FinanceService()
cs = CalendarService()
rs = RSSService()

push_subscriptions: dict = {}
user_settings: dict = {}
rss_feeds: list = []

# ── Данные ─────────────────────────────────────────────────────────────
def load_data():
    global push_subscriptions, user_settings, rss_feeds
    for fname, var_name in [(SUBS_FILE, "push_subscriptions"), (SETTINGS_FILE, "user_settings"), (RSS_FILE, "rss_feeds")]:
        if os.path.exists(fname):
            try:
                with open(fname, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if var_name == "push_subscriptions":
                        push_subscriptions = data
                    elif var_name == "user_settings":
                        user_settings = data
                    else:
                        rss_feeds = data
            except Exception as e:
                log.error(f"Ошибка загрузки {fname}: {e}")

def save_json(fname: str, data):
    try:
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"Ошибка сохранения {fname}: {e}")

load_data()

# ── Фоновые задачи ─────────────────────────────────────────────────────
async def broadcast_worker():
    log.info("Push-worker started")
    while True:
        try:
            sub_data = push_subscriptions.get("default")
            if sub_data and VAPID_PRIVATE_KEY:
                notify_time = sub_data.get("notify_time", "08:00")
                city = sub_data.get("city", "")
                now_utc = datetime.now(timezone.utc).strftime("%H:%M")

                if now_utc == notify_time and city:
                    log.info(f"📤 Отправка push для {city}")
                    data = await ws.get_current(city)
                    if data:
                        temp = data["main"]["temp"]
                        desc = data["weather"][0]["description"]
                        msg = json.dumps({
                            "title": f"☀️ Погода в {city}",
                            "body": f"{temp:.0f}°C, {desc}",
                            "icon": "/static/icon.png",
                        })
                        try:
                            webpush(
                                subscription_info=sub_data["subscription"],
                                data=msg,
                                vapid_private_key=VAPID_PRIVATE_KEY,
                                vapid_claims={"sub": VAPID_EMAIL},
                            )
                        except WebPushException as e:
                            log.error(f"Push ошибка: {e}")

            await asyncio.sleep(60 - datetime.now().second)
        except Exception as e:
            log.error(f"Ошибка broadcast_worker: {e}")
            await asyncio.sleep(60)

# ── Lifespan и FastAPI App ────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    asyncio.create_task(broadcast_worker())
    yield
    # Shutdown
    await ws.close()
    await ns.close()
    await ss.close()
    await fs.close()
    await cs.close()
    await rs.close()

app = FastAPI(title="SkyPulse Web", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Pydantic модели ──────────────────────────────────────────────────
class PushSubscribeRequest(BaseModel):
    subscription: dict
    city: str = ""
    notify_time: str = "08:00"

class RSSAddRequest(BaseModel):
    url: str

class SettingsRequest(BaseModel):
    home_city: str = ""
    units: str = "metric"

# ── Эндпоинты ────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/health")
async def health():
    return {"status": "ok", "service": "SkyPulse Web"}

# ── Погода
@app.get("/api/weather/current")
async def weather_current(city: str, units: str = "metric", lang: str = "ru"):
    data = await ws.get_current(city, units=units, lang=lang)
    if not data:
        raise HTTPException(status_code=404, detail="Город не найден")
    return {
        "raw": data,
        "formatted": ws.format_current(data, units=units),
        "coord": data.get("coord", {}),
        "name": data.get("name", city),
    }

@app.get("/api/weather/current/coords")
async def weather_current_coords(lat: float, lon: float, units: str = "metric", lang: str = "ru"):
    data = await ws.get_current_by_coords(lat, lon, units=units, lang=lang)
    if not data:
        backup = await ws.get_current_backup(lat, lon)
        if backup:
            return {"formatted": ws.format_current_backup(backup), "backup": True}
        raise HTTPException(status_code=503, detail="Сервис погоды недоступен")
    return {
        "raw": data,
        "formatted": ws.format_current(data, units=units),
        "coord": data.get("coord", {}),
        "name": data.get("name", ""),
    }

@app.get("/api/weather/forecast")
async def weather_forecast(lat: float, lon: float, units: str = "metric", lang: str = "ru"):
    data = await ws.get_forecast_by_coords(lat, lon, units=units, lang=lang)
    if not data or data.get("cod") != "200":
        raise HTTPException(status_code=404, detail="Город не найден")
    return {"formatted": ws.format_forecast(data, units=units)}

@app.get("/api/weather/air")
async def weather_air(lat: float, lon: float):
    data = await ws.get_air_quality(lat, lon)
    return {"formatted": ws.format_air_quality(data)}

@app.get("/api/weather/clothing")
async def weather_clothing(lat: float, lon: float, units: str = "metric"):
    data = await ws.get_current_by_coords(lat, lon, units=units)
    if not data:
        raise HTTPException(status_code=503, detail="Недоступно")
    return {"formatted": ws.format_clothing(data)}

@app.get("/api/weather/chart")
async def weather_chart(lat: float, lon: float, units: str = "metric"):
    data = await ws.get_forecast_by_coords(lat, lon, units=units)
    if not data:
        raise HTTPException(status_code=503, detail="Недоступно")
    return {"formatted": ws.format_temp_chart(data, units=units)}

@app.get("/api/weather/alerts")
async def weather_alerts(lat: float, lon: float, units: str = "metric"):
    data = await ws.get_forecast_by_coords(lat, lon, units=units)
    if not data:
        raise HTTPException(status_code=503, detail="Недоступно")
    return {"formatted": ws.format_alerts(data)}

@app.get("/api/weather/uv")
async def weather_uv(lat: float, lon: float, units: str = "metric"):
    data = await ws.get_current_by_coords(lat, lon, units=units)
    if not data:
        raise HTTPException(status_code=503, detail="Недоступно")
    return {"formatted": ws.format_uv_estimate(data)}

@app.get("/api/weather/radar")
async def weather_radar(lat: float, lon: float):
    url = ws.get_radar_url(lat, lon)
    return {"url": url}

# ── Новости
@app.get("/api/news/{category}")
async def news_category(category: str):
    data = await ns.get_news_by_category(category)
    if not data:
        raise HTTPException(status_code=503, detail="Новости недоступны")
    titles = {
        "general": "🌍 Главные события",
        "technology": "💻 IT и Технологии",
        "business": "💰 Деловой вестник",
        "sports": "⚽ Спорт",
        "auto": "🚗 Авто",
        "entertainment": "🎬 Культура",
        "science": "🧬 Наука",
        "health": "💊 Здоровье",
    }
    title = titles.get(category, "Новости")
    return {
        "articles": data.get("articles", []),
        "title": title,
        "formatted": ns.format_news(data, category_title=f"🔥 {title}"),
    }

# ── Финансы
@app.get("/api/finance/rates")
async def finance_rates():
    rates = await fs.get_rates()
    if not rates:
        raise HTTPException(status_code=503, detail="Курсы недоступны")
    return {"formatted": fs.format_rates(rates), "rates": rates}

# ── Космос
@app.get("/api/space/news")
async def space_news(limit: int = 5):
    news = await ss.get_latest_news(limit=limit)
    if not news:
        raise HTTPException(status_code=503, detail="Космические новости недоступны")
    return {"articles": news, "formatted": ss.format_news(news)}

# ── Календарь
@app.get("/api/calendar/holidays")
async def calendar_holidays(country: str = "RU"):
    holidays = await cs.get_holidays(country)
    if not holidays:
        raise HTTPException(status_code=503, detail="Праздники недоступны")
    return {"formatted": cs.format_holidays(holidays), "holidays": holidays}

# ── RSS
@app.get("/api/rss/feeds")
async def rss_list():
    return {"feeds": rss_feeds}

@app.post("/api/rss/feeds")
async def rss_add(req: RSSAddRequest):
    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Некорректный URL")
    if url in rss_feeds:
        raise HTTPException(status_code=409, detail="Лента уже добавлена")
    data = await rs.fetch_feed(url)
    if not data:
        raise HTTPException(status_code=422, detail="Не удалось получить RSS по этому URL")
    rss_feeds.append(url)
    save_json(RSS_FILE, rss_feeds)
    return {"ok": True, "count": len(data)}

@app.delete("/api/rss/feeds/{idx}")
async def rss_delete(idx: int):
    if idx < 0 or idx >= len(rss_feeds):
        raise HTTPException(status_code=404, detail="Лента не найдена")
    removed = rss_feeds.pop(idx)
    save_json(RSS_FILE, rss_feeds)
    return {"ok": True, "removed": removed}

@app.get("/api/rss/feeds/{idx}/read")
async def rss_read(idx: int):
    if idx < 0 or idx >= len(rss_feeds):
        raise HTTPException(status_code=404, detail="Лента не найдена")
    url = rss_feeds[idx]
    data = await rs.fetch_feed(url)
    if not data:
        raise HTTPException(status_code=503, detail="Не удалось загрузить ленту")
    domain = url.replace("https://", "").replace("http://", "").split("/")[0]
    return {"articles": data, "formatted": rs.format_feed(domain, data)}

# ── Push
@app.get("/api/push/vapid-public-key")
async def get_vapid_key():
    return {"key": VAPID_PUBLIC_KEY}

@app.post("/api/push/subscribe")
async def push_subscribe(req: PushSubscribeRequest):
    push_subscriptions["default"] = {
        "subscription": req.subscription,
        "city": req.city,
        "notify_time": req.notify_time,
    }
    save_json(SUBS_FILE, push_subscriptions)
    return {"ok": True}

@app.delete("/api/push/subscribe")
async def push_unsubscribe():
    push_subscriptions.pop("default", None)
    save_json(SUBS_FILE, push_subscriptions)
    return {"ok": True}

@app.get("/api/push/status")
async def push_status():
    sub = push_subscriptions.get("default")
    if sub:
        return {"subscribed": True, "city": sub.get("city", ""), "time": sub.get("notify_time", "")}
    return {"subscribed": False}

# ── Настройки
@app.get("/api/settings")
async def get_settings():
    return user_settings.get("default", {"home_city": "", "units": "metric"})

@app.post("/api/settings")
async def save_settings(req: SettingsRequest):
    if req.home_city:
        data = await ws.get_current(req.home_city)
        if not data:
            raise HTTPException(status_code=404, detail="Город не найден")
        req.home_city = data["name"]
    user_settings["default"] = {"home_city": req.home_city, "units": req.units}
    save_json(SETTINGS_FILE, user_settings)
    return {"ok": True, "home_city": req.home_city}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
