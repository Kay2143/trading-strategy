"""
이동평균 크로스오버 전략의 공통 로직 (데이터 로딩, 신호 계산, 백테스트, 통계).
ma_crossover_backtest.py와 optimize_ma.py가 공유해서 사용.
"""

import pandas as pd
import FinanceDataReader as fdr

_data_cache: dict[str, pd.DataFrame] = {}


def load_data(ticker: str, start: str, end: str | None) -> pd.DataFrame:
    key = f"{ticker}_{start}_{end}"
    if key in _data_cache:
        return _data_cache[key]
    df = fdr.DataReader(ticker, start, end)
    if df.empty:
        raise ValueError(f"데이터를 가져오지 못했습니다: ticker={ticker}")
    _data_cache[key] = df
    return df


def compute_signals(df: pd.DataFrame, short_window: int, long_window: int) -> pd.DataFrame:
    df = df.copy()
    df["MA_short"] = df["Close"].rolling(short_window).mean()
    df["MA_long"] = df["Close"].rolling(long_window).mean()

    # 골든크로스(1) / 데드크로스(-1) / 보유(0)
    df["position"] = 0
    df.loc[df["MA_short"] > df["MA_long"], "position"] = 1
    df["signal"] = df["position"].diff()  # 부호 변화로 매수/매도 시점 감지
    return df


def backtest(
    df: pd.DataFrame,
    initial_cash: float = 10_000_000,
    buy_fee_rate: float = 0.00015,   # 매수 수수료 약 0.015%
    sell_fee_rate: float = 0.00015,  # 매도 수수료 약 0.015%
    sell_tax_rate: float = 0.0018,   # 매도 증권거래세 약 0.18% (실제 세율은 수시로 변경되므로 확인 필요)
) -> tuple[pd.DataFrame, list[dict]]:
    cash = initial_cash
    shares = 0
    equity_curve = []
    trades = []

    for date, row in df.iterrows():
        price = row["Close"]
        signal = row["signal"]

        if pd.notna(signal) and signal > 0 and shares == 0:
            buy_shares = int(cash // (price * (1 + buy_fee_rate)))
            if buy_shares > 0:
                cost = buy_shares * price * (1 + buy_fee_rate)
                cash -= cost
                shares += buy_shares
                trades.append({"date": date, "type": "BUY", "price": price, "shares": buy_shares})

        elif pd.notna(signal) and signal < 0 and shares > 0:
            proceeds = shares * price * (1 - sell_fee_rate - sell_tax_rate)
            cash += proceeds
            trades.append({"date": date, "type": "SELL", "price": price, "shares": shares})
            shares = 0

        equity_curve.append(cash + shares * price)

    df = df.copy()
    df["equity"] = equity_curve
    return df, trades


def compute_stats(df: pd.DataFrame, initial_cash: float) -> dict:
    final_equity = df["equity"].iloc[-1]
    total_return = (final_equity / initial_cash - 1) * 100

    running_max = df["equity"].cummax()
    drawdown = (df["equity"] - running_max) / running_max
    mdd = drawdown.min() * 100

    buy_hold_return = (df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100

    n_years = (df.index[-1] - df.index[0]).days / 365.25
    cagr = ((final_equity / initial_cash) ** (1 / n_years) - 1) * 100 if n_years > 0 else float("nan")
    buy_hold_cagr = ((1 + buy_hold_return / 100) ** (1 / n_years) - 1) * 100 if n_years > 0 else float("nan")

    return {
        "총수익률(%)": round(total_return, 2),
        "CAGR(%)": round(cagr, 2),
        "MDD(%)": round(mdd, 2),
        "단순보유 수익률(%)": round(buy_hold_return, 2),
        "단순보유 CAGR(%)": round(buy_hold_cagr, 2),
        "최종 자산": round(final_equity),
    }


def run_backtest(df_raw: pd.DataFrame, short: int, long: int, initial_cash: float = 10_000_000) -> dict:
    """구간(df_raw)에 대해 신호 계산 + 백테스트 + 통계까지 한번에 수행."""
    df = compute_signals(df_raw, short, long)
    df, trades = backtest(df, initial_cash=initial_cash)
    stats = compute_stats(df, initial_cash)
    stats["매매횟수"] = len(trades)
    return stats


def compute_trend_signals(df: pd.DataFrame, window: int) -> pd.DataFrame:
    """단일 장기 추세선 필터: 종가가 이동평균선 위에 있으면 보유, 아래면 현금."""
    df = df.copy()
    df["MA_long"] = df["Close"].rolling(window).mean()
    df["MA_short"] = df["Close"]  # plot_result 재사용을 위한 별칭
    df["position"] = 0
    df.loc[df["Close"] > df["MA_long"], "position"] = 1
    df["signal"] = df["position"].diff()
    return df


def run_trend_backtest(df_raw: pd.DataFrame, window: int, initial_cash: float = 10_000_000) -> dict:
    df = compute_trend_signals(df_raw, window)
    df, trades = backtest(df, initial_cash=initial_cash)
    stats = compute_stats(df, initial_cash)
    stats["매매횟수"] = len(trades)
    return stats
