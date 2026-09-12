"""
Minervini Trend Template 스크리닝 조건의 과거 검증.
RS(상대강도)는 유니버스 전체 종목의 252일 수익률 횡단면 순위로 매일 계산.
신호 발생일 이후 5/10/20거래일 수익률을 기준선(아무 날에나 매수)과 비교, 4개 시대로 나눠서 확인.

사용 예:
    python validate_trend_template.py
"""

import sys
import numpy as np
import pandas as pd

from market_data import get_universe, fetch_all
from trend_template import compute_trend_template_fields
from optimize_ma import split_periods

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

HORIZONS = [5, 10, 20]
N_PERIODS = 4
MIN_CONDITIONS_OPTIONS = [6, 7, 8]  # RS>=70 포함 8개 중 몇 개 이상 만족해야 신호로 볼지


def main():
    top_n = 300
    print(f"시가총액 상위 {top_n}개 종목 리스트업 중...")
    universe = get_universe(top_n)
    print("데이터 로딩 중 (전체 히스토리)...")
    data = fetch_all(universe["Code"].tolist(), start="2011-01-01")
    print(f"{len(data)}개 종목 로딩 완료")

    # 1) 종목별 지표 계산
    indicators = {code: compute_trend_template_fields(df) for code, df in data.items()}

    # 2) RS 백분위: 전체 종목의 252일 수익률을 날짜별로 횡단면 순위 매기기
    returns_wide = pd.DataFrame({code: ind["Return_252d"] for code, ind in indicators.items()})
    rs_percentile_wide = returns_wide.rank(axis=1, pct=True) * 100

    sample_df = next(iter(data.values()))
    periods_meta = split_periods(sample_df, N_PERIODS)
    period_labels = [f"{p.index[0].date()}~{p.index[-1].date()}" for p in periods_meta]
    print("시대 구간: " + " | ".join(period_labels))
    edges = np.linspace(0, len(sample_df), N_PERIODS + 1).astype(int)
    period_boundaries = [(sample_df.index[edges[i]], sample_df.index[min(edges[i + 1], len(sample_df) - 1)])
                          for i in range(N_PERIODS)]

    for min_cond in MIN_CONDITIONS_OPTIONS:
        print(f"\n{'=' * 60}\n조건 {min_cond}/8 이상 만족 기준\n{'=' * 60}")

        signal_returns = {h: [] for h in HORIZONS}
        baseline_returns = {h: [] for h in HORIZONS}
        period_stats = {p: {"signal": {h: [] for h in HORIZONS}, "baseline": {h: [] for h in HORIZONS}}
                         for p in range(N_PERIODS)}
        n_signals = 0

        for code, ind in indicators.items():
            close = ind["Close"]
            valid = ind["MA200"].notna() & ind["MA200_1m_ago"].notna()

            cond1 = (close > ind["MA150"]) & (close > ind["MA200"])
            cond2 = ind["MA150"] > ind["MA200"]
            cond3 = ind["MA200"] > ind["MA200_1m_ago"]
            cond4 = (ind["MA50"] > ind["MA150"]) & (ind["MA150"] > ind["MA200"])
            cond5 = close > ind["MA50"]
            cond6 = close >= ind["Low_52w"] * 1.25
            cond7 = close >= ind["High_52w"] * 0.75

            rs = rs_percentile_wide[code].reindex(ind.index)
            cond8 = rs >= 70

            n_passed = (cond1.astype(int) + cond2.astype(int) + cond3.astype(int) + cond4.astype(int)
                        + cond5.astype(int) + cond6.astype(int) + cond7.astype(int) + cond8.fillna(False).astype(int))
            signal_mask = valid & (n_passed >= min_cond)
            signal_mask = signal_mask.fillna(False)

            n_signals += int(signal_mask.sum())
            close_vals = close.values
            idx_positions = np.where(signal_mask.values)[0]
            valid_positions = np.where(valid.fillna(False).values)[0]

            for pos in idx_positions:
                for h in HORIZONS:
                    if pos + h < len(close_vals):
                        ret = (close_vals[pos + h] / close_vals[pos] - 1) * 100
                        signal_returns[h].append(ret)
                        for p, (start, end) in enumerate(period_boundaries):
                            if start <= ind.index[pos] <= end:
                                period_stats[p]["signal"][h].append(ret)
                                break

            for pos in valid_positions:
                for h in HORIZONS:
                    if pos + h < len(close_vals):
                        ret = (close_vals[pos + h] / close_vals[pos] - 1) * 100
                        baseline_returns[h].append(ret)
                        for p, (start, end) in enumerate(period_boundaries):
                            if start <= ind.index[pos] <= end:
                                period_stats[p]["baseline"][h].append(ret)
                                break

        print(f"신호 표본수: {n_signals}건")
        print(f"{'구간':6s}  {'표본':>6s}", end="")
        for h in HORIZONS:
            print(f"  {h}일후 신호평균  {h}일후 기준선  {h}일후 승률", end="")
        print()

        for h in HORIZONS:
            sig = np.array(signal_returns[h])
            base = np.array(baseline_returns[h])
            sig_mean = sig.mean() if len(sig) else float("nan")
            base_mean = base.mean() if len(base) else float("nan")
            win = (sig > 0).mean() * 100 if len(sig) else float("nan")
            print(f"[전체] {h}일후: 신호 {sig_mean:+.2f}% vs 기준선 {base_mean:+.2f}% (승률 {win:.1f}%, 표본 {len(sig)})")

        print(f"\n--- 시대별 (10일 기준) ---")
        for p in range(N_PERIODS):
            sig = np.array(period_stats[p]["signal"][10])
            base = np.array(period_stats[p]["baseline"][10])
            sig_mean = sig.mean() if len(sig) else float("nan")
            base_mean = base.mean() if len(base) else float("nan")
            print(f"{period_labels[p]:30s} 신호 {sig_mean:+6.2f}%(n={len(sig):5d})  vs  기준선 {base_mean:+6.2f}%")


if __name__ == "__main__":
    main()
