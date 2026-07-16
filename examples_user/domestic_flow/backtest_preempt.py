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


def _diagnose(d: list[dict]) -> dict:
    """하루치 데이터(d[0]=검사일)로 통과/탈락 여부 + 이유 반환
    백테스트에서는 거래대금 필터 생략 — 핵심 조건만 검사
    """
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

    return {'pass': True, 'reason': None,
            'detail': {'등락률': rate, '낙폭': round(drawdown,1), '거래량': today['거래량']}}


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


def _worker(code: str, name: str) -> list[dict]:
    """한 종목의 30일 히스토리에서 이벤트 목록 반환"""
    try:
        time.sleep(0.15)
        data = _fetch_daily_price(code)
    except Exception:
        return []

    if len(data) < 23:
        return []

    # data[0]=오늘(최신), data[1]=어제, ...
    # data[i]가 급등 → data[i+1:]이 선점 조건 검사 윈도우
    # _diagnose는 최소 22개 필요 → i+1+22 <= len(data) → i <= len(data)-23
    max_i = len(data) - 23   # 이 이상이면 전날 데이터 부족
    events = []
    for i in range(max_i + 1):
        surge_day  = data[i]
        pre_window = data[i+1:]   # [0]=전날, [1:21]=이전 20일

        surge_rate = surge_day.get('등락률', 0)
        if surge_rate < SURGE_THRESHOLD:
            continue

        diag    = _diagnose(pre_window)
        measure = _measure(pre_window)
        events.append({
            '코드':   code,
            '종목명': name,
            '급등일': surge_day['날짜'],
            '급등률': surge_rate,
            '통과':   diag['pass'],
            '이유':   diag['reason'],
            '상세':   diag['detail'],
            '실측':   measure,
        })

    return events


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

    all_events = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(_worker, c, n): c for c, n in sample}
        for i, fut in enumerate(as_completed(futures), 1):
            evts = fut.result()
            all_events.extend(evts)
            if i % 30 == 0:
                print(f"  진행 {i}/{len(sample)}...")

    if not all_events:
        print("급등 이벤트 없음 (샘플 부족 또는 최근 장 조용)")
        return

    tp = [e for e in all_events if e['통과']]      # 적중
    fn = [e for e in all_events if not e['통과']]   # 누락

    # 오탐(FP): 조건 통과했지만 급등 안 한 날 — 별도 계산 필요 (복잡도 ↑)
    total_surge = len(all_events)
    print(f"\n총 급등 이벤트: {total_surge}건  (샘플 {len(sample)}종목 × 최근 30일)")

    print("\n" + "=" * 60)
    print(f"✅ 적중 (TP): {len(tp)}건  — 전날 조건 통과 → 다음날 급등")
    print("=" * 60)
    for e in sorted(tp, key=lambda x: x['급등률'], reverse=True)[:15]:
        d = e['상세']
        print(f"  {e['종목명']} ({e['코드']})  {e['급등일']}  +{e['급등률']:.1f}%")
        print(f"    전날: 등락률{d['등락률']:+.1f}%  낙폭{d['낙폭']:+.1f}%  거래량{d['거래량']:,}주")

    print("\n" + "=" * 60)
    print(f"❌ 누락 (FN): {len(fn)}건  — 전날 조건 미통과 → 다음날 급등")
    print("=" * 60)
    # 탈락 이유 통계
    from collections import Counter
    reason_counts = Counter()
    for e in fn:
        for part in (e['이유'] or '').split(' / '):
            reason_counts[part.split('(')[0].strip()[:6]] += 1
    print("  탈락 이유 (중복 포함):")
    for reason, cnt in reason_counts.most_common(8):
        print(f"    {reason}: {cnt}건")

    # ── 급등 전날 실제 수치 분포 ─────────────────────────────
    measured = [e['실측'] for e in all_events if e['실측']]
    if measured:
        drawdowns = sorted(m['낙폭'] for m in measured)
        rates     = sorted(m['등락률'] for m in measured)
        vols      = sorted(m['거래량배수'] for m in measured)

        def pct(lst, p):
            idx = int(len(lst) * p / 100)
            return lst[min(idx, len(lst)-1)]

        print("\n" + "=" * 60)
        print("📊 급등 전날 실제 수치 분포 (조건 조정 참고용)")
        print("=" * 60)
        print(f"  낙폭(%):    중앙값 {pct(drawdowns,50):.1f}%  25% {pct(drawdowns,25):.1f}%  10% {pct(drawdowns,10):.1f}%  최소 {min(drawdowns):.1f}%")
        print(f"  등락률(%):  중앙값 {pct(rates,50):.1f}%  25% {pct(rates,25):.1f}%  75% {pct(rates,75):.1f}%")
        print(f"  거래량배수: 중앙값 {pct(vols,50):.1f}배  75% {pct(vols,75):.1f}배  90% {pct(vols,90):.1f}배  최대 {max(vols):.1f}배")
        print(f"\n  현재 설정: 등락률 ±{PREEMPT_PRICE_RANGE}% / 낙폭 ≤-{PREEMPT_DRAWDOWN}%")

    recall = len(tp) / total_surge * 100 if total_surge else 0
    print(f"\n★ 재현율(Recall): {recall:.1f}%  — 급등 {total_surge}건 중 {len(tp)}건 전날 포착")
    print(f"   (오탐율은 전 종목 전일 대비 별도 계산 필요)")


if __name__ == '__main__':
    main()
