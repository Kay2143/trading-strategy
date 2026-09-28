"""
설정값 로더. 우선순위: 환경변수(클라우드/GitHub Actions) > config.py(로컬 전용, git에 안 올라감).
telegram_alert.py, news_headlines.py는 이 모듈을 통해 설정을 읽는다.
"""

import os

try:
    import config as _local_config
except ImportError:
    _local_config = None


def _get(key: str, default: str = "") -> str:
    val = os.environ.get(key)
    if val:
        return val
    if _local_config is not None:
        return getattr(_local_config, key, default)
    return default


TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _get("TELEGRAM_CHAT_ID")
NAVER_CLIENT_ID = _get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = _get("NAVER_CLIENT_SECRET")

# 매매 계획(수량 계산)용. ACCOUNT_SIZE가 0이면 수량은 표시하지 않고 손절/목표가만 표시.
ACCOUNT_SIZE = float(_get("ACCOUNT_SIZE", "0") or 0)  # 투자 계좌 금액(원)
RISK_PCT = float(_get("RISK_PCT", "1.0") or 1.0)  # 한 종목 손절 시 계좌 대비 최대 손실(%)
