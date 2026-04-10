"""봇 공유 상태 관리 - 검색 기록"""
from utils.config import BOT_SETTINGS

# 사용자별 최근 검색 기록 (메모리 기반)
user_history: dict = {}


def add_to_history(user_id: int, stock_input: str, display_name: str) -> None:
    """검색 기록에 추가 (중복 제거, 최대 N개 유지)"""
    if user_id not in user_history:
        user_history[user_id] = []

    # 중복 제거
    user_history[user_id] = [
        item for item in user_history[user_id]
        if item['input'] != stock_input
    ]

    # 최신 항목을 앞에 추가
    user_history[user_id].insert(0, {
        'input': stock_input,
        'display': display_name
    })

    # 최대 개수 유지
    max_items = BOT_SETTINGS['max_history_items']
    user_history[user_id] = user_history[user_id][:max_items]
