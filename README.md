# SkyPulse PWA: Ваш Информационный Хаб Будущего 🌍✨

**SkyPulse** полностью эволюционировал! То, что начиналось как Telegram-бот, теперь превратилось в передовое мобильное веб-приложение (PWA) с футуристичным дизайном в стиле **iOS 26 Liquid Glass**.

![SkyPulse Preview](https://img.shields.io/badge/PWA-Ready-success?style=for-the-badge&logo=pwa) ![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)

## 🎨 Дизайн и UI/UX
- **Liquid Glass System:** Настоящий стекломорфизм с экстремальным размытием (blur 40px), переотражениями и плавающими элементами интерфейса.
- **Animated Mesh Background:** Динамичный задний фон с объемными "орбами" (цветовыми пятнами), которые медленно дрейфуют под матовым стеклом карточек.
- **Spring Physics:** Интерактивные капсулы-кнопки и плавающая нижняя панель навигации (bottom frosted bar) с пружинной отдачей.
- **CSS Neon Weather Icons:** Динамичные неоновые иконки погоды, полностью отрисованные на чистом градиентном CSS с анимацией пульсаций (3D-ореол и свечение без использования изображений!).

## 🌟 Ключевые возможности

### 🌤 Умная погода (2x2 Grid)
- Отслеживание текущей климатической картины по геолокации или выбору города (OpenWeatherMap).
- Резервная интеграция с Open-Meteo на случай падения основного сервиса.

### 📰 Агрегация новостей и Космос
- Сбор главных новостей по категориям (Бизнес, IT, Наука, Здоровье).
- Отдельный раздел для последних новостей космических запусков от NASA и SpaceX (через Spaceflight News API).

### 📈 Финансы и RSS-ридер
- Отслеживание курсов мировых валют к рублю в реальном времени.
- Механизм добавления любых сторонних RSS-лент прямо в интерфейс с парсером ленты на лету.

### 🔔 Web Push-уведомления
- Service Worker работает в фоне и доставляет Push-уведомления (утренние сводки погоды), даже когда браузер телефона закрыт!

### ⚙️ Serverless & Ephemeral-дизайн
- Настройки пользователя (темы, города, подписки на уведомления) хранятся в **localStorage** телефона. Приложение автоматически синхронизируется с облаком, благодаря чему данные переживают "холодные старты" бесплатных серверов (включая Render.com).

## 🛠 Технологический стек

- **Backend:** Python 3.10+, FastAPI (Asynchronous), Uvicorn, Aiohttp (Асинхронные HTTP запросы к сторонним сервисам).
- **Frontend:** Vanilla JavaScript, HTML5, CSS3 (CSS Grid, Variables, Keyframes, Webkit Backdrop Filter).
- **PWA:** Service Workers, Web Push API, pywebpush, Web App Manifest.

## 🚀 Быстрый старт

### 1. Установка
```bash
git clone https://github.com/namexample100-ux/SkyPulse-Web.git
cd SkyPulse-Web
pip install -r requirements.txt
```

### 2. Конфигурация
Создайте файл `.env` в корне проекта (или добавьте эти переменные в настройки вашего хостинга, например Render).

```env
OWM_API_KEY=ваш_ключ_от_OpenWeatherMap
VAPID_PUBLIC_KEY=ваш_публичный_ключ_VAPID_для_Push
VAPID_PRIVATE_KEY=ваш_приватный_ключ_VAPID_для_Push
VAPID_EMAIL=mailto:support@yourdomain.com
```

> **Совет:** Для генерации VAPID-ключей можно использовать команду:
> `vapid --gen` (нужно установить библиотеку `vapid-cli` через npm)

### 3. Запуск
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## 📂 Структура проекта
- `main.py` — Точка входа в приложение, маршрутизатор FastAPI (`/api/`).
- `static/index.html` — Frontend SPA с Liquid Glass интерфейсом.
- `static/sw.js` — Service Worker для обработки push-сообщений.
- `static/manifest.json` — Файл конфигурации для установки PWA.
- Сервисы интеграции данных: `weather.py`, `news.py`, `space_service.py`, `finance_service.py`, `rss_service.py`.

---
*С любовью к эстетике и технологиям. Держите руку на пульсе мира!* 🌌
