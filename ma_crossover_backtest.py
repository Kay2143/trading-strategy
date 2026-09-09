"""
이동평균 크로스오버(골든크로스/데드크로스) 전략 백테스트

- 데이터: FinanceDataReader (무료, 키움 API 불필요)
- 전략: 단기 이동평균선이 장기 이동평균선을 상향 돌파(골든크로스)하면 매수,
        하향 돌파(데드크로스)하면 매도
- 출력: 매매 내역, 수익률, 최대낙폭(MDD), 단순보유(Buy&Hold) 대비 비교, 차트 이미지 저장

사용 예:
    python ma_crossover_backtest.py --ticker 005930 --start 2020-01-01 --short 5 --long 20
"""

import argparse
import sys
import matplotlib.pyplot as plt
import matplotlib

from strategy_lib import load_data, compute_signals, backtest, compute_stats

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False


def plot_result(df: pd.DataFrame, trades: list[dict], ticker: str, out_path: str):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True,
                                    gridspec_kw={"height_ratios": [2, 1]})

    ax1.plot(df.index, df["Close"], label="종가", color="black", linewidth=1)
    ax1.plot(df.index, df["MA_short"], label="단기이평", color="orange", linewidth=1)
    ax1.plot(df.index, df["MA_long"], label="장기이평", color="blue", linewidth=1)

    buys = [t for t in trades if t["type"] == "BUY"]
    sells = [t for t in trades if t["type"] == "SELL"]
    if buys:
        ax1.scatter([t["date"] for t in buys], [t["price"] for t in buys],
                    marker="^", color="red", s=100, label="매수", zorder=5)
    if sells:
        ax1.scatter([t["date"] for t in sells], [t["price"] for t in sells],
                    marker="v", color="blue", s=100, label="매도", zorder=5)

    ax1.set_title(f"{ticker} 이동평균 크로스오버 전략")
    ax1.legend()
    ax1.grid(alpha=0.3)

    ax2.plot(df.index, df["equity"], label="전략 자산", color="green")
    ax2.set_ylabel("평가금액")
    ax2.legend()
    ax2.grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    print(f"차트 저장: {out_path}")


def main():
    parser = argparse.ArgumentParser(description="이동평균 크로스오버 백테스트")
    parser.add_argument("--ticker", default="005930", help="종목코드 (예: 삼성전자 005930)")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--short", type=int, default=5, help="단기 이동평균 기간")
    parser.add_argument("--long", type=int, default=20, help="장기 이동평균 기간")
    parser.add_argument("--cash", type=float, default=10_000_000, help="초기 투자금")
    args = parser.parse_args()

    df = load_data(args.ticker, args.start, args.end)
    df = compute_signals(df, args.short, args.long)
    df, trades = backtest(df, initial_cash=args.cash)
    stats = compute_stats(df, args.cash)

    print(f"\n=== {args.ticker} | 단기{args.short} / 장기{args.long} 크로스오버 결과 ===")
    for k, v in stats.items():
        print(f"{k}: {v}")

    print(f"\n총 매매 횟수: {len(trades)}회")
    for t in trades:
        print(f"  {t['date'].date()} {t['type']:4s} {t['price']:,.0f}원 x {t['shares']}주")

    out_path = f"backtest_{args.ticker}_{args.short}_{args.long}.png"
    plot_result(df, trades, args.ticker, out_path)


if __name__ == "__main__":
    main()
