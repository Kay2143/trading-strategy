"""
이동평균 크로스오버 파라미터 최적화 (여러 종목 x 여러 단기/장기 조합 x 여러 시대의 과거 데이터)

단순히 "학습구간 vs 검증구간" 반으로만 나누면, 검증구간에 특이한 급등장/급락장이 끼는 경우
결과가 그 한 시기에 좌우되어 버린다. 그래서 전체 기간을 N개의 시대(period)로 쪼개서
각 조합이 여러 시장 국면(횡보/상승/하락)에서 얼마나 "꾸준히" 통하는지를 본다.

사용 예:
    python optimize_ma.py
    python optimize_ma.py --tickers 005930,000660,035420 --periods 4
"""

import argparse
import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib

from strategy_lib import load_data, run_backtest

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False

DEFAULT_TICKERS = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "035420": "NAVER",
    "005380": "현대차",
    "051910": "LG화학",
}

SHORT_WINDOWS = [5, 10, 15, 20, 25, 30]
LONG_WINDOWS = [20, 40, 60, 90, 120, 150]


def split_periods(df: pd.DataFrame, n_periods: int) -> list[pd.DataFrame]:
    edges = np.linspace(0, len(df), n_periods + 1).astype(int)
    return [df.iloc[edges[i]:edges[i + 1]] for i in range(n_periods)]


def main():
    parser = argparse.ArgumentParser(description="이동평균 크로스오버 파라미터 최적화 (다구간)")
    parser.add_argument("--tickers", default=None, help="쉼표로 구분된 종목코드 (기본: 5개 대형주)")
    parser.add_argument("--start", default="2011-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--periods", type=int, default=4, help="시대 구간 개수 (기본 4)")
    parser.add_argument("--cash", type=float, default=10_000_000)
    parser.add_argument("--top", type=int, default=15, help="출력할 상위 조합 개수")
    args = parser.parse_args()

    tickers = {t: t for t in args.tickers.split(",")} if args.tickers else DEFAULT_TICKERS

    print(f"대상 종목: {', '.join(f'{n}({c})' for c, n in tickers.items())}")
    print("데이터 로딩 중...")

    raw_data = {}
    for code in tickers:
        try:
            df = load_data(code, args.start, args.end)
            raw_data[code] = df
        except Exception as e:
            print(f"  {tickers[code]}({code}) 로딩 실패: {e}")

    sample_df = next(iter(raw_data.values()))
    period_labels = []
    for p_df in split_periods(sample_df, args.periods):
        period_labels.append(f"{p_df.index[0].date()}~{p_df.index[-1].date()}")
    print(f"실제 데이터 기간: {sample_df.index[0].date()} ~ {sample_df.index[-1].date()} ({len(sample_df)}일)")
    print(f"※ 무료 데이터 소스(Naver) 특성상 최대 약 3000거래일(~12년)까지만 조회됩니다.")
    print(f"시대 구간 ({args.periods}개): " + " | ".join(period_labels))

    combos = [(s, l) for s in SHORT_WINDOWS for l in LONG_WINDOWS if l > s]
    print(f"\n총 {len(combos)}개 조합 x {len(raw_data)}개 종목 x {args.periods}개 구간 백테스트 중...")

    records = []
    for code, df in raw_data.items():
        periods = split_periods(df, args.periods)
        for p_idx, p_df in enumerate(periods):
            for short, long in combos:
                try:
                    stats = run_backtest(p_df, short, long, args.cash)
                except Exception:
                    continue
                records.append({
                    "종목": tickers[code], "코드": code, "구간": p_idx,
                    "단기": short, "장기": long,
                    "CAGR": stats["CAGR(%)"], "MDD": stats["MDD(%)"],
                    "단순보유CAGR": stats["단순보유 CAGR(%)"], "매매횟수": stats["매매횟수"],
                })

    result = pd.DataFrame(records)
    result.to_csv("optimize_results.csv", index=False, encoding="utf-8-sig")
    print(f"전체 결과 저장: optimize_results.csv ({len(result)}행)")

    # 구간별로 종목 평균 낸 성과 (조합, 구간) 단위
    period_avg = result.groupby(["단기", "장기", "구간"]).agg(
        CAGR=("CAGR", "mean"), MDD=("MDD", "mean"), 단순보유CAGR=("단순보유CAGR", "mean"),
    ).reset_index()
    period_avg["승리"] = period_avg["CAGR"] > period_avg["단순보유CAGR"]

    # 조합별로 구간 전체에 걸친 "꾸준함" 집계
    summary = period_avg.groupby(["단기", "장기"]).agg(
        평균CAGR=("CAGR", "mean"),
        최저구간CAGR=("CAGR", "min"),
        평균MDD=("MDD", "mean"),
        승리구간수=("승리", "sum"),
    ).reset_index()
    total_periods = args.periods
    summary["승리구간"] = summary["승리구간수"].astype(str) + f"/{total_periods}"
    summary = summary.round(2).sort_values(
        ["승리구간수", "평균CAGR"], ascending=[False, False]
    )

    buy_hold_avg = period_avg["단순보유CAGR"].mean()
    print(f"\n=== 구간별 꾸준함(승리구간수) 기준 상위 {args.top}개 조합 ===")
    print(f"(참고: 전 구간 평균 단순보유 CAGR = {buy_hold_avg:.2f}%)\n")
    print(summary[["단기", "장기", "승리구간", "평균CAGR", "최저구간CAGR", "평균MDD"]]
          .head(args.top).to_string(index=False))

    # 상위 3개 조합의 구간별 상세 breakdown
    print(f"\n=== 상위 3개 조합의 구간별 상세 (전략 CAGR vs 단순보유 CAGR) ===")
    top3 = summary.head(3)[["단기", "장기"]].values.tolist()
    for short, long in top3:
        sub = period_avg[(period_avg["단기"] == short) & (period_avg["장기"] == long)].sort_values("구간")
        print(f"\n[단기{int(short)} / 장기{int(long)}]")
        for _, row in sub.iterrows():
            mark = "O" if row["승리"] else "X"
            label = period_labels[int(row["구간"])]
            print(f"  {label}: 전략 {row['CAGR']:+.2f}%  vs  단순보유 {row['단순보유CAGR']:+.2f}%  [{mark}]")

    plot_heatmap(summary, "평균CAGR", "optimize_heatmap_cagr.png", "전 구간 평균 CAGR(%)")
    plot_heatmap(summary, "승리구간수", "optimize_heatmap_wins.png",
                 f"단순보유 대비 승리구간 수 (0~{total_periods})")
    plot_period_lines(period_avg, top3, period_labels, "optimize_period_comparison.png")


def plot_heatmap(summary: pd.DataFrame, value_col: str, out_path: str, title: str):
    pivot = summary.pivot(index="단기", columns="장기", values=value_col)
    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(pivot.values, cmap="RdYlGn", aspect="auto")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    ax.set_xlabel("장기 이동평균")
    ax.set_ylabel("단기 이동평균")
    ax.set_title(title)

    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            val = pivot.values[i, j]
            if not np.isnan(val):
                ax.text(j, i, f"{val:.1f}", ha="center", va="center", fontsize=8)

    fig.colorbar(im, ax=ax)
    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    print(f"히트맵 저장: {out_path}")


def plot_period_lines(period_avg: pd.DataFrame, top3: list, period_labels: list, out_path: str):
    fig, ax = plt.subplots(figsize=(10, 6))
    x = range(len(period_labels))

    for short, long in top3:
        sub = period_avg[(period_avg["단기"] == short) & (period_avg["장기"] == long)].sort_values("구간")
        ax.plot(x, sub["CAGR"], marker="o", label=f"단기{int(short)}/장기{int(long)}")

    bh = period_avg.groupby("구간")["단순보유CAGR"].mean().sort_index()
    ax.plot(x, bh.values, marker="s", linestyle="--", color="black", label="단순보유")

    ax.set_xticks(list(x))
    ax.set_xticklabels(period_labels, rotation=20, ha="right")
    ax.set_ylabel("CAGR(%)")
    ax.set_title("구간별 전략 CAGR vs 단순보유 (상위 3개 조합)")
    ax.axhline(0, color="gray", linewidth=0.8)
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    print(f"구간별 비교 차트 저장: {out_path}")


if __name__ == "__main__":
    main()
