"""양음양 D1 승률 vs 코스닥 지수 등락률 비교

이미 생성된 backtest_result.csv를 읽어서
그날 코스닥 지수가 오른 날 / 내린 날로 나눠 승률 차이를 비교한다.

실행:
  cd examples_user/leverage_bot
  uv run python ../domestic_flow/compare_index.py
"""
import sys, os, csv
from collections import defaultdict
from datetime import datetime

_DIR      = os.path.dirname(os.path.abspath(__file__))
_EXAMPLES = os.path.dirname(_DIR)
sys.path.insert(0, _EXAMPLES)

import kis_auth as ka

CSV_IN = os.path.join(_DIR, 'backtest_result.csv')


def fetch_kosdaq_daily() -> dict[str, float]:
    """코스닥 지수 일별 등락률 → {날짜: 등락률%}"""
    ka.auth()
    params = {
        "FID_PERIOD_DIV_CODE":   "D",
        "FID_COND_MRKT_DIV_CODE": "U",
        "FID_INPUT_ISCD":         "1001",   # 코스닥
        "FID_INPUT_DATE_1":       datetime.today().strftime('%Y%m%d'),
    }
    res = ka._url_fetch(
        "/uapi/domestic-stock/v1/quotations/inquire-index-daily-price",
        "FHPUP02120000", "", params
    )
    if not res.isOK():
        print("코스닥 지수 조회 실패")
        return {}

    rows = getattr(res.getBody(), 'output2', None) or []
    result = {}
    for row in rows:
        date = getattr(row, 'stck_bsop_date', '') if hasattr(row, 'stck_bsop_date') else row.get('stck_bsop_date', '')
        try:
            raw  = getattr(row, 'bstp_nmix_prdy_ctrt', '0') if hasattr(row, 'bstp_nmix_prdy_ctrt') else row.get('bstp_nmix_prdy_ctrt', '0')
            rate = float(raw or '0')
        except ValueError:
            rate = 0.0
        if date:
            result[date] = rate
    return result


def main():
    # ── CSV 로드 ─────────────────────────────────────────────
    if not os.path.exists(CSV_IN):
        print(f"CSV 없음: {CSV_IN}\n먼저 backtest_yangumyang.py 를 실행하세요.")
        return

    events = []
    with open(CSV_IN, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            def _f(k): return float(row[k]) if row.get(k) else None
            events.append({
                '날짜': row['날짜'], '종목명': row['종목명'], '패턴': row['패턴'],
                'D1': _f('D1등락'), 'D3': _f('D3등락'), 'D5': _f('D5등락'),
            })

    # ── 코스닥 지수 가져오기 ──────────────────────────────────
    print("코스닥 지수 조회 중...")
    kosdaq = fetch_kosdaq_daily()

    # ── 날짜별 집계 ──────────────────────────────────────────
    by_date = defaultdict(list)
    for e in events:
        by_date[e['날짜']].append(e)

    print(f"\n{'='*75}")
    print(f"  양음양 D1/D3/D5 승률  vs  코스닥 지수 등락률")
    print(f"{'='*75}")
    print(f"{'날짜':<10}  {'코스닥':>7}  {'발동':>4}  {'D1승률':>6} {'D1평균':>7}  {'D3승률':>6} {'D3평균':>7}  판정")
    print(f"{'-'*75}")

    up_days, down_days = [], []

    def _wr_avg(evts, key):
        vals = [e[key] for e in evts if e[key] is not None]
        if not vals: return 0, 0
        w = sum(1 for v in vals if v > 0)
        return w / len(vals) * 100, sum(vals) / len(vals)

    for date in sorted(by_date.keys()):
        evts   = by_date[date]
        idx_rt = kosdaq.get(date)
        n      = len(evts)
        d1wr, d1avg = _wr_avg(evts, 'D1')
        d3wr, d3avg = _wr_avg(evts, 'D3')

        if idx_rt is not None:
            idx_str = f"{idx_rt:+.2f}%"
            판정     = '📈 상승' if idx_rt > 0 else '📉 하락'
            if idx_rt > 0:
                up_days.append(evts)
            else:
                down_days.append(evts)
        else:
            idx_str, 판정 = '   N/A', ''

        print(f"{date:<10}  {idx_str:>7}  {n:>4}  {d1wr:>5.1f}% {d1avg:>+6.2f}%  {d3wr:>5.1f}% {d3avg:>+6.2f}%  {판정}")

    # ── 지수 하락일 vs 상승일 D1/D3/D5 비교 ──────────────────
    def stat(days_evts, key):
        all_e = [e for evts in days_evts for e in evts]
        vals  = [e[key] for e in all_e if e[key] is not None]
        if not vals: return 0, 0, 0
        w = sum(1 for v in vals if v > 0)
        return len(vals), w / len(vals) * 100, sum(vals) / len(vals)

    print(f"\n{'='*75}")
    print(f"  {'구분':<12}  {'일수':>4}  {'D1승률':>6} {'D1평균':>7}  {'D3승률':>6} {'D3평균':>7}  {'D5승률':>6} {'D5평균':>7}")
    print(f"  {'-'*70}")
    for label, days in [('📉 지수 하락일', down_days), ('📈 지수 상승일', up_days)]:
        n1, w1, a1 = stat(days, 'D1')
        n3, w3, a3 = stat(days, 'D3')
        n5, w5, a5 = stat(days, 'D5')
        print(f"  {label:<12}  {len(days):>4}  {w1:>5.1f}% {a1:>+6.2f}%  {w3:>5.1f}% {a3:>+6.2f}%  {w5:>5.1f}% {a5:>+6.2f}%")
    print(f"{'='*75}")
    print()
    n1d, w1d, a1d = stat(down_days, 'D1')
    n3d, w3d, a3d = stat(down_days, 'D3')
    n5d, w5d, a5d = stat(down_days, 'D5')
    print(f"  ▶ 지수 하락일에 매수 시:")
    print(f"     익일(D1):  승률 {w1d:.1f}%  평균 {a1d:+.2f}%")
    print(f"     3일후(D3): 승률 {w3d:.1f}%  평균 {a3d:+.2f}%")
    print(f"     5일후(D5): 승률 {w5d:.1f}%  평균 {a5d:+.2f}%")


if __name__ == '__main__':
    main()
