#!/bin/bash

# 텔레그램 주식 정보 조회 봇 실행 스크립트

# 텔레그램 봇 토큰 설정
export TELEGRAM_BOT_TOKEN='your_telegram_bot_token_here'

echo "📱 텔레그램 주식 정보 조회 봇 시작..."
echo "✅ 텔레그램 봇 토큰 설정 완료"
echo "🚀 봇 실행 중..."
echo ""
echo "리팩토링된 새 버전으로 실행됩니다:"
echo "- 공통 분석 함수 적용"
echo "- 표준화된 예외 처리"  
echo "- 모듈화된 메시지 포맷팅"
echo ""

# 봇 실행 (백그라운드)
cd "$(dirname "$0")"
nohup uv run bot.py > bot.log 2>&1 &
echo "봇이 백그라운드에서 실행되었습니다. PID: $!"
echo "로그 확인: tail -f bot.log"
echo ""
echo "systemd 서비스 사용하려면:"
echo "sudo cp telegram-stock-bot.service /etc/systemd/system/"
echo "sudo systemctl daemon-reload"
echo "sudo systemctl enable telegram-stock-bot"
echo "sudo systemctl start telegram-stock-bot"
