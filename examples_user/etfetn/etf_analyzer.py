"""ETF 분석 함수 모듈"""
import sys
import logging
from datetime import datetime, timedelta

import pandas as pd

sys.path.extend(['..', '.'])
import kis_auth as ka
from etfetn_functions import *

logger = logging.getLogger('etf_analyzer')


def analyze_etf(iscd: str) -> dict:
    """
    ETF 분석 (거래량 기반 지지/저항선 + 이동평균선)

    Args:
        iscd: ETF 종목코드

    Returns:
        dict: 분석 결과
    """
    try:
        # 현재 가격 조회
        current_df = inquire_price(fid_cond_mrkt_div_code="J", fid_input_iscd=iscd)

        if current_df.empty:
            logger.error(f"ETF {iscd}의 현재가 조회 실패")
            return None

        latest_price = float(current_df.iloc[0]['stck_prpr'])
        etf_name = current_df.iloc[0]['bstp_kor_isnm']
        latest_date = datetime.now().strftime('%Y-%m-%d')

        logger.info(f"ETF: {etf_name} ({iscd}), 현재가: {latest_price:,.0f}원")

        # 3년치 일별 데이터 조회
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365*3)

        daily_df = nav_comparison_daily_trend(
            fid_cond_mrkt_div_code="J",
            fid_input_iscd=iscd,
            fid_input_date_1=start_date.strftime('%Y%m%d'),
            fid_input_date_2=end_date.strftime('%Y%m%d')
        )

        if daily_df.empty:
            logger.error("일별 데이터 조회 실패")
            return None

        # 컬럼명 확인 및 데이터 타입 변환
        logger.info(f"일별 데이터 컬럼: {daily_df.columns.tolist()}")

        # 필요한 컬럼: 날짜, 종가, 거래량
        # stck_bsop_date: 날짜, stck_clpr: 종가, acml_vol: 거래량
        daily_df['stck_clpr'] = pd.to_numeric(daily_df['stck_clpr'], errors='coerce')
        daily_df['acml_vol'] = pd.to_numeric(daily_df['acml_vol'], errors='coerce')

        # 결측치 제거
        daily_df = daily_df.dropna(subset=['stck_clpr', 'acml_vol'])

        if len(daily_df) < 120:
            logger.warning(f"데이터가 부족합니다 (최소 120일 필요, 현재 {len(daily_df)}일)")

        # 이동평균선 계산
        daily_df['MA_5'] = daily_df['stck_clpr'].rolling(window=5).mean()
        daily_df['MA_10'] = daily_df['stck_clpr'].rolling(window=10).mean()
        daily_df['MA_20'] = daily_df['stck_clpr'].rolling(window=20).mean()
        daily_df['MA_60'] = daily_df['stck_clpr'].rolling(window=60).mean()
        daily_df['MA_120'] = daily_df['stck_clpr'].rolling(window=120).mean()

        # 분석 결과 저장
        result = {
            'etf_name': etf_name,
            'iscd': iscd,
            'latest_price': latest_price,
            'latest_date': latest_date,
            'volume_analysis': {
                'upper': {},
                'lower': {}
            },
            'ma_analysis': {}
        }

        # 거래량 분석 (상위 10% 거래량 기준)
        volume_threshold = daily_df['acml_vol'].quantile(0.90)
        high_volume_df = daily_df[daily_df['acml_vol'] >= volume_threshold].copy()

        logger.info(f"전체 {len(daily_df)}일 중 상위 10% 거래량 기준: {len(high_volume_df)}일")

        if not high_volume_df.empty:
            # 현재가와의 차이 계산
            high_volume_df['price_diff'] = abs(high_volume_df['stck_clpr'] - latest_price)
            high_volume_df['price_direction'] = high_volume_df['stck_clpr'] - latest_price

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
                        'volume_rank': 100 - int(daily_df['acml_vol'].rank(pct=True).loc[idx] * 100)
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
                            'volume_rank': 100 - int(daily_df['acml_vol'].rank(pct=True).loc[idx] * 100)
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
                        'volume_rank': 100 - int(daily_df['acml_vol'].rank(pct=True).loc[idx] * 100)
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
                            'volume_rank': 100 - int(daily_df['acml_vol'].rank(pct=True).loc[idx] * 100)
                        })

                result['volume_analysis']['lower'] = {
                    'volume_top3': volume_top3,
                    'nearby_top3': nearby_top3
                }

        # 이동평균선 분석
        latest_ma = daily_df.iloc[-1][['MA_5', 'MA_10', 'MA_20', 'MA_60', 'MA_120']].dropna().astype(float)
        ma_diff = latest_price - latest_ma

        # 가장 가까운 저항선 (현재가 위)
        resistance_ma = ma_diff[ma_diff < 0]
        if not resistance_ma.empty:
            closest_resistance = resistance_ma.abs().idxmin()
            result['ma_analysis']['resistance_ma'] = {
                'name': closest_resistance,
                'value': latest_ma[closest_resistance],
                'diff_pct': (latest_ma[closest_resistance] - latest_price) / latest_price * 100
            }

        # 가장 가까운 지지선 (현재가 아래)
        support_ma = ma_diff[ma_diff > 0]
        if not support_ma.empty:
            closest_support = support_ma.idxmin()
            result['ma_analysis']['support_ma'] = {
                'name': closest_support,
                'value': latest_ma[closest_support],
                'diff_pct': (latest_price - latest_ma[closest_support]) / latest_price * 100
            }

        return result

    except Exception as e:
        logger.error(f"ETF 분석 중 오류 발생: {e}", exc_info=True)
        return None


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
