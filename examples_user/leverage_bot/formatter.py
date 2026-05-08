"""Telegram HTML 메시지 포맷터"""
import math
from typing import Optional
from calc import GRADE_CONFIG, TICKER_GRADE, get_warnings, calculate_buy_plan, calculate_from_avg


def _p(x: float) -> str:
    """소수점 둘째 자리 버림 (반올림 없음)"""
    return f'${math.floor(x * 100) / 100:,.2f}'


def _grade_emoji(grade: str) -> str:
    return {'tier1_stable': '🔵', 'tier1_volatile': '🟠', 'tier2': '🟡', 'tier3': '🔴'}.get(grade, '⚪')


def _cond_str(vix: Optional[float], below_50ma: bool, below_200ma: bool, vix_adj: float) -> str:
    """헤더용 한 줄 조건 요약"""
    if below_200ma:
        market = '🚫 200일선↓'
    elif below_50ma:
        market = '📉 50일선↓'
    else:
        market = '✅ 정상'

    if vix is None:
        vix_part = ''
    elif vix >= 40:
        vix_part = f'  🚫 VIX {vix:.1f}'
    elif vix >= 30:
        vix_part = f'  🚫 VIX {vix:.1f}'
    elif vix >= 22:
        vix_part = f'  ⚠️ VIX {vix:.1f}'
    else:
        vix_part = f'  ✅ VIX {vix:.1f}'

    adj = f'  (+{vix_adj:.0f}%p 보정)' if vix_adj > 0 else ''
    return f'{market}{vix_part}{adj}'


def _filter_warnings(warnings: list[str]) -> list[str]:
    """헤더에 이미 표시된 정상 운용 안내는 제거, 액션 필요한 것만 남김"""
    skip = {'✅ 정상 구간', '✅ VIX'}
    return [w for w in warnings if not any(w.startswith(s) for s in skip)]


def format_first_entry(
    ticker: str,
    close_price: float,
    close_date: str,
    vix: Optional[float],
    below_50ma: bool,
    below_200ma: bool,
) -> str:
    """1차 진입가 메시지"""
    grade = TICKER_GRADE[ticker]
    cfg = GRADE_CONFIG[grade]
    plan = calculate_buy_plan(close_price, grade, vix, below_50ma, below_200ma)
    warnings = _filter_warnings(get_warnings(ticker, grade, vix, below_50ma, below_200ma))

    r = plan['rounds'][0]
    buy = _p(r["buy_price"])

    lines = [
        f'{_grade_emoji(grade)} <b>{ticker}</b>  {cfg["name"]}',
        f'<code>{close_date}  종가 ${close_price:,.2f}  진입 −{plan["entry_pct"]:.1f}%</code>',
        _cond_str(vix, below_50ma, below_200ma, plan['vix_adj']),
        '',
        '┌─ <b>1차 진입가</b>',
        f'│  매수가  <b>{buy}</b>',
        f'└  투입    {r["amount"]}만원',
    ]

    if warnings:
        lines += ['', '⚠️ <b>주의</b>']
        for w in warnings:
            lines.append(f'  {w}')

    lines += ['']
    return '\n'.join(lines)


def format_add_buy_result(
    ticker: str,
    close_price: float,
    close_date: str,
    vix: Optional[float],
    below_50ma: bool,
    below_200ma: bool,
    from_round: int,
    input_avg: float,
) -> str:
    """N차 추매 결과 메시지"""
    grade = TICKER_GRADE[ticker]
    cfg = GRADE_CONFIG[grade]
    plan = calculate_from_avg(input_avg, from_round, grade, vix, below_50ma, below_200ma)
    warnings = _filter_warnings(get_warnings(ticker, grade, vix, below_50ma, below_200ma))

    r = plan['round']
    star = '  ★ 권장 마지막 차수' if r['is_last_recommended'] else ''

    # 현재 포지션 기준 목표가/손절가 (입력 평단 기준)
    target_pcts = cfg['target_pcts']
    current_round = from_round - 1
    if current_round == 1:
        cur_tgt_pct = target_pcts[0]
    elif current_round <= 3:
        cur_tgt_pct = target_pcts[1]
    else:
        cur_tgt_pct = target_pcts[2]
    cur_tgt = _p(input_avg * (1 + cur_tgt_pct / 100))
    cur_stp = _p(input_avg * (1 - cfg['stop_pct'] / 100))

    buy  = _p(r["buy_price"])
    avg  = _p(r["avg_price"])
    tgt  = _p(r["target_price"])
    stp  = _p(r["stop_price"])

    lines = [
        f'{_grade_emoji(grade)} <b>{ticker}</b>  {cfg["name"]}',
        f'<code>{close_date}  종가 ${close_price:,.2f}  평단 ${input_avg:,.2f}</code>',
        _cond_str(vix, below_50ma, below_200ma, 0),
        '',
        f'┌─ <b>현재 포지션</b>  ({from_round - 1}차까지)',
        f'│  목표가  {cur_tgt}  <i>(+{cur_tgt_pct:.0f}%)</i>',
        f'└  손절가  {cur_stp}  <i>(−{cfg["stop_pct"]:.0f}%)</i>',
        '',
        f'┌─ <b>{from_round}차 추매</b>{star}',
        f'│  매수가  <b>{buy}</b>',
        f'│  새평단  {avg}',
        f'│  목표가  {tgt}  <i>({r["target_label"]})</i>',
        f'│  손절가  {stp}  <i>(−{cfg["stop_pct"]:.0f}%)</i>',
        f'└  투입 {r["amount"]}만  누적 {r["total_invested"]}만',
    ]

    if warnings:
        lines += ['', '⚠️ <b>주의</b>']
        for w in warnings:
            lines.append(f'  {w}')

    lines += ['']
    return '\n'.join(lines)


def format_unknown_ticker(ticker: str) -> str:
    tickers = ', '.join(sorted(TICKER_GRADE.keys()))
    return (
        f'❌ <b>{ticker}</b>는 등록되지 않은 종목입니다.\n\n'
        f'<b>등록 종목 ({len(TICKER_GRADE)}개):</b>\n'
        f'<code>{tickers}</code>'
    )


def format_start_message() -> str:
    return (
        '📊 <b>레버리지 ETF 매수가 계산기</b>\n\n'
        '티커를 입력하면 1차 진입가를 계산합니다.\n'
        '추가매수는 버튼을 눌러 현재 평단을 입력하면 계산됩니다.\n\n'
        '<b>사용법:</b>  <code>TQQQ</code>  <code>SOXL</code>  <code>NVDL</code> …\n\n'
        '명령어: /list  /vix  /help'
    )


def format_help_message() -> str:
    return (
        '📖 <b>사용 방법</b>\n\n'
        '<b>1차 진입가</b>\n'
        '  티커 입력 → 전날 종가 기준 1차 매수가 계산\n'
        '  50일/200일선 위치 자동 감지\n\n'
        '<b>추가매수</b>\n'
        '  [2차 추매] … [5차 추매] 버튼 클릭\n'
        '  → 현재 평단 입력 → 해당 차수 매수가·목표가·손절가 계산\n\n'
        '<b>명령어</b>\n'
        '  /list    지원 종목 전체 목록\n'
        '  /vix     현재 VIX 조회\n'
        '  /scan    전 종목 MA 위치 스캔\n'
        '  /cancel  평단 입력 취소\n\n'
        '<b>계좌 손실 단계별 방어</b>\n'
        '  −8%   신규 진입 중단\n'
        '  −12%  2·3등급 일부 축소\n'
        '  −15%  전체 시스템 일시 중단\n\n'
        '<b>슬롯 운용 원칙</b>\n'
        '  최대 8슬롯 (1등급 3·2등급 2·3등급 1·현금 1+)\n'
        '  50일선↓: 1차 70만·총 600만 한도·4차까지만\n'
        '  VIX 30+: 신규 거의 중단 (1등급 안정형 소액만)\n'
        '  VIX 40+: 전부 중단'
    )


def format_list_message() -> str:
    t1s = [t for t, g in TICKER_GRADE.items() if g == 'tier1_stable']
    t1v = [t for t, g in TICKER_GRADE.items() if g == 'tier1_volatile']
    t2  = [t for t, g in TICKER_GRADE.items() if g == 'tier2']
    t3  = [t for t, g in TICKER_GRADE.items() if g == 'tier3']
    return (
        '📋 <b>지원 종목 전체 목록</b>\n\n'
        f'🔵 <b>1등급 안정형</b> ({len(t1s)}개)\n'
        f'<code>{" ".join(sorted(t1s))}</code>\n\n'
        f'🟠 <b>1등급 변동형</b> ({len(t1v)}개)\n'
        f'<code>{" ".join(sorted(t1v))}</code>\n\n'
        f'🟡 <b>2등급 단일주</b> ({len(t2)}개)\n'
        f'<code>{" ".join(sorted(t2))}</code>\n\n'
        f'🔴 <b>3등급 고위험</b> ({len(t3)}개)\n'
        f'<code>{" ".join(sorted(t3))}</code>'
    )
