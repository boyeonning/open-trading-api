"""국내주식 수급 스크리너 — 텔레그램 핸들러"""
import asyncio
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from domestic_flow.flow import (
    fetch_ssangkkuli_flow, fetch_consecutive_flow, fetch_pullback_flow,
    format_ssangkkuli_message, format_consecutive_message, format_pullback_message,
    MARKET_CODES,
)

logger = logging.getLogger(__name__)

_FLOW_MODES = ['ssang', 'consec', 'pullback']
_MODE_LABELS = {
    'ssang':    '쌍끌이',
    'consec':   '5일 연속',
    'pullback': '눌림목',
}


def flow_keyboard(market: str, mode: str) -> InlineKeyboardMarkup:
    markets = ['코스피', '코스닥']

    mode_row = [
        InlineKeyboardButton(
            f'{"✅" if m == mode else ""}{_MODE_LABELS[m]}',
            callback_data=f'flow|{market}|{m}'
        )
        for m in _FLOW_MODES
    ]
    mkt_row = [
        InlineKeyboardButton(
            f'{"✅" if mk == market else ""}{mk}',
            callback_data=f'flow|{mk}|{mode}'
        )
        for mk in markets
    ]
    return InlineKeyboardMarkup([mode_row, mkt_row])


async def _run_flow(mode: str, market: str, loop) -> tuple[str, str]:
    """모드별 수급 조회 → (로딩 메시지, 결과 메시지)"""
    if mode == 'ssang':
        loading = '📡 쌍끌이 종목 조회 중...'
        rows = await loop.run_in_executor(None, fetch_ssangkkuli_flow, market)
        msg  = format_ssangkkuli_message(rows, market)

    elif mode == 'consec':
        loading = '🔍 5일 연속 수급 탐색 중...\n<i>(약 15~30초 소요)</i>'
        rows = await loop.run_in_executor(None, fetch_consecutive_flow, 5, market, '전체')
        msg  = format_consecutive_message(rows, 5, market, '전체')

    elif mode == 'pullback':
        loading = (
            '🔍 눌림목 수급 종목 탐색 중...\n'
            '<i>3일 연속수급 + 5일고점 -1~-15% 조정\n'
            '(약 30~60초 소요)</i>'
        )
        rows = await loop.run_in_executor(None, fetch_pullback_flow, market)
        msg  = format_pullback_message(rows, market)

    else:
        loading = ''
        msg = '❌ 알 수 없는 모드'

    return loading, msg


async def cmd_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/flow — 기본값: 코스피 쌍끌이"""
    market = '코스피'
    mode   = 'ssang'

    wait = await update.message.reply_text('📡 수급 조회 중...', parse_mode='HTML')
    loop = asyncio.get_running_loop()
    try:
        _, msg = await _run_flow(mode, market, loop)
        await wait.edit_text(msg, parse_mode='HTML', reply_markup=flow_keyboard(market, mode))
    except Exception as e:
        logger.error(f'수급 조회 오류: {e}', exc_info=True)
        await wait.edit_text(f'❌ 수급 조회 실패: {e}')


async def handle_flow_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """수급 버튼 콜백"""
    query = update.callback_query
    await query.answer()

    try:
        _, market, mode = query.data.split('|')
    except Exception:
        await query.answer('파싱 오류', show_alert=True)
        return

    if market not in MARKET_CODES or mode not in _FLOW_MODES:
        await query.answer('잘못된 파라미터', show_alert=True)
        return

    loop = asyncio.get_running_loop()
    loading, _ = await _run_flow(mode, market, loop)
    await query.edit_message_text(loading, parse_mode='HTML')

    try:
        _, msg = await _run_flow(mode, market, loop)
        await query.edit_message_text(msg, parse_mode='HTML', reply_markup=flow_keyboard(market, mode))
    except Exception as e:
        logger.error(f'수급 콜백 오류: {e}', exc_info=True)
        await query.edit_message_text(f'❌ 수급 조회 실패: {e}')
