# Этап сборки: устанавливаем базовые зависимости и пакеты Python
# Базовый образ прибит по digest — тег (даже точный, 3.14.8-slim) мутабелен.
FROM python:3.14.8-slim@sha256:c3e521df8b2b498a7a682e7e18676771cb80c6b75b8699af886b2d554ce40151 AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    gcc \
    build-essential \
    python3-dev \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt constraints.txt ./

# -c constraints.txt фиксирует и транзитивные зависимости.
# НЕ добавлять сюда отдельных `pip install <пакет>` без версии и без `-c`, и не
# ставить `-U`/`--upgrade` в обход этого набора: любая установка мимо слепка
# превращает каждую пересборку в апгрейд вслепую. Ровно так лёг прод бота
# платежей 15.08.2026 (`pip install -U openai` тянул свежий релиз).
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt -c constraints.txt

# Финальный этап: минимальный образ с необходимыми runtime библиотеками
FROM python:3.14.8-slim@sha256:c3e521df8b2b498a7a682e7e18676771cb80c6b75b8699af886b2d554ce40151

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Устанавливаем необходимые системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Копируем установленные библиотеки из этапа сборки
COPY --from=builder /install /usr/local

# Копируем код приложения
COPY . /app

# ГЕЙТ: несовместимость зависимостей обязана валить СБОРКУ, а не прод.
# 1) pip check — конфликты версий в установленном дереве;
# 2) verify_pins.py — установленное совпадает со слепком, а незапиненная
#    (в т.ч. новая транзитивная) зависимость валит сборку;
# 3) явный импорт ключевых библиотек (в т.ч. httpx — он приходит транзитивно
#    из python-telegram-bot и используется через telegram.request.HTTPXRequest);
# 4) импорт приложения плюс фактическое ПОСТРОЕНИЕ Application с фиктивным
#    токеном: импорт не поймает несовместимость сигнатур, а build_application()
#    ловит. Сеть не трогается — она начинается только в run_polling().
RUN python -m pip check \
    && python verify_pins.py requirements.txt constraints.txt \
    && python -c "import telegram, telegram.ext, telegram.request, httpx, requests, dateutil.relativedelta" \
    && python -c "import bot, search_flights_text; bot.build_application('123456:BUILD-GATE-FAKE-TOKEN')" \
    && echo "dependency gate: OK"

CMD ["python", "bot.py"]
