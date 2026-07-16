"""국내주식 수급 스크리너 — 텔레그램 핸들러"""
import asyncio
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from domestic_flow.flow import (
    fetch_ssangkkuli_flow, fetch_consecutive_flow, fetch_pullback_flow,
    format_ssangkkuli_message, format_consecutive_message, format_pullback_message,
)

logger = logging.getLogger(__name__)

_FLOW_MODES = ['ssang', 'consec', 'pullback']
_MODE_LABELS = {
    'ssang':    '쌍끌이',
    'consec':   '5일 연속',
    'pullback': '양음양',
}
_LOADING_MSG = {
    'ssang':    '📡 쌍끌이 종목 조회 중...',
    'consec':   '🔍 5일 연속 수급 탐색 중...\n<i>(약 15~30초 소요)</i>',
    'pullback': '🕯 양음양 눌림목 탐색 중...\n<i>전 종목 스캔 중 (약 2~3분 소요)\n전일 장대양봉 + 오늘 음봉·거래량↓</i>',
}


def flow_keyboard() -> InlineKeyboardMarkup:
    """모드 선택 버튼 3개 — 클릭 즉시 코스피+코스닥 동시 조회"""
    row = [
        InlineKeyboardButton(_MODE_LABELS[m], callback_data=f'flow|{m}')
        for m in _FLOW_MODES
    ]
    return InlineKeyboardMarkup([row])


async def _run_flow(mode: str, loop) -> str:
    """코스피+코스닥 동시 조회 후 하나의 메시지로 반환"""
    if mode == 'ssang':
        kospi_rows, kosdaq_rows = await asyncio.gather(
            loop.run_in_executor(None, fetch_ssangkkuli_flow, '코스피'),
            loop.run_in_executor(None, fetch_ssangkkuli_flow, '코스닥'),
        )
        return (
            format_ssangkkuli_message(kospi_rows, '코스피')
            + '\n\n'
            + format_ssangkkuli_message(kosdaq_rows, '코스닥')
        )

    elif mode == 'consec':
        kospi_rows, kosdaq_rows = await asyncio.gather(
            loop.run_in_executor(None, fetch_consecutive_flow, 5, '코스피', '전체'),
            loop.run_in_executor(None, fetch_consecutive_flow, 5, '코스닥', '전체'),
        )
        return (
            format_consecutive_message(kospi_rows, 5, '코스피', '전체')
            + '\n\n'
            + format_consecutive_message(kosdaq_rows, 5, '코스닥', '전체')
        )

    elif mode == 'pullback':
        kospi_rows, kosdaq_rows = await asyncio.gather(
            loop.run_in_executor(None, fetch_pullback_flow, '코스피'),
            loop.run_in_executor(None, fetch_pullback_flow, '코스닥'),
        )
        msg = (
            format_pullback_message(kospi_rows, '코스피')
            + '\n\n'
            + format_pullback_message(kosdaq_rows, '코스닥')
        )
        return msg[:4000] + ('...' if len(msg) > 4000 else '')

    return '❌ 알 수 없는 모드'



async def cmd_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/flow — 기본값: 쌍끌이 (코스피+코스닥)"""
    wait = await update.message.reply_text(_LOADING_MSG['ssang'], parse_mode='HTML')
    loop = asyncio.get_running_loop()
    try:
        msg = await _run_flow('ssang', loop)
        await wait.edit_text(msg, parse_mode='HTML', reply_markup=flow_keyboard())
    except Exception as e:
        logger.error(f'수급 조회 오류: {e}', exc_info=True)
        await wait.edit_text(f'❌ 수급 조회 실패: {e}')


async def handle_flow_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """수급 버튼 콜백"""
    query = update.callback_query
    await query.answer()

    try:
        _, mode = query.data.split('|')
    except Exception:
        await query.answer('파싱 오류', show_alert=True)
        return

    if mode not in _FLOW_MODES:
        await query.answer('잘못된 파라미터', show_alert=True)
        return

    await query.edit_message_text(_LOADING_MSG[mode], parse_mode='HTML')

    loop = asyncio.get_running_loop()
    try:
        msg = await _run_flow(mode, loop)
        await query.edit_message_text(msg, parse_mode='HTML', reply_markup=flow_keyboard())
    except Exception as e:
        logger.error(f'수급 콜백 오류: {e}', exc_info=True)
        await query.edit_message_text(f'❌ 수급 조회 실패: {e}')
