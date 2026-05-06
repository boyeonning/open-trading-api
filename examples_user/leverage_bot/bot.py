"""레버리지 ETF 계산기 텔레그램 봇 — 진입점"""
import sys
import os
import logging

# 패키지 경로 설정 (leverage_bot/ 디렉토리 자신을 우선 추가)
_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters,
)

from handlers import (
    cmd_start, cmd_help, cmd_list, cmd_vix, cmd_scan,
    handle_message, handle_callback,
    handle_addbuy_callback, handle_avg_input, cancel_conv,
    WAITING_AVG,
)

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


def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # 추매 대화 흐름: 버튼 클릭 → 평단 입력
    addbuy_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_addbuy_callback, pattern='^addbuy\\|')],
        states={
            WAITING_AVG: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_avg_input)],
        },
        fallbacks=[CommandHandler('cancel', cancel_conv)],
        per_message=False,
    )

    app.add_handler(CommandHandler('start',  cmd_start))
    app.add_handler(CommandHandler('help',   cmd_help))
    app.add_handler(CommandHandler('list',   cmd_list))
    app.add_handler(CommandHandler('vix',    cmd_vix))
    app.add_handler(CommandHandler('scan',   cmd_scan))
    app.add_handler(CallbackQueryHandler(handle_callback, pattern='^calc\\|'))  # 시장위치 버튼
    app.add_handler(addbuy_conv)                                                # 추매 버튼 + 평단 입력
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info('레버리지 ETF 계산기 봇 시작...')
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
