"""공통 분석 파이프라인 - 페이지네이션 데이터 수집"""
import logging
import time
from datetime import datetime, timedelta
from typing import Callable, List
import pandas as pd

logger = logging.getLogger(__name__)


def fetch_paginated_daily_data(
    api_call: Callable[[str], pd.DataFrame],
    date_col: str,
    target_days: int,
    api_delay: float = 0.1,
) -> List[pd.DataFrame]:
    """날짜 기반 페이지네이션으로 KIS 일별 데이터 수집

    api_call: 종료일(YYYYMMDD 문자열)을 받아 DataFrame을 반환하는 함수
    date_col: 날짜 컬럼명 (페이지 이어받기 기준)
    target_days: 목표 수집 일수
    api_delay: API 호출 간격 (초)
    """
    all_data = []
    call_count = 0
    max_calls = target_days // 100 + 5
    current_end = datetime.now().strftime("%Y%m%d")

    while call_count < max_calls:
        logger.info(f"API 호출 {call_count + 1}회차: 종료일 {current_end}")

        result = api_call(current_end)

        if result is None or result.empty:
            logger.warning("더 이상 데이터가 없습니다.")
            break

        all_data.append(result)
        total_rows = sum(len(df) for df in all_data)
        logger.info(f"현재까지 {total_rows}개 수집, 이번: {len(result)}개")

        if total_rows >= target_days:
            logger.info(f"목표 달성: {total_rows}개 >= {target_days}개")
            break

        if len(result) < 100:
            logger.info("마지막 페이지 도달")
            break

        # 다음 페이지: 마지막 날짜의 하루 전
        last_date = result.iloc[-1][date_col]
        if isinstance(last_date, str):
            last_date_str = last_date.replace("-", "").replace("/", "")[:8]
        else:
            last_date_str = str(last_date)[:8]

        last_dt = datetime.strptime(last_date_str, "%Y%m%d")
        current_end = (last_dt - timedelta(days=1)).strftime("%Y%m%d")

        call_count += 1
        time.sleep(api_delay)

    return all_data
