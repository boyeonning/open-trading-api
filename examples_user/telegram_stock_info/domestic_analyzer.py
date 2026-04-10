"""국내주식 분석 모듈"""
import sys
import logging
from datetime import datetime, timedelta
import os
import time

import pandas as pd

sys.path.extend(['..', '.'])
import kis_auth as ka
from domestic_stock_functions import *

from config import ANALYSIS_SETTINGS, FILE_PATHS
from exceptions import (
    StockNotFoundError, DataFetchError, InsufficientDataError, 
    DataValidationError, APIError
)
from analysis_utils import (
    validate_price_data, calculate_moving_averages,
    calculate_volume_analysis, calculate_ma_analysis,
    validate_analysis_data, performance_monitor
)

logger = logging.getLogger(__name__)

# CSV 마스터 파일 캐시 (프로세스 재시작 전까지 유지)
_stock_master_cache = {}


def get_stock_code(stock_name: str) -> tuple[str, str, list]:
    """
    종목명으로 종목코드 찾기

    Args:
        stock_name: 검색할 종목명

    Returns:
        tuple: (종목코드, 종목명, 검색결과리스트)
    
    Raises:
        StockNotFoundError: 종목을 찾을 수 없는 경우
    """
    stocks_info_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                                   FILE_PATHS['stocks_info_dir'].replace('../../', ''))
    kosdaq_file = os.path.join(stocks_info_dir, FILE_PATHS['kosdaq_master'])
    kospi_file = os.path.join(stocks_info_dir, FILE_PATHS['kospi_master'])

    for file_path in [kosdaq_file, kospi_file]:
        if os.path.exists(file_path):
            if file_path not in _stock_master_cache:
                try:
                    df = pd.read_csv(file_path, header=None, names=['단축코드', '표준코드', '한글종목명'], encoding='utf-8')
                except UnicodeDecodeError:
                    df = pd.read_csv(file_path, header=None, names=['단축코드', '표준코드', '한글종목명'], encoding='cp949')
                _stock_master_cache[file_path] = df
            df = _stock_master_cache[file_path]
            # 종목명으로 검색 (부분 일치, 대소문자 무시)
            result = df[df['한글종목명'].str.contains(stock_name, case=False, na=False)]
            if not result.empty:
                search_results = []
                if len(result) > 1:
                    logger.info(f"'{stock_name}' 검색 결과:")
                    for _, row in result.iterrows():
                        logger.info(f"  - {row['한글종목명']} ({row['단축코드']})")
                        search_results.append({
                            'name': row['한글종목명'],
                            'code': row['단축코드']
                        })
                    # 첫 번째 결과 사용
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
    """
    주식 데이터 가져오기
    
    Args:
        stock_code: 종목코드
        target_days: 목표 일수 (None이면 설정에서 가져옴)
    
    Returns:
        pd.DataFrame: 주식 데이터
    
    Raises:
        DataFetchError: 데이터 조회 실패
    """
    if target_days is None:
        target_days = ANALYSIS_SETTINGS['domestic']['target_days']
        
    all_data = []
    end_date_str = datetime.now().strftime("%Y%m%d")

    call_count = 0
    max_calls = int(target_days / 100) + 5

    while call_count < max_calls:
        logger.info(f"API 호출 {call_count + 1}회차: 종료일 {end_date_str}")

        result1, result2 = inquire_daily_itemchartprice(
            env_dv="real",
            fid_cond_mrkt_div_code="J",
            fid_input_iscd=stock_code,
            fid_input_date_1="19000101",
            fid_input_date_2=end_date_str,
            fid_period_div_code="D",
            fid_org_adj_prc="1"
        )

        if result2 is not None and not result2.empty:
            all_data.append(result2)

            total_rows = sum(len(df) for df in all_data)
            logger.info(f"현재까지 {total_rows}개 데이터 수집, 이번 응답: {len(result2)}개")

            if total_rows >= target_days:
                logger.info(f"목표 달성: {total_rows}개 >= {target_days}개")
                break

            if len(result2) < 100:
                logger.info("마지막 데이터까지 수집 완료")
                break

            last_date = result2.iloc[-1, 0]
            if isinstance(last_date, str):
                last_date_str = last_date.replace("-", "").replace("/", "")[:8]
            else:
                last_date_str = str(last_date)[:8]

            last_dt = datetime.strptime(last_date_str, "%Y%m%d")
            end_date_str = (last_dt - timedelta(days=1)).strftime("%Y%m%d")
        else:
            logger.warning("더 이상 데이터가 없습니다.")
            break

        call_count += 1
        time.sleep(0.1)

    if all_data:
        combined_df = pd.concat(all_data, ignore_index=True)
        combined_df = combined_df.sort_values(by=combined_df.columns[0]).reset_index(drop=True)
        logger.info(f"총 {len(combined_df)}개의 데이터를 가져왔습니다.")
        return combined_df
    else:
        raise DataFetchError(stock_code, "데이터를 가져올 수 없습니다.")


@performance_monitor
def analyze_stock(stock_input: str) -> dict:
    """
    국내주식 분석 메인 함수

    Args:
        stock_input: 종목명 또는 종목코드

    Returns:
        분석 결과 딕셔너리
    
    Raises:
        StockNotFoundError: 종목을 찾을 수 없는 경우
        DataFetchError: 데이터 조회 실패
        InsufficientDataError: 데이터 부족
    """
    # 종목 코드 확인
    if len(stock_input) == 6 and (stock_input.isdigit() or stock_input.isalnum()):
        stock_code = stock_input
        stock_name = None
        search_results = []
        logger.info(f"종목코드 직접 입력: {stock_code}")
    else:
        stock_code, stock_name, search_results = get_stock_code(stock_input)

    # 데이터 가져오기
    combined_df = fetch_stock_data(stock_code)

    # 데이터 검증 및 타입 변환
    validate_price_data(combined_df, 'stck_clpr', stock_code)
    combined_df['stck_oprc'] = pd.to_numeric(combined_df['stck_oprc'], errors='coerce')
    combined_df['stck_hgpr'] = pd.to_numeric(combined_df['stck_hgpr'], errors='coerce') 
    combined_df['stck_lwpr'] = pd.to_numeric(combined_df['stck_lwpr'], errors='coerce')
    combined_df['acml_vol'] = pd.to_numeric(combined_df['acml_vol'], errors='coerce')

    # 분석을 위한 최소 데이터 검증
    validate_analysis_data(combined_df, stock_code, 120)

    # 이동평균선 계산
    ma_periods = ANALYSIS_SETTINGS['domestic']['ma_periods']
    combined_df = calculate_moving_averages(combined_df, 'stck_clpr', ma_periods)

    # 가장 최근 데이터
    latest_price = combined_df.iloc[-1]['stck_clpr']
    latest_date = combined_df.iloc[-1]['stck_bsop_date']

    # 결과 딕셔너리
    result = {
        'stock_code': stock_code,
        'stock_name': stock_name,
        'search_results': search_results,
        'latest_date': latest_date,
        'latest_price': latest_price
    }

    # 거래량 분석 (공통 함수 사용)
    result['volume_analysis'] = calculate_volume_analysis(
        combined_df, latest_price, 'stck_clpr', 'acml_vol', 'domestic'
    )

    # 이동평균선 분석 (공통 함수 사용 - 국내주식은 모든 MA 반환)
    result['ma_analysis'] = calculate_ma_analysis(
        combined_df, latest_price, ma_periods, return_all=True
    )

    return result
