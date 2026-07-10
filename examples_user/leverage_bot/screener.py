"""레버리지 ETF 매수 신호 스크리너 — 모든 조건 충족 종목만 텔레그램 알림

사용법:
  uv run screener.py

환경 변수:
  LEVERAGE_BOT_TOKEN 또는 TELEGRAM_BOT_TOKEN  — 봇 토큰
  LEVERAGE_SCREENER_CHAT_ID                   — 메시지 수신 채팅 ID

CRON 등록 예시 (KST 22:30 = ET 09:30 = 미국 시장 개장 직후):
  30 22 * * 1-5  cd /home/boyeon/workspace/open-trading-api && uv run examples_user/leverage_bot/screener.py

매수 가능 판단 기준 (모든 조건 AND):
  1. 200일선 위  (200일선 아래 → 절대 금지)
  2. VIX < 40   (40 이상 → 전부 쉰다)
  3. VIX < 30   (30 이상 → tier1_stable 만 소액 허용, 나머지 금지)
  4. 오늘 저가 ≤ 1차 진입가  (진입가 도달)
     OR 현재가가 진입가 대비 +5% 이내  (근접 — 예비 알림)
"""
import sys
import os
import logging
import math
import asyncio
import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

# leverage_bot 디렉토리를 경로에 추가
_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

from calc import TICKER_GRADE, GRADE_CONFIG, CLUSTERS, calculate_buy_plan

logging.basicConfig(
    format='%(asctime)s %(levelname)s %(message)s',
    level=logging.WARNING,  # 스크리너 실행 시 불필요한 로그 최소화
)
logger = logging.getLogger(__name__)

# ── 환경 변수 ──────────────────────────────────────────────────────────────────
TOKEN   = os.getenv('LEVERAGE_BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.getenv('LEVERAGE_SCREENER_CHAT_ID')

# 근접 알림 기준: 진입가 대비 +X% 이내
APPROACH_THRESHOLD_PCT = 5.0


# ── 가격 조회 ──────────────────────────────────────────────────────────────────
def _fetch_price_pair(ticker: str) -> tuple[float, float, float, str]:
    """
    Yahoo Finance에서 이전 종가와 오늘 현재가(저가 포함) 조회.

    Returns:
        prev_close   : 어제 종가  (1차 진입가 계산 기준)
        current_close: 오늘 종가/현재가
        current_low  : 오늘 저가  (진입가 도달 여부 체크)
        date_str     : 오늘 날짜 문자열
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.upper()}"
    params = {'interval': '1d', 'range': '5d'}
    headers = {'User-Agent': 'Mozilla/5.0'}

    resp = requests.get(url, params=params, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    result = data['chart']['result'][0]
    timestamps = result['timestamp']
    quotes     = result['indicators']['quote'][0]

    closes = quotes['close']
    lows   = quotes.get('low', closes)

    # None 제거
    valid_pairs = [(t, c, l) for t, c, l in zip(timestamps, closes, lows)
                   if c is not None]

    if len(valid_pairs) < 2:
        t, c, l = valid_pairs[-1]
        return c, c, (l or c), datetime.fromtimestamp(t).strftime('%Y-%m-%d')

    t_prev, prev_close, _   = valid_pairs[-2]
    t_cur,  curr_close, cur_low = valid_pairs[-1]
    date_str = datetime.fromtimestamp(t_cur).strftime('%Y-%m-%d')
    return prev_close, curr_close, (cur_low or curr_close), date_str


def _fetch_vix() -> Optional[float]:
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX"
        params = {'interval': '1d', 'range': '5d'}
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        closes = [c for c in data['chart']['result'][0]['indicators']['quote'][0]['close']
                  if c is not None]
        return closes[-1] if closes else None
    except Exception as e:
        logger.warning(f"VIX 조회 실패: {e}")
        return None


def _fetch_ma_status(ticker: str) -> tuple[bool, bool]:
    """Returns (below_50ma, below_200ma)"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.upper()}"
    params = {'interval': '1d', 'range': '1y'}
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data   = resp.json()
        closes = [c for c in data['chart']['result'][0]['indicators']['quote'][0]['close']
                  if c is not None]
        if len(closes) < 50:
            return False, False
        current = closes[-1]
        ma50    = sum(closes[-50:]) / 50
        ma200   = sum(closes[-200:]) / 200 if len(closes) >= 200 else None
        return current < ma50, (current < ma200 if ma200 else False)
    except Exception as e:
        logger.warning(f"{ticker} MA 조회 실패: {e}")
        return False, False


# ── 종목별 신호 판단 ───────────────────────────────────────────────────────────
def _check_one(ticker: str, vix: Optional[float]) -> Optional[dict]:
    """
    모든 조건 체크 후 신호가 있으면 dict 반환, 없으면 None.
    """
    grade = TICKER_GRADE.get(ticker)
    if not grade:
        return None

    # ① MA 위치 조회
    below_50ma, below_200ma = _fetch_ma_status(ticker)

    # ② 200일선 아래 → 절대 금지
    if below_200ma:
        return None

    # ③ VIX 필터
    if vix is not None:
        if vix >= 40:
            return None  # 전부 쉰다
        if vix >= 30 and grade != 'tier1_stable':
            return None  # 1등급 안정형만 소액 허용

    # ④ 가격 조회
    try:
        prev_close, curr_close, curr_low, date_str = _fetch_price_pair(ticker)
    except Exception as e:
        logger.warning(f"{ticker} 가격 조회 실패: {e}")
        return None

    # ⑤ 1차 진입가 계산 (prev_close 기준)
    plan         = calculate_buy_plan(prev_close, grade, vix, below_50ma, below_200ma)
    entry_price  = plan['rounds'][0]['buy_price']
    entry_pct    = plan['entry_pct']

    # ⑥ 신호 판단
    reached     = curr_low   <= entry_price                          # 오늘 저가가 진입가 터치
    approaching = (not reached) and (
        curr_close <= entry_price * (1 + APPROACH_THRESHOLD_PCT / 100)
    )

    if not (reached or approaching):
        return None

    pct_gap = (curr_close - entry_price) / entry_price * 100        # 양수=아직 위, 음수=이미 아래

    return {
        'ticker':       ticker,
        'grade':        grade,
        'prev_close':   prev_close,
        'curr_close':   curr_close,
        'curr_low':     curr_low,
        'entry_price':  entry_price,
        'entry_pct':    entry_pct,
        'pct_gap':      pct_gap,   # curr_close vs entry_price 괴리 (음수 = 이미 진입가 이하)
        'reached':      reached,
        'approaching':  approaching,
        'below_50ma':   below_50ma,
        'plan':         plan,
        'date_str':     date_str,
    }


# ── 메시지 포맷 ───────────────────────────────────────────────────────────────
_GRADE_LABEL = {
    'tier1_stable':   '1등급 안정형',
    'tier1_volatile': '1등급 변동형',
    'tier2':          '2등급 단일주',
    'tier3':          '3등급 고위험',
}
_GRADE_EMOJI = {
    'tier1_stable':   '🔵',
    'tier1_volatile': '🟠',
    'tier2':          '🟡',
    'tier3':          '🔴',
}


def _p(x: float) -> str:
    """소수점 2자리 버림"""
    return f'{math.floor(x * 100) / 100:,.2f}'


def _get_cluster(ticker: str) -> Optional[str]:
    for cluster, tickers in CLUSTERS.items():
        if ticker in tickers:
            return cluster
    return None


def _format_signal(sig: dict) -> str:
    """종목 한 줄 + 상세 포맷"""
    t = sig['ticker']
    g = sig['grade']
    ep = sig['entry_price']
    cc = sig['curr_close']
    cl = sig['curr_low']
    gap = sig['pct_gap']
    r1  = sig['plan']['rounds'][0]

    emoji = _GRADE_EMOJI[g]
    label = _GRADE_LABEL[g]
    cluster = _get_cluster(t)

    # 상태 아이콘
    if sig['reached']:
        status = f'✅ 진입가 도달  (저가 ${_p(cl)} ≤ 진입가 ${_p(ep)})'
    else:
        status = f'📌 진입가 근접  현재 +{gap:.1f}%  (${_p(cc)} → 목표 ${_p(ep)})'

    lines = [
        f'{emoji} <b>{t}</b>  <i>{label}</i>',
        f'   {status}',
        f'   진입가 ${_p(ep)}  <i>(전일종가 ${_p(sig["prev_close"])} −{sig["entry_pct"]:.1f}%)</i>',
        f'   목표가 ${_p(r1["target_price"])}  손절가 ${_p(r1["stop_price"])}',
        f'   1차 투입 {r1["amount"]}만원',
    ]

    if sig['below_50ma']:
        lines.append('   ⚠️ 50일선↓ — 1차 70만·4차 한도·보수적 운용')
    if cluster:
        lines.append(f'   📌 [{cluster}] 동일 클러스터 중복 보유 금지')

    return '\n'.join(lines)


def _vix_comment(vix: Optional[float]) -> str:
    if vix is None:
        return 'VIX: 조회 실패'
    if vix >= 40:
        return f'VIX {vix:.1f} 🚫 전부 쉰다'
    if vix >= 30:
        return f'VIX {vix:.1f} 🚫 1등급 안정형 소액만'
    if vix >= 22:
        return f'VIX {vix:.1f} ⚠️ 1차 진입 1%p 더 깊게 적용 중'
    return f'VIX {vix:.1f} ✅ 정상 운용'


def format_message(results: list[dict], vix: Optional[float], now: datetime) -> str:
    reached    = [r for r in results if r['reached']]
    approaching = [r for r in results if r['approaching']]

    kst = now.strftime('%Y-%m-%d %H:%M KST')
    lines = [
        f'🔔 <b>레버리지 ETF 매수 신호</b>',
        f'<code>{kst}</code>',
        f'{_vix_comment(vix)}',
        '',
    ]

    if not results:
        lines.append('현재 매수 신호 없음 — 모든 종목이 진입가에 미도달')
        return '\n'.join(lines)

    if reached:
        lines.append(f'━━ ✅ <b>진입가 도달</b> ({len(reached)}개) ━━')
        for sig in reached:
            lines.append('')
            lines.append(_format_signal(sig))

    if approaching:
        lines.append('')
        lines.append(f'━━ 📌 <b>진입가 근접 {APPROACH_THRESHOLD_PCT:.0f}% 이내</b> ({len(approaching)}개) ━━')
        for sig in approaching:
            lines.append('')
            lines.append(_format_signal(sig))

    lines += [
        '',
        '<i>⚠️ 동일 클러스터 중복 보유 금지 / 평단 기준 익절·손절 관리</i>',
    ]
    return '\n'.join(lines)


# ── Telegram 전송 ─────────────────────────────────────────────────────────────
def send_telegram(text: str, token: str, chat_id: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        'chat_id':    chat_id,
        'text':       text,
        'parse_mode': 'HTML',
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"텔레그램 전송 실패: {e}")
        return False


# ── 메인 ─────────────────────────────────────────────────────────────────────
async def run_screener() -> list[dict]:
    """모든 종목 병렬 체크 후 신호 목록 반환"""
    tickers = list(TICKER_GRADE.keys())
    loop    = asyncio.get_running_loop()

    # VIX 먼저 조회
    vix = await loop.run_in_executor(None, _fetch_vix)
    print(f'VIX: {vix}')

    # 전부 쉰다면 종목 체크 생략
    if vix is not None and vix >= 40:
        return []

    # 종목별 병렬 체크
    with ThreadPoolExecutor(max_workers=10) as executor:
        tasks = [
            loop.run_in_executor(executor, _check_one, t, vix)
            for t in tickers
        ]
        raw = await asyncio.gather(*tasks)

    signals = [r for r in raw if r is not None]

    # 진입가 도달 → 근접 순 정렬, 같은 상태 내에서는 괴리 작은 순
    signals.sort(key=lambda r: (0 if r['reached'] else 1, r['pct_gap']))
    return signals, vix


def main():
    print('=== 레버리지 ETF 스크리너 시작 ===')
    now = datetime.now()

    signals, vix = asyncio.run(run_screener())

    msg = format_message(signals, vix, now)
    print(msg)  # 터미널에도 출력

    if not TOKEN:
        print('\n⚠️  LEVERAGE_BOT_TOKEN 환경 변수 없음 — 텔레그램 전송 생략')
        return
    if not CHAT_ID:
        print('\n⚠️  LEVERAGE_SCREENER_CHAT_ID 환경 변수 없음 — 텔레그램 전송 생략')
        print('    채팅 ID 확인: 봇에 /start 후 https://api.telegram.org/bot<TOKEN>/getUpdates 조회')
        return

    ok = send_telegram(msg, TOKEN, CHAT_ID)
    print('텔레그램 전송 완료' if ok else '텔레그램 전송 실패')


if __name__ == '__main__':
    main()
