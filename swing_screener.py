"""
코스피/코스닥 스윙 트레이딩 후보 스크리너 + 텔레그램 알림.

매일 장 마감 후 실행 -> 시가총액 상위 종목들을 대상으로
"상승 돌파"(52주 신고가 근접 + 볼린저 상단 돌파 + 거래량 급증)와
"과매도 반등"(RSI 과매도 + 볼린저 하단 근접) 후보를 찾아 텔레그램으로 전송.

사용 예:
    python swing_screener.py
    python swing_screener.py --top-n 300 --max-alerts 8
"""

import argparse
import sys
import time

from datetime import date

import pandas as pd

from market_data import get_universe, fetch_all
from swing_indicators import compute_indicators, classify_signal
from trend_template import compute_trend_template_fields, check_trend_template
from news_headlines import fetch_headlines
from telegram_alert import send_telegram_message
from picks_log import log_picks, already_logged

TREND_TEMPLATE_MIN_CONDITIONS = 8  # 8개 중 8개 (검증됨: 4개 시대 중 3개에서 기준선 대비 약 2배 수익률)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def screen(top_n: int, start: str, max_alerts: int) -> dict:
    print(f"시가총액 상위 {top_n}개 종목 리스트업 중...")
    universe = get_universe(top_n)
    print(f"{len(universe)}개 종목 데이터 수집 중 (병렬)...")

    t0 = time.time()
    data = fetch_all(universe["Code"].tolist(), start=start)
    print(f"{len(data)}개 종목 수집 완료 ({time.time()-t0:.1f}초)")

    name_map = dict(zip(universe["Code"], universe["Name"]))
    candidates = {"돌파": [], "반등": [], "추세템플릿": []}

    # RS(상대강도) 백분위 계산을 위해 전체 종목의 252일 수익률을 먼저 계산 (유니버스 내 상대 순위)
    trend_fields = {}
    returns_252d = {}
    for code, df in data.items():
        if len(df) < 60:
            continue
        trend_fields[code] = compute_trend_template_fields(df)
        returns_252d[code] = trend_fields[code]["Return_252d"].iloc[-1]

    rs_percentiles = (pd.Series(returns_252d).rank(pct=True) * 100).to_dict()

    for code, df in data.items():
        if len(df) < 60:
            continue
        ind = compute_indicators(df)
        latest = ind.iloc[-1]
        signal = classify_signal(latest)
        if signal is not None:
            candidates[signal].append({
                "code": code, "name": name_map.get(code, code),
                "price": latest["Close"], "change_1d": latest["Change_1d"],
                "rsi": latest["RSI"], "bb_percent": latest["BB_percent"],
                "vol_ratio": latest["Volume_ratio"], "pct_from_high": latest["Pct_from_52w_high"],
            })

        tt_row = trend_fields[code].iloc[-1]
        if pd.notna(tt_row.get("MA200")):
            checks = check_trend_template(tt_row)
            rs = rs_percentiles.get(code, float("nan"))
            checks["RS백분위>=70"] = bool(pd.notna(rs) and rs >= 70)
            n_passed = sum(checks.values())
            if n_passed >= TREND_TEMPLATE_MIN_CONDITIONS:
                candidates["추세템플릿"].append({
                    "code": code, "name": name_map.get(code, code),
                    "price": tt_row["Close"], "change_1d": (tt_row["Close"] / df["Close"].iloc[-2] - 1) * 100,
                    "rs_percentile": rs, "n_passed": n_passed,
                })

    candidates["돌파"] = sorted(candidates["돌파"], key=lambda x: x["vol_ratio"], reverse=True)[:max_alerts]
    candidates["반등"] = sorted(candidates["반등"], key=lambda x: x["rsi"])[:max_alerts]
    candidates["추세템플릿"] = sorted(candidates["추세템플릿"], key=lambda x: x["rs_percentile"], reverse=True)[:max_alerts]
    return candidates


def format_message(candidates: dict, with_news: bool) -> str:
    from datetime import datetime
    lines = [f"<b>스윙 스크리닝 결과 {datetime.now().strftime('%Y-%m-%d')}</b>\n"]

    if not candidates["돌파"] and not candidates["반등"] and not candidates["추세템플릿"]:
        lines.append("오늘은 조건에 맞는 후보가 없습니다.")
        return "\n".join(lines)

    if candidates["추세템플릿"]:
        lines.append("<b>[추세템플릿 후보]</b> Minervini Trend Template 8개 조건 전부 충족 "
                      "(검증됨: 10일후 평균 +1.5% vs 기준선 +0.8%, 4개 시대 중 3개에서 우위. "
                      "RS는 자체 유니버스 내 상대 백분위로 근사 계산한 값)")
        for c in candidates["추세템플릿"]:
            lines.append(
                f"• {c['name']}({c['code']}) {c['price']:,.0f}원 "
                f"({c['change_1d']:+.1f}%) RS백분위 {c['rs_percentile']:.0f}"
            )
            if with_news:
                for h in fetch_headlines(c["name"], n=2):
                    lines.append(f"   [{h['sentiment']}] {h['title']}")
        lines.append("")

    if candidates["돌파"]:
        lines.append("<b>[상승 돌파 후보]</b> 신고가 근접 + 거래량 급증 (검증됨: 10일후 평균 +2.5%, 4개 시대 전부 기준선 상회)")
        for c in candidates["돌파"]:
            lines.append(
                f"• {c['name']}({c['code']}) {c['price']:,.0f}원 "
                f"({c['change_1d']:+.1f}%) 거래량 {c['vol_ratio']:.1f}배 "
                f"고점대비 {c['pct_from_high']:.1f}%"
            )
            if with_news:
                for h in fetch_headlines(c["name"], n=2):
                    lines.append(f"   [{h['sentiment']}] {h['title']}")
        lines.append("")

    if candidates["반등"]:
        lines.append("<b>[과매도 반등 후보 - 참고용]</b> RSI 과매도 + 볼린저 하단 (근거 약함: 시대별 편차 크고 일부 구간 무효과)")
        for c in candidates["반등"]:
            lines.append(
                f"• {c['name']}({c['code']}) {c['price']:,.0f}원 "
                f"({c['change_1d']:+.1f}%) RSI {c['rsi']:.0f}"
            )
            if with_news:
                for h in fetch_headlines(c["name"], n=2):
                    lines.append(f"   [{h['sentiment']}] {h['title']}")

    lines.append("\n※ 참고용 스크리닝 결과이며 매매 조언이 아닙니다. 매수/매도 판단과 책임은 본인에게 있습니다.")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="스윙 트레이딩 스크리너")
    parser.add_argument("--top-n", type=int, default=300, help="시가총액 상위 몇 개 종목을 스캔할지")
    parser.add_argument("--start", default="2024-01-01", help="지표 계산용 데이터 시작일")
    parser.add_argument("--max-alerts", type=int, default=8, help="카테고리별 최대 알림 종목 수")
    parser.add_argument("--no-news", action="store_true", help="뉴스 조회 건너뛰기")
    parser.add_argument("--dry-run", action="store_true", help="테스트용: 로그 기록/텔레그램 전송 없이 결과만 출력")
    parser.add_argument("--force", action="store_true", help="오늘 이미 실행됐어도 강제로 다시 전송 (수동 재실행용)")
    args = parser.parse_args()

    if not args.dry_run and not args.force and already_logged(date.today()):
        print("오늘은 이미 스크리닝이 실행되어 알림이 발송됐습니다. 중복 전송 방지를 위해 건너뜁니다.")
        print("(강제로 다시 보내려면 --force 옵션 사용)")
        return

    candidates = screen(args.top_n, args.start, args.max_alerts)
    message = format_message(candidates, with_news=not args.no_news)

    print("\n" + message + "\n")

    if args.dry_run:
        print("[dry-run] 로그 기록 및 텔레그램 전송 생략됨")
        return

    n_logged = log_picks(candidates, date.today())
    print(f"픽 기록: {n_logged}건 저장 (picks_log.csv)")
    send_telegram_message(message)


if __name__ == "__main__":
    main()
