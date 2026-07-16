"""상승장 vs 하락장 양음양 백테스트 비교

상승장: 2025/10 ~ 2026/02  (코스닥 900 → 1193, 강한 상승)
하락장: 2026/05 ~ 현재     (코스닥 1075 → 790, 급락)

실행:
  cd examples_user/leverage_bot
  uv run python ../domestic_flow/backtest_bull_bear.py
"""
import sys, os, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

_DIR      = os.path.dirname(os.path.abspath(__file__))
_EXAMPLES = os.path.dirname(_DIR)
sys.path.insert(0, _EXAMPLES)

import kis_auth as ka
from domestic_flow.flow import (
    _load_all_stock_codes,
    _check_yangumyang, _check_yangumyang_p3,
)

# ── 기간 설정 ────────────────────────────────────────────────
PERIODS = {
    '📈 상승장 (25.10~26.02)': ('20251001', '20260228'),
    '📉 하락장 (26.05~현재)':   ('20260501', '20260716'),
}
MARKET   = '코스닥'
SAMPLE_N = 300   # 종목 수 (많을수록 정확하지만 느림)


def _fetch_price_range(code: str, start: str, end: str) -> list[dict]:
    """기간별 시세 (FHKST03010100) → 최신순 리스트"""
    params = {
        'FID_COND_MRKT_DIV_CODE': 'J',
        'FID_INPUT_ISCD':         code,
        'FID_INPUT_DATE_1':       start,
        'FID_INPUT_DATE_2':       end,
        'FID_PERIOD_DIV_CODE':    'D',
        'FID_ORG_ADJ_PRC':        '1',
    }
    res = ka._url_fetch(
        '/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice',
        'FHKST03010100', '', params,
    )
    if not res.isOK():
        return []

    rows = getattr(res.getBody(), 'output2', None) or []
    result = []
    for r in rows:
        r = dict(r) if not isinstance(r, dict) else r
        try:
            close  = int(r.get('stck_clpr', 0) or 0)
            open_  = int(r.get('stck_oprc', 0) or 0)
            high   = int(r.get('stck_hgpr', 0) or 0)
            low    = int(r.get('stck_lwpr', 0) or 0)
            vol    = int(r.get('acml_vol',  0) or 0)
            vrss   = int(r.get('prdy_vrss', 0) or 0)  # 전일 대비 (부호 포함)
            prev_c = close - vrss
            rate   = vrss / prev_c * 100 if prev_c > 0 else 0.0
        except (ValueError, ZeroDivisionError):
            continue
        result.append({
            '날짜':   r.get('stck_bsop_date', ''),
            '시가':   open_,
            '종가':   close,
            '고가':   high,
            '저가':   low,
            '거래량': vol,
            '등락률': round(rate, 2),
        })
    # API가 최신→과거 순으로 반환 → 그대로 사용 (yangumyang 함수가 최신순 기대)
    return result


def _fetch_index_range(start: str, end: str) -> dict[str, float]:
    """코스닥 지수 기간별 등락률 → {날짜: 등락률%}"""
    params = {
        'FID_COND_MRKT_DIV_CODE': 'U',
        'FID_INPUT_ISCD':         '1001',
        'FID_INPUT_DATE_1':       start,
        'FID_INPUT_DATE_2':       end,
        'FID_PERIOD_DIV_CODE':    'D',
    }
    res = ka._url_fetch(
        '/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice',
        'FHKUP03500100', '', params,
    )
    if not res.isOK():
        return {}

    rows = getattr(res.getBody(), 'output2', None) or []
    result = {}
    for r in rows:
        r = dict(r) if not isinstance(r, dict) else r
        date = r.get('stck_bsop_date', '')
        try:
            close  = float(r.get('bstp_nmix_prpr', 0) or 0)
            vrss   = float(r.get('bstp_nmix_prdy_vrss', 0) or 0)
            prev_c = close - vrss
            rate   = vrss / prev_c * 100 if prev_c > 0 else 0.0
        except (ValueError, ZeroDivisionError):
            rate = 0.0
        if date:
            result[date] = round(rate, 2)
    return result


def _worker(code: str, name: str, start: str, end: str) -> list[dict]:
    try:
        time.sleep(0.15)
        data = _fetch_price_range(code, start, end)
    except Exception:
        return []

    if len(data) < 12:
        return []

    events = []
    for i in range(1, len(data) - 10):
        window     = data[i:]
        check_date = window[0]['날짜']

        pattern = _check_yangumyang(window) or _check_yangumyang_p3(window)
        if pattern is None:
            continue

        check_close = window[0]['종가']

        def pct(idx):
            if i < idx or check_close == 0:
                return None
            return round((data[i - idx]['종가'] - check_close) / check_close * 100, 2)

        events.append({
            '날짜': check_date,
            '패턴': pattern['패턴'],
            'D1':   pct(1),
            'D3':   pct(3),
            'D5':   pct(5),
        })
    return events


def _run_period(label: str, start: str, end: str, stocks: list) -> dict:
    """한 기간 백테스트 → 날짜별 이벤트 딕셔너리 반환"""
    print(f"\n  [{label}] {start}~{end}  {len(stocks)}종목 스캔 중...")
    all_events = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(_worker, c, n, start, end): c for c, n in stocks}
        done = 0
        for fut in as_completed(futures):
            all_events.extend(fut.result())
            done += 1
            if done % 100 == 0:
                print(f"    진행 {done}/{len(stocks)}...")
    return all_events


def _stats(events, key):
    vals = [e[key] for e in events if e.get(key) is not None]
    if not vals:
        return '-', '-', '-'
    w   = sum(1 for v in vals if v > 0)
    avg = sum(vals) / len(vals)
    return len(vals), f'{w/len(vals)*100:.1f}%', f'{avg:+.2f}%'


def main():
    ka.auth()
    import random
    all_stocks = _load_all_stock_codes(MARKET)
    sample = random.sample(all_stocks, min(SAMPLE_N, len(all_stocks)))

    print(f"{'='*65}")
    print(f"  상승장 vs 하락장  양음양 백테스트  ({MARKET} {SAMPLE_N}종목)")
    print(f"{'='*65}")

    results = {}
    for label, (start, end) in PERIODS.items():
        events = _run_period(label, start, end, sample)
        results[label] = events

    # ── 종합 비교 ────────────────────────────────────────────
    print(f"\n\n{'='*65}")
    print(f"  종합 비교  (D1=익일 / D3=3일후 / D5=5일후)")
    print(f"{'='*65}")
    print(f"  {'구분':<22}  {'발동':>4}  {'D1승률':>6} {'D1평균':>7}  {'D3승률':>6} {'D3평균':>7}  {'D5승률':>6} {'D5평균':>7}")
    print(f"  {'-'*62}")

    for label, events in results.items():
        n1, w1, a1 = _stats(events, 'D1')
        n3, w3, a3 = _stats(events, 'D3')
        n5, w5, a5 = _stats(events, 'D5')
        total = len(events)
        print(f"  {label:<22}  {total:>4}  {w1:>6} {a1:>7}  {w3:>6} {a3:>7}  {w5:>6} {a5:>7}")

    # ── 날짜별 지수 방향 교차 분석 ────────────────────────────
    print(f"\n\n{'='*65}")
    print(f"  지수 상승일 vs 하락일 비교 (각 기간 내)")
    print(f"{'='*65}")

    for label, (start, end) in PERIODS.items():
        events  = results[label]
        idx_map = _fetch_index_range(start, end)
        by_date = defaultdict(list)
        for e in events:
            by_date[e['날짜']].append(e)

        up_e, dn_e = [], []
        for date, evts in by_date.items():
            rate = idx_map.get(date)
            if rate is None:
                continue
            if rate > 0:
                up_e.extend(evts)
            else:
                dn_e.extend(evts)

        print(f"\n  {label}")
        for sublabel, evts in [('  지수 상승일', up_e), ('  지수 하락일', dn_e)]:
            n1, w1, a1 = _stats(evts, 'D1')
            n3, w3, a3 = _stats(evts, 'D3')
            print(f"    {sublabel:<12} 발동 {n1 if isinstance(n1,int) else 0:>4}건  "
                  f"D1: {w1:>6} {a1:>7}  D3: {w3:>6} {a3:>7}")


if __name__ == '__main__':
    main()
