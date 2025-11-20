"""해외주식 분석 테스트"""
import sys
import logging

sys.path.extend(['..', '.'])
import kis_auth as ka
from stock_analyzer import analyze_stock

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

# 인증
ka.auth()

# 분석할 종목
EXCHANGE = "NAS"  # NAS: 나스닥, NYS: 뉴욕, AMS: 아멕스
SYMBOL = "NVDA"   # 테슬라

print(f"분석 시작: {EXCHANGE}:{SYMBOL}")
print("=" * 60)

result = analyze_stock(EXCHANGE, SYMBOL)

print(f"\n종목: {result['symbol']} ({result['exchange']})")
print(f"현재가: ${result['latest_price']:,.2f}")
print(f"기준일: {result['latest_date']}")
print("=" * 60)

# 상방 거래량 분석
if 'upper' in result['volume_analysis']:
    upper = result['volume_analysis']['upper']
    print(f"\n📈 저항선 (상방)")
    print("-" * 60)

    if 'closest_list' in upper:
        for i, closest in enumerate(upper['closest_list'], 1):
            print(f"[{i}순위] ${closest['price']:,.2f} (+{closest['diff_pct']:.1f}%)")
            print(f"     {closest['date']} / 거래량 {closest['volume']:,} (상위 {closest['volume_rank']:.0f}%)")

    if 'max_volume' in upper:
        max_vol = upper['max_volume']
        print(f"[최대] ${max_vol['price']:,.2f} (+{max_vol['diff_pct']:.1f}%)")
        print(f"     {max_vol['date']} / 최대 거래량 {max_vol['volume']:,}")

# 하방 거래량 분석
if 'lower' in result['volume_analysis']:
    lower = result['volume_analysis']['lower']
    print(f"\n📉 지지선 (하방)")
    print("-" * 60)

    if 'closest_list' in lower:
        for i, closest in enumerate(lower['closest_list'], 1):
            print(f"[{i}순위] ${closest['price']:,.2f} ({closest['diff_pct']:.1f}%)")
            print(f"     {closest['date']} / 거래량 {closest['volume']:,} (상위 {closest['volume_rank']:.0f}%)")

    if 'max_volume' in lower:
        max_vol = lower['max_volume']
        print(f"[최대] ${max_vol['price']:,.2f} ({max_vol['diff_pct']:.1f}%)")
        print(f"     {max_vol['date']} / 최대 거래량 {max_vol['volume']:,}")

# 이동평균선 분석
ma_analysis = result.get('ma_analysis', {})
if 'support_ma' in ma_analysis or 'resistance_ma' in ma_analysis:
    print(f"\n📊 이동평균선")
    print("-" * 60)

    if 'resistance_ma' in ma_analysis:
        ma = ma_analysis['resistance_ma']
        print(f"🔴 저항: {ma['name']} ${ma['value']:,.2f} ({ma['diff_pct']:.1f}%)")

    if 'support_ma' in ma_analysis:
        ma = ma_analysis['support_ma']
        print(f"🟢 지지: {ma['name']} ${ma['value']:,.2f} (+{ma['diff_pct']:.1f}%)")

print("\n" + "=" * 60)
