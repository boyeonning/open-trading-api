"""국내주식 기관/외국인 수급 조회 — KIS API

모드:
  fetch_flow            : 오늘 가집계 순매수 상위 (빠름 ~2초, 장중만 유효)
  fetch_ssangkkuli_flow : 쌍끌이 — 외국인 + 기관 둘 다 오늘 순매수 종목
  fetch_consecutive_flow: N일 연속 순매수 종목 (중간 ~15-30초)
  fetch_pullback_flow   : 눌림목 — 수급 들어오다 단기 조정 중인 종목 (느림 ~30-60초)
"""
import sys
import os
import logging
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

_DIR      = os.path.dirname(os.path.abspath(__file__))
_EXAMPLES = os.path.dirname(_DIR)
sys.path.insert(0, _EXAMPLES)

import kis_auth as ka

logger = logging.getLogger(__name__)

# ── 상수 ──────────────────────────────────────────────────
MARKET_CODES = {
    '전체':   '0000',
    '코스피': '0001',
    '코스닥': '1001',
}
INVESTOR_CODES = {
    '전체':   '0',
    '외국인': '1',
    '기관':   '2',
}

# 눌림목 기준
PULLBACK_MIN_PCT = -15.0   # 5일 고점 대비 최대 하락폭
PULLBACK_MAX_PCT =  -1.0   # 5일 고점 대비 최소 하락폭
PULLBACK_MIN_CONSEC_DAYS = 3  # 연속 수급 최소 일수

# ── KIS API 직접 호출 ──────────────────────────────────────
def _fetch_today_top(market: str, investor: str, top_n: int) -> list[dict]:
    """FHPTJ04400000 — 오늘 가집계 순매수 상위 종목"""
    ka.auth()

    params = {
        "FID_COND_MRKT_DIV_CODE": "V",
        "FID_COND_SCR_DIV_CODE":  "16449",
        "FID_INPUT_ISCD":         MARKET_CODES.get(market, '0000'),
        "FID_DIV_CLS_CODE":       "1",
        "FID_RANK_SORT_CLS_CODE": "0",
        "FID_ETC_CLS_CODE":       INVESTOR_CODES.get(investor, '0'),
    }
    res = ka._url_fetch("/uapi/domestic-stock/v1/quotations/foreign-institution-total",
                        "FHPTJ04400000", "", params)
    if not res.isOK():
        return []

    def _int(v):
        try:
            return int(v or '0')
        except (ValueError, TypeError):
            return 0

    rows = res.getBody().output or []
    result = []
    for row in rows[:top_n]:
        try:
            rate = float(row.get('prdy_ctrt', '0') or '0')
        except ValueError:
            rate = 0.0
        result.append({
            '종목명':       row.get('hts_kor_isnm', '').strip(),
            '코드':         row.get('mksc_shrn_iscd', ''),
            '현재가':       _int(row.get('stck_prpr', '0')),
            '등락률':       rate,
            '외국인순매수': _int(row.get('frgn_ntby_tr_pbmn', '0')),  # 백만원
            '기관순매수':   _int(row.get('orgn_ntby_tr_pbmn', '0')),  # 백만원
        })
    return result


def _fetch_daily_flow(stock_code: str, today_str: str) -> list[dict]:
    """FHPTJ04160001 — 종목 일별 투자자 매매동향 output2 (일별 수급)"""
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD":         stock_code,
        "FID_INPUT_DATE_1":       today_str,
        "FID_ORG_ADJ_PRC":        "",
        "FID_ETC_CLS_CODE":       "",
    }
    res = ka._url_fetch("/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily",
                        "FHPTJ04160001", "", params)
    if not res.isOK():
        return []

    rows = getattr(res.getBody(), 'output2', None) or []
    result = []
    for row in rows:
        def _int(v):
            try:
                return int(v or '0')
            except (ValueError, TypeError):
                return 0
        result.append({
            '날짜':         row.get('stck_bsop_date', ''),
            '외국인순매수': _int(row.get('frgn_ntby_qty', '0')),    # 주
            '기관순매수':   _int(row.get('orgn_ntby_qty', '0')),    # 주
            '외국인대금':   _int(row.get('frgn_ntby_tr_pbmn', '0')),
            '기관대금':     _int(row.get('orgn_ntby_tr_pbmn', '0')),
        })
    return result


def _fetch_daily_price(stock_code: str) -> list[dict]:
    """FHKST01010400 — 일별 시가/고가/저가/종가 (최근 30거래일, 최신순)"""
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD":         stock_code,
        "FID_PERIOD_DIV_CODE":    "D",
        "FID_ORG_ADJ_PRC":        "1",
    }
    res = ka._url_fetch("/uapi/domestic-stock/v1/quotations/inquire-daily-price",
                        "FHKST01010400", "", params)
    if not res.isOK():
        return []

    rows = res.getBody().output or []
    result = []
    for row in rows:
        def _int(v):
            try:
                return int(v or '0')
            except (ValueError, TypeError):
                return 0
        result.append({
            '날짜': row.get('stck_bsop_date', ''),
            '종가': _int(row.get('stck_clpr', '0')),
            '고가': _int(row.get('stck_hgpr', '0')),
            '저가': _int(row.get('stck_lwpr', '0')),
        })
    return result


# ── 조건 판별 ──────────────────────────────────────────────
def _check_consecutive(daily: list[dict], days: int, investor: str) -> Optional[dict]:
    """최근 N일 연속 순매수 여부"""
    if len(daily) < days:
        return None

    recent = daily[:days]
    frgn_all = all(d['외국인순매수'] > 0 for d in recent)
    orgn_all  = all(d['기관순매수']   > 0 for d in recent)

    if investor == '외국인' and not frgn_all:
        return None
    if investor == '기관' and not orgn_all:
        return None
    if investor == '전체' and not (frgn_all or orgn_all):
        return None

    return {
        '연속_외국인':    frgn_all,
        '연속_기관':      orgn_all,
        '외국인누적수량': sum(d['외국인순매수'] for d in recent),
        '기관누적수량':   sum(d['기관순매수']   for d in recent),
        '기준일수':       days,
    }


def _check_pullback(price_data: list[dict]) -> Optional[dict]:
    """
    눌림목 조건:
      - 최근 5일 고점 대비 -3% ~ -10% (조정 중)
      - 현재가 > 20일선 (상승 추세 유지)
    """
    if len(price_data) < 20:
        return None

    current     = price_data[0]['종가']
    high_5d     = max(d['고가'] for d in price_data[:5])
    ma20        = sum(d['종가'] for d in price_data[:20]) / 20

    if current <= 0 or high_5d <= 0:
        return None

    pullback_pct = (current - high_5d) / high_5d * 100  # 음수=하락

    # 눌림 범위 체크
    if not (PULLBACK_MIN_PCT <= pullback_pct <= PULLBACK_MAX_PCT):
        return None

    ma20_gap_pct = (current - ma20) / ma20 * 100

    return {
        '눌림률':       pullback_pct,
        '5일고점':      high_5d,
        'MA20':         round(ma20),
        'MA20괴리율':   ma20_gap_pct,
    }


# ── 공개 인터페이스 ────────────────────────────────────────
def fetch_flow(market: str = '전체', investor: str = '전체', top_n: int = 15) -> list[dict]:
    """오늘 가집계 순매수 상위 (빠름)"""
    return _fetch_today_top(market, investor, top_n)


def fetch_ssangkkuli_flow(market: str = '전체', top_n: int = 15) -> list[dict]:
    """쌍끌이 — 외국인 + 기관 둘 다 오늘 순매수인 종목"""
    rows = _fetch_today_top(market, '전체', 50)
    result = [r for r in rows if r['외국인순매수'] > 0 and r['기관순매수'] > 0]
    # 외국인+기관 합산 대금 기준 정렬
    result.sort(key=lambda r: r['외국인순매수'] + r['기관순매수'], reverse=True)
    return result[:top_n]


def fetch_consecutive_flow(
    days: int = 5,
    market: str = '전체',
    investor: str = '전체',
    top_n: int = 30,
) -> list[dict]:
    """N일 연속 순매수 종목 필터링"""
    candidates = _fetch_today_top(market, investor, top_n)
    if not candidates:
        return []

    today_str = datetime.today().strftime('%Y%m%d')

    def _worker(stock: dict) -> Optional[dict]:
        code = stock['코드']
        if not code:
            return None
        try:
            time.sleep(0.1)
            daily = _fetch_daily_flow(code, today_str)
            consec = _check_consecutive(daily, days, investor)
            if consec:
                return {**stock, **consec}
        except Exception as e:
            logger.warning(f"{code} 연속수급 조회 실패: {e}")
        return None

    results = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(_worker, s): s for s in candidates}
        for future in as_completed(futures):
            r = future.result()
            if r:
                results.append(r)

    results.sort(
        key=lambda r: r.get('외국인누적수량', 0) + r.get('기관누적수량', 0),
        reverse=True
    )
    return results


def fetch_pullback_flow(market: str = '전체', top_n: int = 30) -> list[dict]:
    """
    눌림목 스크리너:
      수급(기관 or 외국인 5일+ 연속) + 눌림(5일 고점 -3~-10%) + 추세(MA20 위)
    """
    candidates = _fetch_today_top(market, '전체', top_n)
    if not candidates:
        return []

    today_str = datetime.today().strftime('%Y%m%d')

    def _worker(stock: dict) -> Optional[dict]:
        code = stock['코드']
        if not code:
            return None
        try:
            time.sleep(0.1)
            # ① 수급 체크
            daily_flow = _fetch_daily_flow(code, today_str)
            consec = _check_consecutive(daily_flow, PULLBACK_MIN_CONSEC_DAYS, '전체')
            if not consec:
                return None

            time.sleep(0.1)
            # ② 가격/눌림 체크
            price_data = _fetch_daily_price(code)
            pullback = _check_pullback(price_data)
            if not pullback:
                return None

            return {**stock, **consec, **pullback}
        except Exception as e:
            logger.warning(f"{code} 눌림목 조회 실패: {e}")
        return None

    results = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(_worker, s): s for s in candidates}
        for future in as_completed(futures):
            r = future.result()
            if r:
                results.append(r)

    # 눌림률 작은 순 (덜 빠진 것 = 더 안전한 눌림)
    results.sort(key=lambda r: r['눌림률'], reverse=True)
    return results


# ── 포맷 ──────────────────────────────────────────────────
def _rate_str(rate: float) -> str:
    emoji = '🔺' if rate > 0 else ('🔻' if rate < 0 else '➖')
    sign  = '+' if rate >= 0 else ''
    return f'{emoji}{sign}{rate:.2f}%'


_KOSPI_CODES: set = set()
_KOSDAQ_CODES: set = set()

def _load_market_codes():
    """코스피/코스닥 종목코드 마스터 로드 (최초 1회)"""
    global _KOSPI_CODES, _KOSDAQ_CODES
    if _KOSPI_CODES or _KOSDAQ_CODES:
        return

    _STOCKS_DIR = os.path.join(os.path.dirname(_EXAMPLES), 'stocks_info')
    for fname, target in [('kospi_code_part1.tmp', _KOSPI_CODES),
                           ('kosdaq_code_part1.tmp', _KOSDAQ_CODES)]:
        path = os.path.join(_STOCKS_DIR, fname)
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding='utf-8') as f:
                for line in f:
                    code = line.split(',')[0].strip()
                    if code:
                        target.add(code)
        except Exception as e:
            logger.warning(f'{fname} 로드 실패: {e}')


def _market_tag(code: str) -> str:
    """종목코드 → [코스피] / [코스닥] 태그"""
    _load_market_codes()
    if code in _KOSPI_CODES:
        return '[코스피]'
    if code in _KOSDAQ_CODES:
        return '[코스닥]'
    return ''


def format_today_message(rows: list[dict], market: str, investor: str) -> str:
    inv_label = {'전체': '외국인+기관', '외국인': '외국인', '기관': '기관'}
    if not rows:
        return (
            '❌ 수급 데이터 없음\n'
            '<i>가집계는 장중에만 갱신됩니다\n'
            '(외국인 09:30/11:20/13:20/14:30\n'
            ' 기관    10:00/11:20/13:20/14:30)</i>'
        )
    lines = [
        f'📊 <b>{market} {inv_label.get(investor, investor)} 순매수 상위</b>',
        '<i>오늘 가집계 기준</i>',
    ]
    for i, r in enumerate(rows, 1):
        def _fmt(v: int) -> str:
            aw = v / 100
            return f'{"+"}' f'{aw:,.0f}억' if v >= 0 else f'{aw:,.0f}억'
        lines.append(
            f'\n{i}. <b>{r["종목명"]}</b> <code>{r["코드"]}</code> <i>{_market_tag(r["코드"])}</i>\n'
            f'   {r["현재가"]:,}원 {_rate_str(r["등락률"])}\n'
            f'   외국인 {_fmt(r["외국인순매수"])}  기관 {_fmt(r["기관순매수"])}'
        )
    return '\n'.join(lines)


def format_ssangkkuli_message(rows: list[dict], market: str) -> str:
    if not rows:
        return f'📊 <b>{market} 쌍끌이</b>\n\n해당 종목 없음'
    lines = [
        f'📊 <b>{market} 쌍끌이 (외국인+기관 동시 순매수)</b>',
        '<i>오늘 가집계 기준</i>',
    ]
    for i, r in enumerate(rows, 1):
        def _fmt(v):
            aw = v / 100
            return f'+{aw:,.0f}억' if v >= 0 else f'{aw:,.0f}억'
        lines.append(
            f'\n{i}. <b>{r["종목명"]}</b> <code>{r["코드"]}</code> <i>{_market_tag(r["코드"])}</i>\n'
            f'   {r["현재가"]:,}원 {_rate_str(r["등락률"])}\n'
            f'   외국인 {_fmt(r["외국인순매수"])}  기관 {_fmt(r["기관순매수"])}'
        )
    return '\n'.join(lines)


def format_consecutive_message(rows: list[dict], days: int, market: str, investor: str) -> str:
    inv_label = {'전체': '외국인+기관', '외국인': '외국인', '기관': '기관'}
    if not rows:
        return f'📊 <b>{market} {days}일 연속 순매수</b>\n\n해당 종목 없음'
    lines = [
        f'📊 <b>{market} {inv_label.get(investor, investor)} {days}일 연속 순매수</b>',
        f'<i>후보 30종목 기준 · {len(rows)}개 해당</i>',
    ]
    for i, r in enumerate(rows, 1):
        tags = []
        if r.get('연속_외국인'):
            tags.append('외국인✅')
        if r.get('연속_기관'):
            tags.append('기관✅')

        def _qty(v):
            return f'+{v // 1000:,}천주' if v >= 0 else f'{v // 1000:,}천주'

        lines.append(
            f'\n{i}. <b>{r["종목명"]}</b> <code>{r["코드"]}</code> <i>{_market_tag(r["코드"])}</i>\n'
            f'   {r["현재가"]:,}원 {_rate_str(r["등락률"])}\n'
            f'   {"  ".join(tags)}\n'
            f'   외국인 {_qty(r["외국인누적수량"])}  기관 {_qty(r["기관누적수량"])}  <i>({days}일 합계)</i>'
        )
    return '\n'.join(lines)


def format_pullback_message(rows: list[dict], market: str) -> str:
    if not rows:
        return (
            f'📊 <b>{market} 눌림목 수급 종목</b>\n\n'
            '해당 종목 없음\n'
            f'<i>조건: 3일 연속 수급 + 5일고점 대비 -1~-15% 조정</i>'
        )
    lines = [
        f'📊 <b>{market} 눌림목 수급 종목</b>',
        f'<i>3일 연속수급 + 5일고점 -{abs(PULLBACK_MAX_PCT):.0f}~{abs(PULLBACK_MIN_PCT):.0f}% 조정 · {len(rows)}개</i>',
    ]
    for i, r in enumerate(rows, 1):
        tags = []
        if r.get('연속_외국인'):
            tags.append('외국인✅')
        if r.get('연속_기관'):
            tags.append('기관✅')

        pullback = r['눌림률']
        ma20_gap = r['MA20괴리율']

        lines.append(
            f'\n{i}. <b>{r["종목명"]}</b> <code>{r["코드"]}</code> <i>{_market_tag(r["코드"])}</i>\n'
            f'   {r["현재가"]:,}원 {_rate_str(r["등락률"])}\n'
            f'   {"  ".join(tags)}\n'
            f'   5일고점 대비 <b>{pullback:.1f}%</b>  MA20 대비 +{ma20_gap:.1f}%\n'
            f'   MA20 {r["MA20"]:,}원  5일고점 {r["5일고점"]:,}원'
        )
    return '\n'.join(lines)
