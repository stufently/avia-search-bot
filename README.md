# avia-search-bot

Простой набор скриптов для поиска авиабилетов:

1. **search_flights_text.py** — CLI‑инструмент для поиска по API Aviasales (Travelpayouts).  
2. **bot.py** — Telegram‑бот, обёртка над CLI: отвечает на текстовые запросы.

## Требования

- Python 3.7+  
- Пакеты:
    ```
    pip install requests python-dateutil python-telegram-bot>=20.0
    ```

## Настройка

1. Откройте `search_flights_text.py` и замените:
    ```
    API_TOKEN = 'ВАШ_TRAVELPAYOUTS_API_TOKEN'
    ```
2. Откройте `bot.py` и замените:
    ```
    TELEGRAM_TOKEN = 'ВАШ_TELEGRAM_BOT_TOKEN'
    ```

## Запуск

### Telegram‑бот
    python3 bot.py

В Telegram отправьте боту, например:
    Париж Лондон на 5–10 дней в одну сторону

## Лицензия

MIT


## 🐳 Docker Deployment

Запуск с Docker Compose:

   ```bash
   docker-compose up -d
   ```

   Для обновления новой версиии image:

   ```bash
   docker-compose pull
   docker-compose down
   docker-compose up -d
   ```
