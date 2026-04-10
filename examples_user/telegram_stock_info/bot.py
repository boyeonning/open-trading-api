"""텔레그램 주식 분석 봇 - 진입점"""
import sys
import os
import logging

# 현재 디렉토리를 최우선으로 설정 (utils, analyzers, handlers, api 패키지 검색용)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.extend(['..', '../..'])

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler

from handlers.command_handlers import start, help_command, vol_command, history_command
from handlers.message_handlers import analyze_message
from handlers.callback_handlers import button_callback

# 로깅 설정
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 텔레그램 봇 토큰 (환경 변수에서 가져오기)
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN 환경 변수를 설정해주세요!")


def main():
    """봇 초기화 및 실행"""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("history", history_command))
    application.add_handler(CommandHandler("vol", vol_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze_message))

    logger.info("텔레그램 봇 시작...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
