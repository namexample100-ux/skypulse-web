"""Погодный Telegram-бот — хендлеры, клавиатуры, FSM."""

import asyncio
import logging
import sys
import time
import json
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Awaitable

from aiogram import Bot, Dispatcher, Router, F, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, TelegramObject,
    KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    InlineKeyboardButton, InlineKeyboardMarkup,
)
from aiohttp import web

from config import BOT_TOKEN, ADMIN_ID, MAX_FAVORITES, THROTTLE_RATE
from weather import WeatherService
from news import NewsService
from space_service import SpaceService
from finance_service import FinanceService
from calendar_service import CalendarService
from rss_service import RSSService
from ai_service import AIService

# ── Логирование ─────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
log = logging.getLogger(__name__)

# ── Сервси и хранилище ──────────────────────────────────────────────────
ws = WeatherService()
ns = NewsService()
ss = SpaceService()
fs = FinanceService()
cs = CalendarService()
rs = RSSService()
ai = AIService()
router = Router()

# In-memory хранилище избранных: {user_id: [city1, city2, ...]}
favorites: dict[int, list[str]] = {}
FAVS_FILE = "favs.json"

# Хранилище настроек: {user_id: {"home_city": ..., "lang": "ru", "units": "metric"}}
user_settings: dict[int, dict] = {}
SETTINGS_FILE = "settings.json"

# Хранилище рассылок: {user_id: {"city": ..., "time": "HH:MM", "tz": ...}}
subscriptions: dict[int, dict] = {}
SUBS_FILE = "subs.json"

def load_data():
    """Загрузка всех данных из JSON."""
    global subscriptions, favorites, user_settings
    
    # Загрузка подписок
    if os.path.exists(SUBS_FILE):
        try:
            with open(SUBS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                subscriptions = {int(k): v for k, v in data.items()}
        except Exception as e:
            log.error(f"Ошибка загрузки подписок: {e}")
            
    # Загрузка избранного
    if os.path.exists(FAVS_FILE):
        try:
            with open(FAVS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                favorites = {int(k): v for k, v in data.items()}
        except Exception as e:
            log.error(f"Ошибка загрузки избранного: {e}")

    # Загрузка настроек
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                user_settings = {int(k): v for k, v in data.items()}
        except Exception as e:
            log.error(f"Ошибка загрузки настроек: {e}")

def save_subs():
    try:
        with open(SUBS_FILE, "w", encoding="utf-8") as f:
            json.dump(subscriptions, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"Ошибка сохранения подписок: {e}")

def save_favs():
    try:
        with open(FAVS_FILE, "w", encoding="utf-8") as f:
            json.dump(favorites, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"Ошибка сохранения избранного: {e}")

def save_settings():
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(user_settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"Ошибка сохранения настроек: {e}")

load_data()

def get_prefs(uid: int) -> tuple[str, str]:
    """Получить (units, lang) для пользователя."""
    s = user_settings.get(uid, {})
    return s.get("units", "metric"), s.get("lang", "ru")

# Кэш последнего запроса для inline-кнопок: {user_id: {"lat": ..., "lon": ..., "city": ...}}
last_query: dict[int, dict] = {}


# ── FSM-состояния ───────────────────────────────────────────────────────

class UserState(StatesGroup):
    waiting_city_current = State()
    waiting_city_forecast = State()
    waiting_city_fav = State()
    waiting_compare_1 = State()
    waiting_compare_2 = State()
    waiting_city_date = State()
    waiting_date = State()
    waiting_city_sub = State()
    waiting_time_sub = State()
    waiting_news_query = State()
    waiting_news_search = State()
    waiting_rss_url = State()
    # Настройки
    waiting_home_city = State()
    waiting_news_region = State()
    waiting_ai_question = State()


# ── Throttling Middleware ────────────────────────────────────────────────

class ThrottlingMiddleware(BaseMiddleware):
    """Простая защита от спама."""

    def __init__(self, rate: float = THROTTLE_RATE):
        self.rate = rate
        self._last: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user:
            now = time.time()
            if now - self._last.get(user.id, 0) < self.rate:
                if isinstance(event, Message):
                    await event.answer("⏳ Слишком частые запросы, подождите секунду…")
                return
            self._last[user.id] = now
        return await handler(event, data)


class AccessMiddleware(BaseMiddleware):
    """Ограничение доступа: бот отвечает только админу, если ADMIN_ID задан."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Если ADMIN_ID не задан в .env, пропускаем всех (по умолчанию)
        if not ADMIN_ID:
            return await handler(event, data)

        user = data.get("event_from_user")
        if user:
            # Сравниваем ID (учитываем, что в .env это строка)
            if str(user.id) != str(ADMIN_ID):
                # Если это сообщение, вежливо отвечаем один раз (или можно просто игнорировать)
                if isinstance(event, Message):
                    # Чтобы не спамить в ответ на каждое сообщение чужака, 
                    # можно отвечать только на /start или вообще молчать.
                    if event.text == "/start":
                        await event.answer("🔒 **Доступ ограничен.**\nЭтот бот является частным информационным хабом.")
                return 
        
        return await handler(event, data)


# ── Клавиатуры ──────────────────────────────────────────────────────────

def main_keyboard() -> ReplyKeyboardMarkup:
    """Главная reply-клавиатура."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🌤 Погода"), KeyboardButton(text="🚀 Космос")],
            [KeyboardButton(text="📰 Новости"), KeyboardButton(text="📈 Финансы")],
            [KeyboardButton(text="🤖 Спроси ИИ"), KeyboardButton(text="⭐ Избранное")],
            [KeyboardButton(text="📍 Геолокация"), KeyboardButton(text="🗓 Календарь")],
            [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="ℹ️ Помощь")],
        ],
        resize_keyboard=True,
    )


def settings_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура настроек."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏠 Мой город"), KeyboardButton(text="🌍 Язык")],
            [KeyboardButton(text="🌡 Единицы"), KeyboardButton(text="📡 Источники новостей")],
            [KeyboardButton(text="🔔 Рассылка"), KeyboardButton(text="🏠 Главное меню")],
        ],
        resize_keyboard=True,
    )


def weather_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура управления погодой."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🌤 Погода сейчас"), KeyboardButton(text="📊 Прогноз 5 дней")],
            [KeyboardButton(text="🏙 Сравнить города"), KeyboardButton(text="📅 На конкретную дату")],
            [KeyboardButton(text="➕ Добавить в избранное"), KeyboardButton(text="🏠 Главное меню")],
        ],
        resize_keyboard=True,
    )


def news_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура управления новостями."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔥 Топ новости"), KeyboardButton(text="⚡️ AI-Сводка дня")],
            [KeyboardButton(text="📡 RSS Ленты")],
            [KeyboardButton(text="🏠 Главное меню")],
        ],
        resize_keyboard=True,
    )


def rss_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура управления RSS-лентами."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Мои ленты"), KeyboardButton(text="➕ Добавить ленту")],
            [KeyboardButton(text="🏠 Главное меню")],
        ],
        resize_keyboard=True,
    )


def space_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура управления космическими новостями."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚀 Последние новости")],
            [KeyboardButton(text="🏠 Главное меню")],
        ],
        resize_keyboard=True,
    )


def finance_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура управления финансовыми новостями."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💰 Курсы валют")],
            [KeyboardButton(text="🏠 Главное меню")],
        ],
        resize_keyboard=True,
    )


def calendar_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура управления календарем."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🗓 Праздники (РФ)")],
            [KeyboardButton(text="🏠 Главное меню")],
        ],
        resize_keyboard=True,
    )


def lang_inline() -> InlineKeyboardMarkup:
    """Выбор языка."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Русский 🇷🇺", callback_data="set_lang:ru"),
            InlineKeyboardButton(text="English 🇺🇸", callback_data="set_lang:en"),
        ]
    ])


def units_inline() -> InlineKeyboardMarkup:
    """Выбор единиц измерения."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Celsius (°C)", callback_data="set_units:metric"),
            InlineKeyboardButton(text="Fahrenheit (°F)", callback_data="set_units:imperial"),
        ]
    ])


def detail_inline(lat: float, lon: float) -> InlineKeyboardMarkup:
    """Inline-кнопки после текущей погоды."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Прогноз", callback_data=f"forecast:{lat}:{lon}"),
            InlineKeyboardButton(text="🌬 Воздух", callback_data=f"air:{lat}:{lon}"),
            InlineKeyboardButton(text="🕒 Время", callback_data=f"time:{lat}:{lon}"),
        ],
        [
            InlineKeyboardButton(text="👗 Одежда", callback_data=f"cloth:{lat}:{lon}"),
            InlineKeyboardButton(text="📈 График", callback_data=f"chart:{lat}:{lon}"),
            InlineKeyboardButton(text="🌧 Осадки", callback_data=f"radar:{lat}:{lon}"),
        ],
        [
            InlineKeyboardButton(text="🌡 UV-индекс", callback_data=f"uv:{lat}:{lon}"),
            InlineKeyboardButton(text="⚠️ Алерты", callback_data=f"alerts:{lat}:{lon}"),
        ],
        [InlineKeyboardButton(text="⭐ В избранное", callback_data="add_fav")],
    ])

def news_categories_inline() -> InlineKeyboardMarkup:
    """Выбор категории новостей (RSS)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💻 IT", callback_data="news_cat:technology"),
            InlineKeyboardButton(text="💰 Бизнес", callback_data="news_cat:business"),
        ],
        [
            InlineKeyboardButton(text="⚽ Спорт", callback_data="news_cat:sports"),
            InlineKeyboardButton(text="🎬 Культура", callback_data="news_cat:entertainment"),
        ],
        [
            InlineKeyboardButton(text="🧬 Наука", callback_data="news_cat:science"),
            InlineKeyboardButton(text="💊 Здоровье", callback_data="news_cat:health"),
        ],
        [
            InlineKeyboardButton(text="🚗 Авто", callback_data="news_cat:auto"),
            InlineKeyboardButton(text="🌍 Главное", callback_data="news_cat:general"),
        ],
    ])



def favorites_inline(user_id: int) -> InlineKeyboardMarkup | None:
    """Inline-клавиатура с избранными городами."""
    cities = favorites.get(user_id, [])
    if not cities:
        return None
    buttons = [[InlineKeyboardButton(text=f"🏙 {c}", callback_data=f"fav:{c}")] for c in cities]
    buttons.append([InlineKeyboardButton(text="🗑 Очистить всё", callback_data="clear_fav")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def date_keyboard(tz_offset: int = 0) -> ReplyKeyboardMarkup:
    """Клавиатура с датами на ближайшие 5 дней."""
    buttons = []
    base = datetime.now(tz=timezone(timedelta(seconds=tz_offset)))
    for i in range(5):
        d = base + timedelta(days=i)
        date_str = d.strftime("%d.%m")
        day_name = d.strftime("%a")
        # Простой маппинг дней недели
        ru_days = {"Mon": "Пн", "Tue": "Вт", "Wed": "Ср", "Thu": "Чт", "Fri": "Пт", "Sat": "Сб", "Sun": "Вс"}
        label = f"{date_str} ({ru_days.get(day_name, day_name)})"
        buttons.append([KeyboardButton(text=label)])
    
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)


# ── Хендлеры команд ─────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 <b>Привет! Я — SkyPulse.</b>\n\n"
        "Ваш универсальный помощник 2-в-1: <b>Погода + Новости</b>.\n"
        "Выбери раздел на клавиатуре ниже:",
        reply_markup=main_keyboard(),
    )


# ── Навигация по разделам ──────────────────────────────────────────────

@router.message(F.text == "🌤 Погода")
async def nav_weather_menu(message: Message):
    await message.answer("Перехожу в раздел <b>Погода</b> 🌤:", reply_markup=weather_keyboard())


@router.message(F.text == "📰 Новости")
async def nav_news_menu(message: Message):
    await message.answer("Перехожу в раздел <b>Новости</b> 📰:", reply_markup=news_keyboard())


@router.message(F.text == "🚀 Космос")
async def nav_space_menu(message: Message):
    await message.answer("Добро пожаловать в <b>Космический Пульс</b> 🚀:\nЛучшие новости о космосе и технологиях NASA/SpaceX.", reply_markup=space_keyboard())


@router.message(F.text == "📈 Финансы")
async def nav_finance_menu(message: Message):
    await message.answer("Добро пожаловать в <b>Финансовый Пульс</b> 📈:\nАктуальные курсы валют и экономические данные.", reply_markup=finance_keyboard())


@router.message(F.text == "🗓 Календарь")
async def nav_calendar_menu(message: Message):
    await message.answer("Добро пожаловать в <b>Календарный Пульс</b> 🗓:\nПраздники, мировое время и важные даты.", reply_markup=calendar_keyboard())


@router.message(F.text == "🏠 Главное меню")
async def nav_main_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Вы вернулись в главное меню:", reply_markup=main_keyboard())


@router.message(F.text == "📍 Геолокация")
async def ask_location(message: Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Отправить мою геолокацию", request_location=True)],
            [KeyboardButton(text="🏠 Главное меню")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer(
        "📍 Нажмите на кнопку ниже, чтобы я узнал ваши координаты и показал погоду:", 
        reply_markup=kb
    )


@router.message(F.text == "⚙️ Настройки")
async def nav_settings_menu(message: Message):
    await message.answer("⚙️ <b>Настройки SkyPulse</b>\n\nЗдесь вы можете персонализировать бота под себя:", reply_markup=settings_keyboard())


# ── AI Ассистент ────────────────────────────────────────────────────────

@router.message(F.text == "🤖 Спроси ИИ")
async def ai_ask_start(message: Message, state: FSMContext):
    await state.set_state(UserState.waiting_ai_question)
    await message.answer(
        "🤖 <b>Я слушаю!</b>\n"
        "Задайте любой вопрос. Я использую сверхбыстрый интеллект Cerebras, чтобы ответить мгновенно.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🏠 Главное меню")]],
            resize_keyboard=True
        )
    )

@router.message(UserState.waiting_ai_question)
async def ai_process_question(message: Message, state: FSMContext):
    if message.text == "🏠 Главное меню":
        await nav_main_menu(message, state)
        return

    wait_msg = await message.answer("⏳ Думаю...")
    response = await ai.get_ai_response(message.text)
    await wait_msg.edit_text(response, parse_mode=ParseMode.MARKDOWN)
    # Оставляем в состоянии вопроса, чтобы можно было переписываться дальше
    await message.answer("👇 Можете задать еще один вопрос или вернуться в меню.", reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🏠 Главное меню")]],
            resize_keyboard=True
        ))

# ── AI Сводка новостей ──────────────────────────────────────────────────

@router.message(F.text == "⚡️ AI-Сводка дня")
async def ai_news_summary(message: Message):
    wait_msg = await message.answer("⏳ Анализирую главные новости дня...")
    
    # Берем новости из категории general для сводки
    data = await ns.get_news_by_category("general")
    if not data:
        await wait_msg.edit_text("❌ Не удалось получить новости для анализа.")
        return

    text = await ns.format_news_summarized(data, "Главные новости")
    await wait_msg.edit_text(text, disable_web_page_preview=True)


@router.message(F.text == "🏠 Мой город")
async def set_home_city_start(message: Message, state: FSMContext):
    uid = message.from_user.id
    current = user_settings.get(uid, {}).get("home_city", "не установлен")
    await state.set_state(UserState.waiting_home_city)
    await message.answer(
        f"🏠 <b>Ваш текущий «Мой город»:</b> {current}\n\n"
        "Введите название города, который будет использоваться по умолчанию:",
        reply_markup=ReplyKeyboardRemove()
    )


@router.message(F.text == "🌍 Язык")
async def set_lang_menu(message: Message):
    await message.answer("🌍 <b>Выберите язык интерфейса:</b>", reply_markup=lang_inline())


@router.message(F.text == "🌡 Единицы")
async def set_units_menu(message: Message):
    await message.answer("🌡 <b>Выберите единицы измерения:</b>", reply_markup=units_inline())




@router.callback_query(F.data.startswith("toggle_src:"))
async def cb_toggle_source(callback: CallbackQuery):
    _, reg, domain = callback.data.split(":")
    uid = callback.from_user.id
    
    if uid not in user_settings: user_settings[uid] = {}
    selected = user_settings[uid].get("news_sources", [])
    
    if domain in selected:
        selected.remove(domain)
    else:
        selected.append(domain)
    
    user_settings[uid]["news_sources"] = selected
    save_settings()
    
    # Обновляем клавиатуру
    await callback.message.edit_reply_markup(reply_markup=news_sources_inline(reg, uid))
    await callback.answer()


@router.callback_query(F.data.startswith("set_lang:"))
async def cb_set_lang(callback: CallbackQuery):
    lang = callback.data.split(":")[1]
    uid = callback.from_user.id
    if uid not in user_settings: user_settings[uid] = {}
    user_settings[uid]["lang"] = lang
    save_settings()
    
    text = "✅ Язык установлен: Русский 🇷🇺" if lang == "ru" else "✅ Language set: English 🇺🇸"
    await callback.message.edit_text(text)
    await callback.answer()


@router.callback_query(F.data.startswith("set_units:"))
async def cb_set_units(callback: CallbackQuery):
    unit = callback.data.split(":")[1]
    uid = callback.from_user.id
    if uid not in user_settings: user_settings[uid] = {}
    user_settings[uid]["units"] = unit
    save_settings()
    
    text = "✅ Единицы измерения: Градусы Цельсия (°C)" if unit == "metric" else "✅ Units set: Fahrenheit (°F)"
    await callback.message.edit_text(text)
    await callback.answer()


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь")
async def cmd_help(message: Message):
    help_text = (
        "<b>🤖 Что умеет SkyPulse «Супер-Информатор»:</b>\n\n"
        "🌤 <b>Погода:</b>\n"
        "• Текущая погода и прогноз на 5 дней\n"
        "• 👗 Рекомендуемая одежда и 🌡 UV-индекс\n"
        "• 🌬 Качество воздуха и 📈 текстовые графики\n"
        "• 🌧 <b>Осадки:</b> живая карта радара RainViewer\n"
        "• 🛡 <b>Backup:</b> автоматический переход на резервный источник\n\n"
        "🚀 <b>Космический Пульс:</b> новости NASA, SpaceX и запусков\n"
        "📈 <b>Финансовый Пульс:</b> курсы USD, EUR, CNY к рублю\n"
        "🗓 <b>Календарный Пульс:</b> праздники и время в городах\n\n"
        "📰 <b>Новости:</b> топы по категориям или поиск по темам\n"
        "� <b>RSS Читалка:</b> добавляйте собственные ленты новостей\n"
        "�📍 <b>Геолокация:</b> мгновенный прогноз для вашего места\n"
        "⭐ <b>Избранное:</b> быстрый доступ к любимым городам\n\n"
        "Просто выбирай разделы на клавиатуре и делай свой день лучше! ✨"
    )
    await message.answer(help_text, reply_markup=main_keyboard())


# ── Текущая погода ──────────────────────────────────────────────────────

@router.message(F.text == "🌤 Погода сейчас")
async def ask_city_current(message: Message, state: FSMContext):
    uid = message.from_user.id
    home = user_settings.get(uid, {}).get("home_city")
    
    if home:
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=f"🏠 {home}")], [KeyboardButton(text="🔎 Другой город")], [KeyboardButton(text="🏠 Главное меню")]],
            resize_keyboard=True
        )
        await message.answer(f"📍 Показать погоду в вашем городе <b>{home}</b> или другом?", reply_markup=kb)
    else:
        await state.set_state(UserState.waiting_city_current)
        await message.answer("🏙 Введите название города:", reply_markup=ReplyKeyboardRemove())


@router.message(F.text == "🔎 Другой город")
async def ask_another_city(message: Message, state: FSMContext):
    await state.set_state(UserState.waiting_city_current)
    await message.answer("🏙 Введите название города:", reply_markup=ReplyKeyboardRemove())


@router.message(F.text.startswith("🏠 "))
async def show_home_weather(message: Message, state: FSMContext):
    # Если это кнопка "🏠 Город"
    city = message.text.replace("🏠 ", "").strip()
    if city == "Главное меню": 
        await nav_main_menu(message, state)
        return
    await show_current(message, state, city)


@router.message(UserState.waiting_city_current)
async def show_current_handler(message: Message, state: FSMContext):
    await show_current(message, state, message.text.strip())

async def show_current(message: Message, state: FSMContext, city: str):
    await state.clear()
    uid = message.from_user.id
    wait_msg = await message.answer("⏳ Загружаю погоду…")

    u, l = get_prefs(uid)
    data = await ws.get_current(city, units=u, lang=l)
    
    if not data:
        # Пытаемся найти координаты через геокодер OWM (если город был найден раньше или просто через поиск)
        # Но проще всего, если data нет, вывести ошибку. 
        # Однако, если у нас есть координаты в кэше для этого города, можем попробовать Open-Meteo.
        await wait_msg.edit_text("❌ Город не найден или сервис OWM недоступен.")
        await message.answer("Выберите действие:", reply_markup=weather_keyboard())
        return

    # Сохраняем для inline-кнопок
    coord = data.get("coord", {})
    last_query[uid] = {
        "lat": coord.get("lat"), "lon": coord.get("lon"),
        "city": data.get("name", city),
    }

    text = ws.format_current(data, units=u)
    
    # Добавляем умный совет от ИИ
    temp = data["main"]["temp"]
    desc = data["weather"][0]["description"]
    advice = await ai.get_weather_advice(desc, temp)
    
    final_text = f"{text}\n\n🤖 <b>Совет от ИИ:</b>\n{advice}"
    
    await wait_msg.edit_text(final_text, reply_markup=detail_inline(coord["lat"], coord["lon"]))
    await message.answer("👇 Или выберите другое действие:", reply_markup=weather_keyboard())


# ── Прогноз 5 дней ──────────────────────────────────────────────────────

@router.message(F.text == "📊 Прогноз 5 дней")
async def ask_city_forecast(message: Message, state: FSMContext):
    await state.set_state(UserState.waiting_city_forecast)
    await message.answer("🏙 Введите название города:", reply_markup=ReplyKeyboardRemove())


@router.message(UserState.waiting_city_forecast)
async def show_forecast(message: Message, state: FSMContext):
    await state.clear()
    city = message.text.strip()
    wait_msg = await message.answer("⏳ Загружаю прогноз…")

    u, l = get_prefs(message.from_user.id)
    data = await ws.get_forecast(city, units=u, lang=l)
    if not data or data.get("cod") != "200":
        await wait_msg.edit_text("❌ Город не найден. Попробуйте ещё раз.")
        await message.answer("Выберите действие:", reply_markup=weather_keyboard())
        return

    text = ws.format_forecast(data)
    await wait_msg.edit_text(text)
    await message.answer("👇 Или выберите другое действие:", reply_markup=weather_keyboard())


# ── Геолокация ──────────────────────────────────────────────────────────

@router.message(F.location)
async def handle_location(message: Message):
    lat = message.location.latitude
    lon = message.location.longitude
    uid = message.from_user.id
    wait_msg = await message.answer("📍 Определяю погоду по вашим координатам…")

    u, l = get_prefs(uid)
    data = await ws.get_current_by_coords(lat, lon, units=u, lang=l)
    
    if not data:
        log.warning(f"OWM failed for coords {lat}, {lon}. Trying Open-Meteo fallback.")
        data_backup = await ws.get_current_backup(lat, lon)
        if data_backup:
            text = ws.format_current_backup(data_backup)
            await wait_msg.edit_text(text, reply_markup=detail_inline(lat, lon))
            return
        
        await wait_msg.edit_text("❌ Не удалось получить погоду даже из резервного источника.")
        return

    coord = data.get("coord", {"lat": lat, "lon": lon})
    last_query[uid] = {
        "lat": coord.get("lat", lat), "lon": coord.get("lon", lon),
        "city": data.get("name", f"{lat:.2f}, {lon:.2f}"),
    }

    text = ws.format_current(data, units=u)
    
    # Добавляем умный совет от ИИ
    temp = data["main"]["temp"]
    desc = data["weather"][0]["description"]
    advice = await ai.get_weather_advice(desc, temp)
    
    final_text = f"{text}\n\n🤖 <b>Совет от ИИ:</b>\n{advice}"
    
    await wait_msg.edit_text(final_text, reply_markup=detail_inline(lat, lon))


# ── Избранное ───────────────────────────────────────────────────────────

@router.message(F.text == "⭐ Избранное")
async def show_favorites(message: Message):
    kb = favorites_inline(message.from_user.id)
    if not kb:
        await message.answer(
            "⭐ У вас пока нет избранных городов.\n"
            "Нажмите «➕ Добавить в избранное», чтобы сохранить город.",
        )
        return
    await message.answer("⭐ <b>Ваши избранные города:</b>", reply_markup=kb)


@router.message(F.text == "➕ Добавить в избранное")
async def ask_city_fav(message: Message, state: FSMContext):
    await state.set_state(UserState.waiting_city_fav)
    await message.answer("🏙 Введите название города для сохранения:", reply_markup=ReplyKeyboardRemove())


@router.message(UserState.waiting_city_fav)
async def add_fav_city(message: Message, state: FSMContext):
    await state.clear()
    city = message.text.strip().title()
    uid = message.from_user.id
    user_favs = favorites.setdefault(uid, [])

    if city.lower() in [c.lower() for c in user_favs]:
        await message.answer(f"ℹ️ <b>{city}</b> уже в избранном!", reply_markup=weather_keyboard())
        return

    if len(user_favs) >= MAX_FAVORITES:
        await message.answer(
            f"⚠️ Максимум {MAX_FAVORITES} городов. Очистите избранное, чтобы добавить новый.",
            reply_markup=weather_keyboard(),
        )
        return

    # Проверяем, что город существует
    data = await ws.get_current(city)
    if not data:
        await message.answer("❌ Город не найден. Попробуйте ещё раз.", reply_markup=weather_keyboard())
        return

    real_name = data.get("name", city)
    user_favs.append(real_name)
    save_favs()
    await message.answer(f"✅ <b>{real_name}</b> добавлен в избранное! ⭐", reply_markup=weather_keyboard())


@router.message(UserState.waiting_home_city)
async def process_home_city(message: Message, state: FSMContext):
    city = message.text.strip().title()
    uid = message.from_user.id
    
    # Проверка существования города
    data = await ws.get_current(city)
    if not data:
        await message.answer("❌ Город не найден. Попробуйте еще раз:")
        return
    
    if uid not in user_settings: user_settings[uid] = {}
    user_settings[uid]["home_city"] = data["name"]
    save_settings()
    
    await state.clear()
    await message.answer(
        f"✅ <b>{data['name']}</b> установлен как ваш основной город!",
        reply_markup=settings_keyboard()
    )


# ── Сравнение городов ───────────────────────────────────────────────────

@router.message(F.text == "🏙 Сравнить города")
async def start_compare(message: Message, state: FSMContext):
    await state.set_state(UserState.waiting_compare_1)
    await message.answer("🏙 Введите название <b>первого</b> города:", reply_markup=ReplyKeyboardRemove())


@router.message(UserState.waiting_compare_1)
async def process_compare_1(message: Message, state: FSMContext):
    city1 = message.text.strip()
    u, l = get_prefs(message.from_user.id)
    data1 = await ws.get_current(city1, units=u, lang=l)
    if not data1:
        await message.answer("❌ Первый город не найден. Попробуйте ещё раз:")
        return
    
    await state.update_data(city1_data=data1)
    await state.set_state(UserState.waiting_compare_2)
    await message.answer(f"✅ Первый город — <b>{data1['name']}</b>\n🏙 Теперь введите название <b>второго</b> города:")


@router.message(UserState.waiting_compare_2)
async def process_compare_2(message: Message, state: FSMContext):
    city2 = message.text.strip()
    u, l = get_prefs(message.from_user.id)
    data2 = await ws.get_current(city2, units=u, lang=l)
    if not data2:
        await message.answer("❌ Второй город не найден. Попробуйте ещё раз:")
        return

    user_data = await state.get_data()
    data1 = user_data['city1_data']
    await state.clear()

    text = ws.format_comparison(data1, data2, units=u)
    await message.answer(text, reply_markup=weather_keyboard())


# ── Сравнение на дату ───────────────────────────────────────────────────

@router.message(F.text == "📅 На конкретную дату")
async def ask_city_date(message: Message, state: FSMContext):
    await state.set_state(UserState.waiting_city_date)
    await message.answer("🏙 Введите название города:", reply_markup=ReplyKeyboardRemove())


@router.message(UserState.waiting_city_date)
async def process_city_date(message: Message, state: FSMContext):
    city = message.text.strip()
    u, l = get_prefs(message.from_user.id)
    data = await ws.get_forecast(city, units=u, lang=l)
    if not data or data.get("cod") != "200":
        await message.answer("❌ Город не найден или прогноз недоступен. Попробуйте ещё раз:")
        return
    
    tz = data.get("city", {}).get("timezone", 0)
    await state.update_data(forecast_data=data, city_name=city)
    await state.set_state(UserState.waiting_date)
    await message.answer(
        f"📅 Выберите дату для города <b>{data['city']['name']}</b>:",
        reply_markup=date_keyboard(tz)
    )


@router.message(UserState.waiting_date)
async def process_date_selection(message: Message, state: FSMContext):
    # Ожидаем текст в формате "DD.MM (День)"
    text_parts = message.text.split(" ")
    if not text_parts:
        await message.answer("❌ Некорректный выбор. Используйте кнопки.")
        return
    
    target_date = text_parts[0] # "15.02"
    user_data = await state.get_data()
    forecast = user_data.get("forecast_data")
    
    if not forecast:
        await state.clear()
        await message.answer("🏠 Ошибка данных. Возвращаюсь в меню.", reply_markup=weather_keyboard())
        return

    await state.clear()
    u, l = get_prefs(message.from_user.id)
    out = ws.format_date_weather(forecast, target_date, units=u)
    await message.answer(out, reply_markup=weather_keyboard())


# ── Ежедневная рассылка ─────────────────────────────────────────────────

@router.message(F.text == "🔔 Рассылка")
async def start_broadcast(message: Message, state: FSMContext):
    uid = message.from_user.id
    sub = subscriptions.get(uid)
    
    if sub:
        msg = (
            f"🔔 <b>Ваша подписка:</b>\n"
            f"📍 Город: {sub['city']}\n"
            f"⏰ Время: {sub['time']}\n\n"
            "Хотите изменить настройки или отключить?"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Изменить", callback_data="sub_new")],
            [InlineKeyboardButton(text="❌ Отключить", callback_data="unsub")]
        ])
        await message.answer(msg, reply_markup=kb)
    else:
        await state.set_state(UserState.waiting_city_sub)
        await message.answer(
            "🔔 <b>Настройка рассылки</b>\n\n"
            "Я буду присылать вам прогноз погоды каждое утро.\n"
            "🏙 Введите название города:",
            reply_markup=ReplyKeyboardRemove()
        )


@router.callback_query(F.data == "sub_new")
async def cb_sub_new(callback: CallbackQuery, state: FSMContext):
    await state.set_state(UserState.waiting_city_sub)
    await callback.message.answer("🏙 Введите название города:", reply_markup=ReplyKeyboardRemove())
    await callback.answer()


@router.callback_query(F.data == "unsub")
async def cb_unsub(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid in subscriptions:
        del subscriptions[uid]
        save_subs()
        await callback.message.edit_text("✅ Рассылка отключена.", reply_markup=None)
    await callback.answer("Подписка удалена")


@router.message(UserState.waiting_city_sub)
async def process_sub_city(message: Message, state: FSMContext):
    city = message.text.strip()
    data = await ws.get_current(city)
    if not data:
        await message.answer("❌ Город не найден. Попробуйте еще раз:")
        return
    
    await state.update_data(sub_city=data["name"], sub_tz=data.get("timezone", 0))
    await state.set_state(UserState.waiting_time_sub)
    await message.answer(
        f"✅ Город: <b>{data['name']}</b>\n"
        f"⏰ Введите время для рассылки в формате <b>ЧЧ:ММ</b> (например, 08:30):"
    )


@router.message(UserState.waiting_time_sub)
async def process_sub_time(message: Message, state: FSMContext):
    time_str = message.text.strip()
    if not re.match(r"^\d{1,2}:\d{2}$", time_str):
        await message.answer("❌ Неверный формат. Введите время как HH:MM (например, 07:00):")
        return
    
    # Нормализуем формат (07:0 -> 07:00, 7:30 -> 07:30)
    try:
        h, m = map(int, time_str.split(":"))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError
        time_str = f"{h:02d}:{m:02d}"
    except ValueError:
        await message.answer("❌ Некорректное время. Попробуйте еще раз:")
        return

    uid = message.from_user.id
    data = await state.get_data()
    
    subscriptions[uid] = {
        "city": data["sub_city"],
        "time": time_str,
        "tz": data["sub_tz"]
    }
    save_subs()
    await state.clear()
    
    await message.answer(
        f"🎉 <b>Готово!</b>\nТеперь я буду присылать прогноз по городу <b>{data['sub_city']}</b> "
        f"каждый день в <b>{time_str}</b>.",
        reply_markup=main_keyboard()
    )


async def broadcast_worker(bot: Bot):
    """Фоновая задача для рассылки погоды."""
    log.info("📢 Воркер рассылки запущен")
    while True:
        try:
            now = datetime.now(timezone.utc)
            # Проверяем каждую подписку
            for uid, sub in list(subscriptions.items()):
                # Время в подписке — это локальное время города пользователя
                # Нам нужно понять, наступило ли оно сейчас
                user_tz = sub.get("tz", 0)
                user_now = now + timedelta(seconds=user_tz)
                curr_time = user_now.strftime("%H:%M")
                
                if curr_time == sub["time"]:
                    log.info(f"Отправка рассылки пользователю {uid} ({sub['city']})")
                    u, l = get_prefs(uid)
                    data = await ws.get_current(sub["city"], units=u, lang=l)
                    if data:
                        text = "🔔 <b>Ежедневный прогноз</b>\n\n" + ws.format_current(data, units=u)
                        try:
                            await bot.send_message(uid, text)
                        except Exception as e:
                            log.error(f"Не удалось отправить рассылку {uid}: {e}")
            
            await asyncio.sleep(60 - datetime.now().second)
        except Exception as e:
            log.error(f"Ошибка в broadcast_worker: {e}")
            await asyncio.sleep(60)


# ── Callback-хендлеры (inline-кнопки) ───────────────────────────────────

@router.callback_query(F.data.startswith("forecast:"))
async def cb_forecast(callback: CallbackQuery):
    _, lat, lon = callback.data.split(":")
    await callback.answer("⏳ Загружаю прогноз…")

    u, l = get_prefs(callback.from_user.id)
    data = await ws.get_forecast_by_coords(float(lat), float(lon), units=u, lang=l)
    if not data:
        await callback.message.answer("❌ Не удалось загрузить прогноз.")
        return

    text = ws.format_forecast(data)
    await callback.message.answer(text)


@router.callback_query(F.data.startswith("air:"))
async def cb_air(callback: CallbackQuery):
    _, lat, lon = callback.data.split(":")
    await callback.answer("⏳ Загружаю данные…")

    u, l = get_prefs(callback.from_user.id)
    data = await ws.get_air_quality(float(lat), float(lon), lang=l)
    lq = last_query.get(callback.from_user.id, {})
    city_name = lq.get("city", "")

    text = ws.format_air_quality(data, city_name)
    await callback.message.answer(text)


@router.callback_query(F.data.startswith("cloth:"))
async def cb_clothing(callback: CallbackQuery):
    _, lat, lon = callback.data.split(":")
    await callback.answer("👗 Подбираю одежду…")

    u, l = get_prefs(callback.from_user.id)
    data = await ws.get_current_by_coords(float(lat), float(lon), units=u, lang=l)
    if not data:
        await callback.message.answer("❌ Не удалось загрузить данные.")
        return

    text = ws.format_clothing(data)
    await callback.message.answer(text)


@router.callback_query(F.data.startswith("chart:"))
async def cb_chart(callback: CallbackQuery):
    _, lat, lon = callback.data.split(":")
    await callback.answer("📈 Строю график…")

    u, l = get_prefs(callback.from_user.id)
    data = await ws.get_forecast_by_coords(float(lat), float(lon), units=u, lang=l)
    if not data:
        await callback.message.answer("❌ Не удалось загрузить данные.")
        return

    text = ws.format_temp_chart(data)
    await callback.message.answer(text)


@router.callback_query(F.data.startswith("uv:"))
async def cb_uv(callback: CallbackQuery):
    _, lat, lon = callback.data.split(":")
    await callback.answer("🌡 Оцениваю UV…")

    u, l = get_prefs(callback.from_user.id)
    data = await ws.get_current_by_coords(float(lat), float(lon), units=u, lang=l)
    if not data:
        await callback.message.answer("❌ Не удалось загрузить данные.")
        return

    text = ws.format_uv_estimate(data)
    await callback.message.answer(text)


@router.callback_query(F.data.startswith("alerts:"))
async def cb_alerts(callback: CallbackQuery):
    _, lat, lon = callback.data.split(":")
    await callback.answer("⚠️ Ищу опасности…")

    u, l = get_prefs(callback.from_user.id)
    data = await ws.get_forecast_by_coords(float(lat), float(lon), units=u, lang=l)
    if not data:
        await callback.message.answer("❌ Не удалось загрузить данные прогноза.")
        return

    text = ws.format_alerts(data)
    await callback.message.answer(text)


@router.callback_query(F.data.startswith("time:"))
async def cb_time(callback: CallbackQuery):
    _, lat, lon = callback.data.split(":")
    await callback.answer("🕒 Сверяю часы…")
    
    u, l = get_prefs(callback.from_user.id)
    data = await ws.get_current_by_coords(float(lat), float(lon), units=u, lang=l)
    if not data:
        await callback.message.answer("❌ Не удалось получить данные о времени.")
        return
        
    offset = data.get("timezone", 0)
    city = data.get("name", "Город")
    local_time = cs.get_time_in_timezone(offset)
    
    await callback.message.answer(f"🕒 Текущее время в <b>{city}</b>: <code>{local_time}</code>")


@router.callback_query(F.data.startswith("radar:"))
async def cb_radar(callback: CallbackQuery):
    _, lat, lon = callback.data.split(":")
    await callback.answer("🌧 Открываю карту осадков…")
    url = ws.get_radar_url(float(lat), float(lon))
    await callback.message.answer(
        f"🌧 <b>Карта осадков в реальном времени</b>\n\n"
        f"Посмотрите движение дождевых облаков на RainViewer:\n{url}"
    )


@router.callback_query(F.data == "add_fav")
async def cb_add_fav(callback: CallbackQuery):
    uid = callback.from_user.id
    lq = last_query.get(uid)
    if not lq or not lq.get("city"):
        await callback.answer("Сначала запросите погоду для города!", show_alert=True)
        return

    city = lq["city"]
    user_favs = favorites.setdefault(uid, [])

    if city.lower() in [c.lower() for c in user_favs]:
        await callback.answer(f"{city} уже в избранном!", show_alert=True)
        return

    if len(user_favs) >= MAX_FAVORITES:
        await callback.answer(f"Максимум {MAX_FAVORITES} городов!", show_alert=True)
        return

    user_favs.append(city)
    save_favs()
    await callback.answer(f"✅ {city} добавлен в избранное!", show_alert=True)


@router.callback_query(F.data.startswith("fav:"))
async def cb_fav_city(callback: CallbackQuery, state: FSMContext):
    city = callback.data.split(":", 1)[1]
    await callback.answer(f"⏳ Загружаю {city}…")
    await show_current(callback.message, state, city)


@router.callback_query(F.data == "clear_fav")
async def cb_clear_fav(callback: CallbackQuery):
    uid = callback.from_user.id
    favorites.pop(uid, None)
    save_favs()
    await callback.answer("🗑 Избранное очищено!", show_alert=True)
    await callback.message.edit_text("⭐ Избранное очищено.")


# ── Новостные хендлеры (RSS Engine 2.0) ──────────────────────────────────

@router.message(F.text == "🔥 Топ новости")
async def news_top_selection(message: Message):
    await message.answer("Выберите рубрику новостей:", reply_markup=news_categories_inline())


@router.callback_query(F.data.startswith("news_cat:"))
async def cb_news_category(callback: CallbackQuery):
    cat = callback.data.split(":")[1]
    await callback.answer("🗞 Загружаю из лучших источников…")
    
    # Получаем новости через новый RSS-агрегатор
    data = await ns.get_news_by_category(cat)
    
    titles = {
        "general": "🌍 Главные события",
        "technology": "💻 IT и Технологии",
        "business": "💰 Деловой вестник",
        "sports": "⚽ Спорт-Экспресс",
        "auto": "🚗 Автоновости",
        "entertainment": "🎬 Шоу-биз и Кино",
        "science": "🧬 Научпоп",
        "health": "💊 Здоровье и Жизнь"
    }
    
    title_label = titles.get(cat, "Новости")
    text = ns.format_news(data, category_title=f"🔥 {title_label}")
    
    await callback.message.answer(text, disable_web_page_preview=True)

@router.message(F.text == "📡 RSS Ленты")
async def nav_rss_menu(message: Message):
    await message.answer("Управление вашими <b>RSS-лентами</b> 📡:", reply_markup=rss_keyboard())


@router.message(F.text == "📋 Мои ленты")
async def rss_list_feeds(message: Message):
    uid = message.from_user.id
    feeds = user_settings.get(uid, {}).get("rss_feeds", [])
    
    if not feeds:
        await message.answer("📡 У вас еще нет добавленных RSS-лент.\nНажмите «➕ Добавить ленту», чтобы начать.")
        return
        
    # Создаем инлайн клавиатуру для выбора ленты
    kb = []
    for i, url in enumerate(feeds):
        # Попробуем сократить URL для кнопки
        display = url.replace("https://", "").replace("http://", "").split("/")[0]
        kb.append([InlineKeyboardButton(text=f"📖 {display}", callback_data=f"read_rss:{i}")])
        kb.append([InlineKeyboardButton(text=f"🗑 Удалить {display}", callback_data=f"del_rss:{i}")])
    
    await message.answer("📡 <b>Ваши подписки:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.message(F.text == "➕ Добавить ленту")
async def rss_add_start(message: Message, state: FSMContext):
    await state.set_state(UserState.waiting_rss_url)
    await message.answer(
        "📝 <b>Добавление RSS-ленты</b>\n\nВведите URL-адрес ленты (например: https://habr.com/ru/rss/all/all/):",
        reply_markup=ReplyKeyboardRemove()
    )


@router.message(UserState.waiting_rss_url)
async def rss_add_finish(message: Message, state: FSMContext):
    url = message.text.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        await message.answer("❌ Некорректный URL. Пожалуйста, введите ссылку, начинающуюся с http:// или https://")
        return
        
    await state.clear()
    wait_msg = await message.answer("📡 Проверяю ленту…")
    
    data = await rs.fetch_feed(url)
    if not data:
        await wait_msg.edit_text("❌ Не удалось получить данные по этой ссылке. Убедитесь, что это корректная RSS-лента.")
        return
        
    uid = message.from_user.id
    if uid not in user_settings:
        user_settings[uid] = {}
    
    feeds = user_settings[uid].get("rss_feeds", [])
    if url in feeds:
        await wait_msg.edit_text("⚠️ Эта лента уже есть в вашем списке.")
        await message.answer("Управление RSS:", reply_markup=rss_keyboard())
        return
        
    feeds.append(url)
    user_settings[uid]["rss_feeds"] = feeds
    save_settings()
    
    await wait_msg.edit_text(f"✅ Лента успешно добавлена!\nНайдено записей: {len(data)}")
    await message.answer("Управление RSS:", reply_markup=rss_keyboard())


@router.callback_query(F.data.startswith("read_rss:"))
async def cb_read_rss(callback: CallbackQuery):
    idx = int(callback.data.split(":")[1])
    uid = callback.from_user.id
    feeds = user_settings.get(uid, {}).get("rss_feeds", [])
    
    if idx >= len(feeds):
        await callback.answer("❌ Лента не найдена.")
        return
        
    url = feeds[idx]
    await callback.answer("📡 Читаю ленту…")
    
    data = await rs.fetch_feed(url)
    if not data:
        await callback.message.answer("❌ Не удалось загрузить новости из этой ленты.")
        return
        
    text = rs.format_feed(url.split("/")[2], data)
    await callback.message.answer(text, disable_web_page_preview=True)


@router.callback_query(F.data.startswith("del_rss:"))
async def cb_del_rss(callback: CallbackQuery):
    idx = int(callback.data.split(":")[1])
    uid = callback.from_user.id
    feeds = user_settings.get(uid, {}).get("rss_feeds", [])
    
    if idx >= len(feeds):
        await callback.answer("❌ Лента не найдена.")
        return
        
    url = feeds.pop(idx)
    user_settings[uid]["rss_feeds"] = feeds
    save_settings()
    
    await callback.answer("🗑 Лента удалена!")
    await callback.message.edit_text(f"🗑 Лента <b>{url}</b> удалена.")


@router.message(F.text == "🚀 Последние новости")
async def space_latest_news(message: Message):
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    news = await ss.get_latest_news(limit=5)
    if not news:
        await message.answer("❌ Не удалось получить сводку из космоса. Проверьте заземление.")
        return
        
    text = ss.format_news(news)
    await message.answer(text, disable_web_page_preview=True)


@router.message(F.text == "💰 Курсы валют")
async def finance_rates(message: Message):
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    rates = await fs.get_rates()
    if not rates:
        await message.answer("❌ Не удалось получить курсы валют. Попробуйте позже.")
        return
        
    text = fs.format_rates(rates)
    await message.answer(text)


@router.message(F.text == "🗓 Праздники (РФ)")
async def calendar_holidays(message: Message):
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    holidays = await cs.get_holidays("RU")
    if not holidays:
        await message.answer("❌ Не удалось получить список праздников.")
        return
        
    text = cs.format_holidays(holidays)
    await message.answer(text)


@router.message(F.text)
async def nav_unknown(message: Message):
    await message.answer("🤔 Я вас не понял. Используйте кнопки меню или введите /help.")

# ── Запуск ───────────────────────────────────────────────────────────────

async def handle(request):
    """Хендлер для проверки работоспособности (health-check)."""
    return web.Response(text="SkyPulse Bot is running! 🚀")

async def start_web_server():
    """Запуск мини веб-сервера для Render (чтобы не засыпал)."""
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    # Render передает порт в переменной окружения PORT
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    log.info(f"🌐 Веб-сервер запущен на порту {port}")
    await site.start()

async def main():
    if not BOT_TOKEN:
        log.error("BOT_TOKEN не задан! Создайте файл .env по образцу .env.example")
        return

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # Middleware
    router.message.middleware(AccessMiddleware())
    router.callback_query.middleware(AccessMiddleware())
    router.message.middleware(ThrottlingMiddleware())

    dp.include_router(router)

    # Веб-сервер для Render (health-check)
    asyncio.create_task(start_web_server())

    # Фоновые задачи
    asyncio.create_task(broadcast_worker(bot))

    log.info("🚀 SkyPulse запущен!")
    try:
        await dp.start_polling(bot)
    finally:
        await ws.close()
        await ns.close()
        await ss.close()
        await fs.close()
        await cs.close()
        await rs.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
