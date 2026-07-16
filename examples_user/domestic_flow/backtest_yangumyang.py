"""양음양 스크리너 백테스트

6월부터 매일 양음양 조건 발동 종목을 뽑고
다음날 실제 수익이 났는지 날짜별로 집계한다.

실행:
  cd examples_user/leverage_bot
  uv run python ../domestic_flow/backtest_yangumyang.py
"""
import sys, os, time, csv
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

_DIR      = os.path.dirname(os.path.abspath(__file__))
_EXAMPLES = os.path.dirname(_DIR)
sys.path.insert(0, _EXAMPLES)

import kis_auth as ka
from domestic_flow.flow import (
    _fetch_daily_price, _load_all_stock_codes,
    _check_yangumyang, _check_yangumyang_p3,
)

# ── 설정 ────────────────────────────────────────────────────
MARKET   = '코스닥'   # '코스피' / '코스닥'
START_YM = '202506'  # 이 월(YYYYMM) 이후 날짜만 집계
CSV_OUT  = os.path.join(_DIR, 'backtest_result.csv')


def _worker(code: str, name: str) -> list[dict]:
    try:
        time.sleep(0.12)
        data = _fetch_daily_price(code)
    except Exception:
        return []

    if len(data) < 12:
        return []

    events = []
    for i in range(1, len(data) - 10):
        window   = data[i:]
        check_date = window[0]['날짜']

        # 6월 이전 날짜 스킵
        if check_date[:6] < START_YM:
            continue

        pattern_info = _check_yangumyang(window) or _check_yangumyang_p3(window)
        if pattern_info is None:
            continue

        check_close = window[0]['종가']

        def pct(idx):
            if i < idx or check_close == 0:
                return None
            return round((data[i - idx]['종가'] - check_close) / check_close * 100, 2)

        d1 = pct(1)
        d3 = pct(3)
        d5 = pct(5)

        events.append({
            '날짜':     check_date,
            '종목명':   name,
            '코드':     code,
            '패턴':     pattern_info['패턴'],
            '체크가':   check_close,
            'D1등락':   d1,
            'D3등락':   d3,
            'D5등락':   d5,
            'D1수익':   '✅' if d1 is not None and d1 > 0 else '❌',
            'D3수익':   '✅' if d3 is not None and d3 > 0 else ('❌' if d3 is not None else '-'),
            'D5수익':   '✅' if d5 is not None and d5 > 0 else ('❌' if d5 is not None else '-'),
        })

    return events


def main():
    ka.auth()
    all_stocks = _load_all_stock_codes(MARKET)
    print(f"▶ {MARKET} 전종목 {len(all_stocks)}개 스캔 중... (약 1~3분 소요)\n")

    all_events: list[dict] = []

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(_worker, c, n): c for c, n in all_stocks}
        done = 0
        for fut in as_completed(futures):
            all_events.extend(fut.result())
            done += 1
            if done % 200 == 0:
                print(f"  진행 {done}/{len(all_stocks)}...")

    if not all_events:
        print("발동 이벤트 없음")
        return

    # 날짜순 정렬
    all_events.sort(key=lambda e: e['날짜'])

    # ── 날짜별 출력 ──────────────────────────────────────────
    by_date = defaultdict(list)
    for e in all_events:
        by_date[e['날짜']].append(e)

    total = len(all_events)

    def _w(evts, key):
        return sum(1 for e in evts if e[key] == '✅')
    def _avg(evts, key):
        vals = [e[key] for e in evts if e[key] is not None]
        return sum(vals) / len(vals) if vals else None

    w1 = _w(all_events, 'D1수익')
    print(f"\n{'='*72}")
    print(f"  {MARKET}  6월~ 양음양 발동 종목 & D1/D3/D5 결과")
    print(f"  총 {total}건 / D1승률 {w1/total*100:.1f}%")
    print(f"{'='*72}")
    print(f"{'날짜':<10} {'패':>2}  {'D1':>7} {'D3':>7} {'D5':>7}  종목명")
    print(f"{'-'*72}")

    for date in sorted(by_date.keys()):
        day_evts  = by_date[date]
        day_total = len(day_evts)
        day_w1    = _w(day_evts, 'D1수익')
        print(f"\n── {date}  발동 {day_total}건 / D1수익 {day_w1}건 ──")
        for e in sorted(day_evts, key=lambda x: -(x['D1등락'] or 0)):
            d1s = f"{e['D1등락']:+.1f}%" if e['D1등락'] is not None else '   N/A'
            d3s = f"{e['D3등락']:+.1f}%" if e['D3등락'] is not None else '   N/A'
            d5s = f"{e['D5등락']:+.1f}%" if e['D5등락'] is not None else '   N/A'
            print(f"{'':10} {e['패턴']:>2}  {d1s:>7} {d3s:>7} {d5s:>7}  {e['종목명']}")

    # ── 날짜별 요약 ──────────────────────────────────────────
    print(f"\n{'='*72}")
    print(f"{'날짜':<10}  {'발동':>4}  {'D1승률':>6}  {'D1평균':>7}  {'D3승률':>6}  {'D3평균':>7}  {'D5승률':>6}  {'D5평균':>7}")
    print(f"{'-'*72}")
    for date in sorted(by_date.keys()):
        evts = by_date[date]
        n    = len(evts)
        def row_stat(key_w, key_v):
            w   = _w(evts, key_w)
            avg = _avg(evts, key_v)
            cnt = sum(1 for e in evts if e[key_v] is not None)
            wr  = w / cnt * 100 if cnt else 0
            av  = f"{avg:+.1f}%" if avg is not None else '  N/A'
            return f"{wr:>5.1f}%  {av:>7}"
        print(f"{date:<10}  {n:>4}  {row_stat('D1수익','D1등락')}  {row_stat('D3수익','D3등락')}  {row_stat('D5수익','D5등락')}")

    # 전체 합계
    def tot_stat(key_w, key_v):
        w   = _w(all_events, key_w)
        avg = _avg(all_events, key_v)
        cnt = sum(1 for e in all_events if e[key_v] is not None)
        wr  = w / cnt * 100 if cnt else 0
        av  = f"{avg:+.1f}%" if avg is not None else '  N/A'
        return f"{wr:>5.1f}%  {av:>7}"
    print(f"{'합계':<10}  {total:>4}  {tot_stat('D1수익','D1등락')}  {tot_stat('D3수익','D3등락')}  {tot_stat('D5수익','D5등락')}")

    # ── CSV 저장 ─────────────────────────────────────────────
    with open(CSV_OUT, 'w', newline='', encoding='utf-8-sig') as f:
        fields = ['날짜','종목명','코드','패턴','체크가','D1등락','D1수익','D3등락','D3수익','D5등락','D5수익']
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(all_events)
    print(f"\n📄 CSV 저장 완료: {CSV_OUT}")


if __name__ == '__main__':
    main()
