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

# 양음양 기준
YANGUMYANG_MIN_RISE  =  5.0   # 전일 장대양봉 최소 등락률
YANGUMYANG_MAX_RISE  = 20.0   # 전일 장대양봉 최대 등락률 (초과 시 수익실현 물량 우려)
YANGUMYANG_VOL_RATIO =  0.6   # 오늘 거래량이 전일의 이 비율 이하여야 함
YANGUMYANG_MA5_GAP   = -5.0   # MA5 대비 최대 이탈폭 (이 이상 이탈 시 제외)
YANGUMYANG_MIN_TRADE = 50_000_000_000  # 전일 최소 거래대금 (50억) — 잡주 제외

# 동전주/소형주 제외 기준
MIN_PRICE        = 3_000      # 최소 주가 (원) — 3,000원 미만 제외

# ETF/ETN/인버스/레버리지 제외 키워드
_ETF_KEYWORDS = (
    'KODEX', 'TIGER', 'KBSTAR', 'ARIRANG', 'HANARO', 'KOSEF', 'SOL', 'ACE',
    'RISE', 'PLUS', 'SMART', 'TREX', 'WOORI', 'IBK',
    'ETF', 'ETN', '레버리지', '인버스', '선물', '스팩', 'SPAC',
)

def _is_etf(name: str) -> bool:
    """ETF/ETN/스팩 등 종목명으로 판별"""
    u = name.upper()
    return any(kw in u for kw in _ETF_KEYWORDS)


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
    """FHKST01010400 — 일별 시가/고가/저가/종가/거래량/등락률 (최근 30거래일, 최신순)"""
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
        def _float(v):
            try:
                return float(v or '0')
            except (ValueError, TypeError):
                return 0.0
        result.append({
            '날짜': row.get('stck_bsop_date', ''),
            '시가': _int(row.get('stck_oprc', '0')),
            '종가': _int(row.get('stck_clpr', '0')),
            '고가': _int(row.get('stck_hgpr', '0')),
            '저가': _int(row.get('stck_lwpr', '0')),
            '거래량': _int(row.get('acml_vol', '0')),
            '등락률': _float(row.get('prdy_ctrt', '0')),
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


def _check_yangumyang(price_data: list[dict]) -> Optional[dict]:
    """
    양음양 Pattern 1 조건 (핀업스탁 기법):
      전일: 등락률 +5~+20% 장대양봉 + 평균 대비 대량거래
      오늘: 음봉(종가<시가) + MA5 이탈 안함 + 거래량이 전일의 60% 이하
      현재가가 MA5 -5% 이내
    """
    # MA5 계산을 위해 최소 6일치 필요 (오늘 + 전일 포함 5일)
    if len(price_data) < 6:
        return None

    today     = price_data[0]
    yesterday = price_data[1]

    # MA5: 오늘 포함 최근 5거래일 종가 평균
    ma5 = sum(d['종가'] for d in price_data[:5]) / 5

    # ① 최소 주가 필터 (동전주 제외)
    if today['종가'] < MIN_PRICE:
        return None

    # ② 전일 거래대금 필터 (동전주 제외): 전일종가 × 전일거래량
    prev_trade_amount = yesterday['종가'] * yesterday['거래량']
    if prev_trade_amount < YANGUMYANG_MIN_TRADE:
        return None

    # ③ 전일 장대양봉: +5% ~ +20% + 양봉(종가>시가) + 몸통 50% 이상
    prev_rate = yesterday.get('등락률', 0.0)
    if not (YANGUMYANG_MIN_RISE <= prev_rate <= YANGUMYANG_MAX_RISE):
        return None
    if yesterday['종가'] <= yesterday['시가']:  # 음봉이면 제외
        return None
    prev_rng = yesterday['고가'] - yesterday['저가']
    prev_body = yesterday['종가'] - yesterday['시가']
    if prev_rng > 0 and prev_body / prev_rng < 0.5:  # 몸통이 작으면 제외
        return None

    # ④ 전일 대량거래: 직전 5일(price_data[1:6]) 평균 거래량 대비 1.5배 이상
    prev_5d_vols = [d['거래량'] for d in price_data[1:6]]
    avg_vol = sum(prev_5d_vols) / len(prev_5d_vols) if prev_5d_vols else 0
    if avg_vol > 0 and yesterday['거래량'] < avg_vol * 1.5:
        return None

    today_close = today['종가']
    today_open  = today['시가']

    if today_close <= 0 or today_open <= 0:
        return None

    # ⑤ 오늘 음봉: 종가 < 시가
    if today_close >= today_open:
        return None

    # ⑥ 오늘 거래량이 전일의 60% 이하 (핵심 조건)
    vol_ratio = today['거래량'] / yesterday['거래량'] if yesterday['거래량'] > 0 else 1.0
    if vol_ratio > YANGUMYANG_VOL_RATIO:
        return None

    # ⑦ 현재가가 MA5 기준 -5% 이내 (너무 많이 이탈하면 제외)
    ma5_gap_pct = (today_close - ma5) / ma5 * 100
    if ma5_gap_pct < YANGUMYANG_MA5_GAP:
        return None

    return {
        '전일등락률':  prev_rate,
        'MA5':         round(ma5),
        'MA5괴리율':   ma5_gap_pct,
        '거래량비율':  vol_ratio,
        '전일거래량':  yesterday['거래량'],
        '오늘거래량':  today['거래량'],
        '전일고가':    yesterday['고가'],
        '전일저가':    yesterday['저가'],
        '패턴':        'P1',
    }


def _check_yangumyang_p3(price_data: list[dict]) -> Optional[dict]:
    """
    양음양 Pattern 3:
      장대양봉(+5~20%, 대량거래) 발생 후
      거래량을 감소시키며 단기 이평선(MA5) 위에서 횡보하는 캔들들
      → 오늘 현재가가 MA5 또는 MA10 근처 (±5%)면 매수 타이밍

    Pattern 1과 차이: 음봉 하루가 아니라 수일간 횡보 후 공략
    """
    if len(price_data) < 11:
        return None

    today = price_data[0]

    if today['종가'] < MIN_PRICE:
        return None

    # MA5, MA10 계산
    ma5  = sum(d['종가'] for d in price_data[:5])  / 5
    ma10 = sum(d['종가'] for d in price_data[:10]) / 10

    # 장대양봉 찾기: 최근 2~10일 내 (오늘 제외)
    yangbong_idx = None
    for i in range(2, min(11, len(price_data))):
        d    = price_data[i]
        rate = d.get('등락률', 0)
        # 등락률 +5~20% AND 반드시 양봉(종가 > 시가) AND 몸통이 전체 범위의 50% 이상
        if not (YANGUMYANG_MIN_RISE <= rate <= YANGUMYANG_MAX_RISE):
            continue
        if d['종가'] <= d['시가']:  # 음봉이면 제외
            continue
        rng = d['고가'] - d['저가']
        body = d['종가'] - d['시가']
        if rng > 0 and body / rng < 0.5:  # 몸통이 작으면 (윗꼬리만 긴 경우) 제외
            continue
        # 그 직전 5일 평균 거래량 대비 1.5배 이상
        prev_vols = [price_data[j]['거래량'] for j in range(i+1, min(i+6, len(price_data)))]
        avg_prev  = sum(prev_vols) / len(prev_vols) if prev_vols else 0
        if avg_prev > 0 and d['거래량'] >= avg_prev * 1.5:
            yangbong_idx = i
            break

    if yangbong_idx is None:
        return None

    # 장대양봉 이후 오늘까지 구간 (최신순: [0]=오늘, [yangbong_idx-1]=장대양봉 다음날)
    since = price_data[:yangbong_idx]   # 오늘 포함, 장대양봉은 미포함

    if len(since) < 2:
        return None

    # 거래량 감소 확인: 장대양봉 이후 최대 거래량 < 장대양봉의 60%
    yangbong_vol = price_data[yangbong_idx]['거래량']
    max_since_vol = max(d['거래량'] for d in since)
    if max_since_vol > yangbong_vol * YANGUMYANG_VOL_RATIO:
        return None

    # 5일선 이탈 확인: 횡보 기간 중 종가가 MA5 -5% 이상 이탈하면 안 됨
    for d in since:
        if d['종가'] < ma5 * (1 + YANGUMYANG_MA5_GAP / 100):
            return None

    # 오늘 현재가가 MA5 또는 MA10 ±5% 이내
    ma5_gap  = (today['종가'] - ma5)  / ma5  * 100
    ma10_gap = (today['종가'] - ma10) / ma10 * 100
    near_ma5  = abs(ma5_gap)  <= 5.0
    near_ma10 = abs(ma10_gap) <= 5.0

    if not (near_ma5 or near_ma10):
        return None

    yangbong_day = price_data[yangbong_idx]
    return {
        '장대양봉일':     yangbong_day['날짜'],
        '장대양봉등락률': yangbong_day.get('등락률', 0),
        '장대양봉거래량': yangbong_day['거래량'],
        '횡보일수':       yangbong_idx - 1,
        'MA5':            round(ma5),
        'MA10':           round(ma10),
        'MA5괴리율':      round(ma5_gap, 1),
        'MA10괴리율':     round(ma10_gap, 1),
        'MA5근처':        near_ma5,
        'MA10근처':       near_ma10,
        '오늘거래량':     today['거래량'],
        '패턴':           'P3',
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


def _load_all_stock_codes(market: str) -> list[tuple[str, str]]:
    """마스터 파일에서 6자리 숫자 종목코드 전체 로드 → [(코드, 종목명), ...]"""
    _load_market_codes()  # 캐시 초기화 겸용
    _STOCKS_DIR = os.path.join(os.path.dirname(_EXAMPLES), 'stocks_info')

    if market == '코스피':
        fnames = ['kospi_code_part1.tmp']
    elif market == '코스닥':
        fnames = ['kosdaq_code_part1.tmp']
    else:
        fnames = ['kospi_code_part1.tmp', 'kosdaq_code_part1.tmp']

    stocks = []
    for fname in fnames:
        path = os.path.join(_STOCKS_DIR, fname)
        if not os.path.exists(path):
            continue
        with open(path, encoding='utf-8') as f:
            for line in f:
                parts = line.split(',')
                code = parts[0].strip()
                name = parts[2].strip() if len(parts) >= 3 else ''
                # 6자리 숫자코드만, ETF/ETN/펀드 제외
                if len(code) == 6 and code.isdigit() and not _is_etf(name):
                    stocks.append((code, name))
    return stocks


def fetch_pullback_flow(market: str = '코스피') -> list[dict]:
    """
    양음양 기법 스크리너 (핀업스탁 기법 기반) — Pattern 1 + Pattern 3
    전 종목 스캔 — 코스피 약 1,800개 / 코스닥 약 1,800개

    Pattern 1: 전일 장대양봉 → 오늘 거래량↓ 음봉 (5일선 위)
    Pattern 3: 장대양봉 후 2~10일 거래량 감소 횡보 → MA5/MA10 근처 공략
    """
    stocks = _load_all_stock_codes(market)
    if not stocks:
        return []

    logger.info(f"양음양 스캔 시작: {market} {len(stocks)}개 종목")

    def _worker(code: str, name: str) -> Optional[dict]:
        try:
            time.sleep(0.05)
            price_data = _fetch_daily_price(code)
            # P1 먼저 체크, 없으면 P3 체크
            pattern = _check_yangumyang(price_data) or _check_yangumyang_p3(price_data)
            if not pattern:
                return None
            today = price_data[0]
            return {
                '코드':   code,
                '종목명': name,
                '현재가': today['종가'],
                '등락률': today['등락률'],
                **pattern,
            }
        except Exception as e:
            logger.debug(f"{code} 양음양 조회 실패: {e}")
        return None

    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_worker, c, n): c for c, n in stocks}
        for future in as_completed(futures):
            r = future.result()
            if r:
                results.append(r)

    # MA5 괴리율 높은 순
    results.sort(key=lambda r: r['MA5괴리율'], reverse=True)
    logger.info(f"양음양 스캔 완료: {len(results)}개 해당")
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
    desc = f'+{YANGUMYANG_MIN_RISE:.0f}~{YANGUMYANG_MAX_RISE:.0f}% 장대양봉 후 거래량↓ 눌림목 (MA5 기준)'
    if not rows:
        return (
            f'📊 <b>{market} 양음양 눌림목</b>\n\n'
            '해당 종목 없음\n'
            f'<i>{desc}</i>'
        )

    def _vol(v):
        if v >= 10_000_000:
            return f'{v/10_000_000:.1f}천만주'
        elif v >= 1_000_000:
            return f'{v/1_000_000:.1f}백만주'
        elif v >= 10_000:
            return f'{v/10_000:.0f}만주'
        return f'{v:,}주'

    p1 = [r for r in rows if r.get('패턴') == 'P1'][:8]
    p3 = [r for r in rows if r.get('패턴') == 'P3'][:8]

    lines = [
        f'📊 <b>{market} 양음양 눌림목</b>',
        f'<i>{desc} · {len(rows)}개 (P1:{len(p1)} P3:{len(p3)} 각 최대8개)</i>',
    ]

    if p1:
        lines.append('\n<b>── Pattern 1 (오늘 음봉 눌림) ──</b>')
    for i, r in enumerate(p1, 1):
        ma5_gap  = r['MA5괴리율']
        vol_pct  = r['거래량비율'] * 100
        lines.append(
            f'\n{i}. <b>{r["종목명"]}</b> <code>{r["코드"]}</code> <i>{_market_tag(r["코드"])}</i>\n'
            f'   {r["현재가"]:,}원 {_rate_str(r["등락률"])}\n'
            f'   전일 <b>+{r["전일등락률"]:.1f}%</b> 장대양봉  MA5 {ma5_gap:+.1f}%  ({r["MA5"]:,}원)\n'
            f'   거래량 전일 {_vol(r["전일거래량"])} → 오늘 {_vol(r["오늘거래량"])} (<b>{vol_pct:.0f}%</b>)'
        )

    if p3:
        lines.append('\n<b>── Pattern 3 (횡보 눌림) ──</b>')
    for i, r in enumerate(p3, 1):
        ma_tag = 'MA5' if r.get('MA5근처') else 'MA10'
        ma_gap = r['MA5괴리율'] if r.get('MA5근처') else r['MA10괴리율']
        lines.append(
            f'\n{i}. <b>{r["종목명"]}</b> <code>{r["코드"]}</code> <i>{_market_tag(r["코드"])}</i>\n'
            f'   {r["현재가"]:,}원 {_rate_str(r["등락률"])}\n'
            f'   장대양봉 <b>+{r["장대양봉등락률"]:.1f}%</b> ({r["장대양봉일"]}) → {r["횡보일수"]}일 횡보\n'
            f'   {ma_tag} {ma_gap:+.1f}%  ({r["MA5"]:,}원)  오늘거래량 {_vol(r["오늘거래량"])}'
        )

    return '\n'.join(lines)
