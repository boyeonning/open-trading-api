"""가격 모니터링 — 5분 주기 자동 알림 잡

동작 조건:
  - /alert on 으로 구독한 채팅에만 발송
  - 미국 주식시장 운영 시간(UTC 13:00~21:30, 평일)에만 실행
  - 같은 종목 30분 이내 중복 알림 방지
  - VIX ≥ 40 이면 전체 스킵

알림 기준:
  - 현재가 ≤ 진입가        → 🔴 진입가 도달
  - 현재가 < 전일종가 and 진입가까지 3% 이내 → ⚡ 근접
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from telegram.ext import ContextTypes

from weekly_config import WATCHLIST, SIGNAL_GO
from calc import calculate_buy_plan
from fetcher import fetch_vix, fetch_ticker_snapshot

logger = logging.getLogger(__name__)

UTC = timezone.utc
KST = timezone(timedelta(hours=9))

_GRADE_EMOJI = {'A': '🔵', 'B': '🟢', 'C': '🟡', 'D': '🟠', 'E': '🔴'}

# 미국장 운영 시간대 (UTC) — 여름(EDT)/겨울(EST) 모두 커버
_OPEN_UTC  = 13 * 60      # 13:00 UTC (9:30 AM EDT 기준)
_CLOSE_UTC = 21 * 60 + 30 # 21:30 UTC (5:00 PM EDT 기준, 여유 포함)

_ALERT_COOLDOWN = timedelta(minutes=30)
_NEAR_THRESHOLD = 3.0  # 진입가까지 몇 % 이내를 근접으로 볼지


def _is_market_hours() -> bool:
    """현재가 미국 주식시장 운영 시간인지 확인"""
    now = datetime.now(UTC)
    if now.weekday() >= 5:  # 토·일
        return False
    minutes = now.hour * 60 + now.minute
    return _OPEN_UTC <= minutes <= _CLOSE_UTC


async def check_and_alert(context: ContextTypes.DEFAULT_TYPE):
    """5분마다 실행 — 조건 충족 종목에 자동 알림 발송"""
    chat_ids: set = context.bot_data.get('alert_chats', set())
    if not chat_ids:
        return

    if not _is_market_hours():
        return

    loop = asyncio.get_event_loop()

    candidates = {t: info for t, info in WATCHLIST.items() if info['signal'] in SIGNAL_GO}
    if not candidates:
        return

    # VIX 조회
    vix = await loop.run_in_executor(None, fetch_vix)
    if vix is not None and vix >= 40:
        logger.info(f'모니터: VIX {vix:.1f} ≥ 40, 전체 스킵')
        return

    # 중복 알림 방지 추적
    last_alert: dict = context.bot_data.setdefault('last_alert', {})
    now = datetime.now(UTC)

    reached = []
    near    = []

    for ticker, info in candidates.items():
        snap = await loop.run_in_executor(None, fetch_ticker_snapshot, ticker)
        await asyncio.sleep(0.35)  # KIS rate limit 방지
        if snap is None:
            continue

        grade = info['grade']

        # VIX ≥ 30: A등급만 허용
        if vix is not None and vix >= 30 and grade != 'A':
            continue

        prev_close = snap['prev_close']
        plan    = calculate_buy_plan(prev_close, grade, vix, False, False,
                                     entry_pct_override=info.get('entry_pct'))
        entry   = plan['rounds'][0]['buy_price']
        current = snap['current_price']
        gap_pct = (entry - current) / current * 100  # 양수 = 진입가 아래

        # 쿨다운 체크 (30분 이내 이미 알림 보낸 종목 스킵)
        last = last_alert.get(ticker)
        if last and (now - last) < _ALERT_COOLDOWN:
            continue

        row = (ticker, grade, prev_close, entry, current, gap_pct, info['action'])

        if current <= entry:
            reached.append(row)
            last_alert[ticker] = now
        elif current < prev_close and gap_pct > -_NEAR_THRESHOLD:
            near.append(row)
            last_alert[ticker] = now

    if not reached and not near:
        return

    # ── 메시지 생성 ──────────────────────────────────────
    now_kst = datetime.now(KST).strftime('%H:%M KST')
    vix_txt = f'  VIX {vix:.1f}' if vix is not None else ''
    lines   = [f'🔔 <b>LevDip 자동 알림</b>  {now_kst}{vix_txt}', '']

    def _fmt(ticker, grade, prev_close, entry, current, pct, action):
        return [
            f'{_GRADE_EMOJI[grade]} <b>{ticker}</b>  ({pct:+.1f}%)',
            f'   전일종가 <code>${prev_close:,.2f}</code> → 진입가 <code>${entry:,.2f}</code> | 현재가 <code>${current:,.2f}</code>',
            *([ f'   <i>{action}</i>'] if action else []),
        ]

    if reached:
        lines.append('🔴 <b>진입가 도달!</b>')
        for row in sorted(reached, key=lambda x: x[5]):
            lines += _fmt(*row)

    if near:
        lines += ['', f'⚡ <b>진입가 {_NEAR_THRESHOLD:.0f}% 이내 근접</b>']
        for row in sorted(near, key=lambda x: x[5], reverse=True):
            lines += _fmt(*row)

    msg = '\n'.join(lines)

    for chat_id in list(chat_ids):
        try:
            await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML')
            logger.info(f'알림 발송 → chat_id={chat_id}')
        except Exception as e:
            logger.error(f'알림 발송 실패 (chat_id={chat_id}): {e}')
