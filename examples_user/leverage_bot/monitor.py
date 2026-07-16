"""가격 모니터링 — 5분 주기 자동 알림 잡

동작 조건:
  - /alert on 으로 구독한 채팅에만 발송
  - 미국 주식시장 운영 시간(UTC 13:00~21:30, 평일)에만 실행
  - 같은 종목 30분 이내 중복 알림 방지
  - VIX ≥ 40 이면 전체 스킵

알림 기준:
  - 현재가 ≤ 진입가        → 🔴 진입가 도달
  - 현재가 < 전일종가 and 진입가까지 3% 이내 → ⚡ 근접

양음양 알림:
  - 평일 09:05 (장 시작 직후) + 14:50 (종가 매수 타이밍) 2회 발송
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from telegram.ext import ContextTypes

from weekly_config import WATCHLIST, SIGNAL_GO
from calc import calculate_buy_plan
from fetcher import fetch_vix, fetch_ticker_snapshot
from domestic_flow.flow import fetch_pullback_flow, format_pullback_message, _fetch_market_phase

logger = logging.getLogger(__name__)

UTC = timezone.utc
KST = timezone(timedelta(hours=9))

_GRADE_EMOJI = {'A': '🔵', 'B': '🟢', 'C': '🟡', 'D': '🟠', 'E': '🔴'}

# 미국장 운영 시간대 (UTC) — 여름(EDT)/겨울(EST) 모두 커버
_OPEN_UTC  = 13 * 60      # 13:00 UTC (9:30 AM EDT 기준)
_CLOSE_UTC = 21 * 60 + 30 # 21:30 UTC (5:00 PM EDT 기준, 여유 포함)

_ALERT_COOLDOWN = timedelta(minutes=30)
_NEAR_THRESHOLD = 1.0  # 진입가까지 몇 % 이내를 근접으로 볼지 (너무 넓으면 오알림)


def _is_market_hours() -> bool:
    """현재가 미국 주식시장 운영 시간인지 확인"""
    now = datetime.now(UTC)
    if now.weekday() >= 5:  # 토·일
        return False
    minutes = now.hour * 60 + now.minute
    return _OPEN_UTC <= minutes <= _CLOSE_UTC


def _fmt_row(ticker, grade, prev_close, entry, current, pct, action):
    return [
        f'{_GRADE_EMOJI[grade]} <b>{ticker}</b>  ({pct:+.1f}%)',
        f'   전일종가 <code>${prev_close:,.2f}</code> → 진입가 <code>${entry:,.2f}</code> | 현재가 <code>${current:,.2f}</code>',
        *([ f'   <i>{action}</i>'] if action else []),
    ]


async def _run_check(context: ContextTypes.DEFAULT_TYPE, force: bool = False) -> str:
    """
    실제 가격 체크 로직. force=True 이면 쿨다운·장외 체크 무시.
    반환값: 알림 메시지 문자열 (알림 조건 없으면 상태 요약 문자열)
    """
    loop = asyncio.get_running_loop()
    candidates = {t: info for t, info in WATCHLIST.items() if info['signal'] in SIGNAL_GO}

    vix = await loop.run_in_executor(None, fetch_vix)
    if not force and vix is not None and vix >= 40:
        return f'VIX {vix:.1f} ≥ 40 — 전체 스킵'

    last_alert: dict = context.bot_data.setdefault('last_alert', {})
    now = datetime.now(UTC)

    reached, near, skipped = [], [], []

    for ticker, info in candidates.items():
        snap = await loop.run_in_executor(None, fetch_ticker_snapshot, ticker)
        await asyncio.sleep(0.35)
        if snap is None:
            skipped.append(ticker)
            continue

        grade = info['grade']
        if not force and vix is not None and vix >= 30 and grade != 'A':
            continue

        prev_close = snap['prev_close']
        plan    = calculate_buy_plan(prev_close, grade, vix, False, False,
                                     entry_pct_override=info.get('entry_pct'))
        entry   = plan['rounds'][0]['buy_price']
        current = snap['current_price']
        gap_pct = (entry - current) / current * 100

        last = last_alert.get(ticker)
        if not force and last and (now - last) < _ALERT_COOLDOWN:
            continue

        row = (ticker, grade, prev_close, entry, current, gap_pct, info['action'])

        if current <= entry:
            reached.append(row)
            if not force:
                last_alert[ticker] = now
        elif current < prev_close and gap_pct > -_NEAR_THRESHOLD:
            near.append(row)
            if not force:
                last_alert[ticker] = now

    # ── 메시지 생성 ──────────────────────────────────────
    now_kst = datetime.now(KST).strftime('%H:%M KST')
    vix_txt = f'  VIX {vix:.1f}' if vix is not None else ''
    prefix  = '🔍 <b>즉시 체크 결과</b>' if force else '🔔 <b>LevDip 자동 알림</b>'
    lines   = [f'{prefix}  {now_kst}{vix_txt}', '']

    if reached:
        lines.append('🔴 <b>진입가 도달!</b>')
        for row in sorted(reached, key=lambda x: x[5]):
            lines += _fmt_row(*row)
    if near:
        lines += ['', f'⚡ <b>진입가 {_NEAR_THRESHOLD:.0f}% 이내 근접</b>']
        for row in sorted(near, key=lambda x: x[5], reverse=True):
            lines += _fmt_row(*row)

    if not reached and not near:
        # 조건 미달 — 전 종목 현황 요약
        lines.append(f'조건 충족 종목 없음  ({len(candidates)}종목 체크)')
        if skipped:
            lines.append(f'조회 실패: {", ".join(skipped)}')

    return '\n'.join(lines)


async def check_and_alert(context: ContextTypes.DEFAULT_TYPE):
    """5분마다 실행 — 조건 충족 종목에 자동 알림 발송"""
    chat_ids: set = context.bot_data.get('alert_chats', set())
    if not chat_ids:
        return

    if not _is_market_hours():
        return

    msg = await _run_check(context, force=False)

    # 조건 미달이면 발송 안 함 (접두어로 구분)
    if '조건 충족 종목 없음' in msg or msg.startswith('VIX'):
        return

    for chat_id in list(chat_ids):
        try:
            await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML')
            logger.info(f'알림 발송 → chat_id={chat_id}')
        except Exception as e:
            logger.error(f'알림 발송 실패 (chat_id={chat_id}): {e}')


async def check_yangumyang_alert(context: ContextTypes.DEFAULT_TYPE):
    """평일 09:05 / 14:50 KST — 양음양 눌림목 종목 알림"""
    chat_ids: set = context.bot_data.get('alert_chats', set())
    if not chat_ids:
        return

    now_kst = datetime.now(KST)
    hour, minute = now_kst.hour, now_kst.minute
    # 09:05 또는 14:50 트리거 여부 표시
    if hour == 9 and minute < 10:
        label = '🌅 <b>장 시작 양음양 알림</b>'
    else:
        label = '🕯 <b>종가 매수 타이밍 — 양음양 알림</b>'

    loop = asyncio.get_running_loop()
    try:
        kospi_rows, kosdaq_rows, phase = await asyncio.gather(
            loop.run_in_executor(None, fetch_pullback_flow, '코스피'),
            loop.run_in_executor(None, fetch_pullback_flow, '코스닥'),
            loop.run_in_executor(None, _fetch_market_phase),
        )
    except Exception as e:
        logger.error(f'양음양 알림 스캔 실패: {e}', exc_info=True)
        return

    body = (
        format_pullback_message(kospi_rows, '코스피')
        + '\n\n'
        + format_pullback_message(kosdaq_rows, '코스닥')
    )
    time_str = now_kst.strftime('%H:%M KST')
    phase_str = f'\n{phase}\n' if phase else '\n'
    msg = f'{label}  {time_str}{phase_str}\n{body}'
    msg = msg[:4000] + ('...' if len(msg) > 4000 else '')

    for chat_id in list(chat_ids):
        try:
            await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML')
            logger.info(f'양음양 알림 발송 → chat_id={chat_id}')
        except Exception as e:
            logger.error(f'양음양 알림 발송 실패 (chat_id={chat_id}): {e}')
