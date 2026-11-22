import re
from datetime import date, datetime

PIN_LENGTH = 6


def parse_birth_date(raw: str) -> str:
    """'19850312' 또는 '1985-03-12' 같은 입력을 'YYYYMMDD'로 정리한다.

    실제로 없는 날짜거나 범위를 벗어나면 ValueError.
    """
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) != 8:
        raise ValueError("생년월일은 8자리 숫자로 입력해 주세요 (예: 19850312).")
    try:
        parsed = datetime.strptime(digits, "%Y%m%d").date()
    except ValueError:
        raise ValueError("없는 날짜예요. 생년월일을 다시 확인해 주세요.") from None
    if parsed.year < 1850 or parsed > date.today():
        raise ValueError("생년월일 범위를 확인해 주세요.")
    return digits


def format_birth_date(value: str | None) -> str:
    if not value:
        return "모름"
    return f"{value[:4]}.{value[4:6]}.{value[6:]}"


def parse_phone(raw: str) -> str | None:
    """비어 있으면 None. 숫자만 남겨 010-1234-5678 형태로 저장한다."""
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return None
    if not re.fullmatch(r"0\d{8,10}", digits):
        raise ValueError("전화번호를 다시 확인해 주세요 (예: 010-1234-5678).")
    if len(digits) == 11:
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    if digits.startswith("02"):
        return f"02-{digits[2:-4]}-{digits[-4:]}"
    return f"{digits[:3]}-{digits[3:-4]}-{digits[-4:]}"


def validate_pin(pin: str) -> str | None:
    """문제가 있으면 오류 메시지, 괜찮으면 None."""
    if not re.fullmatch(rf"\d{{{PIN_LENGTH}}}", pin or ""):
        return f"PIN은 숫자 {PIN_LENGTH}자리로 입력해 주세요."
    return None
