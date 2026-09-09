"""
스윙 트레이딩용 기술적 지표 계산 (RSI, MACD, 볼린저밴드, 거래량, 52주 고저).
외부 TA 라이브러리 없이 pandas만으로 계산.
"""

import pandas as pd


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    close = df["Close"]
    volume = df["Volume"]

    # RSI(14) - 단순이동평균 기반 (Wilder 평활 아님, 근사치)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    df["RSI"] = 100 - 100 / (1 + rs)

    # MACD(12,26,9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_hist"] = df["MACD"] - df["MACD_signal"]

    # 볼린저밴드(20, 2)
    mid = close.rolling(20).mean()
    std = close.rolling(20).std()
    df["BB_upper"] = mid + 2 * std
    df["BB_lower"] = mid - 2 * std
    df["BB_percent"] = (close - df["BB_lower"]) / (df["BB_upper"] - df["BB_lower"])

    # 거래량 배수 (전일까지의 20일 평균 대비 오늘 거래량)
    avg_vol_20 = volume.rolling(20).mean().shift(1)
    df["Volume_ratio"] = volume / avg_vol_20

    # 최근 모멘텀
    df["Change_5d"] = close.pct_change(5) * 100
    df["Change_1d"] = close.pct_change(1) * 100

    # 52주(약 252거래일) 고저 대비 위치
    df["High_52w"] = close.rolling(252, min_periods=60).max()
    df["Low_52w"] = close.rolling(252, min_periods=60).min()
    df["Pct_from_52w_high"] = (close / df["High_52w"] - 1) * 100
    df["Pct_from_52w_low"] = (close / df["Low_52w"] - 1) * 100

    return df


def classify_signal(latest: pd.Series) -> str | None:
    """최신 행(latest)을 보고 스윙 후보 유형 분류. 해당 없으면 None."""
    rsi = latest["RSI"]
    bb_pct = latest["BB_percent"]
    vol_ratio = latest["Volume_ratio"]
    macd_hist = latest["MACD_hist"]
    pct_from_high = latest["Pct_from_52w_high"]

    if pd.isna(rsi) or pd.isna(bb_pct) or pd.isna(vol_ratio):
        return None

    # 상승 돌파: 52주 신고가 근접 + 볼린저 상단 돌파 + 거래량 급증 + MACD 양전환
    if pct_from_high > -3 and bb_pct > 1.0 and vol_ratio > 2.0 and macd_hist > 0:
        return "돌파"

    # 과매도 반등: RSI 과매도 + 볼린저 하단 근접 + 거래량 마르지 않음(정상 이상)
    if rsi < 32 and bb_pct < 0.15 and vol_ratio > 0.8:
        return "반등"

    return None
