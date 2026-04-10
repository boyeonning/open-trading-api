"""텔레그램 주식 봇 예외 클래스"""


class StockAnalysisError(Exception):
    """주식 분석 관련 기본 예외"""
    pass


class DataFetchError(StockAnalysisError):
    """데이터 조회 실패 예외"""
    
    def __init__(self, symbol: str, message: str = None):
        self.symbol = symbol
        if message is None:
            message = f"종목 '{symbol}'의 데이터를 가져오는데 실패했습니다."
        super().__init__(message)


class StockNotFoundError(StockAnalysisError):
    """종목 검색 실패 예외"""
    
    def __init__(self, symbol: str, message: str = None):
        self.symbol = symbol
        if message is None:
            message = f"종목 '{symbol}'을 찾을 수 없습니다."
        super().__init__(message)


class InvalidInputError(StockAnalysisError):
    """잘못된 입력 형식 예외"""
    
    def __init__(self, input_value: str, expected_format: str = None):
        self.input_value = input_value
        self.expected_format = expected_format
        if expected_format:
            message = f"입력값 '{input_value}'이 올바르지 않습니다. 예상 형식: {expected_format}"
        else:
            message = f"입력값 '{input_value}'이 올바르지 않습니다."
        super().__init__(message)


class InsufficientDataError(StockAnalysisError):
    """분석할 데이터 부족 예외"""
    
    def __init__(self, symbol: str, required_days: int, actual_days: int):
        self.symbol = symbol
        self.required_days = required_days
        self.actual_days = actual_days
        message = f"종목 '{symbol}'의 데이터가 부족합니다 (필요: {required_days}일, 실제: {actual_days}일)"
        super().__init__(message)


class APIError(StockAnalysisError):
    """외부 API 호출 오류 예외"""
    
    def __init__(self, api_name: str, error_code: str = None, message: str = None):
        self.api_name = api_name
        self.error_code = error_code
        if message is None:
            if error_code:
                message = f"{api_name} API 호출 실패 (오류코드: {error_code})"
            else:
                message = f"{api_name} API 호출 실패"
        super().__init__(message)


class DataValidationError(StockAnalysisError):
    """데이터 검증 실패 예외"""
    
    def __init__(self, field_name: str, reason: str):
        self.field_name = field_name
        self.reason = reason
        message = f"데이터 검증 실패 - {field_name}: {reason}"
        super().__init__(message)


class AuthenticationError(StockAnalysisError):
    """인증 실패 예외"""
    
    def __init__(self, message: str = "KIS API 인증에 실패했습니다."):
        super().__init__(message)


class RateLimitError(StockAnalysisError):
    """API 호출 제한 초과 예외"""
    
    def __init__(self, retry_after: int = None):
        self.retry_after = retry_after
        if retry_after:
            message = f"API 호출 제한 초과. {retry_after}초 후 다시 시도하세요."
        else:
            message = "API 호출 제한 초과. 잠시 후 다시 시도하세요."
        super().__init__(message)


class ConfigurationError(StockAnalysisError):
    """설정 오류 예외"""
    
    def __init__(self, config_name: str, message: str = None):
        self.config_name = config_name
        if message is None:
            message = f"설정 오류: {config_name}"
        super().__init__(message)