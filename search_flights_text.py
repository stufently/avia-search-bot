#!/usr/bin/env python3
# file: search_flights_text.py

import os
import re
import sys
import requests
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from difflib import SequenceMatcher, get_close_matches

# ====== Явные «город‑алиасы»: ввод пользователя → правильное название для API
CITY_ALIASES = {
    "Питер": "Санкт-Петербург",
    # при желании можно добавить:
    # "СПб": "Санкт-Петербург",
    # "Мск": "Москва",
}

# ====== Настройки API v3 ======
API_TOKEN              =  os.getenv("API_TOKEN")
PRICES_FOR_DATES_URL   = 'https://api.travelpayouts.com/aviasales/v3/prices_for_dates'
GROUPED_PRICES_URL     = 'https://api.travelpayouts.com/aviasales/v3/grouped_prices'
AUTOCOMPLETE_URL       = 'https://autocomplete.travelpayouts.com/places2'

# ====== Месяцы ======
MONTHS = {
    'январь': 1, 'февраль': 2, 'март': 3, 'апрель': 4,
    'май': 5, 'июнь': 6, 'июль': 7, 'август': 8,
    'сентябрь': 9, 'октябрь': 10, 'ноябрь': 11, 'декабрь': 12
}
MONTH_ALIASES = {
    'января': 'январь', 'февраля': 'февраль', 'марта': 'март', 'апреля': 'апрель',
    'мая': 'май', 'июня': 'июнь', 'июля': 'июль', 'августа': 'август',
    'сентября': 'сентябрь', 'октября': 'октябрь', 'ноября': 'ноябрь', 'декабря': 'декабрь'
}
MONTH_MAP = {**MONTHS}
for form, base in MONTH_ALIASES.items():
    MONTH_MAP[form] = MONTHS[base]

# ====== Шаблоны разбора ======
CITY = r'(?P<from>[\w\-]+)\s+(?P<to>[\w\-]+)'
RANGE_PATTERN = re.compile(
    fr'{CITY}\s+с\s+(?P<start>\d{{1,2}})\s+по\s+(?P<end>\d{{1,2}})\s+(?P<month>\w+)(?:\s+(?P<direct>прям\w*))?',
    flags=re.IGNORECASE
)
NO_MONTH_RANGE = re.compile(
    fr'{CITY}\s+с\s+(?P<start>\d{{1,2}})\s+по\s+(?P<end>\d{{1,2}})(?:\s+(?P<direct>прям\w*))?',
    flags=re.IGNORECASE
)
DURATION_PATTERN = re.compile(
    fr'{CITY}\s+на\s+(?:(?P<month>\w+)\s+)?(?P<min>\d+)[–-](?P<max>\d+)\s*дн\w*(?:\s+(?P<direct>прям\w*))?',
    flags=re.IGNORECASE
)


def normalize_month(name: str) -> int:
    key = name.lower()
    if key in MONTH_MAP:
        return MONTH_MAP[key]
    candidates = get_close_matches(key, MONTH_MAP.keys(), n=1, cutoff=0.4)
    if candidates:
        corr = candidates[0]
        base = MONTH_ALIASES.get(corr, corr)
        print(f"[!] Исправили месяц «{name}» → «{base}»")
        return MONTHS[base]
    raise ValueError(f"Не удалось распознать месяц «{name}»")


def best_suggestion(term: str, suggestions: list) -> dict:
    term_l = term.lower()
    best, best_ratio = suggestions[0], 0.0
    for s in suggestions:
        plain = s.get('name', '').split(',')[0].lower()
        r = SequenceMatcher(None, term_l, plain).ratio()
        if r > best_ratio:
            best, best_ratio = s, r
    fixed = best['name'].split(',')[0]
    if fixed.lower() != term_l:
        print(f"[!] Исправили город «{term}» → «{fixed}»")
    return best


def get_place(city: str) -> dict:
    city_search = CITY_ALIASES.get(city.capitalize(), city)
    resp = requests.get(
        AUTOCOMPLETE_URL,
        params={'term': city_search, 'locale': 'ru', 'types[]': 'city'},
        headers={'Accept-Encoding': 'gzip, deflate'}
    )
    resp.raise_for_status()
    data = resp.json()
    if not data:
        print(f"Ошибка: для города «{city_search}» не найден ни один аэропорт.")
        sys.exit(1)
    return best_suggestion(city_search, data)


def parse_query(msg: str) -> dict:
    msg = msg.replace('→', ' ').replace('\u00A0', ' ')
    msg = msg.replace('\u2011', '-')
    msg = re.sub(r'[—–]', '-', msg)
    msg = re.sub(r'^([\w\-]+)\s*-\s*([\w\-]+)', r'\1 \2', msg)
    msg = re.sub(r'\s+', ' ', msg).strip()

    today = date.today()

    if m := RANGE_PATTERN.search(msg):
        frm, to = m.group('from'), m.group('to')
        s_day, e_day = int(m.group('start')), int(m.group('end'))
        month = normalize_month(m.group('month'))
        year = today.year + (1 if month < today.month else 0)
        return {
            'origin_city':      frm.capitalize(),
            'destination_city': to.capitalize(),
            'depart_date':      date(year, month, s_day).isoformat(),
            'return_date':      date(year, month, e_day).isoformat(),
            'direct':           bool(m.group('direct'))
        }

    if m := NO_MONTH_RANGE.search(msg):
        frm, to = m.group('from'), m.group('to')
        s_day, e_day = int(m.group('start')), int(m.group('end'))
        year, month = today.year, today.month
        return {
            'origin_city':      frm.capitalize(),
            'destination_city': to.capitalize(),
            'depart_date':      date(year, month, s_day).isoformat(),
            'return_date':      date(year, month, e_day).isoformat(),
            'direct':           bool(m.group('direct'))
        }

    if m := DURATION_PATTERN.search(msg):
        frm, to = m.group('from'), m.group('to')
        mn, mx = int(m.group('min')), int(m.group('max'))
        if mn > mx:
            print(f"[!] Исправили длительности: {mn}–{mx} → {mx}–{mn}")
            mn, mx = mx, mn
        if m.group('month'):
            month = normalize_month(m.group('month'))
            year = today.year + (1 if month < today.month else 0)
        else:
            month, year = today.month, today.year
        return {
            'origin_city':      frm.capitalize(),
            'destination_city': to.capitalize(),
            'depart_month':     f"{year}-{month:02d}",
            'min_days':         mn,
            'max_days':         mx,
            'direct':           bool(m.group('direct'))
        }

    raise ValueError("неправильный формат")


def search_flights(params: dict) -> list:
    hdr = {'X-Access-Token': API_TOKEN, 'Accept-Encoding': 'gzip, deflate'}
    ori, dst, mkt = params['ori'], params['dst'], params['market']
    ow = 'true' if params.get('oneway') else 'false'
    dr = 'true' if params.get('direct') else 'false'
    out = []

    # 1) One‑way exact dates
    if params.get('oneway') and 'depart_date' in params and 'return_date' in params:
        st = date.fromisoformat(params['depart_date'])
        en = date.fromisoformat(params['return_date'])
        for i in range((en - st).days + 1):
            d = st + timedelta(days=i)
            p = {
                'origin':      ori, 'destination': dst,
                'departure_at':d.isoformat(),
                'currency':    'RUB', 'market': mkt,
                'one_way':     ow, 'direct': dr,
                'sorting':     'price', 'limit': 1000, 'page': 1
            }
            r = requests.get(PRICES_FOR_DATES_URL, params=p, headers=hdr)
            r.raise_for_status()
            for t in r.json().get('data', []):
                out.append({
                    'depart': t['departure_at'][:10],
                    'price':  t.get('price', 0),
                    'stops':  t.get('transfers', 0)
                })
        return sorted(out, key=lambda x: x['price'])

    # 2) One‑way single or month search
    if params.get('oneway'):
        if 'depart_date' in params:
            p = {
                'origin':      ori, 'destination': dst,
                'departure_at':params['depart_date'],
                'currency':    'RUB', 'market': mkt,
                'one_way':     ow, 'direct': dr,
                'sorting':     'price', 'limit': 1000, 'page': 1
            }
            r = requests.get(PRICES_FOR_DATES_URL, params=p, headers=hdr)
            r.raise_for_status()
            for t in r.json().get('data', []):
                out.append({
                    'depart': t['departure_at'][:10],
                    'price':  t.get('price', 0),
                    'stops':  t.get('transfers', 0)
                })
            return sorted(out, key=lambda x: x['price'])
        p = {
            'origin':      ori, 'destination': dst,
            'currency':    'RUB', 'market': mkt,
            'group_by':    'departure_at',
            'departure_at':params['depart_month'],
            'direct':      dr,
            'sorting':     'price', 'limit': 1000, 'page': 1
        }
        r = requests.get(GROUPED_PRICES_URL, params=p, headers=hdr)
        r.raise_for_status()
        for dep, info in r.json().get('data', {}).items():
            out.append({
                'depart': dep,
                'price':  info.get('price', 0),
                'stops':  info.get('transfers', 0)
            })
        return sorted(out, key=lambda x: x['price'])

    # 3) Round‑trip exact dates
    if 'depart_date' in params and 'return_date' in params:
        p = {
            'origin':      ori, 'destination': dst,
            'departure_at':params['depart_date'],
            'return_at':   params['return_date'],
            'currency':    'RUB', 'market': mkt,
            'one_way':     'false', 'direct': dr,
            'sorting':     'price', 'limit': 1000, 'page': 1
        }
        r = requests.get(PRICES_FOR_DATES_URL, params=p, headers=hdr)
        r.raise_for_status()
        for t in r.json().get('data', []):
            dep, ret = t['departure_at'][:10], t['return_at'][:10]
            out.append({
                'depart': dep,
                'return': ret,
                'price':  t.get('price', 0),
                'stops':  t.get('transfers', 0),
                'length': (date.fromisoformat(ret) - date.fromisoformat(dep)).days
            })
        return sorted(out, key=lambda x: x['price'])

    # 4) Round‑trip duration
    for length in range(params['min_days'], params['max_days'] + 1):
        p = {
            'origin':        ori, 'destination': dst,
            'currency':      'RUB', 'market': mkt,
            'group_by':      'departure_at',
            'departure_at':  params['depart_month'],
            'trip_duration': length,
            'direct':        dr,
            'sorting':       'price', 'limit': 1000, 'page': 1
        }
        r = requests.get(GROUPED_PRICES_URL, params=p, headers=hdr)
        r.raise_for_status()
        for dep, info in r.json().get('data', {}).items():
            out.append({
                'depart': dep,
                'return': info.get('return_at', '')[:10],
                'length': length,
                'price':  info.get('price', 0),
                'stops':  info.get('transfers', 0)
            })
    return sorted(out, key=lambda x: x['price'])
