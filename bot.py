#!/usr/bin/env python3
# file: bot.py

import logging
import re
from datetime import date, timedelta

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.request import HTTPXRequest  # для python-telegram-bot ≥20

# Токен вашего бота Telegram
TELEGRAM_TOKEN = 'ВАШ_TELEGRAM_TOKEN'

# Импортируем функции из скрипта поиска
from search_flights_text import parse_query, get_place, search_flights

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Я помогу найти авиабилеты.\n\n"
        "Отправь запрос в формате:\n"
        "`ГородA ГородB с 10 по 15 мая`\n"
        "или\n"
        "`ГородA ГородB на 5–10 дней`\n"
        "Добавь «в одну сторону», если нужен только туда.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Пример запроса:\n"
        "`Москва Питер с 12 по 18 июня`\n"
        "или\n"
        "`Париж Лондон на 3–5 дней в одну сторону`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_text = update.message.text

    # проверяем, нужна ли «в одну сторону»
    oneway = bool(re.search(r'\bв\s+одну\s+сторону\b', user_text, flags=re.IGNORECASE))
    clean_text = re.sub(r'\bв\s+одну\s+сторону\b', '', user_text, flags=re.IGNORECASE).strip()

    try:
        params = parse_query(clean_text)
        params['oneway'] = oneway

        orig = get_place(params['origin_city'])
        dstn = get_place(params['destination_city'])
        params.update({
            'ori':    orig['code'].upper(),
            'dst':    dstn['code'].upper(),
            'market': orig['country_code'].lower()
        })

        flights = search_flights(params)
        if params.get('direct') and not flights:
            params['direct'] = False
            flights = search_flights(params)

        if not flights:
            await update.message.reply_text("😞 Извините, рейсы не найдены.")
            return

        # даты для заголовка
        depart_date = params.get('depart_date')
        return_date = params.get('return_date') or (
            (date.fromisoformat(depart_date) + timedelta(days=params.get('length', 0))).isoformat()
        )

        # формируем шапку
        header = (
            "=== 🛫 Параметры поиска ===\n"
            f"📍 Откуда: {params['origin_city']} ({params['ori']})\n"
            f"📍 Куда: {params['destination_city']} ({params['dst']})\n"
            f"✈️ Тип поездки: {'Туда' if params['oneway'] else 'Туда и обратно'}\n"
            f"📅 Даты: {depart_date} → {return_date}\n"
            f"🛂 Только прямые: {'Да' if params.get('direct') else 'Нет'}\n"
            "========================\n\n"
            f"Найдено {len(flights)} вариантов (по цене).\n"
            "Ссылки выводятся только для первых 20 вариантов.\n\n"
        )

        # убрали &marker=14042 из ссылки
        if oneway:
            general_url = (
                f"https://www.aviasales.ru/search/{params['ori']}"
                f"{depart_date[8:]}{depart_date[5:7]}"
                f"{params['dst']}1"
                f"?filter_baggage=false"
                f"&filter_stops={'false' if params['direct'] else 'true'}"
            )
        else:
            general_url = (
                f"https://www.aviasales.ru/search/{params['ori']}"
                f"{depart_date[8:]}{depart_date[5:7]}"
                f"{params['dst']}{return_date[8:]}{return_date[5:7]}1"
                f"?filter_baggage=false"
                f"&filter_stops={'false' if params['direct'] else 'true'}"
            )

        header += f"🔗 Поиск всех вариантов: {general_url}\n\n"

        # составляем список без повторяющихся ссылок
        lines = []
        for i, f in enumerate(flights[:20], start=1):
            if oneway:
                line = f"{i}. {f['depart']} • {f['price']}₽ • пересадок: {f['stops']}"
            else:
                ret = f.get('return') or (
                    (date.fromisoformat(f['depart']) + timedelta(days=f.get('length', 0))).isoformat()
                )
                extra = f" • {f['length']} дн." if 'length' in f else ""
                line = f"{i}. {f['depart']} → {ret}{extra} • {f['price']}₽ • пересадок: {f['stops']}"
            lines.append(line)

        await update.message.reply_text(header + "\n".join(lines))

    except ValueError as e:
        await update.message.reply_text(f"⚠️ Ошибка разбора запроса: {e}")
    except Exception:
        logger.exception("Ошибка при поиске рейсов")
        await update.message.reply_text("❗ Произошла ошибка при поиске. Попробуйте позже.")


def main() -> None:
    request = HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=10.0,
        read_timeout=20.0,
        write_timeout=20.0,
    )

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .request(request)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_query))

    app.run_polling()


if __name__ == "__main__":
    main()
