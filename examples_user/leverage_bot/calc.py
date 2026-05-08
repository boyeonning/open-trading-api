"""레버리지 ETF 투자기법 v4.5 — 등급/계산 데이터"""
from typing import Optional

# ──────────────────────────────────────────────────────────
#  등급별 운용 파라미터
# ──────────────────────────────────────────────────────────
GRADE_CONFIG: dict[str, dict] = {
    'tier1_stable': {
        'name': '1등급 안정형',
        'entry_pct': 3.0,
        'add_pct': 4.0,
        'target_pcts': [4.0, 6.0, 8.0],
        'stop_pct': 6.0,
        'hold_days': 5,
        'amounts': [100, 150, 150, 200, 200],
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
        'hold_days': 4,
        'amounts': [100, 150, 150, 200, 200],
    },
}

TICKER_GRADE: dict[str, str] = {
    # 1등급 안정형
    'UPRO': 'tier1_stable', 'SSO': 'tier1_stable', 'QLD': 'tier1_stable',
    'USD':  'tier1_stable', 'UWM': 'tier1_stable', 'FAS': 'tier1_stable',
    'DRN':  'tier1_stable',
    # 1등급 변동형
    'TQQQ': 'tier1_volatile', 'SOXL': 'tier1_volatile', 'TECL': 'tier1_volatile',
    'TNA':  'tier1_volatile', 'LABU': 'tier1_volatile', 'DPST': 'tier1_volatile',
    'ERX':  'tier1_volatile', 'NAIL': 'tier1_volatile', 'FNGU': 'tier1_volatile',
    'YINN': 'tier1_volatile',
    # 2등급
    'NVDL': 'tier2', 'TSLL': 'tier2', 'AVL':  'tier2', 'ARMG': 'tier2',
    'TSMX': 'tier2', 'PTIR': 'tier2', 'GGLL': 'tier2', 'ORCX': 'tier2',
    'ROBN': 'tier2', 'MRVU': 'tier2', 'VRTL': 'tier2', 'AAPU': 'tier2',
    'METU': 'tier2', 'MSFU': 'tier2', 'AMZU': 'tier2', 'MUU':  'tier2',
    'ASMU': 'tier2', 'SMCX': 'tier2', 'CSEX': 'tier2', 'SOFA': 'tier2',
    'BABU': 'tier2', 'OKLL': 'tier2',
    # 3등급
    'AGQ':  'tier3', 'UCO':  'tier3', 'BOIL': 'tier3', 'TMF':  'tier3',
    'TYD':  'tier3', 'YCL':  'tier3', 'BITX': 'tier3', 'ETHU': 'tier3',
    'XXRP': 'tier3', 'SOLT': 'tier3', 'MSTX': 'tier3', 'CONL': 'tier3',
}

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
    'AI·반도체':  '동시 1종목 (QQQ 50일↑ + VIX≤22일 때만 최대 2종목)',
    '메가테크':   '동시 최대 2종목',
    '크립토':     '동시 1종목',
    '중국':       '동시 1종목',
    '금융':       '동시 1종목',
    '금리·채권':  '동시 1종목',
}

FORBIDDEN_COMBOS: dict[str, list[str]] = {
    'AI·반도체': ['SOXL+NVDL+AVL', 'NVDL+MRVU+ASMU', 'SOXL+TSMX+MUU'],
    '메가테크':  ['TQQQ+AAPU+MSFU', 'FNGU+GGLL+METU'],
}

SPECIAL_WARNINGS: dict[str, str] = {
    # 완충재 관계 (3배 부담 시 대체)
    'SSO':  'UPRO(S&P500 3배)의 완충재 — UPRO가 부담스러우면 SSO',
    'QLD':  'TQQQ(나스닥 3배)의 완충재 — TQQQ가 부담스러우면 QLD',
    'USD':  'SOXL(반도체 3배)의 완충재 — SOXL이 부담스러우면 USD',
    'UWM':  'TNA(Russell 3배)의 완충재 — TNA가 부담스러우면 UWM',
    # 고위험·고변동
    'BOIL': '최고위험 — 천연가스 2배, 롤오버 비용 극심',
    'SMCX': '고변동 별도 분류 — AI칩 EMS, 진입 신중',
    'YCL':  'BOJ·일본 CPI·엔캐리 청산 이벤트 주의',
    # 크립토 — 선택 기준 포함
    'BITX': '크립토 BTC 2배 — 주말 포함 24시간 변동·갭 리스크 큼 (BITX/BITU/BTCL 중 BITX 선택)',
    'ETHU': '크립토 ETH 2배 — 24시간 변동 (ETHU/ETHT 중 ETHU 선택)',
    'XXRP': '크립토 XRP 2배 — 24시간 변동 (XXRP/UXRP/XRPK 중 XXRP 선택)',
    'SOLT': '크립토 SOL 2배 — 24시간 변동 (SOLT/SOLX 중 SOLT 선택)',
    'MSTX': 'BTC 고베타 — 비트코인 방향성에 극도로 민감 (MSTX/MSTU 중 MSTX 선택)',
    'CONL': '크립토 고베타 — 규제 리스크 포함 (CONL/CONX 중 CONL 선택)',
    # 2등급 신규 편입 우선순위: AVL→ARMG→TSMX→PTIR→MRVU→VRTL→ROBN
    'AVL':  '신규 우선순위 1위 (AVL→ARMG→TSMX→PTIR→MRVU→VRTL→ROBN) — AVGO 2배, AI·반도체 클러스터',
    'ARMG': '신규 우선순위 2위 (AVL→ARMG→TSMX→PTIR→MRVU→VRTL→ROBN) — ARM 2배, AI·반도체 클러스터',
    'TSMX': '신규 우선순위 3위 (AVL→ARMG→TSMX→PTIR→MRVU→VRTL→ROBN) — TSM 2배, AI·반도체 클러스터',
    'PTIR': '신규 우선순위 4위 (AVL→ARMG→TSMX→PTIR→MRVU→VRTL→ROBN) — PLTR 2배, 메가테크 클러스터',
    'MRVU': '신규 우선순위 5위 (AVL→ARMG→TSMX→PTIR→MRVU→VRTL→ROBN) — MRVL 2배, 소액 테스트 중',
    'VRTL': '신규 우선순위 6위 (AVL→ARMG→TSMX→PTIR→MRVU→VRTL→ROBN) — VRT 2배, 소액 테스트 중',
    'ROBN': '신규 우선순위 7위 (AVL→ARMG→TSMX→PTIR→MRVU→VRTL→ROBN) — HOOD 2배, 크립토 심리 민감',
    # 기타 감시 중
    'CSEX': '신규 편입 — CLS 2배, 감시 중',
    'SOFA': '신규 편입 — SOFI 2배, 감시 중',
    'BABU': '중국주 레버리지 — BABA 2배, 규제·상장폐지 리스크',
    'OKLL': '감시 중 — 상황에 따라 3등급 하향 또는 제외 가능',
}


def get_ticker_cluster(ticker: str) -> Optional[str]:
    for cluster, tickers in CLUSTERS.items():
        if ticker in tickers:
            return cluster
    return None


def calculate_buy_plan(close_price: float, grade: str,
                       vix: Optional[float] = None,
                       below_50ma: bool = False,
                       below_200ma: bool = False) -> dict:
    """
    1~5차 매수가, 평단, 목표가, 손절가 계산.

    추매 로직:
      1차: 전날 종가 × (1 − entry_pct%)
      N차(N≥2): 직전 평단 × (1 − add_pct%)
    목표·손절: 각 차수별 평단 기준
    """
    cfg = GRADE_CONFIG[grade]
    vix_adj = 1.0 if (vix is not None and 22 <= vix < 30) else 0.0
    entry_pct = cfg['entry_pct'] + vix_adj
    add_pct = cfg['add_pct']
    target_pcts = cfg['target_pcts']
    stop_pct = cfg['stop_pct']

    amounts = list(cfg['amounts'])
    recommended_max = 4 if below_50ma else 5
    if below_50ma:
        amounts[0] = 70   # 1차 축소

    rounds = []
    avg = 0.0
    total_invested = 0

    for i in range(5):
        buy_price = (close_price * (1 - entry_pct / 100) if i == 0
                     else avg * (1 - add_pct / 100))
        amount = amounts[i]
        new_total = total_invested + amount
        new_avg = buy_price if total_invested == 0 else (
            total_invested * avg + amount * buy_price) / new_total

        total_invested = new_total
        avg = new_avg

        if i == 0:
            target, label = avg * (1 + target_pcts[0] / 100), f'+{target_pcts[0]:.0f}%'
        elif i <= 2:
            target, label = avg * (1 + target_pcts[1] / 100), f'+{target_pcts[1]:.0f}%'
        else:
            target, label = avg * (1 + target_pcts[2] / 100), f'+{target_pcts[2]:.0f}% / 본전'

        rounds.append({
            'round': i + 1,
            'buy_price': buy_price,
            'avg_price': avg,
            'amount': amount,
            'total_invested': total_invested,
            'target_price': target,
            'target_label': label,
            'stop_price': avg * (1 - stop_pct / 100),
            'is_last_recommended': (i + 1 == recommended_max and below_50ma),
        })

    return {
        'rounds': rounds,
        'hold_days': cfg['hold_days'],
        'recommended_max': recommended_max,
        'vix_adj': vix_adj,
        'entry_pct': entry_pct,
        'add_pct': add_pct,
    }


def calculate_from_avg(avg_price: float, from_round: int, grade: str,
                       vix: Optional[float] = None,
                       below_50ma: bool = False,
                       below_200ma: bool = False) -> dict:
    """
    실제 평단 기준으로 N차부터 추매 계획 계산.

    avg_price : 현재 보유 평균단가
    from_round: 계산 시작 차수 (2~5)
    """
    cfg = GRADE_CONFIG[grade]
    add_pct = cfg['add_pct']
    target_pcts = cfg['target_pcts']
    stop_pct = cfg['stop_pct']
    amounts = list(cfg['amounts'])

    recommended_max = 4 if below_50ma else 5
    if below_50ma:
        amounts[0] = 70

    # 이전 차수 누적 투입금 (표준 금액 기준)
    prev_invested = sum(amounts[:from_round - 1])
    avg = avg_price
    total_invested = prev_invested

    rounds = []
    for i in range(from_round - 1, 5):  # 0-indexed
        buy_price = avg * (1 - add_pct / 100)
        amount = amounts[i]
        new_total = total_invested + amount
        new_avg = (total_invested * avg + amount * buy_price) / new_total

        total_invested = new_total
        avg = new_avg

        round_num = i + 1
        if round_num == 1:
            target, label = avg * (1 + target_pcts[0] / 100), f'+{target_pcts[0]:.0f}%'
        elif round_num <= 3:
            target, label = avg * (1 + target_pcts[1] / 100), f'+{target_pcts[1]:.0f}%'
        else:
            target, label = avg * (1 + target_pcts[2] / 100), f'+{target_pcts[2]:.0f}% / 본전'

        rounds.append({
            'round': round_num,
            'buy_price': buy_price,
            'avg_price': avg,
            'amount': amount,
            'total_invested': total_invested,
            'target_price': target,
            'target_label': label,
            'stop_price': avg * (1 - stop_pct / 100),
            'is_last_recommended': (round_num == recommended_max and below_50ma),
        })

    return {
        'round': rounds[0],   # 해당 차수 1개만
        'from_round': from_round,
        'input_avg': avg_price,
        'hold_days': cfg['hold_days'],
        'recommended_max': recommended_max,
        'add_pct': add_pct,
    }


def get_warnings(ticker: str, grade: str,
                 vix: Optional[float],
                 below_50ma: bool,
                 below_200ma: bool) -> list[str]:
    warnings: list[str] = []
    cluster = get_ticker_cluster(ticker)

    # 시장 위치
    if below_200ma:
        if grade == 'tier1_stable':
            warnings.append('⚠️ 200일선 아래 — 1등급 안정형만 1차 금액 절반으로 소액 가능')
        else:
            warnings.append('🚫 200일선 아래 — 신규 진입 금지')
    elif below_50ma:
        warnings.append('⚠️ 50일선 아래 — 투입 축소 (1차 70만원, 총 600만원 한도, 4차 권장)')
    else:
        warnings.append('✅ 정상 구간 (50/200일선 위) — 정상 운용')

    # VIX
    if vix is not None:
        if vix >= 40:
            warnings.append(f'🚫 VIX {vix:.1f} ≥ 40 — 전부 쉰다')
        elif vix >= 30:
            warnings.append(f'🚫 VIX {vix:.1f} ≥ 30 — 신규 거의 중단 (1등급 안정형 소액만)')
        elif vix >= 22:
            warnings.append(f'⚠️ VIX {vix:.1f} — 1차 진입 1%p 더 깊게 보정 적용')
        else:
            warnings.append(f'✅ VIX {vix:.1f} ≤ 22 — 정상 운용')

    # 등급별 특이사항
    if grade == 'tier3':
        warnings.append('⚠️ 3등급 특수·고위험 — 주력 아님, 1슬롯 한도')
    if grade == 'tier2':
        warnings.append('⚠️ 2등급 단일주 — 기초자산 실적 발표 전후 진입 금지')

    # 종목 특이사항
    if ticker in SPECIAL_WARNINGS:
        warnings.append(f'⚠️ {ticker}: {SPECIAL_WARNINGS[ticker]}')

    # 클러스터
    if cluster:
        rule = CLUSTER_RULE.get(cluster)
        if rule:
            warnings.append(f'📌 [{cluster}] {rule}')
        combos = FORBIDDEN_COMBOS.get(cluster)
        if combos:
            warnings.append(f'🚫 금지 조합: {" / ".join(combos)}')

    # 이벤트
    warnings.append('📅 CPI·PCE·FOMC·고용·파월·실적 발표 전후 진입 자제')

    return warnings
