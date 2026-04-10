"""텔레그램 커맨드 핸들러 (/start, /help, /vol, /history)"""
import logging
import asyncio
import functools

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import kis_auth as ka
from analyzers.domestic import get_stock_code
from utils.analysis_utils import analyze_intraday_volume_sr
from utils.formatter import format_intraday_sr_message
from utils.exceptions import StockAnalysisError
from handlers.state import user_history
from handlers.message_handlers import handle_analysis_error

logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start 명령어 핸들러"""
    user_id = update.effective_user.id

    keyboard = []
    if user_id in user_history and user_history[user_id]:
        keyboard.append([InlineKeyboardButton("📜 최근 검색 기록", callback_data="show_history")])
    keyboard.append([InlineKeyboardButton("🌍 해외주식 거래소 선택", callback_data="select_exchange")])

    await update.message.reply_text(
        "📈 주식 분석 봇입니다!\n\n"
        "🇰🇷 <b>국내주식</b>\n"
        "• 종목명 또는 종목코드 입력\n"
        "• 예: 삼성전자, NAVER, 005930\n\n"
        "🇺🇸 <b>해외주식</b>\n"
        "• '해외주식 거래소 선택' 버튼 클릭\n"
        "• 또는 직접 입력: 거래소:티커 (예: NAS:TSLA)\n\n"
        "명령어:\n"
        "/start - 시작\n"
        "/help - 도움말\n"
        "/history - 최근 검색 기록\n"
        "/vol <종목> - 당일 1분봉 지지/저항",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/help 명령어 핸들러"""
    await update.message.reply_text(
        "📊 <b>주식 분석 봇 사용법</b>\n\n"
        "<b>🇰🇷 국내주식</b>\n"
        "종목명 또는 종목코드 입력\n"
        "• 2년치 데이터 분석\n"
        "예: 삼성전자, NAVER, 005930\n\n"
        "<b>🇺🇸 해외주식</b>\n"
        "거래소:종목코드 형식 입력\n"
        "• 1년치 데이터 분석\n"
        "예: NAS:TSLA, NYS:AAPL, NAS:NVDA\n\n"
        "<b>📈 ETF</b>\n"
        "종목코드 직접 입력\n"
        "• 3년치 데이터 분석\n"
        "예: 069500, 152100\n\n"
        "<b>거래소 코드:</b>\n"
        "• NAS: 나스닥\n"
        "• NYS: 뉴욕증권거래소\n"
        "• AMS: 아멕스\n\n"
        "<b>📊 당일 1분봉 지지/저항</b>\n"
        "/vol <종목명 또는 코드>\n"
        "예: /vol 삼성전자, /vol 005930\n\n"
        "<b>분석 내용:</b>\n"
        "• 저항선/지지선 (거래량 기반)\n"
        "• 이동평균선 분석 (5, 10, 20, 60, 120일)\n"
        "• 주요 가격대 식별",
        parse_mode='HTML'
    )


async def vol_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/vol - 당일 1분봉 거래량 기반 지지/저항 조회"""
    if not context.args:
        await update.message.reply_text(
            "📊 <b>1분봉 거래량 지지/저항 조회</b>\n\n"
            "사용법: /vol <종목명 또는 코드>\n"
            "예: /vol 삼성전자\n"
            "예: /vol 005930",
            parse_mode='HTML'
        )
        return

    stock_input = ' '.join(context.args).strip()
    wait_msg = await update.message.reply_text(
        f"🔍 '{stock_input}' 당일 1분봉 분석 중...\n(약 10~20초 소요)"
    )

    try:
        ka.auth()
        loop = asyncio.get_running_loop()

        if len(stock_input) == 6 and stock_input.isdigit():
            stock_code = stock_input
            stock_name = stock_input
        else:
            stock_code, stock_name, _ = get_stock_code(stock_input)

        result = await loop.run_in_executor(
            None,
            functools.partial(analyze_intraday_volume_sr, stock_code, stock_name, "real")
        )

        await wait_msg.edit_text(format_intraday_sr_message(result), parse_mode='HTML')

    except StockAnalysisError as e:
        await wait_msg.edit_text(handle_analysis_error(e))
    except Exception as e:
        logger.error(f"/vol 분석 오류: {e}", exc_info=True)
        await wait_msg.edit_text(handle_analysis_error(e))


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/history - 최근 검색 기록"""
    user_id = update.effective_user.id

    if user_id not in user_history or not user_history[user_id]:
        await update.message.reply_text(
            "📜 최근 검색 기록이 없습니다.\n\n"
            "종목을 검색하면 여기에 표시됩니다."
        )
        return

    keyboard = [
        [InlineKeyboardButton(item['display'], callback_data=f"stock:{item['input']}")]
        for item in user_history[user_id]
    ]
    keyboard.append([InlineKeyboardButton("🗑️ 기록 삭제", callback_data="clear_history")])

    await update.message.reply_text(
        "📜 <b>최근 검색 기록</b>\n\n버튼을 눌러 다시 조회하세요!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )
