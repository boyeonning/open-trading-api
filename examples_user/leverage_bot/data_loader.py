"""주간 기법 HTML 파일 파서 — data/ 폴더에서 최신 파일 자동 선택

파일 네이밍 규칙: YYYY-MM-DD_*.html (앞 날짜 기준으로 최신 파일 선택)
파싱 대상: 섹션 2.5 전체 감시 리스트 테이블
  열: 종목 | 등급 | 5거래일 | MA50 | MA200 | 신호 | 조치
"""
import os
import re
import html as _html
from typing import Optional

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

# 신호 이모지 분류
SIGNAL_GO   = {'🔵', '🟢'}   # 진입 검토 가능
SIGNAL_COND = {'🟡'}          # 조건부 (표시하되 ⚠️ 플래그)
SIGNAL_HOLD = {'🟠'}          # 신규 보류 (50일선 아래 등)
SIGNAL_STOP = {'🔴'}          # 접근 금지 (200일선 아래)


def _extract_ticker(text: str) -> Optional[str]:
    """'S&P500 3배(UPRO)' → 'UPRO'"""
    m = re.search(r'\(([A-Z0-9]+)\)', text)
    return m.group(1) if m else None


def _extract_grade(text: str) -> Optional[str]:
    """'A 저변동' → 'A'"""
    m = re.match(r'([A-E])\s', text.strip())
    return m.group(1) if m else None


def _strip_tags(html_text: str) -> str:
    """HTML 태그 제거 + 엔티티 디코드"""
    return _html.unescape(re.sub(r'<[^>]+>', '', html_text)).strip()


def get_latest_file() -> Optional[str]:
    """data/ 폴더에서 YYYY-MM-DD_ 로 시작하는 주간 기법 HTML 중 가장 최신 파일 반환"""
    if not os.path.isdir(_DATA_DIR):
        return None
    files = sorted(
        [f for f in os.listdir(_DATA_DIR)
         if f.endswith('.html') and re.match(r'^\d{4}-\d{2}-\d{2}_', f)],
        reverse=True,
    )
    return os.path.join(_DATA_DIR, files[0]) if files else None


def load_latest_watchlist() -> tuple[dict[str, dict], Optional[str]]:
    """
    최신 HTML 파일에서 '전체 감시 리스트' 테이블 파싱.

    Returns:
        (watchlist, filename)
        watchlist: {
            'UPRO': {
                'grade':  'A',
                'signal': '🔵',
                'action': '주중 눌림 -3% 도달, 1차만 검토',
                'name':   'S&P500 3배(UPRO)',
            },
            ...
        }
        filename: 파싱에 사용한 파일명 (없으면 None)
    """
    path = get_latest_file()
    if not path:
        return {}, None

    with open(path, encoding='utf-8') as f:
        html = f.read()

    # 섹션 2.5 전체 감시 리스트 이후의 첫 번째 </table> 까지
    m = re.search(r'전체 감시 리스트(.*?)</table>', html, re.DOTALL)
    if not m:
        return {}, os.path.basename(path)

    section = m.group(1)
    result: dict[str, dict] = {}

    for row_m in re.finditer(r'<tr[^>]*>(.*?)</tr>', section, re.DOTALL):
        row_html = row_m.group(1)
        cells = [_strip_tags(c) for c in re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.DOTALL)]

        if len(cells) < 6:
            continue  # 헤더행 또는 병합행 스킵

        ticker = _extract_ticker(cells[0])
        grade  = _extract_grade(cells[1])

        if not ticker or not grade:
            continue

        signal = cells[5].strip()
        action = cells[6].strip() if len(cells) > 6 else ''

        result[ticker] = {
            'grade':  grade,
            'signal': signal,
            'action': action,
            'name':   cells[0],
        }

    return result, os.path.basename(path)
