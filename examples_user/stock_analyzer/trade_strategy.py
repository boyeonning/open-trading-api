"""
주식 기술적 분석 스크립트
Usage:
    python analyze.py 062040
    python analyze.py 한화오션
"""
import sys
import os
import warnings
import logging
import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
logging.disable(logging.CRITICAL)

# telegram_stock_info 경로 추가
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_DIR = os.path.join(os.path.dirname(BASE_DIR), 'telegram_stock_info')
sys.path.extend([BOT_DIR, os.path.dirname(BASE_DIR)])

import kis_auth as ka
from analyzers.domestic import fetch_stock_data
from utils.analysis_utils import calculate_moving_averages


def find_stock_name(code: str) -> str:
    """마스터 CSV에서 종목명 조회"""
    stocks_dir = os.path.join(os.path.dirname(os.path.dirname(BASE_DIR)), 'stocks_info')
    for f in ['kis_kospi_code_mst.csv', 'kis_kosdaq_code_mst.csv']:
        fp = os.path.join(stocks_dir, f)
        if not os.path.exists(fp):
            continue
        try:
            df = pd.read_csv(fp, header=None, names=['단축코드', '표준코드', '한글종목명'], encoding='utf-8')
        except UnicodeDecodeError:
            df = pd.read_csv(fp, header=None, names=['단축코드', '표준코드', '한글종목명'], encoding='cp949')
        r = df[df['단축코드'] == code]
        if not r.empty:
            return r.iloc[0]['한글종목명']
    return '(종목명 없음)'


def find_stock_code(name: str) -> tuple[str, str]:
    """종목명으로 코드 조회, (코드, 종목명) 반환"""
    stocks_dir = os.path.join(os.path.dirname(os.path.dirname(BASE_DIR)), 'stocks_info')
    for f in ['kis_kospi_code_mst.csv', 'kis_kosdaq_code_mst.csv']:
        fp = os.path.join(stocks_dir, f)
        if not os.path.exists(fp):
            continue
        try:
            df = pd.read_csv(fp, header=None, names=['단축코드', '표준코드', '한글종목명'], encoding='utf-8')
        except UnicodeDecodeError:
            df = pd.read_csv(fp, header=None, names=['단축코드', '표준코드', '한글종목명'], encoding='cp949')
        r = df[df['한글종목명'].str.contains(name, case=False, na=False)]
        if not r.empty:
            row = r.iloc[0]
            return row['단축코드'], row['한글종목명']
    return None, None


def analyze(stock_input: str):
    # 종목코드/종목명 구분
    if len(stock_input) == 6 and stock_input.isdigit():
        stock_code = stock_input
        stock_name = find_stock_name(stock_code)
    else:
        stock_code, stock_name = find_stock_code(stock_input)
        if not stock_code:
            print(f"[오류] '{stock_input}' 종목을 찾을 수 없습니다.")
            sys.exit(1)

    # 데이터 수집
    ka.auth()
    df = fetch_stock_data(stock_code)
    for col in ['stck_clpr', 'stck_oprc', 'stck_hgpr', 'stck_lwpr', 'acml_vol']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = calculate_moving_averages(df, 'stck_clpr', [5, 10, 20, 60, 120, 240])

    latest = df.iloc[-1]
    price = float(latest['stck_clpr'])
    date = latest['stck_bsop_date']

    # ATR14
    df['tr'] = np.maximum(
        df['stck_hgpr'] - df['stck_lwpr'],
        np.maximum(
            abs(df['stck_hgpr'] - df['stck_clpr'].shift(1)),
            abs(df['stck_lwpr'] - df['stck_clpr'].shift(1))
        )
    )
    atr14 = float(df['tr'].tail(14).mean())

    # RSI14
    delta = df['stck_clpr'].diff()
    avg_gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    avg_loss = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    rsi14 = float((100 - (100 / (1 + avg_gain / avg_loss))).iloc[-1])

    # 볼린저 밴드(20일)
    ma20_roll = df['stck_clpr'].rolling(20).mean()
    std20_roll = df['stck_clpr'].rolling(20).std()
    bb_upper = float(ma20_roll.iloc[-1] + 2 * std20_roll.iloc[-1])
    bb_lower = float(ma20_roll.iloc[-1] - 2 * std20_roll.iloc[-1])

    # 기간별 고저
    r20 = df.tail(20)
    r60 = df.tail(60)
    high20, low20 = float(r20['stck_hgpr'].max()), float(r20['stck_lwpr'].min())
    high60, low60 = float(r60['stck_hgpr'].max()), float(r60['stck_lwpr'].min())

    # 거래량
    vol5 = float(df['acml_vol'].tail(5).mean())
    vol20 = float(df['acml_vol'].tail(20).mean())
    vol_ratio = vol5 / vol20 if vol20 > 0 else 0

    # 지지선 계산 (현재가 아래에 있는 값들)
    support_candidates = {}

    # 최근 저점들 (5일/10일/20일)
    low5  = float(df.tail(5)['stck_lwpr'].min())
    low10 = float(df.tail(10)['stck_lwpr'].min())
    if low5 < price:
        support_candidates['5일저점'] = low5
    if low10 < price:
        support_candidates['10일저점'] = low10
    if low20 < price:
        support_candidates['20일저점'] = low20

    # 현재가 아래 이평선
    for period in [5, 10, 20, 60, 120, 240]:
        col = f'MA_{period}'
        if col in df.columns and pd.notna(latest[col]):
            val = float(latest[col])
            if val < price:
                support_candidates[f'MA{period}'] = val

    # 볼린저 하단
    if bb_lower < price:
        support_candidates['볼린저하단'] = bb_lower

    # 저항선 계산 (현재가 위에 있는 값들)
    resistance_candidates = {}
    high5  = float(df.tail(5)['stck_hgpr'].max())
    high10 = float(df.tail(10)['stck_hgpr'].max())
    if high5 > price:
        resistance_candidates['5일고점'] = high5
    if high10 > price:
        resistance_candidates['10일고점'] = high10
    if high20 > price:
        resistance_candidates['20일고점'] = high20
    for period in [5, 10, 20, 60, 120, 240]:
        col = f'MA_{period}'
        if col in df.columns and pd.notna(latest[col]):
            val = float(latest[col])
            if val > price:
                resistance_candidates[f'MA{period}'] = val
    if bb_upper > price:
        resistance_candidates['볼린저상단'] = bb_upper

    # 1차 손절선: 현재가 바로 아래 가장 가까운 지지선 아래 (ATR * 0.5 여유)
    supports_below = {k: v for k, v in support_candidates.items() if v < price}
    if supports_below:
        nearest_support_name = max(supports_below, key=lambda k: supports_below[k])
        nearest_support = supports_below[nearest_support_name]
        stop_loss = nearest_support - atr14 * 0.5
    else:
        nearest_support_name = '볼린저하단'
        nearest_support = bb_lower
        stop_loss = bb_lower - atr14 * 0.5

    # 1차/2차 목표가: 현재가 바로 위 가장 가까운 저항선 순서
    resistances_above = sorted(
        [(k, v) for k, v in resistance_candidates.items() if v > price],
        key=lambda x: x[1]
    )
    target1_name, target1 = resistances_above[0] if len(resistances_above) > 0 else ('없음', price * 1.05)
    target2_name, target2 = resistances_above[1] if len(resistances_above) > 1 else ('없음', price * 1.10)

    # 손익비 계산
    risk = price - stop_loss
    reward1 = target1 - price
    reward2 = target2 - price
    rr1 = reward1 / risk if risk > 0 else 0
    rr2 = reward2 / risk if risk > 0 else 0

    # 출력
    sep = '=' * 50
    print(sep)
    print(f"  종목: {stock_name} ({stock_code})")
    print(f"  기준일: {date}  현재가: {price:,.0f}원")
    print(sep)

    print("\n[이동평균선]")
    for period in [5, 10, 20, 60, 120, 240]:
        col = f'MA_{period}'
        val = float(latest[col]) if col in df.columns and pd.notna(latest[col]) else None
        if val:
            diff_pct = (price - val) / val * 100
            sign = '▲' if diff_pct >= 0 else '▼'
            print(f"  MA{period:3d}: {val:>10,.0f}원  ({sign}{abs(diff_pct):.1f}%)")
        else:
            print(f"  MA{period:3d}: N/A")

    print("\n[보조 지표]")
    print(f"  ATR14:      {atr14:>10,.0f}원  (일평균 변동폭)")
    print(f"  RSI14:      {rsi14:>10.1f}    ({'과매도' if rsi14 < 30 else '과매수' if rsi14 > 70 else '중립'})")
    print(f"  볼린저 상단: {bb_upper:>10,.0f}원")
    print(f"  볼린저 하단: {bb_lower:>10,.0f}원")

    print("\n[기간별 고저]")
    print(f"  20일 고점: {high20:>10,.0f}원 / 저점: {low20:>10,.0f}원")
    print(f"  60일 고점: {high60:>10,.0f}원 / 저점: {low60:>10,.0f}원")

    print("\n[거래량]")
    print(f"  5일 평균:  {vol5:>12,.0f}")
    print(f"  20일 평균: {vol20:>12,.0f}")
    print(f"  비율(5/20): {vol_ratio:.2f}  ({'거래량 증가' if vol_ratio > 1.2 else '거래량 감소' if vol_ratio < 0.8 else '보통'})")

    print("\n[매매 참고]")
    print(f"  지지선(근거): {nearest_support:>10,.0f}원  ({nearest_support_name})")
    print(f"  손절선:       {stop_loss:>10,.0f}원  (지지선 - ATR×0.5)")
    print(f"  1차 목표:     {target1:>10,.0f}원  ({target1_name})")
    print(f"  2차 목표:     {target2:>10,.0f}원  ({target2_name})")
    print(f"  손익비(1차):  1 : {rr1:.1f}")
    print(f"  손익비(2차):  1 : {rr2:.1f}")

    print("\n[최근 10일 캔들]")
    for _, row in df.tail(10).iterrows():
        o, h, l, c = int(row['stck_oprc']), int(row['stck_hgpr']), int(row['stck_lwpr']), int(row['stck_clpr'])
        v = int(row['acml_vol'])
        sign = '▲' if c >= o else '▼'
        print(f"  {row['stck_bsop_date']}: 시{o:,} 고{h:,} 저{l:,} 종{c:,} {sign}{abs(c-o):,}  거래량{v:,}")

    print(sep)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python analyze.py <종목코드 또는 종목명>")
        print("  예) python analyze.py 062040")
        print("  예) python analyze.py 한화오션")
        sys.exit(1)

    analyze(sys.argv[1])
