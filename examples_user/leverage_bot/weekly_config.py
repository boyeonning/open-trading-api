"""주간 기법 데이터 — 매주 Claude가 HTML 파싱 후 갱신, 봇은 이 파일만 참조

신호:
    🔵🟢 = 진입 검토 가능
    🟡   = 조건부 (표시하되 ⚠️ 플래그)
    🟠   = 신규 보류 (50일선 아래)
    🔴   = 접근 금지 (200일선 아래)

entry_pct:
    None  → GRADE_CONFIG 기본값 사용
    float → 해당 % 강제 적용 (메가캡 예외 등)
"""

WEEKLY_DATE  = "2026-07-11"
WEEKLY_TITLE = "7월 2주차"

# 신호 분류 (handlers에서 직접 비교용)
SIGNAL_GO   = {'🔵', '🟢'}
SIGNAL_COND = {'🟡'}
SIGNAL_HOLD = {'🟠'}
SIGNAL_STOP = {'🔴'}

WATCHLIST: dict[str, dict] = {
    # ── 진입 검토 (🔵) ─────────────────────────────────────
    'UPRO': {'grade': 'A', 'signal': '🔵', 'entry_pct': None,
             'action': '주중 눌림 -3% 도달, 1차만 검토'},
    'SSO':  {'grade': 'A', 'signal': '🔵', 'entry_pct': None,
             'action': '주중 눌림 -3% 도달, 1차만 검토'},
    'QLD':  {'grade': 'A', 'signal': '🔵', 'entry_pct': None,
             'action': '주중 눌림 -3% 도달, 1차만 검토'},
    'TQQQ': {'grade': 'B', 'signal': '🔵', 'entry_pct': None,
             'action': '주중 눌림 -4% 도달, 1차만 검토'},
    'TECL': {'grade': 'C', 'signal': '🔵', 'entry_pct': None,
             'action': '주중 눌림 -5% 도달, 1차만 검토'},
    'FNGU': {'grade': 'A', 'signal': '🔵', 'entry_pct': None,
             'action': '주중 눌림 -3% 도달, 1차만 검토'},
    'AAPU': {'grade': 'A', 'signal': '🔵', 'entry_pct': None,
             'action': '주중 눌림 -3% 도달, 1차만 검토'},
    'ASMU': {'grade': 'C', 'signal': '🔵', 'entry_pct': None,
             'action': '주중 눌림 -5% 도달, 1차만 검토'},

    # ── 조건부 (🟡) ────────────────────────────────────────
    'NVDL': {'grade': 'B', 'signal': '🟡', 'entry_pct': None,
             'action': '메가캡 조건부: 1차만, 반도체 클러스터 중복 금지'},
    'TSLL': {'grade': 'D', 'signal': '🟡', 'entry_pct': 7.0,
             'action': '메가캡 예외: 1차만, 기준 -7%로 깊게'},
    'GGLL': {'grade': 'A', 'signal': '🟡', 'entry_pct': 4.0,
             'action': '메가캡 예외: 1차만, 기준 -4%로 깊게'},
    'AVL':  {'grade': 'C', 'signal': '🟡', 'entry_pct': 6.0,
             'action': '메가캡 예외: 1차만, 기준 -6%로 깊게'},

    # ── 신규 보류 (🟠) — 50일선 아래 ──────────────────────
    'SOXL': {'grade': 'E', 'signal': '🟠', 'entry_pct': None,
             'action': '50일선 아래, 신규 보류'},
    'PTIR': {'grade': 'B', 'signal': '🟠', 'entry_pct': None,
             'action': '50일선 아래, 신규 보류'},
    'MRVU': {'grade': 'E', 'signal': '🟠', 'entry_pct': None,
             'action': '50일선 아래, 신규 보류'},
    'MSTX': {'grade': 'B', 'signal': '🟠', 'entry_pct': None,
             'action': '50일선 아래, 신규 보류'},
    'UCO':  {'grade': 'B', 'signal': '🟠', 'entry_pct': None,
             'action': '50일선 아래, 신규 보류'},

    # ── 접근 금지 (🔴) — 200일선 아래 ─────────────────────
    'BITX': {'grade': 'B', 'signal': '🔴', 'entry_pct': None,
             'action': '200일선 아래, 접근금지'},
    'ETHU': {'grade': 'C', 'signal': '🔴', 'entry_pct': None,
             'action': '200일선 아래, 접근금지'},
    'AGQ':  {'grade': 'C', 'signal': '🔴', 'entry_pct': None,
             'action': '200일선 아래, 접근금지'},
    'TMF':  {'grade': 'A', 'signal': '🔴', 'entry_pct': None,
             'action': '200일선 아래, 접근금지'},
}
