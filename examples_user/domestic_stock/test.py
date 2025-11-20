import sys
import logging

sys.path.extend(['..', '.'])
import kis_auth as ka
from stock_analyzer import analyze_stock

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 인증
ka.auth()
trenv = ka.getTREnv()

# 2년치 데이터를 100개씩 가져오기
import time


def get_stock_code(stock_name: str) -> str:
    """종목명으로 종목코드 찾기"""
    # 코스닥, 코스피 모두 검색
    kosdaq_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                               "stocks_info", "kosdaq_code_part1.tmp")
    kospi_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                              "stocks_info", "kospi_code_part1.tmp")

    for file_path in [kosdaq_file, kospi_file]:
        if os.path.exists(file_path):
            # Try utf-8 first (for newly generated files), fallback to cp949
            try:
                df = pd.read_csv(file_path, header=None, names=['단축코드', '표준코드', '한글종목명'], encoding='utf-8')
            except UnicodeDecodeError:
                df = pd.read_csv(file_path, header=None, names=['단축코드', '표준코드', '한글종목명'], encoding='cp949')
            # 종목명으로 검색 (부분 일치, 대소문자 무시)
            result = df[df['한글종목명'].str.contains(stock_name, case=False, na=False)]
            if not result.empty:
                if len(result) > 1:
                    logger.info(f"'{stock_name}' 검색 결과:")
                    for _, row in result.iterrows():
                        logger.info(f"  - {row['한글종목명']} ({row['단축코드']})")
                    # 첫 번째 결과 사용
                    stock_code = result.iloc[0]['단축코드']
                    logger.info(f"첫 번째 결과 사용: {result.iloc[0]['한글종목명']} ({stock_code})")
                    return stock_code
                else:
                    stock_code = result.iloc[0]['단축코드']
                    logger.info(f"종목 찾음: {result.iloc[0]['한글종목명']} ({stock_code})")
                    return stock_code

    raise ValueError(f"종목명 '{stock_name}'을 찾을 수 없습니다. 코스피/코스닥 마스터 파일을 먼저 생성하세요.")


# 종목 설정 (종목명 또는 종목코드)
STOCK_INPUT = "에코프로비엠"  # 종목명 (예: "삼성전자", "NAVER") 또는 종목코드 (예: "005930")

# 숫자로만 이루어진 경우 종목코드, 아니면 종목명으로 검색
if STOCK_INPUT.isdigit():
    STOCK_CODE = STOCK_INPUT
    logger.info(f"종목코드 직접 입력: {STOCK_CODE}")
else:
    STOCK_CODE = get_stock_code(STOCK_INPUT)

target_days = 365 * 2  # 2년
all_data = []
end_date_str = datetime.now().strftime("%Y%m%d")

call_count = 0
max_calls = int(target_days / 100) + 5  # 대략 필요한 호출 횟수 + 여유

while call_count < max_calls:
    logger.info(f"API 호출 {call_count + 1}회차: 종료일 {end_date_str}")

    result1, result2 = inquire_daily_itemchartprice(
        env_dv="real",
        fid_cond_mrkt_div_code="J",
        fid_input_iscd=STOCK_CODE,
        fid_input_date_1="19000101",  # 충분히 과거 날짜
        fid_input_date_2=end_date_str,
        fid_period_div_code="D",
        fid_org_adj_prc="1"
    )

    # result2가 DataFrame이면 리스트에 추가
    if result2 is not None and not result2.empty:
        all_data.append(result2)

        # 총 데이터 수 확인
        total_rows = sum(len(df) for df in all_data)
        logger.info(f"현재까지 {total_rows}개 데이터 수집, 이번 응답: {len(result2)}개")

        # 2년치 데이터를 충분히 모았으면 종료
        if total_rows >= target_days:
            logger.info(f"목표 달성: {total_rows}개 >= {target_days}개")
            break

        # 100개 미만이면 더 이상 데이터가 없는 것
        if len(result2) < 100:
            logger.info("마지막 데이터까지 수집 완료")
            break

        # 마지막 행의 날짜를 다음 end_date로 설정 (하루 전으로)
        last_date = result2.iloc[-1, 0]  # 첫 번째 컬럼이 날짜라고 가정
        # 날짜 형식 파싱 (YYYYMMDD로 변환)
        if isinstance(last_date, str):
            last_date_str = last_date.replace("-", "").replace("/", "")[:8]
        else:
            last_date_str = str(last_date)[:8]

        # 하루 전 날짜로 설정 (중복 방지)
        last_dt = datetime.strptime(last_date_str, "%Y%m%d")
        end_date_str = (last_dt - timedelta(days=1)).strftime("%Y%m%d")
    else:
        logger.warning("더 이상 데이터가 없습니다.")
        break

    call_count += 1
    time.sleep(0.1)  # API 호출 제한 고려

# 모든 데이터 합치기
if all_data:
    combined_df = pd.concat(all_data, ignore_index=True)
    # 날짜 기준 정렬 (오래된 것부터)
    combined_df = combined_df.sort_values(by=combined_df.columns[0]).reset_index(drop=True)

    logger.info(f"총 {len(combined_df)}개의 데이터를 가져왔습니다.")

    # 데이터 타입 변환
    combined_df['stck_clpr'] = combined_df['stck_clpr'].astype(float)
    combined_df['stck_oprc'] = combined_df['stck_oprc'].astype(float)
    combined_df['stck_hgpr'] = combined_df['stck_hgpr'].astype(float)
    combined_df['stck_lwpr'] = combined_df['stck_lwpr'].astype(float)
    combined_df['acml_vol'] = combined_df['acml_vol'].astype(float)

    # 이동평균선 계산
    combined_df['MA_5'] = combined_df['stck_clpr'].rolling(window=5).mean()
    combined_df['MA_10'] = combined_df['stck_clpr'].rolling(window=10).mean()
    combined_df['MA_60'] = combined_df['stck_clpr'].rolling(window=60).mean()
    combined_df['MA_120'] = combined_df['stck_clpr'].rolling(window=120).mean()

    # 가장 최근 종가
    latest_price = combined_df.iloc[-1]['stck_clpr']
    latest_date = combined_df.iloc[-1]['stck_bsop_date']

    print(f"\n{'='*60}")
    print(f"종목 코드: {STOCK_CODE}")
    print(f"최근 일자: {latest_date}")
    print(f"현재 종가: {latest_price:,.0f}원")
    print(f"{'='*60}")

    # 거래량 분석: 상방/하방에서 거래량 많이 터진 날 찾기
    # 1. 현재 종가와의 차이 계산
    combined_df['price_diff'] = (combined_df['stck_clpr'] - latest_price).abs()
    combined_df['price_direction'] = combined_df['stck_clpr'] - latest_price  # 양수: 상방, 음수: 하방

    # 2. 상위 거래량 필터링 (예: 상위 10% 거래량)
    volume_threshold = combined_df['acml_vol'].quantile(0.90)  # 상위 10%
    high_volume_df = combined_df[combined_df['acml_vol'] >= volume_threshold].copy()

    if not high_volume_df.empty:
        # 3-1. 상방(현재가보다 높은 가격대)에서 거래량 많이 터진 날
        upper_high_vol = high_volume_df[high_volume_df['price_direction'] > 0].copy()
        if not upper_high_vol.empty:
            # 상방 중 가장 가까운 날
            closest_upper = upper_high_vol.loc[upper_high_vol['price_diff'].idxmin()]

            print(f"\n[상방 거래량 상위 중 현재가와 가장 가까운 날]")
            print(f"  - 일자: {closest_upper['stck_bsop_date']}")
            print(f"  - 종가: {closest_upper['stck_clpr']:,.0f}원")
            print(f"  - 현재가와의 차이: +{closest_upper['stck_clpr'] - latest_price:,.2f}원 (+{(closest_upper['stck_clpr'] - latest_price) / latest_price * 100:.2f}%)")
            print(f"  - 거래량: {int(closest_upper['acml_vol']):,}주")
            print(f"  - 거래량 순위: 상위 {100 - int(combined_df['acml_vol'].rank(pct=True).loc[closest_upper.name] * 100):.0f}%")

            # 상방에서 거래량 가장 많았던 날
            max_vol_upper = upper_high_vol.loc[upper_high_vol['acml_vol'].idxmax()]
            print(f"\n  [상방 거래량 최대]")
            print(f"  - 일자: {max_vol_upper['stck_bsop_date']}")
            print(f"  - 종가: {max_vol_upper['stck_clpr']:,.0f}원 (+{(max_vol_upper['stck_clpr'] - latest_price) / latest_price * 100:.2f}%)")
            print(f"  - 거래량: {int(max_vol_upper['acml_vol']):,}주")
        else:
            print(f"\n[상방 거래량 상위]")
            print(f"  - 현재가보다 높은 가격대에서 거래량 상위 데이터가 없습니다.")

        # 3-2. 하방(현재가보다 낮은 가격대)에서 거래량 많이 터진 날
        lower_high_vol = high_volume_df[high_volume_df['price_direction'] < 0].copy()
        if not lower_high_vol.empty:
            # 하방 중 가장 가까운 날
            closest_lower = lower_high_vol.loc[lower_high_vol['price_diff'].idxmin()]

            print(f"\n[하방 거래량 상위 중 현재가와 가장 가까운 날]")
            print(f"  - 일자: {closest_lower['stck_bsop_date']}")
            print(f"  - 종가: {closest_lower['stck_clpr']:,.0f}원")
            print(f"  - 현재가와의 차이: {closest_lower['stck_clpr'] - latest_price:,.2f}원 ({(closest_lower['stck_clpr'] - latest_price) / latest_price * 100:.2f}%)")
            print(f"  - 거래량: {int(closest_lower['acml_vol']):,}주")
            print(f"  - 거래량 순위: 상위 {100 - int(combined_df['acml_vol'].rank(pct=True).loc[closest_lower.name] * 100):.0f}%")

            # 하방에서 거래량 가장 많았던 날
            max_vol_lower = lower_high_vol.loc[lower_high_vol['acml_vol'].idxmax()]
            print(f"\n  [하방 거래량 최대]")
            print(f"  - 일자: {max_vol_lower['stck_bsop_date']}")
            print(f"  - 종가: {max_vol_lower['stck_clpr']:,.0f}원 ({(max_vol_lower['stck_clpr'] - latest_price) / latest_price * 100:.2f}%)")
            print(f"  - 거래량: {int(max_vol_lower['acml_vol']):,}주")
        else:
            print(f"\n[하방 거래량 상위]")
            print(f"  - 현재가보다 낮은 가격대에서 거래량 상위 데이터가 없습니다.")
    else:
        logger.warning("거래량 상위 데이터를 찾을 수 없습니다.")

    # 현재 종가보다 낮은 이동평균선 중 가장 가까운 것
    latest_ma = combined_df.iloc[-1][['MA_5', 'MA_10', 'MA_60', 'MA_120']].dropna().astype(float)
    ma_diff = latest_price - latest_ma
    ma_diff = ma_diff[ma_diff >= 0]  # 하방만 (현재 종가가 MA보다 위에 있는 경우)

    if ma_diff.empty:
        print(f"\n[하방 이동평균선]")
        print(f"  - 현재 종가보다 낮은 이동평균선이 없습니다.")
    else:
        closest_ma_name = ma_diff.idxmin()
        closest_ma_value = latest_ma[closest_ma_name]

        print(f"\n[하방 이동평균선]")
        print(f"  - 이름: {closest_ma_name}")
        print(f"  - 가격: {closest_ma_value:,.2f}원")
        print(f"  - 현재가와 차이: {latest_price - closest_ma_value:,.2f}원 ({(latest_price - closest_ma_value) / closest_ma_value * 100:.2f}%)")



else:
    logger.warning("가져온 데이터가 없습니다.")