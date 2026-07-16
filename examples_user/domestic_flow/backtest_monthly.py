"""선점 스크리너 월간 날짜별 백테스트

방식:
  샘플 종목의 최근 30일 일봉을 가져와
  각 날짜별로 "스크리너 발동 종목 → 다음날 실제 등락률"을 집계한다.

출력:
  날짜별 테이블: 발동수 / TP(+10%↑) / 평균등락률 / 발동 종목 목록

실행:
  cd examples_user/leverage_bot
  uv run python ../domestic_flow/backtest_monthly.py
"""
import sys, os, time, random
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

_DIR      = os.path.dirname(os.path.abspath(__file__))
_EXAMPLES = os.path.dirname(_DIR)
sys.path.insert(0, _EXAMPLES)

import kis_auth as ka
from domestic_flow.flow import (
    _fetch_daily_price, _load_all_stock_codes,
    PREEMPT_MIN_PRICE, PREEMPT_MIN_TRADE,
)

# ── 설정 ───────────────────────────────────────────────────
SURGE_THRESHOLD  = 10.0    # 급등 기준 (%)
SAMPLE_N         = 500     # 샘플 종목 수
MARKET           = '코스닥'

PREEMPT_PRICE_RANGE = 5.0
PREEMPT_DRAWDOWN    = 30.0
PREEMPT_MIN_VOL     = 10_000


def _check_base(d: list[dict]) -> bool:
    """기본 선점 조건 (flow.py _check_preempt와 동일)"""
    if len(d) < 22:
        return False
    today     = d[0]
    yesterday = d[1]
    hist      = d[1:21]

    if today['종가'] < PREEMPT_MIN_PRICE: return False
    if today['거래량'] < PREEMPT_MIN_VOL: return False
    if yesterday['종가'] * yesterday['거래량'] < PREEMPT_MIN_TRADE: return False
    if abs(today.get('등락률', 0)) > PREEMPT_PRICE_RANGE: return False

    recent_high = max(h['고가'] for h in hist)
    drawdown = (today['종가'] - recent_high) / recent_high * 100
    if drawdown > -PREEMPT_DRAWDOWN: return False

    recent_low = min(h['저가'] for h in hist)
    if recent_low > 0 and today['종가'] > recent_low * 1.10: return False

    recent5 = [d[i].get('등락률', 0) for i in range(1, 6) if i < len(d)]
    if sum(1 for r in recent5 if r < 0) < 3: return False

    return True


def _extra(d: list[dict]) -> dict:
    """추가 후보 조건 플래그"""
    today = d[0]
    close, open_, high, low = today['종가'], today['시가'], today['고가'], today['저가']

    # D: 오늘 양봉 (종가 > 시가)
    d_bull = close > open_

    # E: 종가가 일중 범위 상단 50% 이상 (아랫꼬리 양봉, 매수세 강함)
    rng = high - low
    e_upper = (close - low) / rng > 0.5 if rng > 0 else False

    return {'D_양봉': d_bull, 'E_상단마감': e_upper}


def _worker(code: str, name: str) -> list[dict]:
    """한 종목 30일치 분석 → 스크리너 발동 이벤트 목록"""
    try:
        time.sleep(0.12)
        data = _fetch_daily_price(code)
    except Exception:
        return []

    if len(data) < 23:
        return []

    events = []
    # data[0]=오늘, data[i]=i일 전
    # 체크일 = data[i+1], 다음날(결과) = data[i]
    # 조건: i+1+21 < len(data) → i < len(data)-22
    for i in range(len(data) - 22):
        check_window = data[i+1:]       # [0]=체크일, [1:21]=이전 20일
        next_day     = data[i]          # 결과 (체크일의 다음 날)

        if not _check_base(check_window):
            continue

        check_date  = check_window[0]['날짜']
        next_rate   = next_day.get('등락률', 0)
        next_price  = next_day['종가']
        check_price = check_window[0]['종가']
        flags       = _extra(check_window)

        events.append({
            '날짜':     check_date,
            '코드':     code,
            '종목명':   name,
            '체크가':   check_price,
            '다음날가': next_price,
            '등락률':   next_rate,
            '급등':     next_rate >= SURGE_THRESHOLD,
            **flags,
        })

    return events


def main():
    print("=" * 65)
    print(f"  선점 스크리너 월간 날짜별 백테스트  ({MARKET}  {SAMPLE_N}종목)")
    print(f"  급등 기준 +{SURGE_THRESHOLD}%  |  조건: 낙폭-{PREEMPT_DRAWDOWN}% 바닥근처 연속눌림")
    print("=" * 65)

    ka.auth()
    all_stocks = _load_all_stock_codes(MARKET)
    sample = random.sample(all_stocks, min(SAMPLE_N, len(all_stocks)))
    print(f"\n▶ {len(sample)}종목 분석 중 (약 1~2분)...\n")

    # 날짜별 집계
    by_date = defaultdict(list)   # date → [event, ...]

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(_worker, c, n): c for c, n in sample}
        for i, fut in enumerate(as_completed(futures), 1):
            for evt in fut.result():
                by_date[evt['날짜']].append(evt)
            if i % 100 == 0:
                print(f"  진행 {i}/{len(sample)}...")

    if not by_date:
        print("발동 이벤트 없음")
        return

    # 날짜 오름차순 출력
    dates = sorted(by_date.keys())
    total_fires = total_tp = 0

    print("\n" + "=" * 65)
    print(f"{'날짜':<10} {'발동':>4} {'TP':>4} {'정밀도':>7}  발동 종목 (다음날 등락률)")
    print("-" * 65)

    for date in dates:
        evts  = by_date[date]
        tp    = [e for e in evts if e['급등']]
        fires = len(evts)
        prec  = len(tp) / fires * 100 if fires else 0
        total_fires += fires
        total_tp    += len(tp)

        # 종목 목록: TP는 굵게 표시 (텍스트론 * 표시)
        stock_list = []
        for e in sorted(evts, key=lambda x: x['등락률'], reverse=True)[:8]:
            mark = '★' if e['급등'] else ' '
            stock_list.append(f"{mark}{e['종목명']}({e['등락률']:+.1f}%)")

        stocks_str = '  '.join(stock_list)
        print(f"{date:<10} {fires:>4} {len(tp):>4} {prec:>6.1f}%  {stocks_str}")

    print("=" * 65)
    overall_prec = total_tp / total_fires * 100 if total_fires else 0
    print(f"{'합계':<10} {total_fires:>4} {total_tp:>4} {overall_prec:>6.1f}%")
    print(f"\n★ = 다음날 +{SURGE_THRESHOLD}%↑ 급등 종목")

    # ── 추가 조건 조합별 정밀도 ──────────────────────────────
    all_evts = [e for evts in by_date.values() for e in evts]
    combos = [
        ('기본 (A+C)',         lambda e: True),
        ('+D 양봉',            lambda e: e.get('D_양봉')),
        ('+E 상단마감',         lambda e: e.get('E_상단마감')),
        ('+D+E',              lambda e: e.get('D_양봉') and e.get('E_상단마감')),
    ]
    print("\n" + "=" * 65)
    print(f"  {'조합':<20} {'발동':>5} {'TP':>4} {'정밀도':>8}")
    print(f"  {'-'*40}")
    for label, cond in combos:
        sub   = [e for e in all_evts if cond(e)]
        tp    = sum(1 for e in sub if e['급등'])
        prec  = tp / len(sub) * 100 if sub else 0
        mark  = ' ◀' if prec == max(
            (sum(1 for e in [e for e in all_evts if c(e)] if e['급등']) /
             max(len([e for e in all_evts if c(e)]), 1) * 100)
            for _, c in combos
        ) else ''
        print(f"  {label:<20} {len(sub):>5} {tp:>4} {prec:>7.1f}%{mark}")
    print("=" * 65)


if __name__ == '__main__':
    main()
