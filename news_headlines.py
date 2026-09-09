"""
네이버 뉴스 검색 오픈API로 종목 관련 최근 헤드라인 조회 (선택 기능).
config.py에 NAVER_CLIENT_ID/SECRET이 없으면 조용히 빈 리스트 반환 -> 스크리너 본기능에는 영향 없음.
"""

import re
import html
import requests
import settings

POSITIVE_WORDS = ["상승", "호실적", "역대 최대", "target 상향", "목표가 상향", "수주", "흑자",
                   "신고가", "급등", "호조", "확대", "성장", "매수", "협력", "계약 체결"]
NEGATIVE_WORDS = ["하락", "급락", "적자", "리콜", "소송", "감사의견", "횡령", "배임", "조사",
                   "제재", "감산", "부진", "목표가 하향", "매도", "우려", "위기"]


def _strip_tags(text: str) -> str:
    return html.unescape(re.sub(r"<.*?>", "", text))


def fetch_headlines(keyword: str, n: int = 3) -> list[dict]:
    if not settings.NAVER_CLIENT_ID or not settings.NAVER_CLIENT_SECRET:
        return []
    try:
        resp = requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            params={"query": keyword, "display": n, "sort": "date"},
            headers={
                "X-Naver-Client-Id": settings.NAVER_CLIENT_ID,
                "X-Naver-Client-Secret": settings.NAVER_CLIENT_SECRET,
            },
            timeout=5,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
    except Exception:
        return []

    headlines = []
    for item in items:
        title = _strip_tags(item.get("title", ""))
        headlines.append({"title": title, "link": item.get("link", ""), "sentiment": _tag_sentiment(title)})
    return headlines


def _tag_sentiment(title: str) -> str:
    """아주 단순한 키워드 매칭. 정교한 감성분석이 아니라 참고용 태그일 뿐."""
    pos = any(w in title for w in POSITIVE_WORDS)
    neg = any(w in title for w in NEGATIVE_WORDS)
    if pos and not neg:
        return "+"
    if neg and not pos:
        return "-"
    return "="
