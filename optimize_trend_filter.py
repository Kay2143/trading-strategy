"""
장기 추세선(단일 이동평균) 필터 전략 백테스트: 종가가 N일선 위 -> 보유, 아래 -> 현금.
개별 종목 크로스오버 전략이 단순보유를 못 이긴 결과를 보고, 잦은 매매 대신
큰 하락만 피하는 이 방식이 더 견고한지 같은 방식(여러 종목 x 여러 시대)으로 검증.
지수(KOSPI) 자체도 함께 비교.

사용 예:
    python optimize_trend_filter.py
"""

import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib

from strategy_lib import load_data, run_trend_backtest
from optimize_ma import split_periods, DEFAULT_TICKERS

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False

TARGETS = {**DEFAULT_TICKERS, "KS11": "코스피지수"}
WINDOWS = [100, 150, 200, 250]
N_PERIODS = 4
CASH = 10_000_000


def main():
    print(f"대상: {', '.join(f'{n}({c})' for c, n in TARGETS.items())}")
    print("데이터 로딩 중...")

    raw_data = {}
    for code in TARGETS:
        try:
            raw_data[code] = load_data(code, "2011-01-01", None)
        except Exception as e:
            print(f"  {TARGETS[code]}({code}) 로딩 실패: {e}")

    sample_df = raw_data["005930"]
    period_labels = [f"{p.index[0].date()}~{p.index[-1].date()}" for p in split_periods(sample_df, N_PERIODS)]
    print(f"시대 구간: " + " | ".join(period_labels))

    records = []
    for code, df in raw_data.items():
        periods = split_periods(df, N_PERIODS)
        for p_idx, p_df in enumerate(periods):
            for window in WINDOWS:
                try:
                    stats = run_trend_backtest(p_df, window, CASH)
                except Exception:
                    continue
                records.append({
                    "종목": TARGETS[code], "코드": code, "구간": p_idx, "이평선": window,
                    "CAGR": stats["CAGR(%)"], "MDD": stats["MDD(%)"],
                    "단순보유CAGR": stats["단순보유 CAGR(%)"], "매매횟수": stats["매매횟수"],
                })

    result = pd.DataFrame(records)
    result.to_csv("trend_filter_results.csv", index=False, encoding="utf-8-sig")

    period_avg = result.groupby(["이평선", "구간"]).agg(
        CAGR=("CAGR", "mean"), MDD=("MDD", "mean"), 단순보유CAGR=("단순보유CAGR", "mean"),
    ).reset_index()
    period_avg["승리"] = period_avg["CAGR"] > period_avg["단순보유CAGR"]

    summary = period_avg.groupby("이평선").agg(
        평균CAGR=("CAGR", "mean"), 최저구간CAGR=("CAGR", "min"),
        평균MDD=("MDD", "mean"), 승리구간수=("승리", "sum"),
    ).reset_index().round(2)
    print(f"\n=== N일 추세선 필터: 전체 종목(지수 포함) x {N_PERIODS}구간 평균 ===")
    print(f"(참고: 단순보유 평균 CAGR = {period_avg['단순보유CAGR'].mean():.2f}%)\n")
    print(summary.to_string(index=False))

    # 지수(KOSPI)만 따로: 트렌드 필터가 원래 지수/ETF에서 더 잘 통한다는 통념 검증
    kospi = result[result["코드"] == "KS11"]
    kospi_summary = kospi.groupby("이평선").agg(
        평균CAGR=("CAGR", "mean"), 평균MDD=("MDD", "mean"),
    ).reset_index().round(2)
    kospi_bh = kospi.groupby("구간")["단순보유CAGR"].mean()
    print(f"\n=== 코스피 지수만 별도 비교 (구간 평균 단순보유 CAGR = {kospi_bh.mean():.2f}%) ===")
    print(kospi_summary.to_string(index=False))

    # 상세 breakdown: 가장 승리구간수 많은 이평선
    best_window = summary.sort_values(["승리구간수", "평균CAGR"], ascending=[False, False]).iloc[0]["이평선"]
    sub = period_avg[period_avg["이평선"] == best_window].sort_values("구간")
    print(f"\n=== {int(best_window)}일선 필터 구간별 상세 (전체 종목 평균) ===")
    for _, row in sub.iterrows():
        mark = "O" if row["승리"] else "X"
        print(f"  {period_labels[int(row['구간'])]}: 전략 {row['CAGR']:+.2f}%  vs  단순보유 {row['단순보유CAGR']:+.2f}%  [{mark}]  MDD {row['MDD']:.1f}%")

    plot_comparison(period_avg, period_labels, "trend_filter_comparison.png")


def plot_comparison(period_avg: pd.DataFrame, period_labels: list, out_path: str):
    fig, ax = plt.subplots(figsize=(10, 6))
    x = range(len(period_labels))
    for window in WINDOWS:
        sub = period_avg[period_avg["이평선"] == window].sort_values("구간")
        ax.plot(x, sub["CAGR"], marker="o", label=f"{window}일선 필터")
    bh = period_avg.groupby("구간")["단순보유CAGR"].mean().sort_index()
    ax.plot(x, bh.values, marker="s", linestyle="--", color="black", label="단순보유")
    ax.set_xticks(list(x))
    ax.set_xticklabels(period_labels, rotation=20, ha="right")
    ax.set_ylabel("CAGR(%)")
    ax.set_title("구간별 추세선 필터 CAGR vs 단순보유")
    ax.axhline(0, color="gray", linewidth=0.8)
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    print(f"\n차트 저장: {out_path}")


if __name__ == "__main__":
    main()
