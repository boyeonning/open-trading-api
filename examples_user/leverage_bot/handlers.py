"""텔레그램 핸들러 — 커맨드·메시지·콜백"""
import logging
import asyncio
import math
from datetime import datetime, timezone, timedelta
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from calc import TICKER_GRADE, calculate_buy_plan
from fetcher import fetch_prev_close, fetch_vix, fetch_ma_status, fetch_ticker_snapshot
from weekly_config import (
    WATCHLIST, WEEKLY_DATE, WEEKLY_TITLE,
    SIGNAL_GO, SIGNAL_COND, SIGNAL_HOLD, SIGNAL_STOP,
)

KST = timezone(timedelta(hours=9))
from formatter import (
    format_first_entry, format_add_buy_result,
    format_start_message, format_help_message,
    format_list_message, format_unknown_ticker,
)

logger = logging.getLogger(__name__)

# ConversationHandler 상태
WAITING_AVG = 1

# 등급 입력 약어 → grade key (HTML 기법표 A~E 등급)
_GRADE_MAP = {
    'a': 'A',
    'b': 'B',
    'c': 'C',
    'd': 'D',
    'e': 'E',
}


# ──────────────────────────────────────────────────────────
#  인라인 키보드
# ──────────────────────────────────────────────────────────
def _menu_keyboard() -> InlineKeyboardMarkup:
    """메인 메뉴 인라인 키보드"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton('📈 VIX 확인',     callback_data='menu|vix'),
        ],
        [
            InlineKeyboardButton('🔄 쌍끌이',   callback_data='flow|ssang'),
            InlineKeyboardButton('📅 5일연속',  callback_data='flow|consec'),
            InlineKeyboardButton('🕯 양음양',   callback_data='flow|pullback'),
        ],
    ])


def _make_keyboard(ticker: str, grade: str, close: float, date: str,
                   vix: Optional[float], below_50ma: bool, below_200ma: bool) -> InlineKeyboardMarkup:
    vix_s = f'{vix:.1f}' if vix else ''
    ab_base = f"addbuy|{ticker}|{grade}|{close:.2f}|{date}|{vix_s}|{int(below_50ma)}|{int(below_200ma)}"
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
    # 시작하는 순간 자동으로 알림 구독 (별도 /alert on 없이)
    chat_id = update.effective_chat.id
    context.bot_data.setdefault('alert_chats', set()).add(chat_id)
    logger.warning(f"chat_id: {chat_id}")
    await update.message.reply_text(
        '📊 <b>LevDip</b>  레버리지 ETF 눌림 매수 도우미\n\n'
        '버튼을 눌러 원하는 기능을 선택하세요.\n'
        '<i>티커를 직접 입력하면 진입가를 바로 계산합니다.</i>',
        parse_mode='HTML',
        reply_markup=_menu_keyboard(),
    )


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
async def cmd_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """이번 주 기법 데이터 요약 (weekly_config 기준)"""
    _GRADE_EMOJI = {'A': '🔵', 'B': '🟢', 'C': '🟡', 'D': '🟠', 'E': '🔴'}

    go   = [(t, i) for t, i in WATCHLIST.items() if i['signal'] in SIGNAL_GO]
    cond = [(t, i) for t, i in WATCHLIST.items() if i['signal'] in SIGNAL_COND]
    hold = [(t, i) for t, i in WATCHLIST.items() if i['signal'] in SIGNAL_HOLD]
    stop = [(t, i) for t, i in WATCHLIST.items() if i['signal'] in SIGNAL_STOP]

    def _fmt(items):
        return '  '.join(
            f'{_GRADE_EMOJI[i["grade"]]}{t}({i["grade"]})' for t, i in sorted(items)
        ) or '없음'

    lines = [
        f'📋 <b>주간 기법</b>  {WEEKLY_TITLE}',
        f'기준일: {WEEKLY_DATE}  총 {len(WATCHLIST)}종목',
        '',
        f'🔵🟢 <b>진입 검토</b> ({len(go)}종목)',
        _fmt(go),
        '',
        f'🟡 <b>조건부</b> ({len(cond)}종목)',
        _fmt(cond),
        '',
        f'🟠 <b>신규 보류</b> ({len(hold)}종목)',
        _fmt(hold),
        '',
        f'🔴 <b>접근 금지</b> ({len(stop)}종목)',
        _fmt(stop),
    ]
    await update.message.reply_text('\n'.join(lines), parse_mode='HTML')


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts = update.message.text.strip().upper().split()
    ticker = parts[0]
    grade_input = parts[1].lower() if len(parts) > 1 else None

    # 등급 우선순위: 직접 입력 > weekly_config > calc.py TICKER_GRADE
    if grade_input and _GRADE_MAP.get(grade_input):
        grade = _GRADE_MAP[grade_input]
    else:
        weekly_info = WATCHLIST.get(ticker)
        grade = (weekly_info['grade'] if weekly_info else None) or TICKER_GRADE.get(ticker)

    if not grade:
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

        msg = format_first_entry(ticker, close, date, vix, below_50ma, below_200ma, grade)
        kb = _make_keyboard(ticker, grade, close, date, vix, below_50ma, below_200ma)
        await wait.edit_text(msg, parse_mode='HTML', reply_markup=kb)

    except Exception as e:
        logger.error(f'{ticker} 처리 오류: {e}', exc_info=True)
        await wait.edit_text(f'❌ 오류 발생: {e}')


# ──────────────────────────────────────────────────────────
#  콜백 — 메뉴 버튼 (menu|...)
# ──────────────────────────────────────────────────────────
async def handle_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, action = query.data.split('|', 1)

    # 공통: 메뉴 메시지를 로딩 텍스트로 교체 후 결과로 갱신
    _LOADING = {
        'vix':    '⏳ VIX 조회 중...',
        'weekly': '',
    }

    if action == 'weekly':
        _GE = {'A': '🔵', 'B': '🟢', 'C': '🟡', 'D': '🟠', 'E': '🔴'}
        go   = [(t, i) for t, i in WATCHLIST.items() if i['signal'] in SIGNAL_GO]
        cond = [(t, i) for t, i in WATCHLIST.items() if i['signal'] in SIGNAL_COND]
        hold = [(t, i) for t, i in WATCHLIST.items() if i['signal'] in SIGNAL_HOLD]
        stop = [(t, i) for t, i in WATCHLIST.items() if i['signal'] in SIGNAL_STOP]
        def _fmt(items):
            return '  '.join(f'{_GE[i["grade"]]}{t}({i["grade"]})' for t, i in sorted(items)) or '없음'
        msg = '\n'.join([
            f'📋 <b>주간 기법</b>  {WEEKLY_TITLE}',
            f'기준일: {WEEKLY_DATE}  총 {len(WATCHLIST)}종목', '',
            f'🔵🟢 <b>진입 검토</b> ({len(go)}종목)', _fmt(go), '',
            f'🟡 <b>조건부</b> ({len(cond)}종목)', _fmt(cond), '',
            f'🟠 <b>신규 보류</b> ({len(hold)}종목)', _fmt(hold), '',
            f'🔴 <b>접근 금지</b> ({len(stop)}종목)', _fmt(stop),
        ])
        await query.edit_message_text(msg, parse_mode='HTML', reply_markup=_menu_keyboard())
        return

    if action == 'back':
        await query.edit_message_text(
            '📊 <b>LevDip</b>  레버리지 ETF 눌림 매수 도우미\n\n'
            '버튼을 눌러 원하는 기능을 선택하세요.\n'
            '<i>티커를 직접 입력하면 진입가를 바로 계산합니다.</i>',
            parse_mode='HTML',
            reply_markup=_menu_keyboard(),
        )
        return

    # 로딩 메시지 표시
    await query.edit_message_text(_LOADING.get(action, '⏳ 로딩 중...'), parse_mode='HTML')
    loop = asyncio.get_running_loop()

    try:
        if action == 'check':
            from domestic_flow.handlers import _run_flow  # noqa — 재사용 불가, 직접 구현
            msg = await _run_cmd_check(loop)
            await query.edit_message_text(msg, parse_mode='HTML', reply_markup=_menu_keyboard())

        elif action == 'vix':
            vix = await loop.run_in_executor(None, fetch_vix)
            if vix is None:
                msg = '❌ VIX 조회 실패'
            else:
                level = '😱 극도 공포' if vix >= 40 else ('⚠️ 공포' if vix >= 30 else ('😰 경계' if vix >= 20 else '😊 안정'))
                msg = f'📈 <b>VIX</b>  <code>{vix:.2f}</code>  {level}'
            await query.edit_message_text(msg, parse_mode='HTML', reply_markup=_menu_keyboard())




    except Exception as e:
        logger.error(f'메뉴 콜백 오류 ({action}): {e}', exc_info=True)
        await query.edit_message_text(f'❌ 오류: {e}', reply_markup=_menu_keyboard())


async def _run_cmd_check(loop) -> str:
    """cmd_check 로직 재사용 — menu|check 콜백용"""
    vix = await loop.run_in_executor(None, fetch_vix)

    candidates = {
        t: info for t, info in WATCHLIST.items()
        if info['signal'] in SIGNAL_GO | SIGNAL_COND
    }

    lines = ['📊 <b>진입가 스캔</b>\n']
    reached, near, rest = [], [], []

    for ticker, info in candidates.items():
        snap = await loop.run_in_executor(None, fetch_ticker_snapshot, ticker)
        await asyncio.sleep(0.35)
        if snap is None:
            continue
        grade = info['grade']
        plan  = calculate_buy_plan(snap['prev_close'], grade, vix, False, False,
                                   entry_pct_override=info.get('entry_pct'))
        entry   = plan['rounds'][0]['buy_price']
        current = snap['current_price']
        gap_pct = (entry - current) / current * 100
        signal  = info['signal']
        row = (ticker, grade, signal, snap['prev_close'], entry, current, gap_pct)

        if current <= entry:
            reached.append(row)
        elif gap_pct > -1.0:
            near.append(row)
        else:
            rest.append(row)

    def _fmt(rows, label):
        out = [f'<b>{label}</b>']
        for ticker, grade, signal, prev, entry, current, gap in sorted(rows, key=lambda x: x[6]):
            out.append(
                f'{signal} <b>{ticker}</b>  현재 <code>${current:,.2f}</code>  '
                f'진입 <code>${entry:,.2f}</code>  ({gap:+.1f}%)'
            )
        return '\n'.join(out)

    if reached:
        lines.append(_fmt(reached, '🔴 진입가 도달'))
    if near:
        lines.append(_fmt(near, '⚡ 1% 이내 근접'))
    if rest:
        lines.append(_fmt(rest, '📋 대기 중'))

    vix_txt = f'\n\n<i>VIX {vix:.1f}</i>' if vix else ''
    return '\n\n'.join(lines) + vix_txt


# ──────────────────────────────────────────────────────────
#  콜백 — 시장 위치 버튼 (calc|...)
# ──────────────────────────────────────────────────────────
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        _, ticker, grade, close_str, date, vix_str, b50_str, b200_str = query.data.split('|')
        close = float(close_str)
        vix = float(vix_str) if vix_str else None
        below_50ma = bool(int(b50_str))
        below_200ma = bool(int(b200_str))
    except Exception as e:
        logger.error(f'콜백 파싱 오류: {e}')
        await query.edit_message_text('❌ 오류가 발생했습니다. 다시 입력해 주세요.')
        return

    msg = format_first_entry(ticker, close, date, vix, below_50ma, below_200ma, grade)
    kb = _make_keyboard(ticker, grade, close, date, vix, below_50ma, below_200ma)
    await query.edit_message_text(msg, parse_mode='HTML', reply_markup=kb)


# ──────────────────────────────────────────────────────────
#  콜백 — 추매 버튼 (addbuy|...) → 평단 입력 대기
# ──────────────────────────────────────────────────────────
async def handle_addbuy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        # addbuy|TICKER|GRADE|CLOSE|DATE|VIX|BELOW50|BELOW200|ROUND
        _, ticker, grade, close_str, date, vix_str, b50_str, b200_str, round_str = query.data.split('|')
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
        'grade': grade,
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
        grade=d.get('grade'),
    )
    await update.message.reply_text(msg, parse_mode='HTML')

    context.user_data.clear()
    return ConversationHandler.END


async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text('취소했습니다.')
    return ConversationHandler.END


