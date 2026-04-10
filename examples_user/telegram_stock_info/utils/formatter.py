"""텔레그램 메시지 포맷터"""
from typing import Dict, List, Optional


def format_header(result: dict, is_overseas: bool = False, is_etf: bool = False) -> str:
    """메시지 헤더 포맷팅"""
    if is_etf:
        name = result.get('etf_name', result.get('iscd'))
        price = f"{result['latest_price']:,.0f}원"
        icon = "📈"
    elif is_overseas:
        name = f"{result.get('symbol')} ({result.get('exchange')})"
        price = f"${result['latest_price']:,.2f}"
        icon = "📊"
    else:
        name = result.get('stock_name', result['stock_code'])
        price = f"{result['latest_price']:,.0f}원"
        icon = "📊"
    
    header = f"{icon} <b>{name}</b>\n"
    header += f"💰 <b>{price}</b> ({result['latest_date']})\n"
    header += f"━━━━━━━━━━━━━━━━━━━\n\n"
    
    # 여러 검색 결과가 있는 경우 표시
    if result.get('search_results') and len(result['search_results']) > 1:
        header += f"💡 '{result.get('stock_name')}' 외 {len(result['search_results'])-1}개 검색됨\n\n"
    
    return header


def format_volume_section(volume_data: List[Dict], title: str, is_overseas: bool = False) -> str:
    """거래량 섹션 포맷팅"""
    if not volume_data:
        return ""
    
    section = f"{title}\n"
    for i, item in enumerate(volume_data, 1):
        diff_pct = item['diff_pct']
        
        if is_overseas:
            if diff_pct >= 0:
                price_str = f"${item['price']:,.2f} (+{diff_pct:.1f}%)"
            else:
                price_str = f"${item['price']:,.2f} ({diff_pct:.1f}%)"
        else:
            if diff_pct >= 0:
                price_str = f"{item['price']:,.0f}원 (+{diff_pct:.1f}%)"
            else:
                price_str = f"{item['price']:,.0f}원 ({diff_pct:.1f}%)"
        
        section += f"<b>[{i}위]</b> {price_str}\n"
        section += f"     {item['date']} / 거래량 {item['volume']:,} (상위 {item['volume_rank']:.0f}%)\n"
    
    return section + "\n"


def format_volume_analysis(volume_analysis: Dict, is_overseas: bool = False) -> str:
    """거래량 분석 전체 포맷팅"""
    msg = ""
    
    # 상방 분석
    if 'upper' in volume_analysis:
        upper = volume_analysis['upper']
        msg += f"📈 <b>저항선 (상방)</b>\n\n"
        
        # 전체 거래량 순위
        if upper.get('volume_top3'):
            msg += format_volume_section(
                upper['volume_top3'], "📊 <b>전체 거래량 순위</b>", is_overseas
            )
        
        # 10% 이내 거래량 순위
        if upper.get('nearby_top3'):
            msg += format_volume_section(
                upper['nearby_top3'], "📍 <b>10% 이내 거래량 순위</b>", is_overseas
            )
    
    # 하방 분석
    if 'lower' in volume_analysis:
        lower = volume_analysis['lower']
        msg += f"📉 <b>지지선 (하방)</b>\n\n"
        
        # 전체 거래량 순위
        if lower.get('volume_top3'):
            msg += format_volume_section(
                lower['volume_top3'], "📊 <b>전체 거래량 순위</b>", is_overseas
            )
        
        # 10% 이내 거래량 순위
        if lower.get('nearby_top3'):
            msg += format_volume_section(
                lower['nearby_top3'], "📍 <b>10% 이내 거래량 순위</b>", is_overseas
            )
    
    # ±20% 이내 전체 거래량 Top 3
    if volume_analysis.get('volume_top3_20pct_all'):
        msg += f"━━━━━━━━━━━━━━━━━━━\n"
        msg += format_volume_section(
            volume_analysis['volume_top3_20pct_all'], 
            "💎 <b>±20% 이내 거래량 Top 3</b>", 
            is_overseas
        )
    
    return msg


def format_ma_analysis(ma_analysis: Dict, is_overseas: bool = False) -> str:
    """이동평균선 분석 포맷팅"""
    if not ma_analysis or ('support_ma' not in ma_analysis and 'resistance_ma' not in ma_analysis):
        return ""
    
    msg = f"━━━━━━━━━━━━━━━━━━━\n"
    msg += f"📊 <b>이동평균선</b>\n"
    
    # 저항선 MA
    if 'resistance_ma' in ma_analysis:
        resistance = ma_analysis['resistance_ma']
        
        # 리스트인 경우 (국내주식 스타일 - 모든 저항선)
        if isinstance(resistance, list):
            msg += f"🔴 <b>저항선</b>\n"
            for ma in resistance:
                if is_overseas:
                    msg += f"  {ma['name']}: ${ma['value']:,.2f} (+{abs(ma['diff_pct']):.1f}%)\n"
                else:
                    msg += f"  {ma['name']}: {ma['value']:,.0f}원 (+{abs(ma['diff_pct']):.1f}%)\n"
        
        # 딕셔너리인 경우 (해외주식 스타일 - 가장 가까운 것)
        elif isinstance(resistance, dict):
            msg += f"🔴 <b>가장 가까운 저항선</b>\n"
            if is_overseas:
                msg += f"  {resistance['name']}: ${resistance['value']:,.2f} (+{abs(resistance['diff_pct']):.1f}%)\n"
            else:
                msg += f"  {resistance['name']}: {resistance['value']:,.0f}원 (+{abs(resistance['diff_pct']):.1f}%)\n"
    
    # 지지선 MA
    if 'support_ma' in ma_analysis:
        support = ma_analysis['support_ma']
        
        # 리스트인 경우 (국내주식 스타일 - 모든 지지선)
        if isinstance(support, list):
            msg += f"🟢 <b>지지선</b>\n"
            for ma in support:
                if is_overseas:
                    msg += f"  {ma['name']}: ${ma['value']:,.2f} (-{ma['diff_pct']:.1f}%)\n"
                else:
                    msg += f"  {ma['name']}: {ma['value']:,.0f}원 (-{ma['diff_pct']:.1f}%)\n"
        
        # 딕셔너리인 경우 (해외주식 스타일 - 가장 가까운 것)
        elif isinstance(support, dict):
            msg += f"🟢 <b>가장 가까운 지지선</b>\n"
            if is_overseas:
                msg += f"  {support['name']}: ${support['value']:,.2f} (-{support['diff_pct']:.1f}%)\n"
            else:
                msg += f"  {support['name']}: {support['value']:,.0f}원 (-{support['diff_pct']:.1f}%)\n"
    
    return msg


def format_analysis_message(result: dict, is_overseas: bool = False, is_etf: bool = False) -> str:
    """분석 결과를 텔레그램 메시지 포맷으로 변환
    
    Args:
        result: 분석 결과 딕셔너리
        is_overseas: 해외주식 여부
        is_etf: ETF 여부
    
    Returns:
        포맷팅된 메시지 문자열
    """
    # 헤더
    msg = format_header(result, is_overseas, is_etf)
    
    # 거래량 분석
    if 'volume_analysis' in result:
        msg += format_volume_analysis(result['volume_analysis'], is_overseas)
    
    # 이동평균선 분석  
    if 'ma_analysis' in result:
        msg += format_ma_analysis(result['ma_analysis'], is_overseas)
    
    return msg


def format_error_message(error_type: str, details: str = None) -> str:
    """에러 메시지 포맷팅
    
    Args:
        error_type: 에러 타입 ('not_found', 'api_error', 'format_error')
        details: 추가 상세 정보
    
    Returns:
        포맷팅된 에러 메시지
    """
    error_messages = {
        'not_found': '❌ 종목을 찾을 수 없습니다.',
        'api_error': '❌ 분석 중 오류가 발생했습니다.\n잠시 후 다시 시도해주세요.',
        'format_error': '❌ 입력 형식을 확인해주세요.\n국내: 종목명 또는 종목코드\n해외: 거래소:종목코드 (예: NAS:TSLA)',
        'insufficient_data': '❌ 분석할 데이터가 부족합니다.',
        'authentication': '❌ 인증에 실패했습니다.',
        'rate_limit': '❌ API 호출 제한 초과.\n잠시 후 다시 시도하세요.'
    }
    
    base_msg = error_messages.get(error_type, '❌ 알 수 없는 오류가 발생했습니다.')
    
    if details:
        return f"{base_msg}\n\n상세: {details}"
    
    return base_msg


def format_intraday_sr_message(result: dict) -> str:
    """1분봉 거래량 지지/저항 분석 결과 포맷팅

    Args:
        result: analyze_intraday_volume_sr() 반환값

    Returns:
        포맷팅된 텔레그램 HTML 메시지
    """
    if 'error' in result:
        return f"❌ {result['error']}"

    name = result.get('stock_name') or result.get('stock_code', '')
    code = result.get('stock_code', '')
    current_price = result['current_price']
    total_candles = result.get('total_candles', 0)

    msg = f"📊 <b>{name}</b> ({code})\n"
    msg += f"💰 <b>현재가: {current_price:,}원</b>\n"
    msg += f"━━━━━━━━━━━━━━━━━━━\n"
    msg += f"⏱ 오늘 1분봉 거래량 지지/저항\n\n"

    # 저항선 (상방)
    resistance = result.get('resistance')
    if resistance:
        time_str = resistance['time']
        # HHMMSS → HH:MM 포맷
        if len(time_str) >= 4:
            time_str = f"{time_str[:2]}:{time_str[2:4]}"
        msg += f"📈 <b>저항 (상방 최대 거래량)</b>\n"
        msg += f"   가격: {resistance['price']:,}원 (+{resistance['diff_pct']:.2f}%)\n"
        msg += f"   시각: {time_str}\n"
        msg += f"   거래량: {resistance['volume']:,}\n\n"
    else:
        msg += f"📈 <b>저항</b>: 데이터 없음\n\n"

    # 지지선 (하방)
    support = result.get('support')
    if support:
        time_str = support['time']
        if len(time_str) >= 4:
            time_str = f"{time_str[:2]}:{time_str[2:4]}"
        msg += f"📉 <b>지지 (하방 최대 거래량)</b>\n"
        msg += f"   가격: {support['price']:,}원 ({support['diff_pct']:.2f}%)\n"
        msg += f"   시각: {time_str}\n"
        msg += f"   거래량: {support['volume']:,}\n\n"
    else:
        msg += f"📉 <b>지지</b>: 데이터 없음\n\n"

    msg += f"<i>기준: 당일 {total_candles}개 1분봉</i>"
    return msg


def format_analyzing_message(stock_input: str, analysis_type: str) -> str:
    """분석 시작 메시지 포맷팅
    
    Args:
        stock_input: 입력된 종목
        analysis_type: 분석 타입 ('domestic', 'overseas', 'etf')
    
    Returns:
        포맷팅된 분석 시작 메시지
    """
    type_info = {
        'domestic': '🇰🇷 국내주식 (약 10-30초 소요)',
        'overseas': '🌍 해외주식 (약 10-30초 소요)',
        'etf': '📈 ETF (약 10-30초 소요)'
    }
    
    return f"🔍 '{stock_input}' 분석 중...\n{type_info.get(analysis_type, '분석 중...')}"