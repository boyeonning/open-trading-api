# 📱 텔레그램 주식 정보 조회 봇

텔레그램으로 종목명을 입력하면 자동으로 분석 결과를 받을 수 있는 간편한 봇입니다.

## ✨ 주요 기능

- 🇰🇷 **국내 주식**: 종목명 또는 코드로 검색 (2년치 데이터)
- 🇺🇸 **해외 주식**: NYSE, NASDAQ, AMEX 지원 (1년치 데이터)
- 📈 **ETF**: 국내 ETF 정보 조회 (3년치 데이터)
- 📜 **검색 기록**: 최근 6개 검색 기록 저장
- 📊 **상세 분석**: 저항선/지지선, 이동평균선 등

## 🚀 빠른 시작

### 1. 텔레그램 봇 토큰 발급

1. 텔레그램에서 [@BotFather](https://t.me/botfather) 검색
2. `/newbot` 명령어로 새 봇 생성
3. 봇 이름과 사용자명 설정
4. 발급받은 토큰 복사

### 2. 환경 변수 설정

```bash
# Linux/Mac
export TELEGRAM_BOT_TOKEN="여기에_발급받은_토큰"

# 또는 .env 파일에 저장
echo 'TELEGRAM_BOT_TOKEN="여기에_발급받은_토큰"' > .env
```

### 3. 봇 실행

```bash
cd telegram_stock_info
./start_bot.sh
```

또는 직접 실행:
```bash
uv run bot.py
```

### 4. 텔레그램에서 사용

1. 텔레그램에서 봇 검색
2. `/start` 명령어로 시작
3. 종목 입력:
   - **국내**: 삼성전자, NAVER, 005930
   - **해외**: NAS:TSLA, NYS:AAPL
   - **ETF**: 069500, 152100

## 📊 사용 예시

### 국내 주식
```
삼성전자
NAVER
005930
```

### 해외 주식
```
NAS:TSLA    (나스닥: 테슬라)
NYS:AAPL    (뉴욕증권거래소: 애플)
NAS:NVDA    (나스닥: 엔비디아)
AMS:SPY     (아멕스)
```

### ETF
```
069500      (KODEX 200)
152100      (ARIRANG 200)
```

## 📖 분석 정보

### 상방 거래량 분석 (저항선)
- 현재가보다 높은 가격대의 고거래량 구간
- 전체 거래량 TOP 3
- 10% 이내 거래량 TOP 3

### 하방 거래량 분석 (지지선)
- 현재가보다 낮은 가격대의 고거래량 구간
- 전체 거래량 TOP 3
- 10% 이내 거래량 TOP 3

### 이동평균선
- MA_5, MA_10, MA_20, MA_60, MA_120
- 현재가 대비 차이율(%) 표시
- 저항선/지지선 구분

## 📝 명령어

- `/start` - 봇 시작
- `/help` - 도움말
- `/history` - 최근 검색 기록

## 🔧 트러블슈팅

### 봇이 응답하지 않는 경우
1. `TELEGRAM_BOT_TOKEN` 환경 변수 확인
2. 터미널 로그 확인
3. KIS API 인증 정보 확인 (`kis_devlp.yaml`)

### "종목을 찾을 수 없습니다" 오류
코스피/코스닥 마스터 파일 생성:
```bash
cd ../../stocks_info
uv run kis_kospi_code_mst.py
uv run kis_kosdaq_code_mst.py
```

### 분석이 느린 경우
- API 호출 제한으로 10-30초 소요
- 정상적인 동작입니다

## 📁 파일 구조

```
telegram_stock_info/
├── bot.py                  # 텔레그램 봇 메인
├── domestic_analyzer.py    # 국내 주식 분석
├── overseas_analyzer.py    # 해외 주식 분석
├── etf_analyzer.py         # ETF 분석
├── start_bot.sh           # 실행 스크립트
└── README.md              # 이 파일
```

## 🔒 보안 주의사항

⚠️ **절대 공개하지 마세요:**
- 텔레그램 봇 토큰
- KIS API 키 정보
- `.env` 파일을 `.gitignore`에 추가하세요

## 💡 팁

- 여러 종목 연속 조회 가능
- 검색 기록 기능으로 빠른 재조회
- 봇을 백그라운드로 실행하면 언제든 사용 가능

## 🎯 거래소 코드

| 코드 | 거래소 |
|------|--------|
| NAS  | 나스닥 (NASDAQ) |
| NYS  | 뉴욕증권거래소 (NYSE) |
| AMS  | 아멕스 (AMEX) |

## 📞 문의

문제가 있거나 개선 사항이 있으면 이슈를 등록해주세요!
