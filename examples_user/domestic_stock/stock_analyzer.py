"""주식 분석 함수 모듈"""
import sys
import logging
from datetime import datetime, timedelta
import os
import time

import pandas as pd

sys.path.extend(['..', '.'])
import kis_auth as ka
from domestic_stock_functions import *

logger = logging.getLogger(__name__)


def get_stock_code(stock_name: str) -> tuple[str, str, list]:
    """
    종목명으로 종목코드 찾기

    Returns:
        tuple: (종목코드, 종목명, 검색결과리스트)
    """
    kosdaq_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                               "stocks_info", "kosdaq_code_part1.tmp")
    kospi_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                              "stocks_info", "kospi_code_part1.tmp")

    for file_path in [kosdaq_file, kospi_file]:
        if os.path.exists(file_path):
            # Try utf-8 first (for newly generated files), fallback to cp949
            try:
                df = pd.read_csv(file_path, header=None, names=['단축코드', '표준코드', '한글종목명'], encoding='utf-8')
            except UnicodeDecodeError:
                df = pd.read_csv(file_path, header=None, names=['단축코드', '표준코드', '한글종목명'], encoding='cp949')
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

    raise ValueError(f"종목명 '{stock_name}'을 찾을 수 없습니다. 코스피/코스닥 마스터 파일을 먼저 생성하세요.")


def fetch_stock_data(stock_code: str, target_days: int = 1095) -> pd.DataFrame:
    """주식 데이터 가져오기"""
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
        raise ValueError("데이터를 가져올 수 없습니다.")


def analyze_stock(stock_input: str) -> dict:
    """
    주식 분석 메인 함수

    Args:
        stock_input: 종목명 또는 종목코드

    Returns:
        분석 결과 딕셔너리
    """
    # 종목 코드 확인
    if stock_input.isdigit():
        stock_code = stock_input
        stock_name = None
        search_results = []
        logger.info(f"종목코드 직접 입력: {stock_code}")
    else:
        stock_code, stock_name, search_results = get_stock_code(stock_input)

    # 데이터 가져오기
    combined_df = fetch_stock_data(stock_code)

    # 데이터 타입 변환
    combined_df['stck_clpr'] = combined_df['stck_clpr'].astype(float)
    combined_df['stck_oprc'] = combined_df['stck_oprc'].astype(float)
    combined_df['stck_hgpr'] = combined_df['stck_hgpr'].astype(float)
    combined_df['stck_lwpr'] = combined_df['stck_lwpr'].astype(float)
    combined_df['acml_vol'] = combined_df['acml_vol'].astype(float)

    # 이동평균선 계산
    combined_df['MA_5'] = combined_df['stck_clpr'].rolling(window=5).mean()
    combined_df['MA_10'] = combined_df['stck_clpr'].rolling(window=10).mean()
    combined_df['MA_20'] = combined_df['stck_clpr'].rolling(window=20).mean()
    combined_df['MA_60'] = combined_df['stck_clpr'].rolling(window=60).mean()
    combined_df['MA_120'] = combined_df['stck_clpr'].rolling(window=120).mean()

    # 가장 최근 데이터
    latest_price = combined_df.iloc[-1]['stck_clpr']
    latest_date = combined_df.iloc[-1]['stck_bsop_date']

    # 결과 딕셔너리
    result = {
        'stock_code': stock_code,
        'stock_name': stock_name,
        'search_results': search_results,
        'latest_date': latest_date,
        'latest_price': latest_price,
        'volume_analysis': {},
        'ma_analysis': {}
    }

    # 거래량 분석
    combined_df['price_diff'] = (combined_df['stck_clpr'] - latest_price).abs()
    combined_df['price_direction'] = combined_df['stck_clpr'] - latest_price

    volume_threshold = combined_df['acml_vol'].quantile(0.90)
    high_volume_df = combined_df[combined_df['acml_vol'] >= volume_threshold].copy()

    if not high_volume_df.empty:
        # 상방 분석
        upper_high_vol = high_volume_df[high_volume_df['price_direction'] > 0].copy()
        if not upper_high_vol.empty:
            # 전체 상방에서 거래량 Top 3
            upper_sorted = upper_high_vol.sort_values('acml_vol', ascending=False)

            volume_top3 = []
            for i, (idx, row) in enumerate(upper_sorted.iterrows()):
                if i >= 3:
                    break
                volume_top3.append({
                    'date': row['stck_bsop_date'],
                    'price': row['stck_clpr'],
                    'diff_pct': (row['stck_clpr'] - latest_price) / latest_price * 100,
                    'volume': int(row['acml_vol']),
                    'volume_rank': 100 - int(combined_df['acml_vol'].rank(pct=True).loc[idx] * 100)
                })

            # 10% 이내에서 거래량 Top 3
            upper_10pct = upper_high_vol[
                (upper_high_vol['stck_clpr'] - latest_price) / latest_price * 100 <= 10
            ].copy()

            nearby_top3 = []
            if not upper_10pct.empty:
                upper_10pct_sorted = upper_10pct.sort_values('acml_vol', ascending=False)
                for i, (idx, row) in enumerate(upper_10pct_sorted.iterrows()):
                    if i >= 3:
                        break
                    nearby_top3.append({
                        'date': row['stck_bsop_date'],
                        'price': row['stck_clpr'],
                        'diff_pct': (row['stck_clpr'] - latest_price) / latest_price * 100,
                        'volume': int(row['acml_vol']),
                        'volume_rank': 100 - int(combined_df['acml_vol'].rank(pct=True).loc[idx] * 100)
                    })

            result['volume_analysis']['upper'] = {
                'volume_top3': volume_top3,
                'nearby_top3': nearby_top3
            }

        # 하방 분석
        lower_high_vol = high_volume_df[high_volume_df['price_direction'] < 0].copy()
        if not lower_high_vol.empty:
            # 전체 하방에서 거래량 Top 3
            lower_sorted = lower_high_vol.sort_values('acml_vol', ascending=False)

            volume_top3 = []
            for i, (idx, row) in enumerate(lower_sorted.iterrows()):
                if i >= 3:
                    break
                volume_top3.append({
                    'date': row['stck_bsop_date'],
                    'price': row['stck_clpr'],
                    'diff_pct': (row['stck_clpr'] - latest_price) / latest_price * 100,
                    'volume': int(row['acml_vol']),
                    'volume_rank': 100 - int(combined_df['acml_vol'].rank(pct=True).loc[idx] * 100)
                })

            # 10% 이내에서 거래량 Top 3
            lower_10pct = lower_high_vol[
                (latest_price - lower_high_vol['stck_clpr']) / latest_price * 100 <= 10
            ].copy()

            nearby_top3 = []
            if not lower_10pct.empty:
                lower_10pct_sorted = lower_10pct.sort_values('acml_vol', ascending=False)
                for i, (idx, row) in enumerate(lower_10pct_sorted.iterrows()):
                    if i >= 3:
                        break
                    nearby_top3.append({
                        'date': row['stck_bsop_date'],
                        'price': row['stck_clpr'],
                        'diff_pct': (row['stck_clpr'] - latest_price) / latest_price * 100,
                        'volume': int(row['acml_vol']),
                        'volume_rank': 100 - int(combined_df['acml_vol'].rank(pct=True).loc[idx] * 100)
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
