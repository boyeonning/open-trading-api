"""해외주식 분석 모듈"""
import sys
import logging
from datetime import datetime, timedelta
import os
import time

import pandas as pd

sys.path.extend(['..', '.'])
import kis_auth as ka
from overseas_stock_functions import *

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

logger = logging.getLogger(__name__)


@performance_monitor
def fetch_stock_data(excd: str, symb: str, target_days: int = None) -> pd.DataFrame:
    """
    해외주식 데이터 가져오기 (최대 100개씩 페이징)

    Args:
        excd: 거래소코드 (NAS: 나스닥, NYS: 뉴욕, AMS: 아멕스, etc)
        symb: 종목코드 (예: TSLA, AAPL)
        target_days: 목표 데이터 일수 (None이면 설정에서 가져옴)

    Returns:
        pd.DataFrame: 주식 데이터
    
    Raises:
        DataFetchError: 데이터 조회 실패
        APIError: API 호출 오류
    """
    if target_days is None:
        target_days = ANALYSIS_SETTINGS['overseas']['target_days']
        
    logger.info(f"해외주식 데이터 수집 시작: {excd}:{symb}")

    all_data2 = []
    end_date_str = datetime.now().strftime("%Y%m%d")

    call_count = 0
    max_calls = int(target_days / 100) + 5

    settings = ANALYSIS_SETTINGS['overseas']
    max_retries = settings['api_retry_count']
    retry_delay = settings['api_retry_delay']
    api_delay = settings['api_call_delay']

    while call_count < max_calls:
        logger.info(f"API 호출 {call_count + 1}회차: 종료일 {end_date_str}")

        retry_count = 0
        result1, result2 = None, None

        while retry_count < max_retries:
            try:
                # dailyprice 호출
                result1, result2 = dailyprice(
                    auth="",
                    excd=excd,
                    symb=symb,
                    gubn="0",  # 일별
                    bymd=end_date_str,
                    modp="1",  # 수정주가 반영
                    env_dv="real"
                )
                break  # 성공하면 재시도 루프 탈출
            except Exception as e:
                retry_count += 1
                if retry_count < max_retries:
                    wait_time = retry_count * retry_delay
                    logger.warning(f"API 호출 실패 (재시도 {retry_count}/{max_retries}): {e}")
                    logger.info(f"{wait_time}초 대기 후 재시도...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"API 호출 최종 실패: {e}")
                    raise APIError("해외주식 API", str(e))

        if result2 is not None and not result2.empty:
            all_data2.append(result2)
            total_records = sum(len(df) for df in all_data2)

            logger.info(f"현재까지 {total_records}개 데이터 수집, 이번 응답: {len(result2)}개")

            # 목표 달성 확인
            if total_records >= target_days:
                logger.info(f"목표 달성: {total_records}개 >= {target_days}개")
                break

            # 100개 미만이면 더 이상 데이터가 없음
            if len(result2) < 100:
                logger.info("마지막 페이지 도달")
                break

            # 다음 조회 기준일: 마지막 날짜의 하루 전
            last_date = result2.iloc[-1]['xymd']
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
        time.sleep(api_delay)

    if not all_data2:
        raise DataFetchError(f"{excd}:{symb}", "데이터를 가져올 수 없습니다.")

    # 모든 데이터 결합
    combined_df = pd.concat(all_data2, ignore_index=True)
    logger.info(f"총 {len(combined_df)}개의 데이터를 가져왔습니다.")

    # 날짜순 정렬 (오래된 것부터)
    combined_df = combined_df.sort_values('xymd').reset_index(drop=True)

    return combined_df


@performance_monitor
def analyze_stock(excd: str, symb: str) -> dict:
    """
    해외주식 분석

    Args:
        excd: 거래소코드 (NAS, NYS, AMS 등)
        symb: 종목코드 (TSLA, AAPL 등)

    Returns:
        dict: 분석 결과
    
    Raises:
        DataFetchError: 데이터 조회 실패
        InsufficientDataError: 데이터 부족
    """
    # 데이터 가져오기
    combined_df = fetch_stock_data(excd, symb)

    # 데이터 검증 및 타입 변환
    validate_price_data(combined_df, 'clos', f"{excd}:{symb}")
    combined_df['open'] = pd.to_numeric(combined_df['open'], errors='coerce')
    combined_df['high'] = pd.to_numeric(combined_df['high'], errors='coerce')
    combined_df['low'] = pd.to_numeric(combined_df['low'], errors='coerce')
    combined_df['tvol'] = pd.to_numeric(combined_df['tvol'], errors='coerce')

    # 분석을 위한 최소 데이터 검증
    validate_analysis_data(combined_df, f"{excd}:{symb}", 60)

    # 이동평균선 계산 (240일 추가로 국내주식과 통일)
    ma_periods = ANALYSIS_SETTINGS['overseas']['ma_periods']
    combined_df = calculate_moving_averages(combined_df, 'clos', ma_periods)

    # 가장 최근 데이터
    latest_price = combined_df.iloc[-1]['clos']
    latest_date = combined_df.iloc[-1]['xymd']

    result = {
        'exchange': excd,
        'symbol': symb,
        'latest_price': latest_price,
        'latest_date': latest_date
    }

    # 거래량 분석 (공통 함수 사용)
    result['volume_analysis'] = calculate_volume_analysis(
        combined_df, latest_price, 'clos', 'tvol', 'overseas'
    )

    # 이동평균선 분석 (공통 함수 사용 - 해외주식은 모든 MA 반환으로 변경)
    result['ma_analysis'] = calculate_ma_analysis(
        combined_df, latest_price, ma_periods, return_all=True
    )

    return result
