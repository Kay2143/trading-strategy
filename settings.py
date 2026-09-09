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
