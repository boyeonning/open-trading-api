"""해외주식 분석 모듈"""
import sys
import logging
import time
import pandas as pd

sys.path.extend(['..', '.'])
import kis_auth as ka
from api.overseas_stock_functions import dailyprice

from utils.config import ANALYSIS_SETTINGS
from utils.exceptions import DataFetchError, APIError
from utils.analysis_utils import (
    validate_price_data, calculate_moving_averages,
    calculate_volume_analysis, calculate_ma_analysis,
    validate_analysis_data, performance_monitor
)
from analyzers.base import fetch_paginated_daily_data

logger = logging.getLogger(__name__)


@performance_monitor
def fetch_stock_data(excd: str, symb: str, target_days: int = None) -> pd.DataFrame:
    """해외주식 일별 데이터 조회 (페이지네이션 + 재시도)"""
    if target_days is None:
        target_days = ANALYSIS_SETTINGS['overseas']['target_days']

    settings = ANALYSIS_SETTINGS['overseas']
    max_retries = settings['api_retry_count']
    retry_delay = settings['api_retry_delay']

    def api_call_with_retry(end_date: str) -> pd.DataFrame:
        """재시도 로직을 포함한 단일 API 호출"""
        for attempt in range(1, max_retries + 1):
            try:
                _, result2 = dailyprice(
                    auth="",
                    excd=excd,
                    symb=symb,
                    gubn="0",
                    bymd=end_date,
                    modp="1",
                    env_dv="real"
                )
                return result2
            except Exception as e:
                if attempt < max_retries:
                    wait = attempt * retry_delay
                    logger.warning(f"API 호출 실패 (재시도 {attempt}/{max_retries}): {e} → {wait}초 대기")
                    time.sleep(wait)
                else:
                    logger.error(f"API 호출 최종 실패: {e}")
                    raise APIError("해외주식 API", str(e))

    all_data = fetch_paginated_daily_data(
        api_call=api_call_with_retry,
        date_col='xymd',
        target_days=target_days,
        api_delay=settings['api_call_delay']
    )

    if not all_data:
        raise DataFetchError(f"{excd}:{symb}", "데이터를 가져올 수 없습니다.")

    combined_df = pd.concat(all_data, ignore_index=True)
    combined_df = combined_df.sort_values('xymd').reset_index(drop=True)
    logger.info(f"총 {len(combined_df)}개의 데이터를 가져왔습니다.")
    return combined_df


@performance_monitor
def analyze_stock(excd: str, symb: str) -> dict:
    """해외주식 분석 메인 함수"""
    combined_df = fetch_stock_data(excd, symb)

    validate_price_data(combined_df, 'clos', f"{excd}:{symb}")
    for col in ['open', 'high', 'low', 'tvol']:
        combined_df[col] = pd.to_numeric(combined_df[col], errors='coerce')

    validate_analysis_data(combined_df, f"{excd}:{symb}", 60)

    ma_periods = ANALYSIS_SETTINGS['overseas']['ma_periods']
    combined_df = calculate_moving_averages(combined_df, 'clos', ma_periods)

    latest_price = combined_df.iloc[-1]['clos']
    latest_date = combined_df.iloc[-1]['xymd']

    return {
        'exchange': excd,
        'symbol': symb,
        'latest_price': latest_price,
        'latest_date': latest_date,
        'volume_analysis': calculate_volume_analysis(
            combined_df, latest_price, 'clos', 'tvol', 'overseas'
        ),
        'ma_analysis': calculate_ma_analysis(
            combined_df, latest_price, ma_periods, return_all=True
        )
    }
