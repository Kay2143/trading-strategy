"""Scheduled, rules-based research brief for the stock research agent.

This script does not place orders or claim to assess fundamentals. It records
technical watchlist candidates and their five-trading-day outcomes for review.
"""

import argparse
import html
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from market_data import fetch_all, get_universe
from telegram_alert import send_telegram_message
from trend_template import check_trend_template, compute_trend_template_fields, compute_rs_percentiles

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
AGENT_DIR = ROOT / "agents" / "주식천재stock-research-agent"
DAILY_DIR = AGENT_DIR / "reports" / "daily"
WEEKLY_DIR = AGENT_DIR / "reports" / "weekly"
LEDGER_PATH = AGENT_DIR / "decisions" / "candidate_ledger.csv"
DATA_START = "2022-01-01"
MIN_HISTORY = 253
MIN_UNIVERSE_COVERAGE = 0.80
MIN_AVG_TURNOVER_KRW = 1_000_000_000
MIN_RS_PERCENTILE = 80.0
MIN_CONDITIONS = 8
MAX_CANDIDATES = 3
FORWARD_HORIZON = 5
LEDGER_COLUMNS = [
    "analysis_date", "code", "name", "entry_price", "benchmark_entry",
    "rs_percentile", "conditions_passed", "avg_turnover_20d_krw", "status",
    "forward_5d_return_pct", "benchmark_5d_return_pct", "excess_5d_return_pct",
    "evaluated_date",
]


def _read_ledger() -> pd.DataFrame:
    if not LEDGER_PATH.exists():
        return pd.DataFrame(columns=LEDGER_COLUMNS)
    ledger = pd.read_csv(LEDGER_PATH, dtype={"code": str})
    for column in LEDGER_COLUMNS:
        if column not in ledger:
            ledger[column] = pd.NA
    return ledger[LEDGER_COLUMNS]


def _save_ledger(ledger: pd.DataFrame) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(LEDGER_PATH, index=False, encoding="utf-8-sig")


def screen_candidates(
    universe: pd.DataFrame,
    data: dict[str, pd.DataFrame],
    analysis_date: pd.Timestamp,
) -> list[dict]:
    """Return a short, strict technical watchlist; fundamentals are not assessed."""
    names = dict(zip(universe["Code"].astype(str), universe["Name"]))
    trend_fields = {}
    annual_returns = {}
    for code, frame in data.items():
        if code == "KS11" or len(frame) < MIN_HISTORY:
            continue
        fields = compute_trend_template_fields(frame)
        latest = fields.iloc[-1]
        if pd.Timestamp(fields.index[-1]).normalize() != analysis_date:
            continue
        if pd.notna(latest["Return_252d"]):
            trend_fields[code] = fields
            annual_returns[code] = latest["Return_252d"]

    percentiles = compute_rs_percentiles(annual_returns)
    candidates = []
    for code, fields in trend_fields.items():
        row = fields.iloc[-1]
        rs = float(percentiles.get(code, float("nan")))
        if pd.isna(rs):
            continue

        checks = check_trend_template(row)
        checks["8_RS백분위>=70"] = rs >= 70
        if sum(checks.values()) < MIN_CONDITIONS or rs < MIN_RS_PERCENTILE:
            continue

        frame = data[code]
        recent_turnover = (frame["Close"] * frame["Volume"]).tail(20)
        avg_turnover = float(recent_turnover.mean())
        if pd.isna(avg_turnover) or avg_turnover < MIN_AVG_TURNOVER_KRW:
            continue

        close = float(row["Close"])
        candidates.append({
            "code": code,
            "name": str(names.get(code, code)),
            "price": close,
            "change_1d_pct": float(frame["Close"].pct_change().iloc[-1] * 100),
            "return_1m_pct": float(frame["Close"].pct_change(21).iloc[-1] * 100),
            "return_3m_pct": float(frame["Close"].pct_change(63).iloc[-1] * 100),
            "return_6m_pct": float(frame["Close"].pct_change(126).iloc[-1] * 100),
            "return_12m_pct": float(row["Return_252d"]),
            "distance_from_high_pct": float((close / row["High_52w"] - 1) * 100),
            "rs_percentile": rs,
            "conditions_passed": int(sum(checks.values())),
            "avg_turnover_20d_krw": avg_turnover,
        })

    return sorted(
        candidates,
        key=lambda item: (item["rs_percentile"], item["return_6m_pct"]),
        reverse=True,
    )[:MAX_CANDIDATES]


def evaluate_pending(
    ledger: pd.DataFrame,
    data: dict[str, pd.DataFrame],
    benchmark: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Settle picks only when five later KOSPI sessions and stock closes exist."""
    if ledger.empty:
        return pd.DataFrame(columns=LEDGER_COLUMNS), ledger

    settled_indices = []
    for idx, record in ledger[ledger["status"] == "pending"].iterrows():
        code = str(record["code"])
        stock = data.get(code)
        if stock is None:
            continue
        pick_date = pd.Timestamp(record["analysis_date"]).normalize()
        benchmark_dates = pd.DatetimeIndex(benchmark.index).normalize()
        positions = benchmark_dates.get_indexer([pick_date])
        if positions[0] < 0:
            continue
        target_pos = positions[0] + FORWARD_HORIZON
        if target_pos >= len(benchmark):
            continue

        target_date = benchmark_dates[target_pos]
        stock_dates = pd.DatetimeIndex(stock.index).normalize()
        stock_pos = stock_dates.get_indexer([target_date])
        if stock_pos[0] < 0:
            continue
        entry = float(record["entry_price"])
        benchmark_entry = float(record["benchmark_entry"])
        if entry <= 0 or benchmark_entry <= 0:
            raise ValueError(f"Invalid entry price in candidate ledger: {code} {pick_date.date()}")

        stock_return = (float(stock["Close"].iloc[stock_pos[0]]) / entry - 1) * 100
        benchmark_return = (
            float(benchmark["Close"].iloc[target_pos]) / benchmark_entry - 1
        ) * 100
        ledger.loc[idx, "status"] = "evaluated"
        ledger.loc[idx, "forward_5d_return_pct"] = stock_return
        ledger.loc[idx, "benchmark_5d_return_pct"] = benchmark_return
        ledger.loc[idx, "excess_5d_return_pct"] = stock_return - benchmark_return
        ledger.loc[idx, "evaluated_date"] = target_date.strftime("%Y-%m-%d")
        settled_indices.append(idx)

    return ledger.loc[settled_indices].copy(), ledger


def _market_context(benchmark: pd.DataFrame) -> dict:
    close = benchmark["Close"]
    if len(close) < MIN_HISTORY:
        raise RuntimeError(f"Insufficient KOSPI index history: {len(close)} rows")
    latest = float(close.iloc[-1])
    ma200 = float(close.rolling(200).mean().iloc[-1])
    return {
        "date": pd.Timestamp(benchmark.index[-1]).normalize(),
        "close": latest,
        "above_ma200": latest > ma200,
        "return_1m_pct": float(close.pct_change(21).iloc[-1] * 100),
        "return_6m_pct": float(close.pct_change(126).iloc[-1] * 100),
    }


def _format_daily_html(
    candidates: list[dict],
    market: dict,
    coverage: float,
    settled: pd.DataFrame,
) -> str:
    market_label = "200일선 위" if market["above_ma200"] else "200일선 아래"
    lines = [
        f"<b>주식천재 일일 리서치 | {market['date']:%Y-%m-%d}</b>",
        f"코스피 {market['close']:,.0f} ({market_label}) | "
        f"1개월 {market['return_1m_pct']:+.1f}% | 6개월 {market['return_6m_pct']:+.1f}%",
        f"시총 상위 유니버스 데이터 수집률 {coverage:.0%}",
        "",
    ]
    if candidates:
        lines.append("<b>[추가 조사 후보 - 기술적 조건만]</b>")
        for item in candidates:
            name = html.escape(item["name"])
            lines.append(
                f"• {name}({item['code']}) {item['price']:,.0f}원 | "
                f"RS {item['rs_percentile']:.0f}백분위 | "
                f"1/3/6/12개월 {item['return_1m_pct']:+.1f}/"
                f"{item['return_3m_pct']:+.1f}/{item['return_6m_pct']:+.1f}/"
                f"{item['return_12m_pct']:+.1f}% | "
                f"20일 평균 거래대금 {item['avg_turnover_20d_krw'] / 1e8:.0f}억원"
            )
    else:
        lines.append("오늘은 엄격한 기술적 품질 기준을 통과한 추가 조사 후보가 없습니다.")

    if not settled.empty:
        mean_return = settled["forward_5d_return_pct"].astype(float).mean()
        mean_excess = settled["excess_5d_return_pct"].astype(float).mean()
        lines.extend([
            "",
            f"<b>5거래일 추적 완료 {len(settled)}건:</b> 평균 {mean_return:+.2f}% | "
            f"코스피 대비 {mean_excess:+.2f}%p",
        ])

    lines.extend([
        "",
        "범위: KRX 시총 상위 300 보통주 일봉 기술 분석. "
        "실적·밸류에이션·제품 트렌드·공시는 아직 검증하지 않았습니다.",
        "RS 80 기준은 별도 백테스트되지 않은 탐색 기준입니다. 후보는 매수 추천이 아니며, "
        "규칙은 자동 변경하지 않고 성과를 누적 기록합니다.",
    ])
    return "\n".join(lines)


def _format_daily_markdown(
    message: str,
    market: dict,
    coverage: float,
    candidate_count: int,
) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"# 일일 리서치 - {market['date']:%Y-%m-%d}\n\n"
        f"- 실행 시각: {generated}\n"
        f"- 기준 데이터 일자: {market['date']:%Y-%m-%d}\n"
        f"- 유니버스 데이터 수집률: {coverage:.1%}\n"
        f"- 후보 수: {candidate_count}\n"
        f"- 데이터 출처: FinanceDataReader 일봉 및 KRX 종목 목록\n"
        f"- 후보 기준: Minervini 8/8 조건, 유니버스 내 1년 수익률 RS 상위 "
        f"{100 - MIN_RS_PERCENTILE:.0f}% 이상, 20일 평균 거래대금 "
        f"{MIN_AVG_TURNOVER_KRW / 1e8:.0f}억원 이상, 최대 {MAX_CANDIDATES}종목\n"
        f"- 검증 상태: RS {MIN_RS_PERCENTILE:.0f} 기준은 독립 백테스트 전 탐색 기준\n"
        f"- 미평가 항목: 실적 성장, PER/ROE, 현금흐름, 뉴스·공시와 제품 트렌드\n"
        f"- 시장 상태: KOSPI {market['close']:,.2f}, 200일선 "
        f"{'상회' if market['above_ma200'] else '하회'}, "
        f"1개월 {market['return_1m_pct']:+.2f}%, "
        f"6개월 {market['return_6m_pct']:+.2f}%\n\n"
        f"{message}\n"
    )


def run_daily(force: bool = False, dry_run: bool = False) -> None:
    universe = get_universe(300)
    if universe.empty:
        raise RuntimeError("KRX universe is empty")

    ledger = _read_ledger()
    pending_codes = ledger.loc[ledger["status"] == "pending", "code"].dropna().astype(str).tolist()
    codes = list(dict.fromkeys(universe["Code"].astype(str).tolist() + pending_codes))
    print(f"Fetching daily bars for {len(codes)} stocks and KOSPI index...")
    data = fetch_all(codes, start=DATA_START)
    benchmark_data = fetch_all(["KS11"], start=DATA_START)
    benchmark = benchmark_data.get("KS11")
    if benchmark is None:
        raise RuntimeError("KOSPI benchmark data (KS11) is unavailable")

    market = _market_context(benchmark)
    latest_date = market["date"]
    age_days = (pd.Timestamp.now().normalize() - latest_date).days
    if age_days > 5:
        raise RuntimeError(f"Market data is stale: latest session {latest_date.date()}")

    coverage = sum(
        code in data
        and pd.Timestamp(data[code].index[-1]).normalize() == latest_date
        for code in universe["Code"].astype(str)
    ) / len(universe)
    if coverage < MIN_UNIVERSE_COVERAGE:
        raise RuntimeError(
            f"Stock data coverage {coverage:.1%} is below required "
            f"{MIN_UNIVERSE_COVERAGE:.0%}"
        )

    report_path = DAILY_DIR / f"{latest_date:%Y-%m-%d}.md"
    if report_path.exists() and not force and not dry_run:
        print(f"Daily report already exists for {latest_date.date()}; skipping duplicate run.")
        return

    settled, ledger = evaluate_pending(ledger, data, benchmark)
    candidates = screen_candidates(universe, data, latest_date)

    existing_keys = set(zip(ledger["analysis_date"].astype(str), ledger["code"].astype(str)))
    benchmark_close = float(benchmark["Close"].iloc[-1])
    new_rows = []
    for item in candidates:
        key = (latest_date.strftime("%Y-%m-%d"), item["code"])
        if key in existing_keys:
            continue
        new_rows.append({
            "analysis_date": key[0],
            "code": item["code"],
            "name": item["name"],
            "entry_price": item["price"],
            "benchmark_entry": benchmark_close,
            "rs_percentile": item["rs_percentile"],
            "conditions_passed": item["conditions_passed"],
            "avg_turnover_20d_krw": item["avg_turnover_20d_krw"],
            "status": "pending",
        })
    if new_rows:
        ledger = pd.concat([ledger, pd.DataFrame(new_rows)], ignore_index=True)

    message = _format_daily_html(candidates, market, coverage, settled)
    if dry_run:
        print(message)
        print("[dry-run] No files written and no Telegram message sent.")
        return

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        _format_daily_markdown(message, market, coverage, len(candidates)),
        encoding="utf-8",
    )
    _save_ledger(ledger)
    print(message)

    if candidates or not settled.empty:
        if not send_telegram_message(message):
            raise RuntimeError("Telegram delivery failed; see telegram_alert.py output")
    else:
        print("No Telegram sent: no candidates or newly settled outcomes.")


def run_weekly_report() -> None:
    ledger = _read_ledger()
    evaluated = ledger[ledger["status"] == "evaluated"].copy()
    today = pd.Timestamp.now().strftime("%Y-%m-%d")
    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=7)
    if not evaluated.empty:
        evaluated_dates = pd.to_datetime(evaluated["evaluated_date"], errors="coerce")
        evaluated = evaluated[evaluated_dates >= cutoff].tail(100)

    if evaluated.empty:
        message = (
            f"<b>주식천재 주간 검증 | {today}</b>\n"
            "최근 7일 동안 새로 완료된 5거래일 추적 결과가 없습니다. 평가 전 후보는 성과에 포함하지 않았습니다."
        )
    else:
        returns = evaluated["forward_5d_return_pct"].astype(float)
        excess = evaluated["excess_5d_return_pct"].astype(float)
        win_rate = (returns > 0).mean() * 100
        beat_rate = (excess > 0).mean() * 100
        message = (
            f"<b>주식천재 주간 검증 | {today}</b>\n"
            f"최근 완료 {len(evaluated)}건 | 5거래일 평균 {returns.mean():+.2f}% | "
            f"중앙값 {returns.median():+.2f}% | 양수 비율 {win_rate:.0f}%\n"
            f"코스피 대비 평균 {excess.mean():+.2f}%p | 초과수익 비율 {beat_rate:.0f}%\n"
            "※ 수수료·세금·슬리피지 미반영. 표본이 작으면 참고치에 불과합니다."
        )

    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    report_path = WEEKLY_DIR / f"{today}.md"
    report_path.write_text(
        f"# 주간 후보 검증 - {today}\n\n{message}\n",
        encoding="utf-8",
    )
    print(message)
    if evaluated.empty:
        print("No Telegram sent: no completed candidate outcomes yet.")
        return
    if not send_telegram_message(message):
        raise RuntimeError("Telegram delivery failed; see telegram_alert.py output")


def main() -> None:
    parser = argparse.ArgumentParser(description="주식천재 정기 리서치 에이전트")
    parser.add_argument("--force", action="store_true", help="같은 데이터 일자의 재실행 및 재전송")
    parser.add_argument("--dry-run", action="store_true", help="전송/파일 저장 없이 분석 결과만 출력")
    parser.add_argument("--weekly-report", action="store_true", help="누적된 5거래일 성과를 주간 요약")
    args = parser.parse_args()
    if args.weekly_report:
        if args.dry_run:
            raise ValueError("--dry-run is only supported for daily analysis")
        run_weekly_report()
    else:
        run_daily(force=args.force, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
