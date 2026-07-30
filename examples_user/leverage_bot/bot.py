"""레버리지 ETF 계산기 텔레그램 봇 — 진입점"""
import sys
import os
import logging

# 패키지 경로 설정 (leverage_bot/ 디렉토리 자신을 우선 추가)
_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

from telegram import Update, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters,
)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from handlers import (
    cmd_start, cmd_help, cmd_list, cmd_vix, cmd_scan, cmd_check, cmd_weekly,
    cmd_alert,
    handle_message, handle_callback, handle_menu_callback,
    handle_addbuy_callback, handle_avg_input, cancel_conv,
    WAITING_AVG,
)
from domestic_flow.handlers import cmd_flow, handle_flow_callback
from datetime import time as dtime
import pytz
from monitor import check_and_alert, check_yangumyang_alert

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('LEVERAGE_BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN')
if not TELEGRAM_BOT_TOKEN:
    raise ValueError(
        "환경 변수 LEVERAGE_BOT_TOKEN 또는 TELEGRAM_BOT_TOKEN을 설정해 주세요.\n"
        "  export LEVERAGE_BOT_TOKEN='<token>'"
    )


async def post_init(app):
    """봇 시작 시 텔레그램 커맨드 메뉴 등록"""
    await app.bot.set_my_commands([
        BotCommand('start',  '봇 시작 및 메인 메뉴'),
        BotCommand('list',   '[미장] 레버리지 ETF 목록 및 등급'),
        BotCommand('vix',    '[미장] VIX 공포지수 조회'),
        BotCommand('scan',   '[미장] 전 종목 50/200일선 스캔'),
        BotCommand('check',  '[미장] 이번 주 진입가 도달 여부 확인'),
        BotCommand('flow',   '[국장] 국내 수급 분석'),
        BotCommand('alert',  '[미장] 진입가 알림 on/off'),
        BotCommand('help',   '도움말'),
    ])


def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # 추매 대화 흐름: 버튼 클릭 → 평단 입력
    addbuy_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_addbuy_callback, pattern='^addbuy\\|')],
        states={
            WAITING_AVG: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_avg_input)],
        },
        fallbacks=[CommandHandler('cancel', cancel_conv)],
        per_message=False,
    )

    KST = pytz.timezone('Asia/Seoul')

    # 5분마다 미국장 레버리지 ETF 알림
    app.job_queue.run_repeating(check_and_alert, interval=300, first=30)

    # 양음양 알림: 평일 14:50 (종가 매수 타이밍)
    app.job_queue.run_daily(
        check_yangumyang_alert,
        time=dtime(14, 50, tzinfo=KST),
        days=(0, 1, 2, 3, 4),
    )

    app.add_handler(CommandHandler('start',  cmd_start))
    app.add_handler(CommandHandler('help',   cmd_help))
    app.add_handler(CommandHandler('list',   cmd_list))
    app.add_handler(CommandHandler('vix',    cmd_vix))
    app.add_handler(CommandHandler('scan',   cmd_scan))
    app.add_handler(CommandHandler('check',  cmd_check))
    app.add_handler(CommandHandler('weekly', cmd_weekly))
    app.add_handler(CommandHandler('alert',  cmd_alert))
    app.add_handler(CommandHandler('flow',   cmd_flow))
    app.add_handler(CallbackQueryHandler(handle_menu_callback, pattern='^menu\\|'))   # 메인 메뉴 버튼
    app.add_handler(CallbackQueryHandler(handle_flow_callback, pattern='^flow\\|'))  # 수급 버튼
    app.add_handler(CallbackQueryHandler(handle_callback, pattern='^calc\\|'))       # 시장위치 버튼
    app.add_handler(addbuy_conv)                                                     # 추매 버튼 + 평단 입력
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info('레버리지 ETF 계산기 봇 시작...')
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
