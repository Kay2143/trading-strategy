"""
스크리닝 후보를 '실제로 무엇을 할지'로 바꿔주는 매매 계획 계산.

- 손절가: 2×ATR(14) 아래, 단 진입가 대비 최대 -8% (Minervini 손절 원칙)
- 목표가: 손절폭의 2배 (손익비 2:1)
- 보유기간: 최대 10거래일 (validate_screener / validate_trend_template 검증 기간)
- 수량: 계좌 대비 1회 손실 한도(RISK_PCT)로 역산, 한 종목 최대 비중 MAX_POSITION_PCT

손절/목표 규칙 자체는 백테스트로 검증된 값이 아니라 일반적인 리스크 관리 원칙임.
"""

import pandas as pd

ATR_WINDOW = 14
ATR_MULT = 2.0
MAX_STOP_PCT = 8.0
REWARD_RISK = 2.0
MAX_HOLD_DAYS = 10
MAX_POSITION_PCT = 25.0


def compute_atr(df: pd.DataFrame, window: int = ATR_WINDOW) -> pd.Series:
    prev_close = df["Close"].shift(1)
    true_range = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return true_range.rolling(window).mean()


def make_plan(df: pd.DataFrame, account_size: float = 0, risk_pct: float = 1.0,
              size_mult: float = 1.0) -> dict:
    entry = float(df["Close"].iloc[-1])
    atr = compute_atr(df).iloc[-1]

    stop = entry * (1 - MAX_STOP_PCT / 100)
    if pd.notna(atr) and atr > 0:
        stop = max(stop, entry - ATR_MULT * atr)  # 둘 중 더 가까운(덜 잃는) 손절선
    risk_per_share = entry - stop
    target = entry + REWARD_RISK * risk_per_share

    plan = {
        "entry": entry, "stop": stop, "target": target,
        "stop_pct": (stop / entry - 1) * 100, "target_pct": (target / entry - 1) * 100,
        "shares": None, "amount": None,
    }

    if account_size > 0 and risk_per_share > 0:
        by_risk = account_size * risk_pct / 100 * size_mult / risk_per_share
        by_cap = account_size * MAX_POSITION_PCT / 100 / entry
        shares = int(min(by_risk, by_cap))
        plan["shares"] = shares
        plan["amount"] = shares * entry
    return plan
