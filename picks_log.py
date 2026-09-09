"""
스크리너가 매일 골라준 종목을 기록해두는 로그. weekly_report.py가 이 로그를 읽어서
5거래일 후 실제 수익률을 계산하는 데 사용.
"""

import os
import pandas as pd

LOG_PATH = os.path.join(os.path.dirname(__file__), "picks_log.csv")
COLUMNS = ["pick_date", "code", "name", "category", "price", "reported"]


def load_log() -> pd.DataFrame:
    if not os.path.exists(LOG_PATH):
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(LOG_PATH, dtype={"code": str})
    df["pick_date"] = pd.to_datetime(df["pick_date"]).dt.date
    return df


def save_log(df: pd.DataFrame):
    df.to_csv(LOG_PATH, index=False, encoding="utf-8-sig")


def already_logged(pick_date) -> bool:
    log = load_log()
    return not log.empty and (log["pick_date"] == pick_date).any()


def log_picks(candidates: dict, pick_date) -> int:
    """오늘 스크리닝 결과를 로그에 추가. 이미 같은 날짜에 기록된 게 있으면 중복 기록하지 않음."""
    log = load_log()
    if not log.empty and (log["pick_date"] == pick_date).any():
        return 0  # 같은 날 중복 실행 방지

    rows = []
    for category, items in candidates.items():
        for c in items:
            rows.append({
                "pick_date": pick_date, "code": c["code"], "name": c["name"],
                "category": category, "price": c["price"], "reported": False,
            })
    if not rows:
        return 0

    new_df = pd.DataFrame(rows)
    combined = pd.concat([log, new_df], ignore_index=True)
    save_log(combined)
    return len(rows)
