"""텔레그램 핸들러 — 커맨드·메시지·콜백"""
import logging
import asyncio
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from calc import TICKER_GRADE
from fetcher import fetch_prev_close, fetch_vix, fetch_ma_status
from formatter import (
    format_first_entry, format_add_buy_result,
    format_start_message, format_help_message,
    format_list_message, format_unknown_ticker,
)

logger = logging.getLogger(__name__)

# ConversationHandler 상태
WAITING_AVG = 1


# ──────────────────────────────────────────────────────────
#  인라인 키보드
# ──────────────────────────────────────────────────────────
def _make_keyboard(ticker: str, close: float, date: str,
                   vix: Optional[float], below_50ma: bool, below_200ma: bool) -> InlineKeyboardMarkup:
    vix_s = f'{vix:.1f}' if vix else ''
    ab_base = f"addbuy|{ticker}|{close:.2f}|{date}|{vix_s}|{int(below_50ma)}|{int(below_200ma)}"
    return InlineKeyboardMarkup([[
        InlineKeyboardButton('2차 추매', callback_data=f'{ab_base}|2'),
        InlineKeyboardButton('3차 추매', callback_data=f'{ab_base}|3'),
        InlineKeyboardButton('4차 추매', callback_data=f'{ab_base}|4'),
        InlineKeyboardButton('5차 추매', callback_data=f'{ab_base}|5'),
    ]])


# ──────────────────────────────────────────────────────────
#  커맨드 핸들러
# ──────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(format_start_message(), parse_mode='HTML')


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(format_help_message(), parse_mode='HTML')


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(format_list_message(), parse_mode='HTML')


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """전 종목 50일/200일선 위치 스캔"""
    wait = await update.message.reply_text('🔍 전 종목 스캔 중... (잠시 대기)', parse_mode='HTML')

    loop = asyncio.get_running_loop()
    tickers = list(TICKER_GRADE.keys())

    results = await asyncio.gather(*[
        loop.run_in_executor(None, fetch_ma_status, t) for t in tickers
    ])

    normal, below50, below200 = [], [], []
    for ticker, (b50, b200) in zip(tickers, results):
        if b200:
            below200.append(ticker)
        elif b50:
            below50.append(ticker)
        else:
            normal.append(ticker)

    def _fmt(lst: list[str]) -> str:
        return ' '.join(sorted(lst)) if lst else '없음'

    msg = (
        '📊 <b>전 종목 MA 스캔 결과</b>\n\n'
        f'✅ <b>정상</b> ({len(normal)}개)\n'
        f'<code>{_fmt(normal)}</code>\n\n'
        f'📉 <b>50일선↓</b> ({len(below50)}개)\n'
        f'<code>{_fmt(below50)}</code>\n\n'
        f'🚫 <b>200일선↓</b> ({len(below200)}개)\n'
        f'<code>{_fmt(below200)}</code>'
    )
    await wait.edit_text(msg, parse_mode='HTML')


async def cmd_vix(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wait = await update.message.reply_text('VIX 조회 중...')
    loop = asyncio.get_running_loop()
    vix = await loop.run_in_executor(None, fetch_vix)

    if vix is None:
        await wait.edit_text('❌ VIX 조회 실패')
        return

    if vix >= 40:
        comment = '🚫 전부 쉰다'
    elif vix >= 30:
        comment = '🚫 신규 거의 중단'
    elif vix >= 22:
        comment = '⚠️ 1차 진입 1%p 더 깊게'
    else:
        comment = '✅ 정상 운용'

    await wait.edit_text(
        f'📈 <b>VIX 현재값: {vix:.2f}</b>\n{comment}',
        parse_mode='HTML'
    )


# ──────────────────────────────────────────────────────────
#  메시지 핸들러 — 티커 입력 → 1차 진입가
# ──────────────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ticker = update.message.text.strip().upper().split()[0]

    if ticker not in TICKER_GRADE:
        await update.message.reply_text(format_unknown_ticker(ticker), parse_mode='HTML')
        return

    wait = await update.message.reply_text(f'🔍 <b>{ticker}</b> 조회 중...', parse_mode='HTML')

    try:
        loop = asyncio.get_running_loop()
        (close, date), vix, (below_50ma, below_200ma) = await asyncio.gather(
            loop.run_in_executor(None, fetch_prev_close, ticker),
            loop.run_in_executor(None, fetch_vix),
            loop.run_in_executor(None, fetch_ma_status, ticker),
        )

        msg = format_first_entry(ticker, close, date, vix, below_50ma, below_200ma)
        kb = _make_keyboard(ticker, close, date, vix, below_50ma, below_200ma)
        await wait.edit_text(msg, parse_mode='HTML', reply_markup=kb)

    except Exception as e:
        logger.error(f'{ticker} 처리 오류: {e}', exc_info=True)
        await wait.edit_text(f'❌ 오류 발생: {e}')


# ──────────────────────────────────────────────────────────
#  콜백 — 시장 위치 버튼 (calc|...)
# ──────────────────────────────────────────────────────────
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        _, ticker, close_str, date, vix_str, b50_str, b200_str = query.data.split('|')
        close = float(close_str)
        vix = float(vix_str) if vix_str else None
        below_50ma = bool(int(b50_str))
        below_200ma = bool(int(b200_str))
    except Exception as e:
        logger.error(f'콜백 파싱 오류: {e}')
        await query.edit_message_text('❌ 오류가 발생했습니다. 다시 입력해 주세요.')
        return

    msg = format_first_entry(ticker, close, date, vix, below_50ma, below_200ma)
    kb = _make_keyboard(ticker, close, date, vix, below_50ma, below_200ma)
    await query.edit_message_text(msg, parse_mode='HTML', reply_markup=kb)


# ──────────────────────────────────────────────────────────
#  콜백 — 추매 버튼 (addbuy|...) → 평단 입력 대기
# ──────────────────────────────────────────────────────────
async def handle_addbuy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        # addbuy|TICKER|CLOSE|DATE|VIX|BELOW50|BELOW200|ROUND
        _, ticker, close_str, date, vix_str, b50_str, b200_str, round_str = query.data.split('|')
        close = float(close_str)
        vix = float(vix_str) if vix_str else None
        below_50ma = bool(int(b50_str))
        below_200ma = bool(int(b200_str))
        from_round = int(round_str)
    except Exception as e:
        logger.error(f'추매 콜백 파싱 오류: {e}')
        await query.answer('파싱 오류가 발생했습니다.', show_alert=True)
        return ConversationHandler.END

    context.user_data.update({
        'ticker': ticker,
        'close': close,
        'date': date,
        'vix': vix,
        'below_50ma': below_50ma,
        'below_200ma': below_200ma,
        'from_round': from_round,
    })

    await query.message.reply_text(
        f'📊 <b>{ticker} {from_round}차 추매 계산</b>\n\n'
        f'현재 보유 <b>평단(평균매수가)</b>을 입력해주세요:\n'
        f'<i>예: 52.30</i>\n\n'
        f'/cancel — 취소',
        parse_mode='HTML',
    )
    return WAITING_AVG


# ──────────────────────────────────────────────────────────
#  평단 입력 수신 → 추매 계획 계산
# ──────────────────────────────────────────────────────────
async def handle_avg_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    try:
        avg_price = float(text.replace(',', ''))
        if avg_price <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text('❌ 숫자로 입력해주세요. (예: 52.30)')
        return WAITING_AVG  # 재입력 대기

    d = context.user_data
    msg = format_add_buy_result(
        ticker=d['ticker'],
        close_price=d['close'],
        close_date=d['date'],
        vix=d['vix'],
        below_50ma=d['below_50ma'],
        below_200ma=d['below_200ma'],
        from_round=d['from_round'],
        input_avg=avg_price,
    )
    await update.message.reply_text(msg, parse_mode='HTML')

    context.user_data.clear()
    return ConversationHandler.END


async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text('취소했습니다.')
    return ConversationHandler.END
