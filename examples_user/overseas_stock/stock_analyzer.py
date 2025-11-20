"""해외주식 분석 함수 모듈"""
import sys
import logging
from datetime import datetime, timedelta
import os
import time

import pandas as pd

sys.path.extend(['..', '.'])
import kis_auth as ka
from overseas_stock_functions import *

logger = logging.getLogger(__name__)


def fetch_stock_data(excd: str, symb: str, target_days: int = 1095) -> pd.DataFrame:
    """
    해외주식 데이터 가져오기 (최대 100개씩 페이징)

    Args:
        excd: 거래소코드 (NAS: 나스닥, NYS: 뉴욕, AMS: 아멕스, etc)
        symb: 종목코드 (예: TSLA, AAPL)
        target_days: 목표 데이터 일수 (기본 365일 = 1년)

    Returns:
        pd.DataFrame: 주식 데이터
    """
    logger.info(f"해외주식 데이터 수집 시작: {excd}:{symb}")

    all_data2 = []
    end_date_str = datetime.now().strftime("%Y%m%d")

    call_count = 0
    max_calls = int(target_days / 100) + 5  # 여유있게 5번 추가

    while call_count < max_calls:
        logger.info(f"API 호출 {call_count + 1}회차: 종료일 {end_date_str}")

        # 재시도 로직 (최대 3번)
        max_retries = 3
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
                    wait_time = retry_count * 2  # 2초, 4초, 6초 대기
                    logger.warning(f"API 호출 실패 (재시도 {retry_count}/{max_retries}): {e}")
                    logger.info(f"{wait_time}초 대기 후 재시도...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"API 호출 최종 실패: {e}")
                    raise

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

        # API 호출 제한 방지 (0.5초 딜레이)
        time.sleep(0.5)

    if not all_data2:
        raise ValueError("데이터를 가져올 수 없습니다.")

    # 모든 데이터 결합
    combined_df = pd.concat(all_data2, ignore_index=True)
    logger.info(f"총 {len(combined_df)}개의 데이터를 가져왔습니다.")

    # 날짜순 정렬 (오래된 것부터)
    combined_df = combined_df.sort_values('xymd').reset_index(drop=True)

    return combined_df


def analyze_stock(excd: str, symb: str) -> dict:
    """
    해외주식 분석

    Args:
        excd: 거래소코드 (NAS, NYS, AMS 등)
        symb: 종목코드 (TSLA, AAPL 등)

    Returns:
        dict: 분석 결과
    """
    # 데이터 가져오기
    combined_df = fetch_stock_data(excd, symb)

    # 데이터 타입 변환
    combined_df['clos'] = combined_df['clos'].astype(float)  # 종가
    combined_df['open'] = combined_df['open'].astype(float)  # 시가
    combined_df['high'] = combined_df['high'].astype(float)  # 고가
    combined_df['low'] = combined_df['low'].astype(float)   # 저가
    combined_df['tvol'] = combined_df['tvol'].astype(float)  # 거래량

    # 이동평균선 계산
    combined_df['MA_5'] = combined_df['clos'].rolling(window=5).mean()
    combined_df['MA_10'] = combined_df['clos'].rolling(window=10).mean()
    combined_df['MA_20'] = combined_df['clos'].rolling(window=20).mean()
    combined_df['MA_60'] = combined_df['clos'].rolling(window=60).mean()
    combined_df['MA_120'] = combined_df['clos'].rolling(window=120).mean()

    # 가장 최근 데이터
    latest_price = combined_df.iloc[-1]['clos']
    latest_date = combined_df.iloc[-1]['xymd']

    result = {
        'exchange': excd,
        'symbol': symb,
        'latest_price': latest_price,
        'latest_date': latest_date,
        'volume_analysis': {},
        'ma_analysis': {}
    }

    # 거래량 분석
    volume_threshold = combined_df['tvol'].quantile(0.90)  # 상위 10%
    high_volume_df = combined_df[combined_df['tvol'] >= volume_threshold].copy()

    if not high_volume_df.empty:
        # 현재가와의 차이 계산
        high_volume_df['price_diff'] = abs(high_volume_df['clos'] - latest_price)
        high_volume_df['price_direction'] = high_volume_df['clos'] - latest_price

        # 상방 분석
        upper_high_vol = high_volume_df[high_volume_df['price_direction'] > 0].copy()
        if not upper_high_vol.empty:
            # 전체 상방에서 거래량 Top 3
            upper_sorted = upper_high_vol.sort_values('tvol', ascending=False)

            volume_top3 = []
            for i, (idx, row) in enumerate(upper_sorted.iterrows()):
                if i >= 3:  # 3개만
                    break
                volume_top3.append({
                    'date': row['xymd'],
                    'price': row['clos'],
                    'diff_pct': (row['clos'] - latest_price) / latest_price * 100,
                    'volume': int(row['tvol']),
                    'volume_rank': 100 - int(combined_df['tvol'].rank(pct=True).loc[idx] * 100)
                })

            # 10% 이내에서 거래량 Top 3
            upper_10pct = upper_high_vol[
                (upper_high_vol['clos'] - latest_price) / latest_price * 100 <= 10
            ].copy()

            nearby_top3 = []
            if not upper_10pct.empty:
                upper_10pct_sorted = upper_10pct.sort_values('tvol', ascending=False)
                for i, (idx, row) in enumerate(upper_10pct_sorted.iterrows()):
                    if i >= 3:
                        break
                    nearby_top3.append({
                        'date': row['xymd'],
                        'price': row['clos'],
                        'diff_pct': (row['clos'] - latest_price) / latest_price * 100,
                        'volume': int(row['tvol']),
                        'volume_rank': 100 - int(combined_df['tvol'].rank(pct=True).loc[idx] * 100)
                    })

            result['volume_analysis']['upper'] = {
                'volume_top3': volume_top3,
                'nearby_top3': nearby_top3
            }

        # 하방 분석
        lower_high_vol = high_volume_df[high_volume_df['price_direction'] < 0].copy()
        if not lower_high_vol.empty:
            # 전체 하방에서 거래량 Top 3
            lower_sorted = lower_high_vol.sort_values('tvol', ascending=False)

            volume_top3 = []
            for i, (idx, row) in enumerate(lower_sorted.iterrows()):
                if i >= 3:  # 3개만
                    break
                volume_top3.append({
                    'date': row['xymd'],
                    'price': row['clos'],
                    'diff_pct': (row['clos'] - latest_price) / latest_price * 100,
                    'volume': int(row['tvol']),
                    'volume_rank': 100 - int(combined_df['tvol'].rank(pct=True).loc[idx] * 100)
                })

            # 10% 이내에서 거래량 Top 3
            lower_10pct = lower_high_vol[
                (latest_price - lower_high_vol['clos']) / latest_price * 100 <= 10
            ].copy()

            nearby_top3 = []
            if not lower_10pct.empty:
                lower_10pct_sorted = lower_10pct.sort_values('tvol', ascending=False)
                for i, (idx, row) in enumerate(lower_10pct_sorted.iterrows()):
                    if i >= 3:
                        break
                    nearby_top3.append({
                        'date': row['xymd'],
                        'price': row['clos'],
                        'diff_pct': (row['clos'] - latest_price) / latest_price * 100,
                        'volume': int(row['tvol']),
                        'volume_rank': 100 - int(combined_df['tvol'].rank(pct=True).loc[idx] * 100)
                    })

            result['volume_analysis']['lower'] = {
                'volume_top3': volume_top3,
                'nearby_top3': nearby_top3
            }

    # 이동평균선 분석
    latest_ma = combined_df.iloc[-1][['MA_5', 'MA_10', 'MA_20', 'MA_60', 'MA_120']].dropna().astype(float)
    ma_diff = latest_price - latest_ma

    # 지지선: 현재가보다 아래에 있는 MA 중 가장 가까운 것
    ma_diff_lower = ma_diff[ma_diff >= 0]
    if not ma_diff_lower.empty:
        closest_ma_name = ma_diff_lower.idxmin()
        closest_ma_value = latest_ma[closest_ma_name]

        result['ma_analysis']['support_ma'] = {
            'name': closest_ma_name,
            'value': closest_ma_value,
            'diff': latest_price - closest_ma_value,
            'diff_pct': (latest_price - closest_ma_value) / closest_ma_value * 100
        }

    # 저항선: 현재가보다 위에 있는 MA 중 가장 가까운 것
    ma_diff_upper = ma_diff[ma_diff < 0]
    if not ma_diff_upper.empty:
        closest_ma_name = ma_diff_upper.idxmax()
        closest_ma_value = latest_ma[closest_ma_name]

        result['ma_analysis']['resistance_ma'] = {
            'name': closest_ma_name,
            'value': closest_ma_value,
            'diff': latest_price - closest_ma_value,
            'diff_pct': (latest_price - closest_ma_value) / closest_ma_value * 100
        }

    # 모든 이동평균선
    result['ma_analysis']['all'] = {}
    for ma_name in ['MA_5', 'MA_10', 'MA_20', 'MA_60', 'MA_120']:
        ma_value = combined_df.iloc[-1][ma_name]
        if pd.notna(ma_value):
            diff = latest_price - ma_value
            result['ma_analysis']['all'][ma_name] = {
                'value': ma_value,
                'diff': diff,
                'diff_pct': diff / ma_value * 100
            }

    return result
