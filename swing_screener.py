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

from market_data import get_universe, fetch_all, get_market_regime
from swing_indicators import compute_indicators, classify_signal
from trend_template import compute_trend_template_fields, check_trend_template
from news_headlines import fetch_headlines
from telegram_alert import send_telegram_message
from picks_log import log_picks, already_logged, recently_alerted
from trade_plan import make_plan, MAX_HOLD_DAYS
import settings

MAX_ACTION_PICKS = 3  # 메시지 맨 위에 매매 계획까지 보여줄 종목 수
WEAK_MARKET_SIZE_MULT = 0.5  # 코스피가 200일선 아래일 때 제안 수량 축소 배율
TREND_TEMPLATE_MIN_CONDITIONS = 8  # 8개 중 8개 (검증됨: 4개 시대 중 3개에서 기준선 대비 약 2배 수익률)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def screen(top_n: int, start: str, max_alerts: int) -> tuple[dict, dict]:
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
    return candidates, data


def build_action_list(candidates: dict, data: dict, recent_codes: set[str], market: dict | None) -> dict:
    """돌파/추세템플릿 후보를 한 줄로 세워 '오늘 볼 종목'(매매 계획 포함)과 나머지로 나눔.
    순서: 두 조건 동시 충족 > 돌파(거래량 배수 순, 검증 근거 가장 강함) > 추세템플릿(RS 순).
    최근 7일 안에 이미 알림이 나간 종목은 새 정보가 아니므로 '조건 유지'로 따로 모음."""
    breakout_codes = {c["code"] for c in candidates["돌파"]}
    trend_codes = {c["code"] for c in candidates["추세템플릿"]}

    ordered, seen = [], set()
    for c in ([c for c in candidates["돌파"] if c["code"] in trend_codes]
              + candidates["돌파"] + candidates["추세템플릿"]):
        if c["code"] in seen:
            continue
        seen.add(c["code"])
        tags = [t for t, codes in (("돌파", breakout_codes), ("추세템플릿", trend_codes)) if c["code"] in codes]
        ordered.append({**c, "tags": tags})

    new = [c for c in ordered if c["code"] not in recent_codes]
    repeat = [c for c in ordered if c["code"] in recent_codes]

    size_mult = WEAK_MARKET_SIZE_MULT if market is not None and not market["strong"] else 1.0
    action = []
    for c in new[:MAX_ACTION_PICKS]:
        plan = make_plan(data[c["code"]], settings.ACCOUNT_SIZE, settings.RISK_PCT, size_mult)
        action.append({**c, "plan": plan})

    return {"action": action, "other_new": new[MAX_ACTION_PICKS:], "repeat": repeat,
            "bounce": candidates["반등"], "size_mult": size_mult}


def _names(items: list[dict]) -> str:
    return ", ".join(f"{c['name']}({c['code']})" for c in items)


def format_message(picks: dict, market: dict | None, with_news: bool) -> str:
    from datetime import datetime
    lines = [f"<b>스윙 스크리닝 {datetime.now().strftime('%Y-%m-%d')}</b>"]

    if market is None:
        lines.append("시장: 코스피 추세 조회 실패")
    elif market["strong"]:
        lines.append(f"시장: 코스피 {market['close']:,.0f} — 200일선 위 (추세추종 유리)")
    else:
        lines.append(f"⚠️ 시장: 코스피 {market['close']:,.0f} — 200일선 아래 (약세장). "
                     f"신규 매수는 보수적으로, 제안 수량 {picks['size_mult']:.0%}로 축소")
    lines.append("")

    if not picks["action"]:
        lines.append("<b>오늘 새로 볼 종목: 없음 → 관망</b>")
    else:
        lines.append(f"<b>🎯 오늘 새로 볼 종목</b> (다음 날 시가가 손절가보다 위일 때만 유효)")
        for i, c in enumerate(picks["action"], 1):
            p = c["plan"]
            lines.append(f"{i}. <b>{c['name']}</b>({c['code']}) [{'+'.join(c['tags'])}] "
                         f"{p['entry']:,.0f}원 ({c['change_1d']:+.1f}%)")
            lines.append(f"   손절 {p['stop']:,.0f} ({p['stop_pct']:+.1f}%) · "
                         f"목표 {p['target']:,.0f} ({p['target_pct']:+.1f}%) · 최대 {MAX_HOLD_DAYS}거래일 보유")
            if p["shares"]:
                lines.append(f"   수량 {p['shares']:,}주 (약 {p['amount'] / 10000:,.0f}만원, "
                             f"손절 시 계좌 -{settings.RISK_PCT * picks['size_mult']:.1f}%)")
            elif p["shares"] == 0:
                lines.append("   수량: 계좌 대비 가격이 높아 1주도 안 됨 → 건너뛰기")
            if with_news:
                for h in fetch_headlines(c["name"], n=2):
                    lines.append(f"   [{h['sentiment']}] {h['title']}")
    lines.append("")

    if picks["other_new"]:
        lines.append(f"그 외 신규 후보: {_names(picks['other_new'])}")
    if picks["repeat"]:
        lines.append(f"조건 유지 중(최근 알림 나감, 신규 진입 근거 약함): {_names(picks['repeat'])}")
    if picks["bounce"]:
        lines.append(f"반등 후보(근거 약함, 참고만): {_names(picks['bounce'])}")

    lines.append("\n규칙: 돌파 = 검증상 10일후 평균 +2.5%(4개 시대 모두 기준선 상회), "
                 "추세템플릿 = 10일후 평균 +1.5%. 손절/목표/수량은 리스크 관리 원칙이며 백테스트로 검증된 값은 아님.")
    lines.append("※ 참고용 스크리닝 결과이며 매매 조언이 아닙니다. 매수/매도 판단과 책임은 본인에게 있습니다.")
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

    candidates, data = screen(args.top_n, args.start, args.max_alerts)
    market = get_market_regime(args.start)
    picks = build_action_list(candidates, data, recently_alerted(date.today()), market)
    message = format_message(picks, market, with_news=not args.no_news)

    print("\n" + message + "\n")

    if args.dry_run:
        print("[dry-run] 로그 기록 및 텔레그램 전송 생략됨")
        return

    n_logged = log_picks(candidates, date.today())
    print(f"픽 기록: {n_logged}건 저장 (picks_log.csv)")
    send_telegram_message(message)


if __name__ == "__main__":
    main()
