"""Market data collection using pykrx and FinanceDataReader."""
import logging
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd

logger = logging.getLogger(__name__)

SHINSEGAE_TICKERS = {
    "004170": "(주)신세계",
    "037710": "(주)광주신세계",
    "031430": "(주)신세계인터내셔날",
    "035510": "(주)신세계아이앤씨",
    "139480": "(주)이마트",
    "031440": "(주)신세계푸드",
}


def get_last_trading_day(base_date: Optional[datetime] = None) -> str:
    from pykrx import stock

    if base_date is None:
        base_date = datetime.today()

    for delta in range(1, 8):
        candidate = base_date - timedelta(days=delta)
        date_str = candidate.strftime("%Y%m%d")
        try:
            df = stock.get_index_ohlcv_by_date(date_str, date_str, "1001")
            if not df.empty:
                return date_str
        except Exception:
            continue

    return (base_date - timedelta(days=1)).strftime("%Y%m%d")


def get_market_summary(date_str: str) -> dict:
    from pykrx import stock

    result = {"date": date_str, "kospi": {}, "kosdaq": {}}

    try:
        kospi = stock.get_index_ohlcv_by_date(date_str, date_str, "1001")
        if not kospi.empty:
            row = kospi.iloc[-1]
            prev = stock.get_index_ohlcv_by_date(
                (datetime.strptime(date_str, "%Y%m%d") - timedelta(days=7)).strftime("%Y%m%d"),
                date_str,
                "1001",
            )
            prev_close = prev.iloc[-2]["종가"] if len(prev) >= 2 else row["시가"]
            change = row["종가"] - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0
            result["kospi"] = {
                "close": float(row["종가"]),
                "change": float(change),
                "change_pct": float(change_pct),
                "volume": int(row["거래량"]),
            }
    except Exception as e:
        logger.warning(f"KOSPI data fetch failed: {e}")

    try:
        kosdaq = stock.get_index_ohlcv_by_date(date_str, date_str, "2001")
        if not kosdaq.empty:
            row = kosdaq.iloc[-1]
            prev = stock.get_index_ohlcv_by_date(
                (datetime.strptime(date_str, "%Y%m%d") - timedelta(days=7)).strftime("%Y%m%d"),
                date_str,
                "2001",
            )
            prev_close = prev.iloc[-2]["종가"] if len(prev) >= 2 else row["시가"]
            change = row["종가"] - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0
            result["kosdaq"] = {
                "close": float(row["종가"]),
                "change": float(change),
                "change_pct": float(change_pct),
                "volume": int(row["거래량"]),
            }
    except Exception as e:
        logger.warning(f"KOSDAQ data fetch failed: {e}")

    return result


def get_fx_and_gold(date_str: str) -> dict:
    import FinanceDataReader as fdr

    result = {"usdkrw": {}, "gold": {}}
    end = datetime.strptime(date_str, "%Y%m%d")
    start = end - timedelta(days=10)

    try:
        df = fdr.DataReader("USD/KRW", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        if not df.empty and len(df) >= 2:
            close = float(df["Close"].iloc[-1])
            prev_close = float(df["Close"].iloc[-2])
            result["usdkrw"] = {
                "close": close,
                "change": close - prev_close,
                "change_pct": (close - prev_close) / prev_close * 100,
            }
    except Exception as e:
        logger.warning(f"USD/KRW fetch failed: {e}")

    try:
        df = fdr.DataReader("GC=F", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        if not df.empty and len(df) >= 2:
            close = float(df["Close"].iloc[-1])
            prev_close = float(df["Close"].iloc[-2])
            result["gold"] = {
                "close": close,
                "change": close - prev_close,
                "change_pct": (close - prev_close) / prev_close * 100,
            }
    except Exception as e:
        logger.warning(f"Gold price fetch failed: {e}")

    return result


def get_stock_data(date_str: str) -> list[dict]:
    from pykrx import stock

    start = (datetime.strptime(date_str, "%Y%m%d") - timedelta(days=10)).strftime("%Y%m%d")
    rows = []

    for ticker, name in SHINSEGAE_TICKERS.items():
        row = {"ticker": ticker, "name": name}
        try:
            df = stock.get_market_ohlcv_by_date(start, date_str, ticker)
            if not df.empty and len(df) >= 2:
                row["close"] = float(df["종가"].iloc[-1])
                row["prev_close"] = float(df["종가"].iloc[-2])
                row["change"] = row["close"] - row["prev_close"]
                row["change_pct"] = row["change"] / row["prev_close"] * 100
                row["volume"] = int(df["거래량"].iloc[-1])
            else:
                row.update({"close": None, "prev_close": None, "change": None, "change_pct": None, "volume": None})
        except Exception as e:
            logger.warning(f"OHLCV fetch failed for {ticker}: {e}")
            row.update({"close": None, "prev_close": None, "change": None, "change_pct": None, "volume": None})

        try:
            df_f = stock.get_market_fundamental_by_date(start, date_str, ticker)
            if not df_f.empty:
                last = df_f.iloc[-1]
                row["per"] = float(last.get("PER", 0)) or None
                row["pbr"] = float(last.get("PBR", 0)) or None
            else:
                row["per"] = None
                row["pbr"] = None
        except Exception as e:
            logger.warning(f"Fundamental fetch failed for {ticker}: {e}")
            row["per"] = None
            row["pbr"] = None

        rows.append(row)

    return rows


def collect_all(date_str: Optional[str] = None) -> dict:
    if date_str is None:
        date_str = get_last_trading_day()

    logger.info(f"Collecting data for trading day: {date_str}")

    market = get_market_summary(date_str)
    fx_gold = get_fx_and_gold(date_str)
    stocks = get_stock_data(date_str)

    return {
        "date": date_str,
        "market": market,
        "fx_gold": fx_gold,
        "stocks": stocks,
    }
