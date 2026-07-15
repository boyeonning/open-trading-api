"""종가·VIX 조회 — KIS API 우선, 실패 시 Yahoo Finance 폴백"""
import sys
import os
import logging
from datetime import datetime
from typing import Optional

import requests

# kis_auth 경로 (examples_user/)
_EXAMPLES = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _EXAMPLES)
# overseas_stock_functions 경로 (examples_user/telegram_stock_info/)
_TGBOT = os.path.join(_EXAMPLES, 'telegram_stock_info')
sys.path.insert(0, _TGBOT)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────
#  티커별 KIS 거래소 코드
#  NYSE Arca 상장 ETF → NYS
#  NASDAQ 상장 ETF    → NAS
# ──────────────────────────────────────────────────────────
_TICKER_EXCD: dict[str, str] = {
    # NASDAQ 상장
    'TQQQ': 'NAS', 'FNGU': 'NAS',
}
_DEFAULT_EXCD = 'AMS'   # NYSE Arca (KIS에서 AMS로 처리)


def _get_excd(ticker: str) -> str:
    return _TICKER_EXCD.get(ticker.upper(), _DEFAULT_EXCD)


# ──────────────────────────────────────────────────────────
#  KIS API로 전날 종가 조회
# ──────────────────────────────────────────────────────────
def _fetch_via_kis(ticker: str) -> tuple[float, float, str]:
    """
    KIS 해외주식 현재체결가 API → (현재가, 전일종가, 날짜) 반환
    Returns:
        (last, base, date_str)
        last  = 현재가 (체결가)
        base  = 기준가 (전날 종가)
    """
    import kis_auth as ka
    from api.overseas_stock_functions import price as kis_price

    excd = _get_excd(ticker)
    ka.auth()
    df = kis_price("", excd, ticker)

    if df is None or df.empty:
        raise ValueError(f"KIS API: {ticker} 데이터 없음")

    row = df.iloc[0]
    date_str = datetime.now().strftime('%Y-%m-%d')

    def _to_float(val) -> Optional[float]:
        return float(val) if val not in ('', None, '0', 0) else None

    last = _to_float(row.get('last'))
    base = _to_float(row.get('base'))

    if last is None and base is None:
        raise ValueError(f"KIS API: {ticker} 유효한 가격 없음 → {row.to_dict()}")

    # 어느 쪽이든 없으면 서로 대체
    last = last or base
    base = base or last

    logger.warning(f"KIS 전체 응답 [{ticker}]: {row.to_dict()}")
    logger.info(f"KIS 현재체결가: {ticker} last(현재가)=${last:.2f} base(기준가)=${base:.2f}")
    return last, base, date_str


# ──────────────────────────────────────────────────────────
#  Yahoo Finance 폴백
# ──────────────────────────────────────────────────────────
def _fetch_via_yahoo(ticker: str) -> tuple[float, str]:
    """Yahoo Finance 공개 API로 최근 종가 조회"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {'interval': '1d', 'range': '5d'}
    headers = {'User-Agent': 'Mozilla/5.0'}

    resp = requests.get(url, params=params, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    result = data['chart']['result'][0]
    timestamps = result['timestamp']
    closes = result['indicators']['quote'][0]['close']

    valid = [(t, c) for t, c in zip(timestamps, closes) if c is not None]
    if not valid:
        raise ValueError(f"Yahoo Finance: {ticker} 유효한 종가 없음")

    last_ts, last_close = valid[-1]
    date_str = datetime.fromtimestamp(last_ts).strftime('%Y-%m-%d')
    logger.info(f"Yahoo Finance 성공: {ticker} ${last_close:.2f}")
    return last_close, date_str


# ──────────────────────────────────────────────────────────
#  공개 인터페이스
# ──────────────────────────────────────────────────────────
def fetch_prev_close(ticker: str) -> tuple[float, str]:
    """
    전날 종가 조회 — KIS API 우선, 실패 시 Yahoo Finance 폴백.
    Returns:
        (prev_close, date_str)
    """
    ticker = ticker.upper()
    try:
        _last, base, date_str = _fetch_via_kis(ticker)
        return base, date_str
    except Exception as e:
        logger.warning(f"KIS API 실패 ({ticker}): {e} → Yahoo Finance 폴백")
        return _fetch_via_yahoo(ticker)


def fetch_vix() -> Optional[float]:
    """VIX 최근값 조회 (Yahoo Finance, 실패 시 None)"""
    try:
        close, _ = _fetch_via_yahoo('^VIX')
        return close
    except Exception as e:
        logger.warning(f"VIX 조회 실패: {e}")
        return None


def fetch_ticker_snapshot(ticker: str) -> Optional[dict]:
    """현재가(KIS last) + 전일종가(Yahoo valid[-1]) 조회.

    전일종가는 fetch_prev_close의 Yahoo 폴백과 동일한 소스(valid[-1])를 사용해
    handle_message와 /check 간 가격 일관성을 보장한다.

    Returns:
        {current_price, prev_close, prev_date}  또는 None
    """
    ticker = ticker.upper()

    # ── 전일종가: Yahoo valid[-1] ─────────────────────────
    # fetch_prev_close Yahoo 폴백과 동일한 소스 → handle_message와 일치
    prev_close = None
    prev_date  = None
    valid      = []
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        resp = requests.get(url, params={'interval': '1d', 'range': '5d'},
                            headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        resp.raise_for_status()
        result = resp.json()['chart']['result'][0]
        valid  = [(t, c) for t, c in zip(result['timestamp'],
                   result['indicators']['quote'][0]['close']) if c is not None]
        if valid:
            prev_close = valid[-1][1]
            prev_date  = datetime.fromtimestamp(valid[-1][0]).strftime('%Y-%m-%d')
    except Exception as e:
        logger.warning(f"{ticker} Yahoo 전일종가 조회 실패: {e}")

    if prev_close is None:
        return None

    # ── 현재가: KIS last (실시간 체결가) ──────────────────
    current = None
    try:
        last, _base, _date = _fetch_via_kis(ticker)
        current = last
        logger.info(f"KIS 현재가: {ticker} ${current:.2f}  Yahoo 전일종가: ${prev_close:.2f}")
    except Exception as e:
        logger.warning(f"{ticker} KIS 현재가 실패: {e} → Yahoo 최근 종가 사용")

    # KIS 실패 시 Yahoo valid[-1]을 현재가로 (장 마감 후에도 최근 종가 표시)
    if current is None:
        current = valid[-1][1] if valid else None

    if current is None:
        return None

    return {'current_price': current, 'prev_close': prev_close, 'prev_date': prev_date}


def fetch_ma_status(ticker: str) -> tuple[bool, bool]:
    """
    50일선 / 200일선 대비 현재가 위치 자동 감지.
    Returns:
        (below_50ma, below_200ma)
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.upper()}"
    params = {'interval': '1d', 'range': '1y'}
    headers = {'User-Agent': 'Mozilla/5.0'}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        closes = [
            c for c in data['chart']['result'][0]['indicators']['quote'][0]['close']
            if c is not None
        ]

        if len(closes) < 50:
            logger.warning(f"{ticker} 데이터 부족({len(closes)}일) — 정상 구간으로 처리")
            return False, False

        current = closes[-1]
        ma50 = sum(closes[-50:]) / 50
        ma200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else None

        below_50ma = current < ma50
        below_200ma = (current < ma200) if ma200 is not None else False

        logger.info(
            f"{ticker} MA 감지: 현재=${current:.2f} "
            f"MA50=${ma50:.2f}({'↓' if below_50ma else '↑'}) "
            f"MA200={f'${ma200:.2f}' if ma200 else 'N/A'}({'↓' if below_200ma else '↑'})"
        )
        return below_50ma, below_200ma

    except Exception as e:
        logger.warning(f"{ticker} MA 조회 실패: {e} — 정상 구간으로 처리")
        return False, False
