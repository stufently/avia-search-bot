#!/usr/bin/env python3
# file: search_flights_text.py

import re
import sys
import calendar
import logging
import requests
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from difflib import SequenceMatcher, get_close_matches

logger = logging.getLogger(__name__)

# ====== Явные «город‑алиасы»: ввод пользователя → правильное название для API
CITY_ALIASES = {
    "Питер":      "Санкт-Петербург",
    "СПб":        "Санкт-Петербург",
    "Мск":        "Москва",
    "Новосибрск": "Новосибирск",
    "Нюренги":    "Нерюнгри",
}

# ====== Настройки API v3 ======
API_TOKEN            = os.getenv("API_TOKEN")
PRICES_FOR_DATES_URL = 'https://api.travelpayouts.com/aviasales/v3/prices_for_dates'
GROUPED_PRICES_URL   = 'https://api.travelpayouts.com/aviasales/v3/grouped_prices'
AUTOCOMPLETE_URL     = 'https://autocomplete.travelpayouts.com/places2'

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

# 1) «с 11 по 16 мая»
RANGE_PATTERN = re.compile(
    fr'{CITY}\s+с\s+(?P<start>\d{{1,2}})\s+по\s+(?P<end>\d{{1,2}})\s+'
    r'(?P<month>\w+)(?:\s+(?P<direct>прям\w*))?',
    flags=re.IGNORECASE
)
# 2) «с 11 по 16» (текущий месяц)
NO_MONTH_RANGE = re.compile(
    fr'{CITY}\s+с\s+(?P<start>\d{{1,2}})\s+по\s+(?P<end>\d{{1,2}})'
    r'(?:\s+(?P<direct>прям\w*))?',
    flags=re.IGNORECASE
)
# 3) «на 3–5 дней»
DURATION_PATTERN = re.compile(
    fr'{CITY}\s+на\s+(?:(?P<month>\w+)\s+)?'
    r'(?P<min>\d+)[–-](?P<max>\d+)\s*дн\w*'
    r'(?:\s+(?P<direct>прям\w*))?',
    flags=re.IGNORECASE
)
# 4) «с 11 мая по 16 мая»
FULL_MONTH_RANGE = re.compile(
    fr'{CITY}\s+с\s+(?P<start>\d{{1,2}})\s+(?P<sm>\w+)\s+по\s+'
    fr'(?P<end>\d{{1,2}})\s+(?P<em>\w+)(?:\s+(?P<direct>прям\w*))?',
    flags=re.IGNORECASE
)

class AirportNotFoundError(Exception):
    """Не найден аэропорт для запрошенного города."""
    pass

def normalize_month(name: str) -> int:
    key = name.lower()
    if key in MONTH_MAP:
        return MONTH_MAP[key]
    candidates = get_close_matches(key, MONTH_MAP.keys(), n=1, cutoff=0.4)
    if candidates:
        corr = candidates[0]
        base = MONTH_ALIASES.get(corr, corr)
        logger.debug("Исправили месяц «%s» → «%s»", name, base)
        return MONTHS[base]
    raise ValueError(f"Не удалось распознать месяц «{name}»")

def best_suggestion(term: str, suggestions: list) -> dict:
    term_l = term.lower()
    best, best_ratio = suggestions[0], 0.0
    for s in suggestions:
        plain = s.get('name','').split(',')[0].lower()
        r = SequenceMatcher(None, term_l, plain).ratio()
        if r > best_ratio:
            best, best_ratio = s, r
    fixed = best['name'].split(',')[0]
    if fixed.lower() != term_l:
        logger.debug("Исправили город «%s» → «%s»", term, fixed)
    return best

def get_place(city: str) -> dict:
    city_search = CITY_ALIASES.get(city.capitalize(), city)
    resp = requests.get(
        AUTOCOMPLETE_URL,
        params={'term': city_search, 'locale': 'ru', 'types[]': 'city'},
        headers={'Accept-Encoding':'gzip, deflate'}
    )
    resp.raise_for_status()
    data = resp.json()
    if not data:
        raise AirportNotFoundError(f"Для города «{city_search}» не найден ни один аэропорт.")
    return best_suggestion(city_search, data)

def parse_query(msg: str) -> dict:
    msg = msg.replace('→',' ').replace('\u00A0',' ')
    msg = msg.replace('\u2011','-')
    msg = re.sub(r'[—–]','-', msg)
    msg = re.sub(r'^([\w\-]+)\s*-\s*([\w\-]+)', r'\1 \2', msg)
    msg = re.sub(r'\s+',' ', msg).strip()

    today = date.today()

    # «с 11 мая по 16 мая»
    if m := FULL_MONTH_RANGE.search(msg):
        frm,to = m.group('from'), m.group('to')
        s_day,e_day = int(m.group('start')), int(m.group('end'))
        sm,em = normalize_month(m.group('sm')), normalize_month(m.group('em'))
        s_year = today.year + (1 if (sm<today.month or (sm==today.month and s_day<today.day)) else 0)
        e_year = s_year if em>=sm else s_year+1
        return {
            'origin_city':      frm.capitalize(),
            'destination_city': to.capitalize(),
            'depart_date':      date(s_year, sm, s_day).isoformat(),
            'return_date':      date(e_year, em, e_day).isoformat(),
            'direct':           bool(m.group('direct'))
        }

    # «с 11 по 16 мая»
    if m := RANGE_PATTERN.search(msg):
        frm,to = m.group('from'), m.group('to')
        s_day,e_day = int(m.group('start')), int(m.group('end'))
        mnum = normalize_month(m.group('month'))
        year = today.year + (1 if mnum<today.month else 0)
        return {
            'origin_city':      frm.capitalize(),
            'destination_city': to.capitalize(),
            'depart_date':      date(year, mnum, s_day).isoformat(),
            'return_date':      date(year, mnum, e_day).isoformat(),
            'direct':           bool(m.group('direct'))
        }

    # «с 11 по 16» (текущий месяц)
    if m := NO_MONTH_RANGE.search(msg):
        frm,to = m.group('from'), m.group('to')
        s_day,e_day = int(m.group('start')), int(m.group('end'))
        year, mnum = today.year, today.month
        return {
            'origin_city':      frm.capitalize(),
            'destination_city': to.capitalize(),
            'depart_date':      date(year, mnum, s_day).isoformat(),
            'return_date':      date(year, mnum, e_day).isoformat(),
            'direct':           bool(m.group('direct'))
        }

    # «на 3–5 дней»
    if m := DURATION_PATTERN.search(msg):
        frm,to = m.group('from'), m.group('to')
        mn,mx = int(m.group('min')), int(m.group('max'))
        if mn>mx:
            mn, mx = mx, mn
        if m.group('month'):
            mnum = normalize_month(m.group('month'))
            year = today.year + (1 if mnum<today.month else 0)
        else:
            mnum, year = today.month, today.year
        return {
            'origin_city':      frm.capitalize(),
            'destination_city': to.capitalize(),
            'depart_month':     f"{year}-{mnum:02d}",
            'min_days':         mn,
            'max_days':         mx,
            'direct':           bool(m.group('direct'))
        }

    raise ValueError("неправильный формат")

def search_flights(params: dict) -> list:
    hdr = {'X-Access-Token': API_TOKEN, 'Accept-Encoding':'gzip, deflate'}
    ori, dst, mkt = params['ori'], params['dst'], params['market']
    ow = 'true' if params.get('oneway') else 'false'
    dr = 'true' if params.get('direct') else 'false'
    out = []

    # 1) One‑way точные даты
    if params.get('oneway') and 'depart_date' in params and 'return_date' in params:
        st = date.fromisoformat(params['depart_date'])
        en = date.fromisoformat(params['return_date'])
        for i in range((en - st).days + 1):
            d = st + timedelta(days=i)
            p = {
                'origin': ori, 'destination': dst,
                'departure_at': d.isoformat(),
                'currency': 'RUB', 'market': mkt,
                'one_way': ow, 'direct': dr,
                'sorting': 'price', 'limit': 1000, 'page': 1
            }
            r = requests.get(PRICES_FOR_DATES_URL, params=p, headers=hdr)
            r.raise_for_status()
            data = r.json().get('data', [])
            logger.debug("One‑way exact (%s→%s): got %d items", d, params['return_date'], len(data))
            for t in data:
                out.append({
                    'depart': t['departure_at'][:10],
                    'price':  t.get('price', 0),
                    'stops':  t.get('transfers', 0)
                })
        return sorted(out, key=lambda x: x['price'])

    # 2) One‑way месяц/текущая дата
    if params.get('oneway'):
        key = 'depart_date' if 'depart_date' in params else 'depart_month'
        url = PRICES_FOR_DATES_URL if key=='depart_date' else GROUPED_PRICES_URL
        p = {
            'origin': ori, 'destination': dst,
            'currency': 'RUB', 'market': mkt,
            'one_way': ow, 'direct': dr,
            'sorting': 'price', 'limit': 1000, 'page': 1
        }
        p[key] = params[key]
        if key == 'depart_month':
            p['group_by'] = 'departure_at'
        r = requests.get(url, params=p, headers=hdr)
        r.raise_for_status()
        data = r.json().get('data', {})
        logger.debug("One‑way %s search: data keys=%s", key, list(data)[:5])
        if isinstance(data, dict):
            for dep, info in data.items():
                out.append({
                    'depart': dep,
                    'price':  info.get('price', 0),
                    'stops':  info.get('transfers', 0)
                })
        else:
            for t in data:
                out.append({
                    'depart': t['departure_at'][:10],
                    'price':  t.get('price', 0),
                    'stops':  t.get('transfers', 0)
                })
        return sorted(out, key=lambda x: x['price'])

    # 3) Round‑trip точные даты
    if 'depart_date' in params and 'return_date' in params:
        p = {
            'origin': ori, 'destination': dst,
            'departure_at': params['depart_date'],
            'return_at': params['return_date'],
            'currency': 'RUB', 'market': mkt,
            'one_way': 'false', 'direct': dr,
            'sorting': 'price', 'limit': 1000, 'page': 1
        }
        r = requests.get(PRICES_FOR_DATES_URL, params=p, headers=hdr)
        r.raise_for_status()
        data = r.json().get('data', [])
        logger.debug("Round‑trip exact: %s → %s: got %d items",
                     params['depart_date'], params['return_date'], len(data))
        for t in data:
            out.append({
                'depart': t['departure_at'][:10],
                'return': t['return_at'][:10],
                'price':  t.get('price', 0),
                'stops':  t.get('transfers', 0),
                'length': (date.fromisoformat(t['return_at'][:10])
                           - date.fromisoformat(t['departure_at'][:10])).days
            })
        return sorted(out, key=lambda x: x['price'])

    # 4) Round‑trip по длительности с fallback
    if 'depart_month' in params:
        year, month = map(int, params['depart_month'].split('-'))
        days_in_month = calendar.monthrange(year, month)[1]
        for length in range(params['min_days'], params['max_days'] + 1):
            # сначала grouped_prices
            pg = {
                'origin': ori, 'destination': dst,
                'currency': 'RUB', 'market': mkt,
                'group_by': 'departure_at',
                'departure_at': params['depart_month'],
                'trip_duration': length,
                'direct': dr,
                'sorting': 'price', 'limit': 1000, 'page': 1
            }
            rg = requests.get(GROUPED_PRICES_URL, params=pg, headers=hdr)
            rg.raise_for_status()
            dg = rg.json().get('data', {})
            if dg:
                logger.debug("Grouped duration %d дн.: %d keys", length, len(dg))
                for dep, info in dg.items():
                    out.append({
                        'depart': dep,
                        'return': info.get('return_at','')[:10],
                        'length': length,
                        'price':  info.get('price', 0),
                        'stops':  info.get('transfers', 0)
                    })
            else:
                logger.debug("Grouped empty for %d дн., fallback to exact dates", length)
                # пробуем каждый день в этом месяце
                for day in range(1, days_in_month + 1):
                    dep_date = date(year, month, day)
                    ret_date = dep_date + timedelta(days=length)
                    pe = {
                        'origin': ori, 'destination': dst,
                        'departure_at': dep_date.isoformat(),
                        'return_at': ret_date.isoformat(),
                        'currency': 'RUB', 'market': mkt,
                        'one_way': 'false', 'direct': dr,
                        'sorting': 'price', 'limit': 1000, 'page': 1
                    }
                    re_ = requests.get(PRICES_FOR_DATES_URL, params=pe, headers=hdr)
                    re_.raise_for_status()
                    de = re_.json().get('data', [])
                    logger.debug("Exact %s→%s: got %d", dep_date, ret_date, len(de))
                    for t in de:
                        out.append({
                            'depart': t['departure_at'][:10],
                            'return': t['return_at'][:10],
                            'price':  t.get('price', 0),
                            'stops':  t.get('transfers', 0),
                            'length': length
                        })
        return sorted(out, key=lambda x: x['price'])

    return sorted(out, key=lambda x: x.get('price', 0))
