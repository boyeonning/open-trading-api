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
def _fetch_via_kis(ticker: str) -> tuple[float, str]:
    """
    KIS 해외주식 현재체결가 API → base(기준가 = 전날 종가) 반환
    auth() 호출 선행 필요
    """
    import kis_auth as ka
    from api.overseas_stock_functions import price as kis_price

    excd = _get_excd(ticker)
    ka.auth()
    df = kis_price("", excd, ticker)

    if df is None or df.empty:
        raise ValueError(f"KIS API: {ticker} 데이터 없음")

    row = df.iloc[0]

    # base = 기준가(전날 종가), 없으면 last(현재가) 사용
    if 'base' in row and row['base'] not in ('', None, '0', 0):
        close = float(row['base'])
    elif 'last' in row and row['last'] not in ('', None, '0', 0):
        close = float(row['last'])
    else:
        raise ValueError(f"KIS API: {ticker} 유효한 가격 없음 → {row.to_dict()}")

    # 날짜: KIS 응답에 t_xhms(시각) 또는 없으면 오늘
    date_str = datetime.now().strftime('%Y-%m-%d')

    logger.info(f"KIS API 성공: {ticker} ${close:.2f} (excd={excd})")
    return close, date_str


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
        (close_price, date_str)
    """
    ticker = ticker.upper()
    try:
        return _fetch_via_kis(ticker)
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
