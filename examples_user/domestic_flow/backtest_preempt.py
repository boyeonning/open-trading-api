"""선점 스크리너 백테스트 (히스토리 기반)

방식:
  전체 종목 중 샘플을 뽑아 30일치 일봉 데이터를 가져온 뒤,
  "급등한 날의 전날"에 _check_preempt 조건이 맞았는지 확인한다.

결과:
  - 적중(TP): 전날 조건 통과 → 다음날 급등
  - 오탐(FP): 전날 조건 통과 → 다음날 급등 안 함
  - 누락(FN): 전날 조건 미통과 → 다음날 급등
  → 정밀도 = TP/(TP+FP),  재현율 = TP/(TP+FN)

실행:
  cd examples_user/leverage_bot
  uv run python ../domestic_flow/backtest_preempt.py
"""
import sys, os, time, random
from concurrent.futures import ThreadPoolExecutor, as_completed

_DIR      = os.path.dirname(os.path.abspath(__file__))
_EXAMPLES = os.path.dirname(_DIR)
sys.path.insert(0, _EXAMPLES)

import kis_auth as ka
from domestic_flow.flow import _fetch_daily_price, _load_all_stock_codes, PREEMPT_MIN_PRICE, PREEMPT_MIN_TRADE

# ── 설정 ───────────────────────────────────────────────────
SURGE_THRESHOLD = 10.0   # 급등 기준 등락률 (%)
SAMPLE_N        = 150    # 샘플 종목 수 (많을수록 정확, 느림)
MARKET          = '코스닥'

# ── 선점 조건 (flow.py와 동일, 파라미터 진단용으로 분리) ──────
PREEMPT_PRICE_RANGE = 5.0
PREEMPT_DRAWDOWN    = 30.0
PREEMPT_MIN_VOL     = 10_000


def _extra_flags(d: list[dict]) -> dict:
    """기본 조건 통과 후 추가 후보 조건 플래그 계산"""
    today = d[0]
    hist  = d[1:21]   # 이전 20일

    # A: 현재가가 20일 최저가 +10% 이내 (바닥 근처)
    recent_lo = min(x['저가'] for x in hist)
    near_bottom = today['종가'] <= recent_lo * 1.10 if recent_lo else False

    # B: 최근 3일 거래량 평균 > 직전 5일 거래량 평균 (거래량 증가 추세)
    recent3 = [d[i]['거래량'] for i in range(1, 4) if i < len(d)]   # 어제~3일전
    prev5   = [d[i]['거래량'] for i in range(4, 9) if i < len(d)]   # 4일전~8일전
    avg3 = sum(recent3) / len(recent3) if recent3 else 0
    avg5 = sum(prev5)   / len(prev5)   if prev5   else 0
    vol_rising = avg3 > avg5 * 1.0   # 최근 3일 평균이 직전 5일보다 많아지는 추세

    # C: 최근 5거래일 중 3일 이상 하락 (연속 눌림 후 보합)
    recent5_rates = [d[i].get('등락률', 0) for i in range(1, 6) if i < len(d)]
    down_days = sum(1 for r in recent5_rates if r < 0)
    after_decline = down_days >= 3

    return {
        'A_near_bottom':  near_bottom,
        'B_vol_rising':   vol_rising,
        'C_after_decline': after_decline,
    }


def _diagnose(d: list[dict]) -> dict:
    """하루치 데이터(d[0]=검사일)로 통과/탈락 여부 + 이유 반환"""
    if len(d) < 22:
        return {'pass': False, 'reason': '데이터부족', 'detail': None}

    today = d[0]
    hist  = d[1:21]

    if today['종가'] < PREEMPT_MIN_PRICE:
        return {'pass': False, 'reason': f"주가 {today['종가']:,}원", 'detail': None}

    rate      = today.get('등락률', 0)
    recent_hi = max(x['고가'] for x in hist)
    drawdown  = (today['종가'] - recent_hi) / recent_hi * 100 if recent_hi else 0

    reasons = []
    if today['거래량'] < PREEMPT_MIN_VOL:
        reasons.append(f'거래량{today["거래량"]:,}주')
    if abs(rate) > PREEMPT_PRICE_RANGE:
        reasons.append(f'등락률{rate:+.1f}%')
    if drawdown > -PREEMPT_DRAWDOWN:
        reasons.append(f'낙폭{drawdown:.1f}%')

    if reasons:
        return {'pass': False, 'reason': ' / '.join(reasons), 'detail': None}

    flags = _extra_flags(d)
    return {'pass': True, 'reason': None,
            'detail': {'등락률': rate, '낙폭': round(drawdown,1), '거래량': today['거래량']},
            'flags': flags}


def _measure(d: list[dict]) -> dict:
    """조건 통과 여부 무관하게 실제 수치 반환 (분포 분석용)"""
    if len(d) < 22:
        return {}
    today = d[0]
    hist  = d[1:21]
    recent_hi = max(x['고가'] for x in hist) if hist else 0
    drawdown  = (today['종가'] - recent_hi) / recent_hi * 100 if recent_hi else 0
    avg_vol   = sum(x['거래량'] for x in hist) / len(hist) if hist else 0
    vol_ratio = today['거래량'] / avg_vol if avg_vol else 0
    return {
        '등락률':     today.get('등락률', 0),
        '낙폭':       round(drawdown, 1),
        '거래량배수': round(vol_ratio, 1),
    }


def _worker(code: str, name: str) -> dict:
    """한 종목의 30일 히스토리 전체 분석
    반환: {
      'surge_events': 급등일 기준 이벤트 (TP/FN),
      'screener_fires': 조건 통과일 기준 이벤트 (TP/FP)
    }
    """
    try:
        time.sleep(0.15)
        data = _fetch_daily_price(code)
    except Exception:
        return {'surge_events': [], 'screener_fires': []}

    if len(data) < 23:
        return {'surge_events': [], 'screener_fires': []}

    # data[0]=오늘(최신), data[1]=어제 ...
    # i = 급등일 또는 조건 체크일 인덱스
    # 조건 체크: data[i+1:] 윈도우, 최소 22개 필요 → i <= len(data)-23
    max_i = len(data) - 23

    surge_events   = []   # 급등한 날 기준 (Recall 계산용)
    screener_fires = []   # 조건 통과한 날 기준 (Precision 계산용)

    for i in range(max_i + 1):
        next_day   = data[i]        # 다음날 (결과)
        check_day  = data[i+1:]     # 오늘 [0] + 이전 20일 [1:21]

        next_rate  = next_day.get('등락률', 0)
        surged     = next_rate >= SURGE_THRESHOLD

        diag    = _diagnose(check_day)
        measure = _measure(check_day)

        # ── 급등 이벤트 기준 (Recall) ──
        if surged:
            surge_events.append({
                '코드': code, '종목명': name,
                '급등일': next_day['날짜'], '급등률': next_rate,
                '통과': diag['pass'], '이유': diag['reason'],
                '상세': diag['detail'], '실측': measure,
            })

        # ── 스크리너 발동 기준 (Precision) ──
        if diag['pass']:
            screener_fires.append({
                '코드': code, '종목명': name,
                '체크일': check_day[0]['날짜'],
                '다음날등락률': next_rate,
                '적중': surged,
                '실측': measure,
                'flags': diag.get('flags', {}),
            })

    return {'surge_events': surge_events, 'screener_fires': screener_fires}


def main():
    print("=" * 60)
    print(f"  선점 스크리너 히스토리 백테스트  ({MARKET})")
    print(f"  급등 기준: +{SURGE_THRESHOLD}%  샘플: {SAMPLE_N}종목")
    print("=" * 60)

    ka.auth()
    all_stocks = _load_all_stock_codes(MARKET)
    if not all_stocks:
        print("종목 코드 로드 실패 (마스터 파일 확인)")
        return

    sample = random.sample(all_stocks, min(SAMPLE_N, len(all_stocks)))
    print(f"\n▶ {len(sample)}종목 30일 히스토리 분석 중...\n")

    all_surge   = []   # 급등 이벤트 (TP+FN)
    all_fires   = []   # 스크리너 발동 이벤트 (TP+FP)

    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(_worker, c, n): c for c, n in sample}
        for i, fut in enumerate(as_completed(futures), 1):
            res = fut.result()
            all_surge.extend(res['surge_events'])
            all_fires.extend(res['screener_fires'])
            if i % 30 == 0:
                print(f"  진행 {i}/{len(sample)}...")

    if not all_surge and not all_fires:
        print("데이터 없음")
        return

    from collections import Counter

    tp = [e for e in all_surge if e['통과']]
    fn = [e for e in all_surge if not e['통과']]
    fp = [e for e in all_fires if not e['적중']]   # 발동했지만 안 오른 날

    total_surge = len(all_surge)
    total_fires = len(all_fires)

    print(f"\n총 급등 이벤트: {total_surge}건  |  스크리너 발동: {total_fires}건")

    # ── Recall ────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"✅ 적중 TP {len(tp)}건  — 조건 통과 → 다음날 급등")
    print("=" * 60)
    for e in sorted(tp, key=lambda x: x['급등률'], reverse=True)[:12]:
        d = e['상세']
        print(f"  {e['종목명']} ({e['코드']})  {e['급등일']}  +{e['급등률']:.1f}%")
        print(f"    전날: 등락률{d['등락률']:+.1f}%  낙폭{d['낙폭']:+.1f}%")

    # ── FN ───────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"❌ 누락 FN {len(fn)}건  — 조건 미통과 → 다음날 급등")
    print("=" * 60)
    reason_counts = Counter()
    for e in fn:
        for part in (e['이유'] or '').split(' / '):
            reason_counts[part[:8]] += 1
    for reason, cnt in reason_counts.most_common(6):
        print(f"  {reason}: {cnt}건")

    # ── FP ───────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"⚠️  오탐 FP {len(fp)}건  — 조건 통과 → 다음날 급등 안 함")
    print("=" * 60)
    if fp:
        fp_rates = sorted(e['다음날등락률'] for e in fp)
        def pct(lst, p):
            idx = int(len(lst) * p / 100)
            return lst[min(idx, len(lst)-1)]
        print(f"  다음날 등락률: 중앙값 {pct(fp_rates,50):+.1f}%  "
              f"25% {pct(fp_rates,25):+.1f}%  75% {pct(fp_rates,75):+.1f}%")

    def pct(lst, p):
        idx = int(len(lst) * p / 100)
        return lst[min(idx, len(lst)-1)]

    # ── FP 다음날 등락률 분포 ─────────────────────────────────
    if fp:
        fp_rates = sorted(e['다음날등락률'] for e in fp)
        print(f"  다음날 등락률: 중앙값 {pct(fp_rates,50):+.1f}%  "
              f"25% {pct(fp_rates,25):+.1f}%  75% {pct(fp_rates,75):+.1f}%")

    # ── 기본 성능 ─────────────────────────────────────────────
    recall    = len(tp) / total_surge * 100 if total_surge else 0
    precision = len(tp) / total_fires * 100 if total_fires else 0

    print("\n" + "=" * 60)
    print("★ 기본 성능 (현재 조건)")
    print("=" * 60)
    print(f"  재현율  (Recall)   : {recall:.1f}%  — 급등 {total_surge}건 중 {len(tp)}건")
    print(f"  정밀도  (Precision): {precision:.1f}%  — 발동 {total_fires}건 중 {len(tp)}건 급등")

    # ── 추가 조건 조합별 정밀도 비교 ──────────────────────────
    print("\n" + "=" * 60)
    print("🔬 추가 조건 조합별 정밀도 비교")
    print("=" * 60)
    print(f"  {'조합':<30} {'발동':>5} {'TP':>4} {'정밀도':>7} {'재현율':>7}")
    print(f"  {'-'*55}")

    flag_combos = [
        ('기본',                    lambda f: True),
        ('+A 바닥근처',             lambda f: f.get('A_near_bottom')),
        ('+B 거래량증가추세',        lambda f: f.get('B_vol_rising')),
        ('+C 연속하락후보합',        lambda f: f.get('C_after_decline')),
        ('+A+B',                   lambda f: f.get('A_near_bottom') and f.get('B_vol_rising')),
        ('+A+C',                   lambda f: f.get('A_near_bottom') and f.get('C_after_decline')),
        ('+B+C',                   lambda f: f.get('B_vol_rising') and f.get('C_after_decline')),
        ('+A+B+C',                 lambda f: f.get('A_near_bottom') and f.get('B_vol_rising') and f.get('C_after_decline')),
    ]

    best_prec, best_name = 0, ''
    for name, cond in flag_combos:
        filtered_fires = [e for e in all_fires if cond(e.get('flags', {}))]
        filtered_tp    = [e for e in filtered_fires if e['적중']]
        # 재현율: 이 조합으로 잡히는 TP / 전체 급등
        combo_recall = len(filtered_tp) / total_surge * 100 if total_surge else 0
        combo_prec   = len(filtered_tp) / len(filtered_fires) * 100 if filtered_fires else 0
        marker = ' ◀' if combo_prec > best_prec and len(filtered_fires) >= 5 else ''
        if combo_prec > best_prec and len(filtered_fires) >= 5:
            best_prec, best_name = combo_prec, name
        print(f"  {name:<30} {len(filtered_fires):>5} {len(filtered_tp):>4} {combo_prec:>6.1f}% {combo_recall:>6.1f}%{marker}")

    print(f"\n  → 최고 정밀도: {best_name}  ({best_prec:.1f}%)")


if __name__ == '__main__':
    main()
