#!/usr/bin/env python3
"""
미국 레버리지 ETF 투자기법 v4.5 — 매수가 계산기

사용법:
    python leverage_calc.py
    python leverage_calc.py TQQQ
    python leverage_calc.py TQQQ --vix 25
    python leverage_calc.py NVDL --below-50ma
    python leverage_calc.py SOXL --below-200ma

전날 종가와 VIX는 Yahoo Finance에서 자동 조회합니다.
"""

import sys
import os
import argparse
import logging
import requests
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# kis_auth 경로 (examples_user/ 기준)
_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

# 거래소 코드 매핑 (KIS API용)
_TICKER_EXCD: dict[str, str] = {'TQQQ': 'NAS', 'FNGU': 'NAS'}
_DEFAULT_EXCD = 'AMS'   # NYSE Arca

# ──────────────────────────────────────────────────────────
#  등급별 운용 파라미터
# ──────────────────────────────────────────────────────────
GRADE_CONFIG = {
    'tier1_stable': {
        'name': '1등급 안정형',
        'entry_pct': 3.0,          # 1차 진입: 전날 종가 대비 -3%
        'add_pct': 4.0,            # 추매: 현재 평단 대비 -4%
        'target_pcts': [4.0, 6.0, 8.0],  # 1차 / 2~3차 / 4~5차 목표수익률
        'stop_pct': 6.0,           # 손절: 평단 대비 -6%
        'hold_days': 5,
        'amounts': [100, 150, 150, 200, 200],  # 차수별 투입 만원 (정상)
    },
    'tier1_volatile': {
        'name': '1등급 변동형',
        'entry_pct': 4.5,
        'add_pct': 5.0,
        'target_pcts': [5.0, 7.0, 9.0],
        'stop_pct': 7.0,
        'hold_days': 4,
        'amounts': [100, 150, 150, 200, 200],
    },
    'tier2': {
        'name': '2등급 핵심 단일주',
        'entry_pct': 5.0,
        'add_pct': 5.0,
        'target_pcts': [5.0, 7.0, 10.0],
        'stop_pct': 6.0,
        'hold_days': 4,
        'amounts': [100, 150, 150, 200, 200],
    },
    'tier3': {
        'name': '3등급 특수·고위험',
        'entry_pct': 6.0,
        'add_pct': 7.0,
        'target_pcts': [6.0, 8.0, 10.0],
        'stop_pct': 7.0,
        'hold_days': 4,   # 3~4일
        'amounts': [100, 150, 150, 200, 200],
    },
}

# ──────────────────────────────────────────────────────────
#  종목 → 등급 매핑
# ──────────────────────────────────────────────────────────
TICKER_GRADE: dict[str, str] = {
    # 1등급 안정형 (지수형·2배 완충재)
    'UPRO': 'tier1_stable', 'SSO': 'tier1_stable', 'QLD': 'tier1_stable',
    'USD':  'tier1_stable', 'UWM': 'tier1_stable', 'FAS': 'tier1_stable',
    'DRN':  'tier1_stable',
    # 1등급 변동형 (3배·고변동 섹터)
    'TQQQ': 'tier1_volatile', 'SOXL': 'tier1_volatile', 'TECL': 'tier1_volatile',
    'TNA':  'tier1_volatile', 'LABU': 'tier1_volatile', 'DPST': 'tier1_volatile',
    'ERX':  'tier1_volatile', 'NAIL': 'tier1_volatile', 'FNGU': 'tier1_volatile',
    'YINN': 'tier1_volatile',
    # 2등급 핵심 단일주 (단일주 2배 ETF)
    'NVDL': 'tier2', 'TSLL': 'tier2', 'AVL':  'tier2', 'ARMG': 'tier2',
    'TSMX': 'tier2', 'PTIR': 'tier2', 'GGLL': 'tier2', 'ORCX': 'tier2',
    'ROBN': 'tier2', 'MRVU': 'tier2', 'VRTL': 'tier2', 'AAPU': 'tier2',
    'METU': 'tier2', 'MSFU': 'tier2', 'AMZU': 'tier2', 'MUU':  'tier2',
    'ASMU': 'tier2', 'SMCX': 'tier2', 'CSEX': 'tier2', 'SOFA': 'tier2',
    'BABU': 'tier2', 'OKLL': 'tier2',
    # 3등급 특수·고위험
    'AGQ':  'tier3', 'UCO':  'tier3', 'BOIL': 'tier3', 'TMF':  'tier3',
    'TYD':  'tier3', 'YCL':  'tier3', 'BITX': 'tier3', 'ETHU': 'tier3',
    'XXRP': 'tier3', 'SOLT': 'tier3', 'MSTX': 'tier3', 'CONL': 'tier3',
}

# ──────────────────────────────────────────────────────────
#  클러스터 정의 (같은 방향 종목 묶음)
# ──────────────────────────────────────────────────────────
CLUSTERS: dict[str, list[str]] = {
    'AI·반도체':   ['SOXL', 'USD', 'NVDL', 'AVL', 'ARMG', 'TSMX',
                    'MRVU', 'VRTL', 'ASMU', 'MUU', 'SMCX', 'CSEX'],
    '메가테크':    ['TQQQ', 'QLD', 'FNGU', 'TECL', 'AAPU', 'MSFU',
                    'GGLL', 'METU', 'AMZU', 'PTIR', 'ORCX'],
    '크립토':      ['BITX', 'ETHU', 'XXRP', 'SOLT', 'MSTX', 'CONL', 'ROBN'],
    '중국':        ['YINN', 'BABU'],
    '금융':        ['FAS', 'DPST', 'SOFA'],
    '금리·채권':   ['TMF', 'TYD', 'YCL'],
    'S&P/Russell': ['UPRO', 'SSO', 'TNA', 'UWM'],
    '기타 섹터':   ['LABU', 'ERX', 'NAIL', 'DRN', 'AGQ', 'UCO', 'BOIL'],
}

CLUSTER_RULE: dict[str, str] = {
    'AI·반도체':  '기본 1종목. 예외(QQQ 50일선 위 + VIX ≤ 22)에만 최대 2종목',
    '메가테크':   '기본 최대 2종목',
    '크립토':     '기본 1종목',
    '중국':       '기본 1종목',
    '금융':       '기본 1종목',
    '금리·채권':  '기본 1종목',
}

FORBIDDEN_COMBOS: dict[str, list[str]] = {
    'AI·반도체': [
        'SOXL + NVDL + AVL',
        'NVDL + MRVU + ASMU',
        'SOXL + TSMX + MUU',
    ],
    '메가테크': [
        'TQQQ + AAPU + MSFU',
        'FNGU + GGLL + METU',
    ],
}


# ──────────────────────────────────────────────────────────
#  데이터 조회 — KIS API 우선, 실패 시 Yahoo Finance 폴백
# ──────────────────────────────────────────────────────────

def _fetch_yahoo(ticker: str) -> tuple[float, str]:
    """Yahoo Finance 공개 API로 최근 종가 조회"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {'interval': '1d', 'range': '5d'}
    headers = {'User-Agent': 'Mozilla/5.0'}

    resp = requests.get(url, params=params, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    result = data['chart']['result'][0]
    timestamps = result['timestamp']
    closes = result['indicators']['quote'][0]['close']

    valid = [(t, c) for t, c in zip(timestamps, closes) if c is not None]
    if not valid:
        raise ValueError(f"{ticker}: 유효한 종가 데이터 없음")

    last_ts, last_close = valid[-1]
    date_str = datetime.fromtimestamp(last_ts).strftime('%Y-%m-%d')
    return last_close, date_str


def _fetch_kis(ticker: str) -> tuple[float, str]:
    """KIS 해외주식 현재체결가 API → base(기준가 = 전날 종가) 반환"""
    import kis_auth as ka
    from telegram_stock_info.api.overseas_stock_functions import price as kis_price

    excd = _TICKER_EXCD.get(ticker, _DEFAULT_EXCD)
    ka.auth()
    df = kis_price("", excd, ticker)

    if df is None or df.empty:
        raise ValueError(f"KIS: {ticker} 데이터 없음")

    row = df.iloc[0]
    for col in ('base', 'last'):
        val = row.get(col, '')
        if val not in ('', None, '0', 0):
            return float(val), datetime.now().strftime('%Y-%m-%d')

    raise ValueError(f"KIS: {ticker} 유효한 가격 없음")


def fetch_prev_close(ticker: str) -> tuple[float, str]:
    """전날 종가 조회 — KIS API 우선, 실패 시 Yahoo Finance 폴백"""
    ticker = ticker.upper()
    try:
        close, date = _fetch_kis(ticker)
        logger.info(f"KIS API: {ticker} ${close:.2f}")
        return close, date
    except Exception as e:
        logger.warning(f"KIS 실패 ({ticker}): {e} → Yahoo Finance 폴백")
        return _fetch_yahoo(ticker)


def fetch_vix() -> Optional[float]:
    """VIX 최근값 조회 (Yahoo Finance, 실패 시 None)"""
    try:
        close, _ = _fetch_yahoo('^VIX')
        return close
    except Exception:
        return None


# ──────────────────────────────────────────────────────────
#  핵심 계산 로직
# ──────────────────────────────────────────────────────────

def calculate_buy_plan(close_price: float, grade: str,
                       vix: Optional[float] = None,
                       below_50ma: bool = False,
                       below_200ma: bool = False) -> dict:
    """
    1차~5차 매수가, 평단, 목표가, 손절가를 계산한다.

    추매 로직:
      - 1차: 전날 종가 × (1 − entry_pct%)
      - N차(N≥2): 직전 평단 × (1 − add_pct%)
      - 새 평단 = (누적투입 × 이전평단 + 이번투입 × 이번매수가) / 새누적투입
    목표가·손절가:
      - 평단 기준으로 계산
    """
    cfg = GRADE_CONFIG[grade]

    # VIX 22~30 구간이면 1차 진입을 1%p 더 깊게
    vix_adj = 1.0 if (vix is not None and 22 <= vix < 30) else 0.0
    entry_pct = cfg['entry_pct'] + vix_adj
    add_pct = cfg['add_pct']
    target_pcts = cfg['target_pcts']
    stop_pct = cfg['stop_pct']

    # 50일선 아래: 1차 금액 70만원, 권장 max 4차, 총 600만원 이내
    amounts = list(cfg['amounts'])
    max_rounds = 5
    recommended_max = 5

    if below_50ma:
        amounts[0] = 70
        recommended_max = 4   # 가능하면 4차에서 멈춤

    rounds = []
    avg = 0.0
    total_invested = 0

    for i in range(max_rounds):
        if i == 0:
            buy_price = close_price * (1 - entry_pct / 100)
        else:
            buy_price = avg * (1 - add_pct / 100)

        amount = amounts[i]
        new_total = total_invested + amount

        if total_invested == 0:
            new_avg = buy_price
        else:
            new_avg = (total_invested * avg + amount * buy_price) / new_total

        total_invested = new_total
        avg = new_avg

        # 목표가: 차수별 기준 상이
        if i == 0:
            target = avg * (1 + target_pcts[0] / 100)
            target_label = f'+{target_pcts[0]:.0f}%'
        elif i <= 2:
            target = avg * (1 + target_pcts[1] / 100)
            target_label = f'+{target_pcts[1]:.0f}%'
        else:
            target = avg * (1 + target_pcts[2] / 100)
            target_label = f'+{target_pcts[2]:.0f}% / 본전'

        stop_loss = avg * (1 - stop_pct / 100)

        rounds.append({
            'round': i + 1,
            'buy_price': buy_price,
            'avg_price': avg,
            'amount': amount,
            'total_invested': total_invested,
            'target_price': target,
            'target_label': target_label,
            'stop_price': stop_loss,
            'is_recommended_last': (i + 1 == recommended_max and below_50ma),
        })

    return {
        'rounds': rounds,
        'hold_days': cfg['hold_days'],
        'recommended_max': recommended_max,
        'vix_adj': vix_adj,
        'entry_pct': entry_pct,
        'add_pct': add_pct,
    }


# ──────────────────────────────────────────────────────────
#  주의사항 생성
# ──────────────────────────────────────────────────────────

def get_warnings(ticker: str, grade: str,
                 vix: Optional[float],
                 below_50ma: bool,
                 below_200ma: bool) -> list[str]:
    warnings: list[str] = []
    cluster = next((c for c, tl in CLUSTERS.items() if ticker in tl), None)

    # ── 시장 위치 ──────────────────────────────────────
    if below_200ma:
        if grade == 'tier1_stable':
            warnings.append('⚠️  200일선 아래 — 1등급 안정형만 1차 금액의 절반(약 50만원)으로 소액 가능')
        else:
            warnings.append('🚫 200일선 아래 — 신규 진입 금지 (이 종목은 매수 중단)')
    elif below_50ma:
        warnings.append('⚠️  50일선 아래 — 투입 금액 축소 (1차 70만원, 총 600만원 한도)')
        warnings.append('⚠️  50일선 아래 — 가능하면 4차에서 멈추기 권장')
    else:
        warnings.append('✅  정상 구간 (50일선·200일선 위) — 정상 운용')

    # ── VIX ───────────────────────────────────────────
    if vix is not None:
        if vix >= 40:
            warnings.append(f'🚫 VIX {vix:.1f} ≥ 40 — 전부 쉰다. 신규 진입 불가')
        elif vix >= 30:
            warnings.append(f'🚫 VIX {vix:.1f} ≥ 30 — 신규 진입 거의 중단 (1등급 안정형 소액만 가능)')
        elif vix >= 22:
            warnings.append(f'⚠️  VIX {vix:.1f} (22~30) — 1차 진입가 1%p 더 깊게 적용됨')
        else:
            warnings.append(f'✅  VIX {vix:.1f} ≤ 22 — 정상 운용')

    # ── 등급별 특수 경고 ───────────────────────────────
    if grade == 'tier3':
        warnings.append('⚠️  3등급 특수·고위험 — 주력이 아닌 특수 상황 종목. 1슬롯만 허용')
        if ticker == 'BOIL':
            warnings.append('🚫 BOIL — 최고위험 (천연가스 2배, 롤오버 비용 극심)')
        if ticker in ('BITX', 'ETHU', 'XXRP', 'SOLT', 'MSTX', 'CONL'):
            warnings.append('⚠️  크립토 레버리지 — 주말 포함 24시간 변동, 갭 리스크 큼')
        if ticker == 'YCL':
            warnings.append('⚠️  YCL — BOJ·일본 CPI·엔캐리 청산 이벤트 주의')

    if grade == 'tier2':
        warnings.append('⚠️  2등급 단일주 — 기초자산 실적 발표 전후 신규 진입 금지')
        if ticker == 'SMCX':
            warnings.append('⚠️  SMCX — 고변동 종목 별도 분류, 진입 신중')

    # ── 클러스터 규칙 ──────────────────────────────────
    if cluster:
        rule = CLUSTER_RULE.get(cluster)
        if rule:
            warnings.append(f'📌 클러스터 [{cluster}] — {rule}')
        combos = FORBIDDEN_COMBOS.get(cluster)
        if combos:
            warnings.append(f'🚫 [{cluster}] 금지 조합: ' + ' / '.join(combos))

    # ── 이벤트 공통 주의 ──────────────────────────────
    warnings.append('📅 이벤트 주의: CPI·PCE·FOMC·고용지표·파월회견·개별주 실적 발표 전후 진입 자제')

    return warnings


# ──────────────────────────────────────────────────────────
#  출력
# ──────────────────────────────────────────────────────────

def print_plan(ticker: str, close_price: float, close_date: str,
               vix: Optional[float],
               below_50ma: bool, below_200ma: bool) -> None:
    grade = TICKER_GRADE.get(ticker)
    if grade is None:
        print(f"\n❌  '{ticker}'는 등록되지 않은 종목입니다.")
        cols = sorted(TICKER_GRADE.keys())
        print("등록 종목:\n  " + "  ".join(f"{t:<6}" for t in cols))
        return

    cfg = GRADE_CONFIG[grade]
    plan = calculate_buy_plan(close_price, grade, vix, below_50ma, below_200ma)
    warnings = get_warnings(ticker, grade, vix, below_50ma, below_200ma)

    W = 68

    # ── 헤더 ──────────────────────────────────────────────
    print()
    print('=' * W)
    vix_str = f"  VIX {vix:.1f}" if vix else ""
    print(f"  {ticker}  |  {cfg['name']}  |  기준: {close_date}{vix_str}")
    print(f"  전날 종가: ${close_price:,.2f}")
    print('=' * W)

    # ── 조건 요약 ──────────────────────────────────────────
    conditions = []
    if below_200ma:
        conditions.append('200일선 아래')
    elif below_50ma:
        conditions.append('50일선 아래')
    else:
        conditions.append('정상 구간')
    if plan['vix_adj'] > 0:
        conditions.append(f'VIX 보정 +{plan["vix_adj"]:.0f}%p')
    print(f"  조건: {' | '.join(conditions)}")
    print(f"  1차 진입 기준: 전날 종가 대비 -{plan['entry_pct']:.1f}%  |  추매: 평단 대비 -{plan['add_pct']:.0f}%")
    print()

    # ── 매수 계획표 ────────────────────────────────────────
    hdr = f"  {'차수':>3}  {'매수가':>8}  {'평단':>8}  {'목표가':>9}  {'손절가':>8}  {'투입':>6}  {'누적':>6}"
    print(hdr)
    print('  ' + '-' * (W - 2))

    for r in plan['rounds']:
        flag = ' ★권장마지막' if r['is_recommended_last'] else ''
        target_str = f"${r['target_price']:>8.2f}({r['target_label']})"
        print(
            f"  {r['round']}차  "
            f"${r['buy_price']:>8.2f}"
            f"  ${r['avg_price']:>7.2f}"
            f"  {target_str:<18}"
            f"  ${r['stop_price']:>7.2f}"
            f"  {r['amount']:>3}만"
            f"  {r['total_invested']:>3}만"
            f"{flag}"
        )

    print()
    print(f"  보유 기간 기준: {plan['hold_days']}일  |  최대 5차, 현금 1슬롯 유지 필수")

    # ── 주의사항 ──────────────────────────────────────────
    print()
    print('─' * W)
    print('  ■ 주의사항')
    print('─' * W)
    for w in warnings:
        print(f"  {w}")

    # ── 계좌 방어선 (참고) ────────────────────────────────
    print()
    print('─' * W)
    print('  ■ 계좌 전체 방어선 (6,400만원 기준)')
    print('  ─────────────────────────────────────')
    print('    -8%  (약 -512만원) → 신규 진입 중단')
    print('   -12%  (약 -768만원) → 2/3등급 일부 축소')
    print('   -15%  (약 -960만원) → 전체 시스템 일시 중단')

    print()
    print('─' * W)
    print('  목표 오면 판다 · 시간 지나면 판다 · 손절 오면 판다')
    print('=' * W)
    print()


# ──────────────────────────────────────────────────────────
#  메인
# ──────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description='미국 레버리지 ETF 투자기법 v4.5 — 매수가 계산기'
    )
    parser.add_argument('ticker', nargs='?', help='종목 티커 (예: TQQQ)')
    parser.add_argument('--vix', type=float, help='VIX 값 직접 입력 (미입력시 자동 조회)')
    parser.add_argument('--below-50ma', action='store_true', dest='below_50ma',
                        help='현재가가 50일선 아래')
    parser.add_argument('--below-200ma', action='store_true', dest='below_200ma',
                        help='현재가가 200일선 아래')
    parser.add_argument('--no-vix', action='store_true', dest='no_vix',
                        help='VIX 자동 조회 생략')
    args = parser.parse_args()

    # ── 티커 입력 ──────────────────────────────────────────
    ticker = (args.ticker or input('종목 티커 입력 (예: TQQQ): ').strip()).upper()

    # ── 전날 종가 조회 ──────────────────────────────────────
    print(f'\n{ticker} 전날 종가 조회 중...')
    try:
        close_price, close_date = fetch_prev_close(ticker)
        print(f'  → {close_date}: ${close_price:,.2f}')
    except Exception as e:
        print(f'  ❌ 자동 조회 실패: {e}')
        raw = input('  종가를 직접 입력하세요 ($): ').strip()
        close_price = float(raw)
        close_date = 'manual'

    # ── VIX 조회 ────────────────────────────────────────────
    vix: Optional[float] = args.vix
    if vix is None and not args.no_vix:
        print('VIX 조회 중...')
        vix = fetch_vix()
        if vix:
            print(f'  → VIX: {vix:.1f}')
        else:
            print('  ⚠️  VIX 조회 실패 — VIX 반영 없이 계산합니다.')

    # ── 시장 위치 입력 ────────────────────────────────────
    below_50ma = args.below_50ma
    below_200ma = args.below_200ma

    if not (args.below_50ma or args.below_200ma):
        print('\n시장 위치 선택:')
        print('  1) 정상 (50일선·200일선 위)')
        print('  2) 50일선 아래  → 투입 축소, 4차 권장')
        print('  3) 200일선 아래 → 신규 진입 금지 (1등급 안정형 제외)')
        ma_input = input('선택 [1]: ').strip() or '1'
        if ma_input == '2':
            below_50ma = True
        elif ma_input == '3':
            below_50ma = True
            below_200ma = True

    print_plan(ticker, close_price, close_date, vix, below_50ma, below_200ma)


if __name__ == '__main__':
    main()
