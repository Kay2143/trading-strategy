import unittest

import pandas as pd

from research_agent import evaluate_pending, screen_candidates


class ResearchAgentTests(unittest.TestCase):
    def test_screen_requires_strict_trend_and_relative_strength(self):
        dates = pd.bdate_range("2024-01-01", periods=400)
        universe = pd.DataFrame({
            "Code": ["000001", "000002", "000003", "000004", "000005"],
            "Name": ["A", "B", "C", "D", "E"],
        })
        data = {}
        for code, daily_growth in zip(universe["Code"], [0.0005, 0.001, 0.0015, 0.002, 0.0025]):
            close = 100 * (1 + daily_growth) ** pd.Series(range(len(dates)))
            data[code] = pd.DataFrame(
                {"Close": close.to_numpy(), "Volume": [10_000_000] * len(dates)},
                index=dates,
            )

        candidates = screen_candidates(universe, data, dates[-1])

        self.assertTrue(candidates)
        self.assertLessEqual(len(candidates), 3)
        self.assertTrue(all(item["conditions_passed"] == 8 for item in candidates))
        self.assertTrue(all(item["rs_percentile"] >= 80 for item in candidates))
        self.assertEqual(candidates[0]["code"], "000005")

    def test_evaluate_pending_waits_for_five_benchmark_sessions(self):
        dates = pd.bdate_range("2026-01-01", periods=20)
        stock = pd.DataFrame({"Close": [100 + i for i in range(20)]}, index=dates)
        benchmark = pd.DataFrame({"Close": [1000 + i for i in range(20)]}, index=dates)
        pick_date = dates[-6]
        ledger = pd.DataFrame([{
            "analysis_date": pick_date.strftime("%Y-%m-%d"),
            "code": "000001",
            "name": "Example",
            "entry_price": stock.loc[pick_date, "Close"],
            "benchmark_entry": benchmark.loc[pick_date, "Close"],
            "status": "pending",
        }])

        settled, updated = evaluate_pending(ledger, {"000001": stock}, benchmark)

        self.assertEqual(len(settled), 1)
        self.assertEqual(updated.iloc[0]["status"], "evaluated")
        self.assertAlmostEqual(
            updated.iloc[0]["forward_5d_return_pct"],
            (stock.iloc[-1]["Close"] / stock.loc[pick_date, "Close"] - 1) * 100,
        )

    def test_evaluate_pending_keeps_unfinished_pick_pending(self):
        dates = pd.bdate_range("2026-01-01", periods=8)
        stock = pd.DataFrame({"Close": range(100, 108)}, index=dates)
        benchmark = pd.DataFrame({"Close": range(1000, 1008)}, index=dates)
        pick_date = dates[-3]
        ledger = pd.DataFrame([{
            "analysis_date": pick_date.strftime("%Y-%m-%d"),
            "code": "000001",
            "name": "Example",
            "entry_price": stock.loc[pick_date, "Close"],
            "benchmark_entry": benchmark.loc[pick_date, "Close"],
            "status": "pending",
        }])

        settled, updated = evaluate_pending(ledger, {"000001": stock}, benchmark)

        self.assertTrue(settled.empty)
        self.assertEqual(updated.iloc[0]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
