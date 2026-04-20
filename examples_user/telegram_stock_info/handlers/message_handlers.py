"""텔레그램 메시지 핸들러 - 종목 분석"""
import logging
import asyncio
import functools

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import kis_auth as ka
from utils.formatter import format_analysis_message, format_error_message, format_analyzing_message
from utils.exceptions import (
    StockAnalysisError, StockNotFoundError, DataFetchError,
    InsufficientDataError, APIError, InvalidInputError
)
from handlers.state import add_to_history

logger = logging.getLogger(__name__)

# 분석 모듈 선택적 임포트
from analyzers.domestic import analyze_stock as analyze_domestic_stock

analyze_overseas_stock = None
try:
    from analyzers.overseas import analyze_stock as analyze_overseas_stock
    logger.info("해외주식 모듈 로드 성공")
except Exception as e:
    logger.warning(f"해외주식 모듈 로드 실패: {e}")

analyze_etf = None
try:
    from analyzers.etf import analyze_etf
    logger.info("ETF 모듈 로드 성공")
except Exception as e:
    logger.warning(f"ETF 모듈 로드 실패: {e}")


def handle_analysis_error(e: Exception) -> str:
    """분석 오류를 사용자 친화적 메시지로 변환"""
    if isinstance(e, StockNotFoundError):
        return format_error_message('not_found', str(e))
    elif isinstance(e, InvalidInputError):
        return format_error_message('format_error', str(e))
    elif isinstance(e, (DataFetchError, APIError)):
        return format_error_message('api_error', str(e))
    elif isinstance(e, InsufficientDataError):
        return format_error_message('insufficient_data', str(e))
    else:
        logger.error(f"예상치 못한 오류: {e}", exc_info=True)
        return format_error_message('api_error')


async def analyze_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """텍스트 입력 → 주식 분석"""
    stock_input = update.message.text.strip()
    user_id = update.effective_user.id

    # 거래소가 선택된 상태면 티커와 조합
    if 'selected_exchange' in context.user_data and ':' not in stock_input:
        stock_input = f"{context.user_data.pop('selected_exchange')}:{stock_input.upper()}"

    is_etf = stock_input.upper().startswith('ETF:')
    is_overseas = ':' in stock_input and not is_etf
    analysis_type = 'etf' if is_etf else ('overseas' if is_overseas else 'domestic')

    wait_msg = await update.message.reply_text(
        format_analyzing_message(stock_input, analysis_type)
    )

    try:
        ka.auth()
        loop = asyncio.get_running_loop()

        if is_etf:
            if analyze_etf is None:
                raise ValueError("ETF 분석 기능이 비활성화되어 있습니다.")
            parts = stock_input.split(':')
            if len(parts) != 2:
                raise ValueError("ETF는 'ETF:종목코드' 형식으로 입력해주세요. (예: ETF:069500)")
            result = await loop.run_in_executor(None, analyze_etf, parts[1])
            message = format_analysis_message(result, is_overseas=False, is_etf=True)
            add_to_history(user_id, stock_input, f"📈 {result.get('etf_name', stock_input)}")

        elif is_overseas:
            if analyze_overseas_stock is None:
                raise ValueError("해외주식 분석 기능이 비활성화되어 있습니다.")
            parts = stock_input.split(':')
            if len(parts) != 2:
                raise ValueError("해외주식은 '거래소:종목코드' 형식으로 입력해주세요. (예: NAS:TSLA)")
            excd, symb = parts[0].upper(), parts[1].upper()
            result = await loop.run_in_executor(
                None, functools.partial(analyze_overseas_stock, excd, symb)
            )
            message = format_analysis_message(result, is_overseas=True)
            add_to_history(user_id, stock_input, f"🇺🇸 {result.get('symbol', stock_input)}")

        else:
            # 국내주식 시도 → 실패 시 ETF 재시도
            try:
                result = await loop.run_in_executor(None, analyze_domestic_stock, stock_input)
                message = format_analysis_message(result, is_overseas=False)
                add_to_history(user_id, stock_input, f"🇰🇷 {result.get('stock_name', stock_input)}")
            except Exception as stock_error:
                if analyze_etf is not None and len(stock_input) == 6:
                    logger.info(f"국내주식 검색 실패, ETF로 재시도: {stock_input}")
                    try:
                        result = await loop.run_in_executor(None, analyze_etf, stock_input)
                        message = format_analysis_message(result, is_overseas=False, is_etf=True)
                        add_to_history(user_id, stock_input, f"📈 {result.get('etf_name', stock_input)}")
                    except Exception as etf_error:
                        logger.error(f"ETF 검색도 실패: {etf_error}")
                        raise stock_error
                else:
                    raise stock_error

        # 캔들 지지/저항 버튼 추가
        reply_markup = None
        if result.get('candle_sr'):
            cache_key = f'candle_sr|{stock_input}'
            context.user_data[cache_key] = {
                'data': result['candle_sr'],
                'is_overseas': is_overseas
            }
            keyboard = [[InlineKeyboardButton(
                "🕯 캔들 지지/저항 보기",
                callback_data=cache_key
            )]]
            reply_markup = InlineKeyboardMarkup(keyboard)

        await wait_msg.edit_text(message, parse_mode='HTML', reply_markup=reply_markup)

    except StockAnalysisError as e:
        await wait_msg.edit_text(handle_analysis_error(e))
    except Exception as e:
        logger.error(f"분석 중 예상치 못한 오류: {e}", exc_info=True)
        await wait_msg.edit_text(handle_analysis_error(e))
