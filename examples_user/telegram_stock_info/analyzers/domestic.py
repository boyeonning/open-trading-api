"""국내주식 분석 모듈"""
import sys
import os
import logging
import pandas as pd

sys.path.extend(['..', '.'])
import kis_auth as ka
from api.domestic_stock_functions import inquire_daily_itemchartprice

from utils.config import ANALYSIS_SETTINGS, FILE_PATHS
from utils.exceptions import StockNotFoundError, DataFetchError
from utils.analysis_utils import (
    validate_price_data, calculate_moving_averages,
    calculate_volume_analysis, calculate_ma_analysis,
    calculate_candle_sr_levels, validate_analysis_data, performance_monitor
)
from analyzers.base import fetch_paginated_daily_data

logger = logging.getLogger(__name__)

# CSV 마스터 파일 캐시 (프로세스 재시작 전까지 유지)
_stock_master_cache = {}


def get_stock_code(stock_name: str) -> tuple[str, str, list]:
    """종목명으로 종목코드 찾기

    Returns:
        tuple: (종목코드, 종목명, 검색결과리스트)

    Raises:
        StockNotFoundError: 종목을 찾을 수 없는 경우
    """
    stocks_info_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        'stocks_info'
    )
    kosdaq_file = os.path.join(stocks_info_dir, FILE_PATHS['kosdaq_master'])
    kospi_file = os.path.join(stocks_info_dir, FILE_PATHS['kospi_master'])

    for file_path in [kosdaq_file, kospi_file]:
        if os.path.exists(file_path):
            if file_path not in _stock_master_cache:
                try:
                    df = pd.read_csv(file_path, header=None,
                                     names=['단축코드', '표준코드', '한글종목명'], encoding='utf-8')
                except UnicodeDecodeError:
                    df = pd.read_csv(file_path, header=None,
                                     names=['단축코드', '표준코드', '한글종목명'], encoding='cp949')
                _stock_master_cache[file_path] = df

            df = _stock_master_cache[file_path]
            result = df[df['한글종목명'].str.contains(stock_name, case=False, na=False)]

            if not result.empty:
                search_results = []
                if len(result) > 1:
                    logger.info(f"'{stock_name}' 검색 결과:")
                    for _, row in result.iterrows():
                        logger.info(f"  - {row['한글종목명']} ({row['단축코드']})")
                        search_results.append({'name': row['한글종목명'], 'code': row['단축코드']})
                    stock_code = result.iloc[0]['단축코드']
                    stock_name_found = result.iloc[0]['한글종목명']
                    logger.info(f"첫 번째 결과 사용: {stock_name_found} ({stock_code})")
                    return stock_code, stock_name_found, search_results
                else:
                    stock_code = result.iloc[0]['단축코드']
                    stock_name_found = result.iloc[0]['한글종목명']
                    logger.info(f"종목 찾음: {stock_name_found} ({stock_code})")
                    return stock_code, stock_name_found, []

    raise StockNotFoundError(stock_name, "코스피/코스닥 마스터 파일을 먼저 생성하세요.")


@performance_monitor
def fetch_stock_data(stock_code: str, target_days: int = None) -> pd.DataFrame:
    """국내주식 일별 데이터 조회 (페이지네이션)"""
    if target_days is None:
        target_days = ANALYSIS_SETTINGS['domestic']['target_days']

    def api_call(end_date: str) -> pd.DataFrame:
        _, result2 = inquire_daily_itemchartprice(
            env_dv="real",
            fid_cond_mrkt_div_code="J",
            fid_input_iscd=stock_code,
            fid_input_date_1="19000101",
            fid_input_date_2=end_date,
            fid_period_div_code="D",
            fid_org_adj_prc="1"
        )
        return result2

    all_data = fetch_paginated_daily_data(
        api_call=api_call,
        date_col='stck_bsop_date',
        target_days=target_days,
        api_delay=0.1
    )

    if not all_data:
        raise DataFetchError(stock_code, "데이터를 가져올 수 없습니다.")

    combined_df = pd.concat(all_data, ignore_index=True)
    combined_df = combined_df.sort_values('stck_bsop_date').reset_index(drop=True)
    logger.info(f"총 {len(combined_df)}개의 데이터를 가져왔습니다.")
    return combined_df


@performance_monitor
def analyze_stock(stock_input: str) -> dict:
    """국내주식 분석 메인 함수"""
    # 6자리 형식(숫자 또는 숫자+알파벳)이면 종목코드로 처리
    if len(stock_input) == 6 and (stock_input.isdigit() or stock_input.isalnum()):
        stock_code = stock_input
        stock_name = None
        search_results = []
        logger.info(f"종목코드 직접 입력: {stock_code}")
    else:
        stock_code, stock_name, search_results = get_stock_code(stock_input)

    combined_df = fetch_stock_data(stock_code)

    validate_price_data(combined_df, 'stck_clpr', stock_code)
    for col in ['stck_oprc', 'stck_hgpr', 'stck_lwpr', 'acml_vol']:
        combined_df[col] = pd.to_numeric(combined_df[col], errors='coerce')

    validate_analysis_data(combined_df, stock_code, 120)

    ma_periods = ANALYSIS_SETTINGS['domestic']['ma_periods']
    combined_df = calculate_moving_averages(combined_df, 'stck_clpr', ma_periods)

    latest_price = combined_df.iloc[-1]['stck_clpr']
    latest_date = combined_df.iloc[-1]['stck_bsop_date']

    return {
        'stock_code': stock_code,
        'stock_name': stock_name,
        'search_results': search_results,
        'latest_date': latest_date,
        'latest_price': latest_price,
        'volume_analysis': calculate_volume_analysis(
            combined_df, latest_price, 'stck_clpr', 'acml_vol', 'domestic'
        ),
        'ma_analysis': calculate_ma_analysis(
            combined_df, latest_price, ma_periods, return_all=True
        ),
        'candle_sr': calculate_candle_sr_levels(
            combined_df, latest_price,
            open_col='stck_oprc', close_col='stck_clpr',
            volume_col='acml_vol', date_col='stck_bsop_date'
        )
    }
