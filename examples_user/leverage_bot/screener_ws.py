"""레버리지 ETF 실시간 WebSocket 매수 신호 스크리너

KIS WebSocket HDFSCNT0 (해외주식 실시간체결가, 미국 0분 지연) 사용.
진입가 도달 즉시 텔레그램 알림 전송.

동작 흐름:
  1. 장 시작 전: 어제 종가 + MA 상태 + VIX 조회 → 진입가 계산
  2. 기본 조건 필터 (200일선 위, VIX 범위)
  3. 통과 종목만 WebSocket 구독
  4. 실시간 체결가가 진입가 이하 → 텔레그램 알림 (당일 1회)
  5. 미국 장 종료(KST 05:05) 자동 종료

사용법:
  uv run screener_ws.py

환경 변수:
  LEVERAGE_BOT_TOKEN 또는 TELEGRAM_BOT_TOKEN  — 봇 토큰
  LEVERAGE_SCREENER_CHAT_ID                   — 수신 채팅 ID

CRON 등록 (KST 22:20 = ET 09:20, 미국 개장 10분 전):
  20 22 * * 1-5  cd /home/boyeon/workspace/open-trading-api && uv run examples_user/leverage_bot/screener_ws.py
"""
import sys
import os
import math
import json
import logging
import asyncio
import requests
import threading
import time
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

# 경로 설정
_DIR      = os.path.dirname(os.path.abspath(__file__))
_EXAMPLES = os.path.dirname(_DIR)
_OVS_WS   = os.path.join(_EXAMPLES, 'overseas_stock')
sys.path.insert(0, _DIR)
sys.path.insert(0, _EXAMPLES)
sys.path.insert(0, _OVS_WS)

import kis_auth as ka
from overseas_stock_functions_ws import delayed_ccnl   # HDFSCNT0
from calc import TICKER_GRADE, CLUSTERS, calculate_buy_plan

logging.basicConfig(
    format='%(asctime)s %(levelname)s %(message)s',
    level=logging.WARNING,
)
logger = logging.getLogger(__name__)

# ── 환경 변수 ──────────────────────────────────────────────────────────────────
TOKEN   = os.getenv('LEVERAGE_BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.getenv('LEVERAGE_SCREENER_CHAT_ID')

# ── KIS 거래소 코드 매핑 (fetcher.py와 동일) ──────────────────────────────────
_TICKER_EXCD: dict[str, str] = {
    'TQQQ': 'NAS', 'FNGU': 'NAS',
}
_DEFAULT_EXCD = 'AMS'

KST = timezone(timedelta(hours=9))

# 미국 장 종료 KST 시각 (정규장 04:00, 여유분 5분)
MARKET_CLOSE_KST_HOUR   = 5
MARKET_CLOSE_KST_MINUTE = 5
# 프리장 시작 KST 시각 (ET 04:00 = KST 17:00)
PREMARKET_START_KST_HOUR = 17


# ── 유틸 ──────────────────────────────────────────────────────────────────────
def _p(x: float) -> str:
    return f'{math.floor(x * 100) / 100:,.2f}'


def _make_tr_key(ticker: str) -> str:
    """WebSocket 구독용 tr_key: D + 거래소코드 + 티커"""
    excd = _TICKER_EXCD.get(ticker.upper(), _DEFAULT_EXCD)
    return f"D{excd}{ticker.upper()}"


def _get_cluster(ticker: str) -> Optional[str]:
    for cluster, tickers in CLUSTERS.items():
        if ticker in tickers:
            return cluster
    return None


def _is_market_closed() -> bool:
    """프리장+정규장 종료 여부 (KST 기준)
    운영 시간: KST 17:00 (ET 04:00 프리장) ~ 05:05 (정규장 마감)
    종료 판단: 05:05 이후이고 17시 이전인 경우
    """
    now = datetime.now(KST)
    h, m = now.hour, now.minute
    if h == MARKET_CLOSE_KST_HOUR and m >= MARKET_CLOSE_KST_MINUTE:
        return True
    if MARKET_CLOSE_KST_HOUR < h < PREMARKET_START_KST_HOUR:
        return True
    return False


# ── 사전 데이터 조회 (WebSocket 연결 전) ─────────────────────────────────────
def _fetch_vix() -> Optional[float]:
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX"
        resp = requests.get(url, params={'interval': '1d', 'range': '5d'},
                            headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        resp.raise_for_status()
        closes = [c for c in resp.json()['chart']['result'][0]
                  ['indicators']['quote'][0]['close'] if c is not None]
        return closes[-1] if closes else None
    except Exception as e:
        logger.warning(f"VIX 조회 실패: {e}")
        return None


def _fetch_prev_close(ticker: str) -> tuple[float, str]:
    """어제 종가 + 날짜 (Yahoo Finance 5일 데이터에서 직전 확정 종가)"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.upper()}"
    resp = requests.get(url, params={'interval': '1d', 'range': '5d'},
                        headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
    resp.raise_for_status()
    result = resp.json()['chart']['result'][0]
    timestamps = result['timestamp']
    closes     = result['indicators']['quote'][0]['close']

    valid = [(t, c) for t, c in zip(timestamps, closes) if c is not None]
    if len(valid) < 2:
        t, c = valid[-1]
        return c, datetime.fromtimestamp(t).strftime('%Y-%m-%d')

    # 직전 확정 종가 (오늘 장중이면 -2번째, 장 마감이면 -1번째)
    t, c = valid[-2]
    return c, datetime.fromtimestamp(t).strftime('%Y-%m-%d')


def _fetch_ma_status(ticker: str) -> tuple[bool, bool]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.upper()}"
    try:
        resp = requests.get(url, params={'interval': '1d', 'range': '1y'},
                            headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        resp.raise_for_status()
        closes = [c for c in resp.json()['chart']['result'][0]
                  ['indicators']['quote'][0]['close'] if c is not None]
        if len(closes) < 50:
            return False, False
        current = closes[-1]
        ma50    = sum(closes[-50:]) / 50
        ma200   = sum(closes[-200:]) / 200 if len(closes) >= 200 else None
        return current < ma50, (current < ma200 if ma200 else False)
    except Exception as e:
        logger.warning(f"{ticker} MA 조회 실패: {e}")
        return False, False


def _fetch_ticker_data(args) -> Optional[dict]:
    """병렬 실행용: 종목 데이터 조회 + 기본 조건 필터"""
    ticker, vix = args
    grade = TICKER_GRADE.get(ticker)
    if not grade:
        return None

    below_50ma, below_200ma = _fetch_ma_status(ticker)

    # 200일선 아래 → 절대 금지
    if below_200ma:
        return None

    # 50일선 아래(🟠 보류) → 신규 진입 금지
    if below_50ma:
        return None

    # VIX 필터
    if vix is not None:
        if vix >= 40:
            return None
        if vix >= 30 and grade != 'A':
            return None

    try:
        prev_close, date_str = _fetch_prev_close(ticker)
    except Exception as e:
        logger.warning(f"{ticker} 종가 조회 실패: {e}")
        return None

    plan        = calculate_buy_plan(prev_close, grade, vix, below_50ma, below_200ma)
    entry_price = plan['rounds'][0]['buy_price']
    entry_pct   = plan['entry_pct']
    r1          = plan['rounds'][0]

    return {
        'ticker':      ticker,
        'grade':       grade,
        'prev_close':  prev_close,
        'entry_price': entry_price,
        'entry_pct':   entry_pct,
        'stop_price':  r1['stop_price'],
        'target_price': r1['target_price'],
        'amount':      r1['amount'],
        'below_50ma':  below_50ma,
        'date_str':    date_str,
        'tr_key':      _make_tr_key(ticker),
    }


# ── Telegram 전송 ─────────────────────────────────────────────────────────────
def send_telegram(text: str) -> bool:
    if not TOKEN or not CHAT_ID:
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'HTML'},
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"텔레그램 전송 실패: {e}")
        return False


# ── 알림 메시지 포맷 ───────────────────────────────────────────────────────────
_GRADE_EMOJI = {
    'A': '🔵', 'B': '🟢', 'C': '🟡', 'D': '🟠', 'E': '🔴',
}
_GRADE_LABEL = {
    'A': 'A등급 (−3%)', 'B': 'B등급 (−4%)', 'C': 'C등급 (−5%)',
    'D': 'D등급 (−6%)', 'E': 'E등급 (−7%)',
}


def _format_alert(info: dict, current_price: float) -> str:
    t       = info['ticker']
    g       = info['grade']
    ep      = info['entry_price']
    sp      = info['stop_price']
    tp      = info['target_price']
    cluster = _get_cluster(t)
    now_kst = datetime.now(KST).strftime('%H:%M KST')

    lines = [
        f'🔔 <b>매수 신호</b>  {now_kst}',
        f'{_GRADE_EMOJI[g]} <b>{t}</b>  <i>{_GRADE_LABEL[g]}</i>',
        f'',
        f'현재가   <code>${_p(current_price)}</code>',
        f'진입가   <code>${_p(ep)}</code>  <i>(전일종가 ${_p(info["prev_close"])} −{info["entry_pct"]:.1f}%)</i>',
        f'목표가   <code>${_p(tp)}</code>',
        f'손절가   <code>${_p(sp)}</code>',
        f'1차 투입  {info["amount"]}만원',
    ]

    if info['below_50ma']:
        lines.append('⚠️ 50일선↓ — 1차 70만·4차 한도·보수적 운용')
    if cluster:
        lines.append(f'📌 [{cluster}] 동일 클러스터 중복 보유 금지')

    return '\n'.join(lines)


# ── WebSocket 스크리너 ─────────────────────────────────────────────────────────
class LeverageScreener:
    def __init__(self, watchlist: dict[str, dict]):
        # watchlist: {ticker: info_dict}
        self.watchlist    = watchlist
        self.alerted: set = set()   # 당일 알림 완료 티커

        # tr_key → ticker 역매핑 (WebSocket 응답 SYMB 파싱용)
        self._tr_key_map: dict[str, str] = {}
        for ticker, info in watchlist.items():
            tk = info['tr_key']
            self._tr_key_map[tk]             = ticker  # DAMSOXL → SOXL
            self._tr_key_map[tk[1:]]         = ticker  # AMSOXL  → SOXL  (D 제외)
            self._tr_key_map[tk[4:]]         = ticker  # SOXL    → SOXL  (DAMS 제외)
            self._tr_key_map[ticker]         = ticker  # SOXL    → SOXL

    def _resolve_ticker(self, symb: str) -> Optional[str]:
        """SYMB 문자열에서 티커 찾기"""
        s = symb.strip().upper()
        return self._tr_key_map.get(s)

    def on_price(self, ws, tr_id: str, df, data_info: dict):
        """WebSocket 체결가 수신 콜백"""
        if df is None or df.empty:
            return

        try:
            for _, row in df.iterrows():
                symb  = str(row.get('SYMB', '')).strip()
                last  = row.get('LAST', '')

                if not symb or not last:
                    continue

                try:
                    price = float(last)
                except (ValueError, TypeError):
                    continue

                ticker = self._resolve_ticker(symb)
                if ticker is None or ticker in self.alerted:
                    continue

                info = self.watchlist.get(ticker)
                if info is None:
                    continue

                # 진입가 도달 체크
                if price <= info['entry_price']:
                    self.alerted.add(ticker)
                    msg = _format_alert(info, price)
                    print(f'[신호] {ticker}  현재가 ${_p(price)}  진입가 ${_p(info["entry_price"])}')
                    send_telegram(msg)

        except Exception as e:
            logger.error(f"체결가 처리 오류: {e}", exc_info=True)


# ── 메인 ─────────────────────────────────────────────────────────────────────
def _prepare_watchlist() -> tuple[Optional[dict], Optional[float]]:
    """비동기 없이 사전 데이터 조회 (WebSocket 연결 전 동기 실행)"""
    vix = _fetch_vix()
    print(f'VIX: {vix}')

    if vix is not None and vix >= 40:
        msg = f'🚫 VIX {vix:.1f} ≥ 40 — 전부 쉰다. 스크리너 종료.'
        print(msg)
        send_telegram(msg)
        return None, vix

    tickers = list(TICKER_GRADE.keys())
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(_fetch_ticker_data, [(t, vix) for t in tickers]))

    watchlist = {r['ticker']: r for r in results if r is not None}

    if not watchlist:
        msg = '감시 대상 종목 없음 (200일선 위 + VIX 조건 통과 종목 0개)'
        print(msg)
        send_telegram(msg)
        return None, vix

    return watchlist, vix


def main():
    print(f'=== 레버리지 ETF WebSocket 스크리너 시작 ({datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")}) ===')

    # ① KIS 인증
    ka.auth()
    ka.auth_ws()

    # ② 사전 데이터 조회
    print('VIX + 종목 데이터 조회 중...')
    watchlist, vix = _prepare_watchlist()
    if watchlist is None:
        return

    print(f'감시 대상: {", ".join(sorted(watchlist.keys()))}')

    # ③ WebSocket 구독 설정
    screener = LeverageScreener(watchlist)

    tr_keys = [info['tr_key'] for info in watchlist.values()]
    ka.KISWebSocket.subscribe(request=delayed_ccnl, data=tr_keys)

    kws = ka.KISWebSocket(api_url="/tryitout")

    # ④ WebSocket을 데몬 스레드에서 실행
    t = threading.Thread(target=kws.start, kwargs={'on_result': screener.on_price}, daemon=True)
    t.start()

    # ⑤ 장 종료(KST 05:05)까지 30초마다 체크 후 프로세스 종료
    while not _is_market_closed():
        time.sleep(30)

    now_kst = datetime.now(KST).strftime('%H:%M KST')
    msg = f'📴 스크리너 종료 ({now_kst}) — 미국 정규장 마감'
    print(msg)
    send_telegram(msg)
    os._exit(0)


if __name__ == '__main__':
    if not TOKEN:
        print('⚠️  LEVERAGE_BOT_TOKEN 환경 변수 없음')
    if not CHAT_ID:
        print('⚠️  LEVERAGE_SCREENER_CHAT_ID 환경 변수 없음')
        print('    채팅 ID: 봇에 /start 후 https://api.telegram.org/bot<TOKEN>/getUpdates 조회')

    main()
