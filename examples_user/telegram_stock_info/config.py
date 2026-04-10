"""텔레그램 주식 봇 설정"""

# 분석 설정
ANALYSIS_SETTINGS = {
    'domestic': {
        'target_days': 730,  # 2년
        'ma_periods': [5, 10, 20, 60, 120, 240],
        'volume_threshold_percentile': 0.90,  # 상위 10% 거래량
        'price_range_limits': {
            'nearby': 10,    # 10% 이내
            'extended': 20   # 20% 이내
        }
    },
    'overseas': {
        'target_days': 365,  # 1년
        'ma_periods': [5, 10, 20, 60, 120, 240],  # 240일 추가
        'volume_threshold_percentile': 0.90,
        'price_range_limits': {
            'nearby': 10,
            'extended': 20
        },
        'api_retry_count': 3,
        'api_retry_delay': 2,  # 초
        'api_call_delay': 0.5  # 초
    },
    'etf': {
        'target_days': 1095,  # 3년
        'ma_periods': [5, 10, 20, 60, 120],
        'volume_threshold_percentile': 0.90,
        'price_range_limits': {
            'nearby': 10,
            'extended': 20
        },
        'min_data_days': 120  # 최소 데이터 요구사항
    }
}

# 거래소 정보
EXCHANGE_NAMES = {
    'NYS': 'NYSE (뉴욕증권거래소)',
    'NAS': 'NASDAQ (나스닥)',
    'AMS': 'AMEX (아멕스)'
}

# UI 설정
UI_MESSAGES = {
    'analyzing': {
        'domestic': '🇰🇷 국내주식 (약 10-30초 소요)',
        'overseas': '🌍 해외주식 (약 10-30초 소요)', 
        'etf': '📈 ETF (약 10-30초 소요)'
    },
    'error_formats': {
        'not_found': '❌ 종목을 찾을 수 없습니다.',
        'api_error': '❌ 분석 중 오류가 발생했습니다.\n잠시 후 다시 시도해주세요.',
        'format_error': '❌ 입력 형식을 확인해주세요.\n국내: 종목명 또는 종목코드\n해외: 거래소:종목코드 (예: NAS:TSLA)'
    }
}

# 파일 경로 설정
FILE_PATHS = {
    'kosdaq_master': 'kosdaq_code_part1.tmp',
    'kospi_master': 'kospi_code_part1.tmp',
    'stocks_info_dir': '../../stocks_info'
}

# 텔레그램 봇 설정
BOT_SETTINGS = {
    'max_history_items': 6,
    'message_parse_mode': 'HTML',
    'keyboard_timeout': 300  # 5분
}

# 로깅 설정
LOGGING_CONFIG = {
    'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    'level': 'INFO',
    'performance_logging': True
}

# API 설정
API_SETTINGS = {
    'timeout': 30,  # 초
    'max_retries': 3,
    'backoff_factor': 2
}