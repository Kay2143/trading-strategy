"""
Mark Minervini의 Trend Template — 시중에 검증된 추세추종 스크리닝 기준.
(참고: Minervini, "Trade Like a Stock Market Wizard")

8개 조건 (원문 기준):
1. 현재가 > 150일선, 200일선
2. 150일선 > 200일선
3. 200일선이 최근 1개월간 상승 추세
4. 50일선 > 150일선 > 200일선 (정배열)
5. 현재가 > 50일선
6. 현재가가 52주 저점 대비 최소 25~30% 이상 상승
7. 현재가가 52주 고점 대비 25% 이내
8. RS(상대강도) 상위권 — 원조는 IBD 전체 시장 대비 백분위(70 이상, 이상적으로 80~90+)이지만,
   우리는 스캔 대상 유니버스(시총 상위 N종목) 내에서의 상대 백분위로 근사 계산.
   (전체 시장 대비 진짜 RS Rating이 아니라 '우리 유니버스 내 상대강도'라는 점을 명확히 할 것)
"""

import pandas as pd


def compute_trend_template_fields(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    close = df["Close"]

    df["MA50"] = close.rolling(50).mean()
    df["MA150"] = close.rolling(150).mean()
    df["MA200"] = close.rolling(200).mean()
    df["MA200_1m_ago"] = df["MA200"].shift(20)  # 약 1개월(20거래일) 전 200일선

    df["High_52w"] = close.rolling(252, min_periods=200).max()
    df["Low_52w"] = close.rolling(252, min_periods=200).min()

    # 상대강도 근사치: 252거래일(약 1년) 수익률 (IBD 방식의 분기 가중 아님 - 단순화)
    df["Return_252d"] = close.pct_change(252) * 100

    return df


def check_trend_template(row: pd.Series) -> dict:
    """8개 조건 중 몇 개를 만족하는지와 개별 결과를 반환. RS 백분위는 별도로 전달받아야 함."""
    checks = {}
    price = row["Close"]

    checks["1_가격>150일선,200일선"] = bool(price > row["MA150"] and price > row["MA200"])
    checks["2_150일선>200일선"] = bool(row["MA150"] > row["MA200"])
    checks["3_200일선_상승추세"] = bool(pd.notna(row["MA200_1m_ago"]) and row["MA200"] > row["MA200_1m_ago"])
    checks["4_정배열(50>150>200)"] = bool(row["MA50"] > row["MA150"] > row["MA200"])
    checks["5_가격>50일선"] = bool(price > row["MA50"])
    checks["6_52주저점대비+25%이상"] = bool(price >= row["Low_52w"] * 1.25)
    checks["7_52주고점대비-25%이내"] = bool(price >= row["High_52w"] * 0.75)

    return checks


def evaluate(df: pd.DataFrame, rs_percentile: float, min_conditions: int = 7) -> dict | None:
    """최신 행에 대해 트렌드 템플릿 평가. RS 조건(백분위 70 이상) 포함 8개 중
    min_conditions개 이상 만족하면 결과 반환, 아니면 None."""
    row = df.iloc[-1]
    if pd.isna(row.get("MA200")):
        return None  # 상장 1년 미만 등 데이터 부족

    checks = check_trend_template(row)
    checks["8_RS백분위>=70"] = bool(rs_percentile >= 70)

    n_passed = sum(checks.values())
    if n_passed < min_conditions:
        return None

    return {
        "n_passed": n_passed,
        "total": len(checks),
        "checks": checks,
        "rs_percentile": rs_percentile,
    }


def compute_rs_percentiles(returns: dict[str, float]) -> dict[str, float]:
    """{code: 252일 수익률} -> {code: 백분위(0~100)}. 유니버스 내 상대 순위."""
    s = pd.Series(returns).dropna()
    ranks = s.rank(pct=True) * 100
    return ranks.to_dict()
