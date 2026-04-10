"""ETF 분석 모듈"""
import sys
import logging
from datetime import datetime, timedelta

import pandas as pd

sys.path.extend(['..', '.'])
import kis_auth as ka
from etfetn_functions import *

from config import ANALYSIS_SETTINGS
from exceptions import (
    DataFetchError, APIError, DataValidationError,
    InsufficientDataError
)
from analysis_utils import (
    validate_price_data, calculate_moving_averages,
    calculate_volume_analysis, calculate_ma_analysis,
    validate_analysis_data, performance_monitor
)

logger = logging.getLogger('etf_analyzer')


@performance_monitor
def analyze_etf(iscd: str) -> dict:
    """
    ETF 분석 (거래량 기반 지지/저항선 + 이동평균선)

    Args:
        iscd: ETF 종목코드

    Returns:
        dict: 분석 결과
    
    Raises:
        DataFetchError: 데이터 조회 실패
        InsufficientDataError: 데이터 부족
    """
    # 현재 가격 조회
    current_df = inquire_price(fid_cond_mrkt_div_code="J", fid_input_iscd=iscd)

    if current_df.empty:
        raise DataFetchError(iscd, f"ETF {iscd}의 현재가 조회 실패")

    latest_price = float(current_df.iloc[0]['stck_prpr'])
    etf_name = current_df.iloc[0]['bstp_kor_isnm']
    latest_date = datetime.now().strftime('%Y-%m-%d')

    logger.info(f"ETF: {etf_name} ({iscd}), 현재가: {latest_price:,.0f}원")

    # 설정에서 목표 일수 가져오기
    settings = ANALYSIS_SETTINGS['etf']
    target_days = settings['target_days']
    
    # 일별 데이터 조회 
    end_date = datetime.now()
    start_date = end_date - timedelta(days=target_days)

    daily_df = nav_comparison_daily_trend(
        fid_cond_mrkt_div_code="J",
        fid_input_iscd=iscd,
        fid_input_date_1=start_date.strftime('%Y%m%d'),
        fid_input_date_2=end_date.strftime('%Y%m%d')
    )

    if daily_df.empty:
        raise DataFetchError(iscd, "일별 데이터 조회 실패")

    logger.info(f"일별 데이터 컬럼: {daily_df.columns.tolist()}")

    # 데이터 검증 및 타입 변환
    validate_price_data(daily_df, 'stck_clpr', iscd)
    daily_df['acml_vol'] = pd.to_numeric(daily_df['acml_vol'], errors='coerce')
    
    # 결측치 제거
    daily_df = daily_df.dropna(subset=['stck_clpr', 'acml_vol'])

    # 분석을 위한 최소 데이터 검증
    min_days = settings['min_data_days']
    validate_analysis_data(daily_df, iscd, min_days)

    # 이동평균선 계산
    ma_periods = settings['ma_periods']
    daily_df = calculate_moving_averages(daily_df, 'stck_clpr', ma_periods)

    # 분석 결과 저장
    result = {
        'etf_name': etf_name,
        'iscd': iscd,
        'latest_price': latest_price,
        'latest_date': latest_date
    }

    # 거래량 분석 (공통 함수 사용)
    result['volume_analysis'] = calculate_volume_analysis(
        daily_df, latest_price, 'stck_clpr', 'acml_vol', 'etf'
    )

    # 이동평균선 분석 (공통 함수 사용 - ETF는 모든 MA 반환)
    result['ma_analysis'] = calculate_ma_analysis(
        daily_df, latest_price, ma_periods, return_all=True
    )

    return result


if __name__ == "__main__":
    # 로깅 설정
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 인증
    ka.auth()

    # 테스트: KODEX 200 (069500)
    result = analyze_etf("069500")

    if result:
        print("\n=== ETF 분석 결과 ===")
        print(f"종목: {result['etf_name']} ({result['iscd']})")
        print(f"현재가: {result['latest_price']:,.0f}원")
        print(f"\n상방 전체 거래량 Top3: {result['volume_analysis']['upper']['volume_top3']}")
        print(f"상방 10% 이내 Top3: {result['volume_analysis']['upper']['nearby_top3']}")
        print(f"\n하방 전체 거래량 Top3: {result['volume_analysis']['lower']['volume_top3']}")
        print(f"하방 10% 이내 Top3: {result['volume_analysis']['lower']['nearby_top3']}")
        print(f"\n이동평균선 분석: {result['ma_analysis']}")
