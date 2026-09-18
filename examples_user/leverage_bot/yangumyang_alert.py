"""양음양 눌림목 알림 — crontab 독립 스크립트

crontab 등록 예시:
  5 9  * * 1-5  cd /home/boyeon/workspace/open-trading-api && uv run examples_user/leverage_bot/yangumyang_alert.py
  50 14 * * 1-5  cd /home/boyeon/workspace/open-trading-api && uv run examples_user/leverage_bot/yangumyang_alert.py

환경변수:
  LEVERAGE_BOT_TOKEN  — 텔레그램 봇 토큰
  ALERT_CHAT_ID       — 수신 채팅 ID
"""
import sys
import os
import logging
import requests
from datetime import datetime, timezone, timedelta

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)
sys.path.insert(0, os.path.dirname(_DIR))

from domestic_flow.flow import fetch_pullback_flow, format_pullback_message, _fetch_market_phase

# .env 파일 로드
_env_path = os.path.join(_DIR, '.env')
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _v = _line.split('=', 1)
                os.environ.setdefault(_k.strip(), _v.strip())

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

TOKEN   = os.environ.get('LEVERAGE_BOT_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.environ.get('ALERT_CHAT_ID')


def send_telegram(text: str, chat_id: str):
    url = f'https://api.telegram.org/bot{TOKEN}/sendMessage'
    resp = requests.post(url, json={'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}, timeout=15)
    resp.raise_for_status()


def main():
    if not TOKEN:
        logger.error('LEVERAGE_BOT_TOKEN 또는 TELEGRAM_BOT_TOKEN 환경변수 없음')
        sys.exit(1)
    if not CHAT_ID:
        logger.error('ALERT_CHAT_ID 환경변수 없음')
        sys.exit(1)

    now_kst = datetime.now(KST)
    hour, minute = now_kst.hour, now_kst.minute
    if hour == 9 and minute < 10:
        label = '🌅 <b>장 시작 양음양 알림</b>'
    else:
        label = '🕯 <b>종가 매수 타이밍 — 양음양 알림</b>'

    try:
        kospi_rows  = fetch_pullback_flow('코스피')
        kosdaq_rows = fetch_pullback_flow('코스닥')
        phase       = _fetch_market_phase()
    except Exception as e:
        logger.error(f'양음양 스캔 실패: {e}', exc_info=True)
        sys.exit(1)

    body = (
        format_pullback_message(kospi_rows, '코스피')
        + '\n\n'
        + format_pullback_message(kosdaq_rows, '코스닥')
    )
    time_str  = now_kst.strftime('%H:%M KST')
    phase_str = f'\n{phase}\n' if phase else '\n'
    msg = f'{label}  {time_str}{phase_str}\n{body}'
    if len(msg) > 4000:
        cut = msg[:4000].rfind('\n')
        msg = msg[:cut] + '\n...'

    try:
        send_telegram(msg, CHAT_ID)
        logger.info(f'양음양 알림 발송 완료 → chat_id={CHAT_ID}')
    except Exception as e:
        logger.error(f'텔레그램 발송 실패: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
