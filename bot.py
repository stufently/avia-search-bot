#!/usr/bin/env python3
# file: bot.py

import os
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
from telegram.request import HTTPXRequest

from search_flights_text import (
    parse_query,
    get_place,
    search_flights,
    AirportNotFoundError
)

# Токен вашего бота Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

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
    text = update.message.text
    oneway = bool(re.search(r'\bв\s+одну\s+сторону\b', text, flags=re.IGNORECASE))
    clean = re.sub(r'\bв\s+одну\s+сторону\b', '', text, flags=re.IGNORECASE).strip()

    try:
        params = parse_query(clean)
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

        # ─── определяем даты ─────────────────────────────────────────────
        if 'depart_date' in params:
            depart_date = params['depart_date']
        else:
            depart_date = flights[0]['depart']

        if 'return_date' in params:
            return_date = params['return_date']
        elif 'return' in flights[0]:
            return_date = flights[0]['return']
        elif 'length' in flights[0]:
            rd = date.fromisoformat(depart_date) + timedelta(days=flights[0]['length'])
            return_date = rd.isoformat()
        else:
            return_date = ''

        # ─── шапка ответа ────────────────────────────────────────────────
        header = (
            "=== 🛫 Параметры поиска ===\n"
            f"📍 Откуда: {params['origin_city']} ({params['ori']})\n"
            f"📍 Куда: {params['destination_city']} ({params['dst']})\n"
            f"✈️ Тип поездки: {'Туда' if oneway else 'Туда и обратно'}\n"
            f"📅 Даты: {depart_date} → {return_date}\n"
            f"🛂 Только прямые: {'Да' if params.get('direct') else 'Нет'}\n"
            "========================\n\n"
            f"Найдено {len(flights)} вариантов (по цене).\n"
            "Ссылки выводятся только для первых 20 вариантов.\n\n"
        )

        # общий URL
        if oneway:
            url = (
                f"https://www.aviasales.ru/search/{params['ori']}"
                f"{depart_date[8:]}{depart_date[5:7]}"
                f"{params['dst']}1?filter_baggage=false"
                f"&filter_stops={'false' if params['direct'] else 'true'}"
            )
        else:
            url = (
                f"https://www.aviasales.ru/search/{params['ori']}"
                f"{depart_date[8:]}{depart_date[5:7]}"
                f"{params['dst']}{return_date[8:]}{return_date[5:7]}1"
                f"?filter_baggage=false"
                f"&filter_stops={'false' if params['direct'] else 'true'}"
            )
        header += f"🔗 Поиск всех вариантов: {url}\n\n"

        # ─── список первых 20 ────────────────────────────────────────────
        lines = []
        for i, f in enumerate(flights[:20], start=1):
            if oneway:
                lines.append(f"{i}. {f['depart']} • {f['price']}₽ • пересадок: {f['stops']}")
            else:
                ret = f.get('return') or (date.fromisoformat(f['depart']) + timedelta(days=f['length'])).isoformat()
                extra = f" • {f['length']} дн." if 'length' in f else ""
                lines.append(f"{i}. {f['depart']} → {ret}{extra} • {f['price']}₽ • пересадок: {f['stops']}")

        await update.message.reply_text(header + "\n".join(lines))

    except ValueError as e:
        await update.message.reply_text(f"⚠️ Ошибка разбора запроса: {e}")
    except AirportNotFoundError as e:
        await update.message.reply_text(f"😞 {e}")
    except Exception:
        logger.exception("Ошибка при поиске рейсов")
        await update.message.reply_text("❗ Произошла ошибка при поиске. Попробуйте позже.")

def build_application(token: str | None = None):
    """Собирает Application с хендлерами, но НЕ запускает polling.

    Вынесено из main() ради гейта сборки: `import bot` проверяет только наличие
    символов, а несовместимость СИГНАТУР (аргументы HTTPXRequest, цепочка
    ApplicationBuilder) видна лишь при фактическом построении объекта. Сеть тут
    не трогается — она начинается в run_polling().
    """
    request = HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=10.0,
        read_timeout=20.0,
        write_timeout=20.0,
    )
    app = ApplicationBuilder().token(token or TELEGRAM_TOKEN).request(request).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_query))
    return app


def main() -> None:
    build_application().run_polling()

if __name__ == "__main__":
    main()
