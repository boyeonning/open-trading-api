#!/bin/bash
# 이 스크립트를 실행하면 봇이 자동으로 시작됩니다
# 사용법: ./setup_autostart.sh

echo "=== 주식 분석 봇 자동 시작 설정 ==="
echo ""
echo "1. systemd 서비스 파일을 시스템에 복사합니다..."
sudo cp stock-bot.service /etc/systemd/system/

echo "2. systemd를 다시 로드합니다..."
sudo systemctl daemon-reload

echo "3. 서비스를 활성화합니다 (부팅 시 자동 시작)..."
sudo systemctl enable stock-bot

echo "4. 서비스를 시작합니다..."
sudo systemctl start stock-bot

echo ""
echo "=== 설정 완료! ==="
echo ""
echo "유용한 명령어:"
echo "  봇 상태 확인:     sudo systemctl status stock-bot"
echo "  봇 시작:         sudo systemctl start stock-bot"
echo "  봇 중지:         sudo systemctl stop stock-bot"
echo "  봇 재시작:       sudo systemctl restart stock-bot"
echo "  로그 확인:       sudo journalctl -u stock-bot -f"
echo "  자동시작 해제:   sudo systemctl disable stock-bot"
