"""
코스피/코스닥 전체 종목 리스트업 + 병렬 시세 데이터 수집.
"""

import re
import concurrent.futures as cf
from datetime import datetime, time as dtime, timedelta
import pandas as pd
import FinanceDataReader as fdr

PREFERRED_PATTERN = re.compile(r".*\d?우(B|\(전환\))?$")
MARKET_CLOSE = dtime(15, 30)
KRX_CACHE_URL = "https://raw.githubusercontent.com/FinanceData/fdr_krx_data_cache/refs/heads/master/data/listing/krx/{date}.csv"


def _fetch_krx_listing() -> pd.DataFrame:
    """fdr.StockListing('KRX')는 당일자 GitHub 캐시가 아직 발행 안 됐으면 404로 실패함.
    최근 며칠 날짜를 거슬러 올라가며 실제로 존재하는 가장 최신 캐시를 찾아서 사용."""
    try:
        return fdr.StockListing("KRX")
    except Exception:
        pass

    for days_back in range(1, 8):
        d = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        url = KRX_CACHE_URL.format(date=d)
        try:
            df = pd.read_csv(url, index_col=0, dtype={"Code": str, "Dept": str, "ChangeCode": str, "MarketId": str})
            print(f"(참고: 오늘자 종목 리스트 캐시가 아직 없어 {d}자 데이터 사용)")
            return df.reset_index(drop=True)
        except Exception:
            continue
    raise RuntimeError("KRX 종목 리스트를 가져오지 못했습니다 (최근 7일 캐시 모두 없음)")


def _trim_incomplete_today(df: pd.DataFrame) -> pd.DataFrame:
    """장중(15:30 이전)에 실행되면 당일자 미완성 봉을 제거하고 전일 확정 종가까지만 사용."""
    if df.empty:
        return df
    now = datetime.now()
    if df.index[-1].date() == now.date() and now.time() < MARKET_CLOSE:
        return df.iloc[:-1]
    return df


def get_universe(top_n: int = 300) -> pd.DataFrame:
    """시가총액 상위 top_n개 보통주(코스피+코스닥, 우선주/스팩 제외) 반환."""
    df = _fetch_krx_listing()
    df = df[df["Market"].isin(["KOSPI", "KOSDAQ"])]
    df = df[~df["Name"].str.contains("스팩", na=False)]
    df = df[~df["Name"].str.match(PREFERRED_PATTERN)]
    df = df.sort_values("Marcap", ascending=False)
    return df.head(top_n)[["Code", "Name", "Market", "Marcap"]].reset_index(drop=True)


def fetch_all(codes: list[str], start: str = "2024-01-01", max_workers: int = 15) -> dict[str, pd.DataFrame]:
    """여러 종목의 일봉 데이터를 병렬로 수집. 실패한 종목은 결과에서 제외."""
    results = {}

    def _fetch(code):
        try:
            df = fdr.DataReader(code, start, None)
            df = _trim_incomplete_today(df)
            if len(df) < 60:  # 신규상장 등 데이터 부족 종목 제외
                return code, None
            return code, df
        except Exception:
            return code, None

    with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        for code, df in ex.map(_fetch, codes):
            if df is not None:
                results[code] = df

    return results
