"""
picks_log.csv에 기록된 종목 중 5거래일이 지난 것들의 실제 수익률을 계산해서
텔레그램으로 주간 결과 리포트 전송. 매주 금요일 장 마감 후 실행.

사용 예:
    python weekly_report.py
"""

import sys
import numpy as np
import pandas as pd

from market_data import fetch_all
from picks_log import load_log, save_log
from telegram_alert import send_telegram_message

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

HORIZON = 5  # 거래일


def evaluate(log: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    pending = log[log["reported"] == False].copy()
    if pending.empty:
        return pending, log

    codes = pending["code"].unique().tolist()
    earliest = pending["pick_date"].min()
    print(f"{len(codes)}개 종목 가격 데이터 조회 중 (기준일: {earliest} 이후)...")
    data = fetch_all(codes, start=str(earliest))

    results = []
    for idx, row in pending.iterrows():
        code = row["code"]
        df = data.get(code)
        if df is None:
            continue
        pick_date = pd.Timestamp(row["pick_date"])
        if pick_date not in df.index:
            # 상장폐지/거래정지 등으로 해당일 데이터가 없는 경우 스킵 (다음 주에 재시도)
            continue
        pos = df.index.get_loc(pick_date)
        if pos + HORIZON >= len(df):
            continue  # 아직 5거래일이 안 지남 -> 다음 주에 평가

        forward_price = df["Close"].iloc[pos + HORIZON]
        ret = (forward_price / row["price"] - 1) * 100
        results.append({**row.to_dict(), "forward_price": forward_price, "return_pct": ret})
        log.loc[idx, "reported"] = True

    return pd.DataFrame(results), log


def format_report(evaluated: pd.DataFrame) -> str:
    from datetime import datetime
    lines = [f"<b>주간 스윙 픽 결과 리포트 ({datetime.now().strftime('%Y-%m-%d')})</b>"]
    lines.append(f"※ 픽 시점 대비 {HORIZON}거래일 후 종가 기준 수익률\n")

    if evaluated.empty:
        lines.append("이번 주에 5거래일이 경과해 평가 가능한 픽이 없습니다.")
        return "\n".join(lines)

    for category in ["돌파", "반등"]:
        sub = evaluated[evaluated["category"] == category]
        if sub.empty:
            continue
        mean_ret = sub["return_pct"].mean()
        win_rate = (sub["return_pct"] > 0).mean() * 100
        lines.append(f"<b>[{category}]</b> {len(sub)}건 | 평균 {mean_ret:+.2f}% | 승률 {win_rate:.0f}%")
        for _, r in sub.sort_values("return_pct", ascending=False).iterrows():
            lines.append(f"  {r['pick_date']} {r['name']}({r['code']}) {r['return_pct']:+.2f}%")
        lines.append("")

    overall_mean = evaluated["return_pct"].mean()
    overall_win = (evaluated["return_pct"] > 0).mean() * 100
    lines.append(f"<b>전체 평균: {overall_mean:+.2f}% | 승률 {overall_win:.0f}% (표본 {len(evaluated)}건)</b>")
    lines.append(f"\n※ 참고: 과거 4개 시대 백테스트 기준 돌파 신호 10일후 평균은 +2.50%였습니다. 표본이 적을수록 결과가 들쭉날쭉할 수 있습니다.")

    return "\n".join(lines)


def main():
    log = load_log()
    if log.empty:
        print("picks_log.csv가 비어있습니다. 스크리너가 먼저 며칠 실행되어야 합니다.")
        send_telegram_message("주간 리포트: 아직 기록된 픽이 없습니다. 스크리너가 평일마다 계속 실행되면 다음 주부터 결과가 쌓입니다.")
        return

    evaluated, updated_log = evaluate(log)
    message = format_report(evaluated)

    print("\n" + message + "\n")
    send_telegram_message(message)

    save_log(updated_log)
    print(f"로그 업데이트 완료 ({len(evaluated)}건 평가 완료 처리)")


if __name__ == "__main__":
    main()
