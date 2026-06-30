"""텔레그램 인라인 버튼 콜백 핸들러"""
import logging
import asyncio
import functools

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import kis_auth as ka
from utils.config import EXCHANGE_NAMES
from utils.formatter import format_analysis_message, format_analyzing_message, format_candle_sr_message
from utils.exceptions import StockAnalysisError
from handlers.state import user_history
from handlers.message_handlers import (
    analyze_domestic_stock, analyze_overseas_stock,
    handle_analysis_error
)
from analyzers.domestic import analyze_stock as _analyze_domestic_market

logger = logging.getLogger(__name__)


async def exchange_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """거래소 선택 화면"""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("🇺🇸 NYSE (뉴욕증권거래소)", callback_data="exchange:NYS")],
        [InlineKeyboardButton("🇺🇸 NASDAQ (나스닥)", callback_data="exchange:NAS")],
        [InlineKeyboardButton("🇺🇸 AMEX (아멕스)", callback_data="exchange:AMS")],
        [InlineKeyboardButton("🔙 돌아가기", callback_data="back_to_stocks")],
    ]

    await query.edit_message_text(
        "🌍 <b>거래소를 선택하세요</b>\n\n"
        "거래소 선택 후 티커를 입력하세요.\n"
        "예: TSLA, AAPL, NVDA",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """인라인 버튼 클릭 핸들러"""
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = update.effective_user.id

    # 최근 검색 기록 표시
    if data == "show_history":
        if user_id not in user_history or not user_history[user_id]:
            await query.edit_message_text("📜 최근 검색 기록이 없습니다.")
            return

        keyboard = [
            [InlineKeyboardButton(item['display'], callback_data=f"stock:{item['input']}")]
            for item in user_history[user_id]
        ]
        keyboard.append([InlineKeyboardButton("🗑️ 기록 삭제", callback_data="clear_history")])
        keyboard.append([InlineKeyboardButton("🔙 돌아가기", callback_data="back_to_start")])

        await query.edit_message_text(
            "📜 <b>최근 검색 기록</b>\n\n버튼을 눌러 다시 조회하세요!",
            reply_markup=InlineKeyboardMarkup(keyboard),
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

        await query.edit_message_text(
            "📈 주식 분석 봇입니다!\n\n"
            "🇰🇷 <b>국내주식</b>\n• 종목명 또는 종목코드 입력\n• 예: 삼성전자, NAVER, 005930\n\n"
            "🇺🇸 <b>해외주식</b>\n• '해외주식 거래소 선택' 버튼 클릭\n• 또는 직접 입력: 거래소:티커 (예: NAS:TSLA)",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
        return

    # 거래소 선택 화면으로 이동
    if data == "select_exchange":
        await exchange_selection(update, context)
        return

    # 거래소 선택 → context에 저장하고 티커 입력 대기
    if data.startswith("exchange:"):
        exchange_code = data.replace("exchange:", "")
        context.user_data['selected_exchange'] = exchange_code

        await query.edit_message_text(
            f"✅ <b>{EXCHANGE_NAMES.get(exchange_code, exchange_code)}</b> 선택됨\n\n"
            f"이제 티커를 입력하세요.\n예: TSLA, AAPL, NVDA, MSFT",
            parse_mode='HTML'
        )
        return

    # 돌아가기 (인기 종목 화면)
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
            [InlineKeyboardButton("🌍 해외주식 거래소 선택", callback_data="select_exchange")],
        ]

        await query.edit_message_text(
            "📊 <b>인기 종목 바로가기</b>\n\n"
            "🇰🇷 국내 인기종목을 선택하거나\n🌍 해외주식은 거래소를 먼저 선택하세요!",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
        return

    # KRX ↔ NXT 시장 전환 버튼
    if data.startswith("market:"):
        # 형식: market:{새 시장코드}:{종목입력값}
        parts = data.split(":", 2)
        if len(parts) != 3:
            return
        new_market, stock_input = parts[1], parts[2]
        market_name = "NXT(넥스트레이드)" if new_market == "NX" else "KRX(한국거래소)"

        wait_msg = await query.message.reply_text(f"⏳ {market_name} 데이터 조회 중...")

        try:
            ka.auth()
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, functools.partial(_analyze_domestic_market, stock_input, new_market)
            )

            message = format_analysis_message(result, is_overseas=False)

            # 반대 시장 전환 버튼 + 캔들 지지/저항 버튼
            keyboard = []
            if new_market == "NX":
                keyboard.append([InlineKeyboardButton(
                    "🔄 KRX(한국거래소)로 조회",
                    callback_data=f"market:J:{stock_input}"
                )])
            else:
                keyboard.append([InlineKeyboardButton(
                    "🔄 NXT(넥스트레이드)로 조회",
                    callback_data=f"market:NX:{stock_input}"
                )])

            if result.get('candle_sr'):
                cache_key = f'candle_sr|{stock_input}'
                context.user_data[cache_key] = {
                    'data': result['candle_sr'],
                    'is_overseas': False
                }
                keyboard.append([InlineKeyboardButton(
                    "🕯 캔들 지지/저항 보기",
                    callback_data=cache_key
                )])

            await wait_msg.edit_text(
                message, parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
            )
        except StockAnalysisError as e:
            await wait_msg.edit_text(handle_analysis_error(e))
        except Exception as e:
            logger.error(f"시장 전환 오류: {e}", exc_info=True)
            await wait_msg.edit_text(handle_analysis_error(e))
        return

    # 캔들 지지/저항 버튼 클릭
    if data.startswith("candle_sr|"):
        cached = context.user_data.get(data)
        if not cached:
            await query.message.reply_text("❌ 데이터가 만료됐습니다. 종목을 다시 조회해주세요.")
            return
        msg = format_candle_sr_message(cached['data'], is_overseas=cached['is_overseas'])
        await query.message.reply_text(msg, parse_mode='HTML')
        return

    # 검색 기록에서 종목 분석
    if not data.startswith("stock:"):
        return

    stock_input = data.replace("stock:", "")
    is_overseas = stock_input.count(':') == 1
    analysis_type = 'overseas' if is_overseas else 'domestic'

    wait_msg = await query.message.reply_text(
        format_analyzing_message(stock_input, analysis_type)
    )

    try:
        ka.auth()
        loop = asyncio.get_running_loop()

        if is_overseas:
            if analyze_overseas_stock is None:
                raise ValueError("해외주식 분석 기능이 비활성화되어 있습니다.")
            parts = stock_input.split(':')
            if len(parts) != 2:
                raise ValueError("해외주식은 '거래소:종목코드' 형식으로 입력해주세요.")
            excd, symb = parts[0].upper(), parts[1].upper()
            result = await loop.run_in_executor(
                None, functools.partial(analyze_overseas_stock, excd, symb)
            )
        else:
            result = await loop.run_in_executor(None, analyze_domestic_stock, stock_input)

        message = format_analysis_message(result, is_overseas=is_overseas)
        await wait_msg.edit_text(message, parse_mode='HTML')

    except StockAnalysisError as e:
        await wait_msg.edit_text(handle_analysis_error(e))
    except Exception as e:
        logger.error(f"버튼 분석 오류: {e}", exc_info=True)
        await wait_msg.edit_text(handle_analysis_error(e))
