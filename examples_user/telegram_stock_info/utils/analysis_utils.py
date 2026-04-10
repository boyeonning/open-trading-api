"""공통 분석 유틸리티 함수"""
import logging
import time
import pandas as pd
from typing import Dict, List, Optional
from functools import wraps
from datetime import datetime

from utils.config import ANALYSIS_SETTINGS
from utils.exceptions import DataValidationError, InsufficientDataError

logger = logging.getLogger(__name__)


def performance_monitor(func):
    """함수 실행 시간을 측정하는 데코레이터"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        elapsed_time = time.time() - start_time
        logger.info(f"{func.__name__} 실행 완료: {elapsed_time:.2f}초")
        return result
    return wrapper


def validate_price_data(df: pd.DataFrame, price_col: str, symbol: str) -> None:
    """가격 데이터 검증"""
    if df.empty:
        raise DataValidationError("데이터프레임", "비어있음")

    if price_col not in df.columns:
        raise DataValidationError(price_col, f"컬럼이 존재하지 않음")

    # 숫자 변환 시도
    df[price_col] = pd.to_numeric(df[price_col], errors='coerce')

    # 유효하지 않은 데이터 체크
    invalid_count = df[price_col].isna().sum()
    if invalid_count > 0:
        logger.warning(f"{symbol}: 유효하지 않은 가격 데이터 {invalid_count}개 발견")
        df.dropna(subset=[price_col], inplace=True)

    # 음수 가격 체크
    negative_count = (df[price_col] <= 0).sum()
    if negative_count > 0:
        logger.warning(f"{symbol}: 음수 또는 0 가격 데이터 {negative_count}개 발견")
        df = df[df[price_col] > 0]

    if len(df) == 0:
        raise DataValidationError(price_col, "유효한 가격 데이터가 없음")


def calculate_moving_averages(df: pd.DataFrame, price_col: str, ma_periods: List[int]) -> pd.DataFrame:
    """이동평균선 계산 (데이터 부족시 해당 기간은 건너뜀)"""
    data_length = len(df)

    for period in ma_periods:
        ma_col = f'MA_{period}'
        if data_length >= period:
            df[ma_col] = df[price_col].rolling(window=period).mean()
        else:
            logger.warning(f"MA{period} 계산 불가: 데이터 {data_length}일 < 필요 {period}일")
    return df


def analyze_volume_by_direction(df: pd.DataFrame, latest_price: float,
                                price_col: str, volume_col: str,
                                direction: str, price_range: float) -> List[Dict]:
    """방향별 거래량 분석 (상방/하방)"""
    if direction == 'upper':
        filtered_df = df[
            (df[price_col] > latest_price) &
            ((df[price_col] - latest_price) / latest_price * 100 <= price_range)
        ].copy()
        diff_calc = lambda price: (price - latest_price) / latest_price * 100
    else:  # lower
        filtered_df = df[
            (df[price_col] < latest_price) &
            ((latest_price - df[price_col]) / latest_price * 100 <= price_range)
        ].copy()
        diff_calc = lambda price: (price - latest_price) / latest_price * 100

    if filtered_df.empty:
        return []

    vol_pct_rank = df[volume_col].rank(pct=True)
    sorted_df = filtered_df.sort_values(volume_col, ascending=False)

    result = []
    for i, (idx, row) in enumerate(sorted_df.iterrows()):
        if i >= 3:
            break
        result.append({
            'date': row.get('stck_bsop_date', row.get('xymd', '')),
            'price': row[price_col],
            'diff_pct': diff_calc(row[price_col]),
            'volume': int(row[volume_col]),
            'volume_rank': 100 - int(vol_pct_rank.loc[idx] * 100)
        })

    return result


@performance_monitor
def calculate_volume_analysis(df: pd.DataFrame, latest_price: float,
                              price_col: str, volume_col: str,
                              analysis_type: str = 'domestic') -> Dict:
    """거래량 분석 통합 함수"""
    if df.empty:
        return {}

    settings = ANALYSIS_SETTINGS[analysis_type]
    volume_threshold = df[volume_col].quantile(settings['volume_threshold_percentile'])

    df['price_direction'] = df[price_col] - latest_price
    high_volume_df = df[df[volume_col] >= volume_threshold].copy()

    result = {}

    if not high_volume_df.empty:
        # 상방 분석
        upper_high_vol = high_volume_df[high_volume_df['price_direction'] > 0]
        if not upper_high_vol.empty:
            result['upper'] = {
                'volume_top3': analyze_volume_by_direction(
                    upper_high_vol, latest_price, price_col, volume_col, 'upper', float('inf')
                ),
                'nearby_top3': analyze_volume_by_direction(
                    df, latest_price, price_col, volume_col, 'upper',
                    settings['price_range_limits']['nearby']
                )
            }

        # 하방 분석
        lower_high_vol = high_volume_df[high_volume_df['price_direction'] < 0]
        if not lower_high_vol.empty:
            result['lower'] = {
                'volume_top3': analyze_volume_by_direction(
                    lower_high_vol, latest_price, price_col, volume_col, 'lower', float('inf')
                ),
                'nearby_top3': analyze_volume_by_direction(
                    df, latest_price, price_col, volume_col, 'lower',
                    settings['price_range_limits']['nearby']
                )
            }

    # ±20% 이내 전체 거래량 Top 3
    extended_range = settings['price_range_limits']['extended']
    range_df = df[
        (abs((df[price_col] - latest_price) / latest_price * 100) <= extended_range)
    ].copy()

    if not range_df.empty:
        range_sorted = range_df.sort_values(volume_col, ascending=False)
        vol_pct_rank = df[volume_col].rank(pct=True)

        volume_top3_all = []
        for i, (idx, row) in enumerate(range_sorted.iterrows()):
            if i >= 3:
                break
            volume_top3_all.append({
                'date': row.get('stck_bsop_date', row.get('xymd', '')),
                'price': row[price_col],
                'diff_pct': (row[price_col] - latest_price) / latest_price * 100,
                'volume': int(row[volume_col]),
                'volume_rank': 100 - int(vol_pct_rank.loc[idx] * 100)
            })

        result['volume_top3_20pct_all'] = volume_top3_all

    return result


@performance_monitor
def calculate_ma_analysis(df: pd.DataFrame, latest_price: float,
                          ma_periods: List[int], return_all: bool = True) -> Dict:
    """이동평균선 분석 통합 함수"""
    if df.empty:
        return {}

    available_ma_columns = [f'MA_{period}' for period in ma_periods if f'MA_{period}' in df.columns]
    if not available_ma_columns:
        return {}

    latest_ma = df.iloc[-1][available_ma_columns].dropna().astype(float)

    if latest_ma.empty:
        return {}

    ma_diff = latest_price - latest_ma
    result = {}

    if return_all:
        # 저항선: 현재가보다 위에 있는 모든 MA (가까운 순)
        resistance_ma = ma_diff[ma_diff < 0]
        if not resistance_ma.empty:
            result['resistance_ma'] = [
                {
                    'name': ma_name,
                    'value': latest_ma[ma_name],
                    'diff': latest_price - latest_ma[ma_name],
                    'diff_pct': (latest_price - latest_ma[ma_name]) / latest_ma[ma_name] * 100
                }
                for ma_name in resistance_ma.abs().sort_values().index
            ]

        # 지지선: 현재가보다 아래에 있는 모든 MA (가까운 순)
        support_ma = ma_diff[ma_diff > 0]
        if not support_ma.empty:
            result['support_ma'] = [
                {
                    'name': ma_name,
                    'value': latest_ma[ma_name],
                    'diff': latest_price - latest_ma[ma_name],
                    'diff_pct': (latest_price - latest_ma[ma_name]) / latest_ma[ma_name] * 100
                }
                for ma_name in support_ma.sort_values().index
            ]

    else:
        # 가장 가까운 저항선/지지선만 반환
        resistance_ma = ma_diff[ma_diff < 0]
        if not resistance_ma.empty:
            closest = resistance_ma.abs().idxmin()
            result['resistance_ma'] = {
                'name': closest,
                'value': latest_ma[closest],
                'diff': latest_price - latest_ma[closest],
                'diff_pct': (latest_price - latest_ma[closest]) / latest_ma[closest] * 100
            }

        support_ma = ma_diff[ma_diff > 0]
        if not support_ma.empty:
            closest = support_ma.idxmin()
            result['support_ma'] = {
                'name': closest,
                'value': latest_ma[closest],
                'diff': latest_price - latest_ma[closest],
                'diff_pct': (latest_price - latest_ma[closest]) / latest_price * 100
            }

    # 모든 이동평균선 정보
    result['all'] = {
        ma_name: {
            'value': latest_ma[ma_name],
            'diff': latest_price - latest_ma[ma_name],
            'diff_pct': (latest_price - latest_ma[ma_name]) / latest_ma[ma_name] * 100
        }
        for ma_name in available_ma_columns
        if ma_name in latest_ma.index and pd.notna(latest_ma[ma_name])
    }

    return result


def fetch_today_minute_candles(stock_code: str, env_dv: str) -> pd.DataFrame:
    """오늘 전체 1분봉 데이터를 페이지네이션으로 수집"""
    # circular import 방지를 위해 함수 내부에서 임포트
    from api.domestic_stock_functions import inquire_time_itemchartprice

    all_candles = []
    now = datetime.now()
    start_hour = now.strftime("%H%M%S")
    if start_hour > "153000":
        start_hour = "153000"

    current_hour = start_hour

    for _ in range(14):  # 최대 14회 호출 (390분 / 30 = 13회)
        try:
            _, output2 = inquire_time_itemchartprice(
                env_dv=env_dv,
                fid_cond_mrkt_div_code="J",
                fid_input_iscd=stock_code,
                fid_input_hour_1=current_hour,
                fid_pw_data_incu_yn="Y"
            )
        except Exception as e:
            logger.warning(f"1분봉 조회 오류 (시각={current_hour}): {e}")
            break

        if output2 is None or output2.empty:
            break

        all_candles.append(output2)

        earliest_time = output2['stck_cntg_hour'].iloc[-1]
        if earliest_time <= "090000":
            break

        current_hour = earliest_time
        time.sleep(0.2)

    if not all_candles:
        return pd.DataFrame()

    df = pd.concat(all_candles, ignore_index=True)
    df = df.drop_duplicates(subset=['stck_cntg_hour'])
    df = df[df['stck_cntg_hour'] >= "090000"]
    return df


def analyze_intraday_volume_sr(stock_code: str, stock_name: str, env_dv: str = "real") -> dict:
    """1분봉 거래량 기반 당일 지지/저항 분석"""
    from api.domestic_stock_functions import inquire_price

    price_df = inquire_price(env_dv=env_dv, fid_cond_mrkt_div_code="J", fid_input_iscd=stock_code)
    if price_df is None or price_df.empty:
        return {'error': '현재가를 조회할 수 없습니다.'}

    current_price = int(pd.to_numeric(price_df['stck_prpr'].iloc[0], errors='coerce'))

    df = fetch_today_minute_candles(stock_code, env_dv)

    if df.empty:
        return {'error': '오늘 1분봉 데이터가 없습니다. 장 중(09:00~15:30)에 다시 시도해주세요.'}

    df['cntg_vol'] = pd.to_numeric(df['cntg_vol'], errors='coerce').fillna(0).astype(int)
    df['stck_prpr'] = pd.to_numeric(df['stck_prpr'], errors='coerce')
    df = df.dropna(subset=['stck_prpr'])

    above = df[df['stck_prpr'] > current_price]
    below = df[df['stck_prpr'] < current_price]

    resistance = None
    if not above.empty:
        row = above.loc[above['cntg_vol'].idxmax()]
        resistance = {
            'price': int(row['stck_prpr']),
            'volume': int(row['cntg_vol']),
            'time': row['stck_cntg_hour'],
            'diff_pct': (float(row['stck_prpr']) - current_price) / current_price * 100
        }

    support = None
    if not below.empty:
        row = below.loc[below['cntg_vol'].idxmax()]
        support = {
            'price': int(row['stck_prpr']),
            'volume': int(row['cntg_vol']),
            'time': row['stck_cntg_hour'],
            'diff_pct': (float(row['stck_prpr']) - current_price) / current_price * 100
        }

    return {
        'stock_code': stock_code,
        'stock_name': stock_name,
        'current_price': current_price,
        'resistance': resistance,
        'support': support,
        'total_candles': len(df)
    }


def validate_analysis_data(df: pd.DataFrame, symbol: str, min_days: int = None) -> None:
    """분석용 데이터 검증"""
    if df.empty:
        raise InsufficientDataError(symbol, min_days or 100, 0)

    if min_days and len(df) < min_days:
        logger.warning(f"{symbol}: 권장 데이터량 부족 (권장: {min_days}일, 실제: {len(df)}일) - 분석 진행")

    logger.info(f"{symbol}: {len(df)}일치 데이터 검증 완료")
