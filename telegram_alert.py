"""
텔레그램으로 메시지 전송. config.py에 토큰/chat_id 설정 필요.
"""

import requests
import settings


def send_telegram_message(text: str) -> bool:
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        print("[텔레그램 미설정] config.py 또는 환경변수에 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID를 설정하세요. 아래는 전송될 내용입니다:\n")
        print(text)
        return False

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    # 텔레그램 메시지는 4096자 제한 -> 넘으면 잘라서 여러 번 전송
    chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)] or [text]

    ok = True
    for chunk in chunks:
        resp = requests.post(url, data={
            "chat_id": settings.TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })
        if resp.status_code != 200:
            print(f"텔레그램 전송 실패: {resp.status_code} {resp.text}")
            ok = False
    return ok
