"""
스윙 스크리너의 "돌파"/"반등" 신호가 과거에 실제로 통했는지 검증.

신호가 뜬 날짜 이후 N거래일 뒤 수익률을 계산해서,
- 아무 날짜에나 샀을 때(기준선)와 비교
- 여러 시대(구간)로 나눠서 특정 시기에만 통했던 건 아닌지 확인

사용 예:
    python validate_screener.py
"""

import sys
import numpy as np
import pandas as pd

from market_data import get_universe, fetch_all
from swing_indicators import compute_indicators
from optimize_ma import split_periods

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

HORIZONS = [5, 10, 20]
N_PERIODS = 4


def find_signal_masks(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    breakout = (
        (df["Pct_from_52w_high"] > -3) & (df["BB_percent"] > 1.0)
        & (df["Volume_ratio"] > 2.0) & (df["MACD_hist"] > 0)
    )
    bounce = (df["RSI"] < 32) & (df["BB_percent"] < 0.15) & (df["Volume_ratio"] > 0.8)
    return breakout.fillna(False), bounce.fillna(False)


def collect_forward_returns(df: pd.DataFrame, mask: pd.Series) -> dict[int, list[float]]:
    out = {h: [] for h in HORIZONS}
    close = df["Close"]
    idx_positions = np.where(mask.values)[0]
    for pos in idx_positions:
        for h in HORIZONS:
            if pos + h < len(close):
                ret = close.iloc[pos + h] / close.iloc[pos] - 1
                out[h].append(ret * 100)
    return out


def main():
    top_n = 300
    print(f"시가총액 상위 {top_n}개 종목 리스트업 중...")
    universe = get_universe(top_n)
    print("데이터 로딩 중 (전체 히스토리)...")
    data = fetch_all(universe["Code"].tolist(), start="2011-01-01")
    print(f"{len(data)}개 종목 로딩 완료")

    sample_df = next(iter(data.values()))
    periods_meta = split_periods(sample_df, N_PERIODS)
    period_labels = [f"{p.index[0].date()}~{p.index[-1].date()}" for p in periods_meta]
    print("시대 구간: " + " | ".join(period_labels))

    # 전체 구간 집계용
    breakout_returns = {h: [] for h in HORIZONS}
    bounce_returns = {h: [] for h in HORIZONS}
    baseline_returns = {h: [] for h in HORIZONS}

    # 구간별 집계용 (기간 인덱스 -> 신호유형 -> horizon -> list)
    period_stats = {p: {"돌파": {h: [] for h in HORIZONS}, "반등": {h: [] for h in HORIZONS},
                         "기준선": {h: [] for h in HORIZONS}} for p in range(N_PERIODS)}

    n_stocks_done = 0
    for code, df in data.items():
        ind = compute_indicators(df)
        breakout_mask, bounce_mask = find_signal_masks(ind)

        close = ind["Close"]
        valid_mask = ind["RSI"].notna() & ind["BB_percent"].notna() & ind["Volume_ratio"].notna()

        br = collect_forward_returns(ind, breakout_mask)
        bo = collect_forward_returns(ind, bounce_mask)
        base = collect_forward_returns(ind, valid_mask)  # 지표 계산 가능한 모든 날 = 기준선

        for h in HORIZONS:
            breakout_returns[h].extend(br[h])
            bounce_returns[h].extend(bo[h])
            baseline_returns[h].extend(base[h])

        # 구간별 분류: 각 신호 발생일이 몇 번째 구간에 속하는지로 나눔
        edges = np.linspace(0, len(ind), N_PERIODS + 1).astype(int)
        for p in range(N_PERIODS):
            lo, hi = edges[p], edges[p + 1]
            sub_idx = ind.index[lo:hi]
            for sig_name, mask in [("돌파", breakout_mask), ("반등", bounce_mask), ("기준선", valid_mask)]:
                sub_mask = mask.loc[sub_idx]
                sub_returns = collect_forward_returns(ind.loc[sub_idx], sub_mask)
                for h in HORIZONS:
                    period_stats[p][sig_name][h].extend(sub_returns[h])

        n_stocks_done += 1

    print(f"\n=== 전체 구간(2014~현재) 신호별 향후 수익률 ===")
    print(f"{'유형':6s} {'표본수':>8s}", end="")
    for h in HORIZONS:
        print(f"  {h}일후평균  {h}일후승률", end="")
    print()

    for name, returns in [("돌파", breakout_returns), ("반등", bounce_returns), ("기준선(전체)", baseline_returns)]:
        n = len(returns[HORIZONS[0]])
        print(f"{name:10s} {n:>8d}", end="")
        for h in HORIZONS:
            arr = np.array(returns[h])
            mean = arr.mean() if len(arr) else float("nan")
            winrate = (arr > 0).mean() * 100 if len(arr) else float("nan")
            print(f"  {mean:+7.2f}%  {winrate:6.1f}%", end="")
        print()

    print(f"\n=== 구간별(시대별) 신호 평균 수익률 비교 (10일 기준) ===")
    print(f"{'구간':30s} {'돌파(표본)':>14s} {'반등(표본)':>14s} {'기준선':>10s}")
    for p in range(N_PERIODS):
        row = period_stats[p]
        def fmt(sig):
            arr = np.array(row[sig][10])
            if len(arr) == 0:
                return "표본없음"
            return f"{arr.mean():+.2f}%({len(arr)})"
        print(f"{period_labels[p]:30s} {fmt('돌파'):>14s} {fmt('반등'):>14s} {fmt('기준선'):>10s}")


if __name__ == "__main__":
    main()
