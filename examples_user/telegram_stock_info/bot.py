"""텔레그램 봇 - 국내/해외 주식 분석"""
import sys
import logging
import os
import asyncio
import functools
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# 현재 디렉토리를 최우선으로 설정
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.extend(['..', '../..'])
import kis_auth as ka

from config import BOT_SETTINGS, EXCHANGE_NAMES, UI_MESSAGES
from exceptions import (
    StockAnalysisError, StockNotFoundError, DataFetchError,
    InsufficientDataError, APIError, InvalidInputError
)
from message_formatter import (
    format_analysis_message, format_error_message, format_analyzing_message,
    format_intraday_sr_message
)

# 로깅 설정
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 국내 주식 analyzer 임포트
from domestic_analyzer import analyze_stock as analyze_domestic_stock, get_stock_code
from analysis_utils import analyze_intraday_volume_sr

# 해외 주식 analyzer 임포트
analyze_overseas_stock = None
try:
    from overseas_analyzer import analyze_stock as analyze_overseas_stock
    logger.info("해외주식 모듈 로드 성공")
except Exception as e:
    logger.warning(f"해외주식 모듈 로드 실패: {e}")
    analyze_overseas_stock = None

# ETF analyzer 임포트
analyze_etf = None
try:
    from etf_analyzer import analyze_etf
    logger.info("ETF 모듈 로드 성공")
except Exception as e:
    logger.warning(f"ETF 모듈 로드 실패: {e}")
    analyze_etf = None

# 텔레그램 봇 토큰 (환경 변수에서 가져오기)
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN 환경 변수를 설정해주세요!")

# 사용자별 최근 검색 기록 저장
user_history = {}


# format_analysis_message 함수는 message_formatter 모듈로 이동됨

def handle_analysis_error(e: Exception) -> str:
    """분석 오류를 사용자 친화적 메시지로 변환"""
    if isinstance(e, StockNotFoundError):
        return format_error_message('not_found', str(e))
    elif isinstance(e, InvalidInputError):
        return format_error_message('format_error', str(e))
    elif isinstance(e, DataFetchError):
        return format_error_message('api_error', str(e))
    elif isinstance(e, InsufficientDataError):
        return format_error_message('insufficient_data', str(e))
    elif isinstance(e, APIError):
        return format_error_message('api_error', str(e))
    else:
        logger.error(f"예상치 못한 오류: {e}", exc_info=True)
        return format_error_message('api_error')


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start 명령어 핸들러"""
    user_id = update.effective_user.id

    # 인라인 키보드 생성
    keyboard = []

    # 최근 검색 기록이 있으면 표시
    if user_id in user_history and user_history[user_id]:
        keyboard.append([InlineKeyboardButton("📜 최근 검색 기록", callback_data="show_history")])

    keyboard.append([InlineKeyboardButton("🌍 해외주식 거래소 선택", callback_data="select_exchange")])

    reply_markup = InlineKeyboardMarkup(keyboard)

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
        reply_markup=reply_markup,
        parse_mode='HTML'
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help 명령어 핸들러"""
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
    """/vol 명령어 - 당일 1분봉 거래량 기반 지지/저항 조회"""
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

        # 종목코드 확인
        if len(stock_input) == 6 and stock_input.isdigit():
            stock_code = stock_input
            stock_name = stock_input
        else:
            stock_code, stock_name, _ = get_stock_code(stock_input)

        result = await loop.run_in_executor(
            None,
            functools.partial(analyze_intraday_volume_sr, stock_code, stock_name, "real")
        )

        message = format_intraday_sr_message(result)
        await wait_msg.edit_text(message, parse_mode='HTML')

    except StockAnalysisError as e:
        await wait_msg.edit_text(handle_analysis_error(e))
    except Exception as e:
        logger.error(f"/vol 분석 오류: {e}", exc_info=True)
        await wait_msg.edit_text(handle_analysis_error(e))


async def analyze_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """메시지 핸들러 - 주식 분석"""
    stock_input = update.message.text.strip()

    # 거래소가 선택된 상태라면 티커와 조합
    if 'selected_exchange' in context.user_data and ':' not in stock_input:
        exchange_code = context.user_data['selected_exchange']
        stock_input = f"{exchange_code}:{stock_input.upper()}"
        # 사용 후 삭제
        del context.user_data['selected_exchange']

    # ETF 여부 판단
    is_etf = stock_input.upper().startswith('ETF:')

    # 해외주식 여부 판단 (거래소:종목코드 형식)
    is_overseas = ':' in stock_input and not is_etf

    # 분석 시작 메시지
    if is_etf:
        analysis_type = 'etf'
    elif is_overseas:
        analysis_type = 'overseas'
    else:
        analysis_type = 'domestic'
    
    wait_msg = await update.message.reply_text(
        format_analyzing_message(stock_input, analysis_type)
    )

    try:
        # KIS 인증
        ka.auth()

        # 주식/ETF 분석 (블로킹 I/O를 스레드풀로 실행해 이벤트 루프 블로킹 방지)
        loop = asyncio.get_running_loop()

        if is_etf:
            # ETF 모듈 체크
            if analyze_etf is None:
                raise ValueError("ETF 분석 기능이 비활성화되어 있습니다.")

            # ETF:종목코드 파싱
            parts = stock_input.split(':')
            if len(parts) != 2:
                raise ValueError("ETF는 'ETF:종목코드' 형식으로 입력해주세요. (예: ETF:069500)")

            iscd = parts[1]
            result = await loop.run_in_executor(None, analyze_etf, iscd)

            # ETF는 is_overseas=False로 처리 (국내 ETF)
            message = format_analysis_message(result, is_overseas=False, is_etf=True)

            # 검색 기록 추가
            user_id = update.effective_user.id
            display_name = f"📈 {result.get('etf_name', stock_input)}"
            add_to_history(user_id, stock_input, display_name)

        elif is_overseas:
            # 해외주식 모듈 체크
            if analyze_overseas_stock is None:
                raise ValueError("해외주식 분석 기능이 비활성화되어 있습니다.")

            # 해외주식: 거래소:종목코드 파싱
            parts = stock_input.split(':')
            if len(parts) != 2:
                raise ValueError("해외주식은 '거래소:종목코드' 형식으로 입력해주세요. (예: NAS:TSLA)")

            excd = parts[0].upper()
            symb = parts[1].upper()
            result = await loop.run_in_executor(
                None, functools.partial(analyze_overseas_stock, excd, symb)
            )

            # 결과 메시지 생성
            message = format_analysis_message(result, is_overseas=True)

            # 검색 기록에 추가
            user_id = update.effective_user.id
            display_name = f"🇺🇸 {result.get('symbol', stock_input)}"
            add_to_history(user_id, stock_input, display_name)

        else:
            # 국내주식 시도
            try:
                result = await loop.run_in_executor(None, analyze_domestic_stock, stock_input)

                # 결과 메시지 생성
                message = format_analysis_message(result, is_overseas=False)

                # 검색 기록에 추가
                user_id = update.effective_user.id
                display_name = f"🇰🇷 {result.get('stock_name', stock_input)}"
                add_to_history(user_id, stock_input, display_name)

            except (ValueError, Exception) as stock_error:
                # 국내주식으로 찾지 못하면 ETF로 시도 (6자리 형식)
                if analyze_etf is not None and len(stock_input) == 6:
                    logger.info(f"국내주식 검색 실패, ETF로 재시도: {stock_input}")
                    try:
                        result = await loop.run_in_executor(None, analyze_etf, stock_input)

                        # ETF 메시지 생성
                        message = format_analysis_message(result, is_overseas=False, is_etf=True)

                        # 검색 기록 추가
                        user_id = update.effective_user.id
                        display_name = f"📈 {result.get('etf_name', stock_input)}"
                        add_to_history(user_id, stock_input, display_name)
                    except Exception as etf_error:
                        # ETF로도 실패하면 원래 에러 발생
                        logger.error(f"ETF 검색도 실패: {etf_error}")
                        raise stock_error
                else:
                    # ETF가 아니거나 모듈이 없으면 원래 에러 발생
                    raise stock_error

        # 결과 전송
        await wait_msg.edit_text(message, parse_mode='HTML')

    except StockAnalysisError as e:
        await wait_msg.edit_text(handle_analysis_error(e))
    except Exception as e:
        logger.error(f"분석 중 예상치 못한 오류: {e}", exc_info=True)
        await wait_msg.edit_text(handle_analysis_error(e))


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """최근 검색 기록 명령어"""
    user_id = update.effective_user.id

    if user_id not in user_history or not user_history[user_id]:
        await update.message.reply_text(
            "📜 최근 검색 기록이 없습니다.\n\n"
            "종목을 검색하면 여기에 표시됩니다."
        )
        return

    keyboard = []
    for item in user_history[user_id]:
        stock_input = item['input']
        display_name = item['display']
        keyboard.append([InlineKeyboardButton(display_name, callback_data=f"stock:{stock_input}")])

    keyboard.append([InlineKeyboardButton("🗑️ 기록 삭제", callback_data="clear_history")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "📜 <b>최근 검색 기록</b>\n\n"
        "버튼을 눌러 다시 조회하세요!",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )


def add_to_history(user_id: int, stock_input: str, display_name: str):
    """검색 기록에 추가"""
    if user_id not in user_history:
        user_history[user_id] = []

    # 중복 제거
    user_history[user_id] = [item for item in user_history[user_id] if item['input'] != stock_input]

    # 최신 항목을 앞에 추가
    user_history[user_id].insert(0, {
        'input': stock_input,
        'display': display_name
    })

    # 최대 개수까지만 유지
    max_items = BOT_SETTINGS['max_history_items']
    user_history[user_id] = user_history[user_id][:max_items]


async def exchange_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """거래소 선택 화면"""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton("🇺🇸 NYSE (뉴욕증권거래소)", callback_data="exchange:NYS"),
        ],
        [
            InlineKeyboardButton("🇺🇸 NASDAQ (나스닥)", callback_data="exchange:NAS"),
        ],
        [
            InlineKeyboardButton("🇺🇸 AMEX (아멕스)", callback_data="exchange:AMS"),
        ],
        [
            InlineKeyboardButton("🔙 돌아가기", callback_data="back_to_stocks"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "🌍 <b>거래소를 선택하세요</b>\n\n"
        "거래소 선택 후 티커를 입력하세요.\n"
        "예: TSLA, AAPL, NVDA",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """버튼 클릭 핸들러"""
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = update.effective_user.id

    # 최근 검색 기록 표시
    if data == "show_history":
        if user_id not in user_history or not user_history[user_id]:
            await query.edit_message_text("📜 최근 검색 기록이 없습니다.")
            return

        keyboard = []
        for item in user_history[user_id]:
            stock_input = item['input']
            display_name = item['display']
            keyboard.append([InlineKeyboardButton(display_name, callback_data=f"stock:{stock_input}")])

        keyboard.append([InlineKeyboardButton("🗑️ 기록 삭제", callback_data="clear_history")])
        keyboard.append([InlineKeyboardButton("🔙 돌아가기", callback_data="back_to_start")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "📜 <b>최근 검색 기록</b>\n\n"
            "버튼을 눌러 다시 조회하세요!",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        return

    # 기록 삭제
    if data == "clear_history":
        if user_id in user_history:
            user_history[user_id] = []
        await query.edit_message_text("✅ 검색 기록이 삭제되었습니다.")
        return

    # 시작 화면으로 돌아가기
    if data == "back_to_start":
        keyboard = []
        if user_id in user_history and user_history[user_id]:
            keyboard.append([InlineKeyboardButton("📜 최근 검색 기록", callback_data="show_history")])
        keyboard.append([InlineKeyboardButton("🌍 해외주식 거래소 선택", callback_data="select_exchange")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "📈 주식 분석 봇입니다!\n\n"
            "🇰🇷 <b>국내주식</b>\n"
            "• 종목명 또는 종목코드 입력\n"
            "• 예: 삼성전자, NAVER, 005930\n\n"
            "🇺🇸 <b>해외주식</b>\n"
            "• '해외주식 거래소 선택' 버튼 클릭\n"
            "• 또는 직접 입력: 거래소:티커 (예: NAS:TSLA)",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        return

    # 거래소 선택 화면으로 이동
    if data == "select_exchange":
        await exchange_selection(update, context)
        return

    # 거래소 선택 시 context에 저장하고 티커 입력 대기
    if data.startswith("exchange:"):
        exchange_code = data.replace("exchange:", "")
        context.user_data['selected_exchange'] = exchange_code

        exchange_names = EXCHANGE_NAMES

        await query.edit_message_text(
            f"✅ <b>{exchange_names.get(exchange_code, exchange_code)}</b> 선택됨\n\n"
            f"이제 티커를 입력하세요.\n"
            f"예: TSLA, AAPL, NVDA, MSFT",
            parse_mode='HTML'
        )
        return

    # 돌아가기
    if data == "back_to_stocks":
        keyboard = [
            [
                InlineKeyboardButton("🇰🇷 삼성전자", callback_data="stock:삼성전자"),
                InlineKeyboardButton("🇰🇷 NAVER", callback_data="stock:NAVER"),
            ],
            [
                InlineKeyboardButton("🇰🇷 카카오", callback_data="stock:카카오"),
                InlineKeyboardButton("🇰🇷 현대차", callback_data="stock:현대차"),
            ],
            [
                InlineKeyboardButton("🌍 해외주식 거래소 선택", callback_data="select_exchange"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "📊 <b>인기 종목 바로가기</b>\n\n"
            "🇰🇷 국내 인기종목을 선택하거나\n"
            "🌍 해외주식은 거래소를 먼저 선택하세요!",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        return

    # 주식 분석 (기존 로직)
    if not data.startswith("stock:"):
        return

    stock_input = data.replace("stock:", "")

    # 해외주식 여부 판단
    is_overseas = stock_input.count(':') == 1  # "NAS:TSLA" 형식

    # 분석 시작 메시지
    analysis_type = 'overseas' if is_overseas else 'domestic'
    wait_msg = await query.message.reply_text(
        format_analyzing_message(stock_input, analysis_type)
    )

    try:
        # KIS 인증
        ka.auth()

        # 주식 분석 (블로킹 I/O를 스레드풀로 실행)
        loop = asyncio.get_running_loop()

        if is_overseas:
            # 해외주식 모듈 체크
            if analyze_overseas_stock is None:
                raise ValueError("해외주식 분석 기능이 비활성화되어 있습니다.")

            # 해외주식: 거래소:종목코드 파싱
            parts = stock_input.split(':')
            if len(parts) != 2:
                raise ValueError("해외주식은 '거래소:종목코드' 형식으로 입력해주세요.")

            excd = parts[0].upper()
            symb = parts[1].upper()
            result = await loop.run_in_executor(
                None, functools.partial(analyze_overseas_stock, excd, symb)
            )
        else:
            # 국내주식
            result = await loop.run_in_executor(None, analyze_domestic_stock, stock_input)

        # 결과 메시지 생성
        message = format_analysis_message(result, is_overseas=is_overseas)

        # 결과 전송
        await wait_msg.edit_text(message, parse_mode='HTML')

    except StockAnalysisError as e:
        await wait_msg.edit_text(handle_analysis_error(e))
    except Exception as e:
        logger.error(f"분석 중 예상치 못한 오류: {e}", exc_info=True)
        await wait_msg.edit_text(handle_analysis_error(e))


def main():
    """메인 함수"""
    # 애플리케이션 생성
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # 핸들러 등록
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("history", history_command))
    application.add_handler(CommandHandler("vol", vol_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze_message))

    # 봇 시작
    logger.info("텔레그램 봇 시작...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
