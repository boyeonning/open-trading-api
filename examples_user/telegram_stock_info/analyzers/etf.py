"""ETF 분석 모듈"""
import sys
import logging
from datetime import datetime, timedelta

import pandas as pd

sys.path.extend(['..', '.'])
import kis_auth as ka
from api.etfetn_functions import inquire_price, nav_comparison_daily_trend

from utils.config import ANALYSIS_SETTINGS
from utils.exceptions import DataFetchError
from utils.analysis_utils import (
    validate_price_data, calculate_moving_averages,
    calculate_volume_analysis, calculate_ma_analysis,
    validate_analysis_data, performance_monitor
)

logger = logging.getLogger(__name__)


@performance_monitor
def analyze_etf(iscd: str) -> dict:
    """ETF 분석 (거래량 기반 지지/저항선 + 이동평균선)"""
    # 현재 가격 조회
    current_df = inquire_price(fid_cond_mrkt_div_code="J", fid_input_iscd=iscd)

    if current_df.empty:
        raise DataFetchError(iscd, f"ETF {iscd}의 현재가 조회 실패")

    latest_price = float(current_df.iloc[0]['stck_prpr'])
    etf_name = current_df.iloc[0]['bstp_kor_isnm']
    latest_date = datetime.now().strftime('%Y-%m-%d')

    logger.info(f"ETF: {etf_name} ({iscd}), 현재가: {latest_price:,.0f}원")

    settings = ANALYSIS_SETTINGS['etf']
    end_date = datetime.now()
    start_date = end_date - timedelta(days=settings['target_days'])

    daily_df = nav_comparison_daily_trend(
        fid_cond_mrkt_div_code="J",
        fid_input_iscd=iscd,
        fid_input_date_1=start_date.strftime('%Y%m%d'),
        fid_input_date_2=end_date.strftime('%Y%m%d')
    )

    if daily_df.empty:
        raise DataFetchError(iscd, "일별 데이터 조회 실패")

    validate_price_data(daily_df, 'stck_clpr', iscd)
    daily_df['acml_vol'] = pd.to_numeric(daily_df['acml_vol'], errors='coerce')
    daily_df = daily_df.dropna(subset=['stck_clpr', 'acml_vol'])

    validate_analysis_data(daily_df, iscd, settings['min_data_days'])

    ma_periods = settings['ma_periods']
    daily_df = calculate_moving_averages(daily_df, 'stck_clpr', ma_periods)

    return {
        'etf_name': etf_name,
        'iscd': iscd,
        'latest_price': latest_price,
        'latest_date': latest_date,
        'volume_analysis': calculate_volume_analysis(
            daily_df, latest_price, 'stck_clpr', 'acml_vol', 'etf'
        ),
        'ma_analysis': calculate_ma_analysis(
            daily_df, latest_price, ma_periods, return_all=True
        )
    }
