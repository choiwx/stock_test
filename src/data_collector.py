"""Market data collection using FinanceDataReader and yfinance."""
import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import FinanceDataReader as fdr

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
    if base_date is None:
        base_date = datetime.today()

    for delta in range(1, 8):
        candidate = base_date - timedelta(days=delta)
        if candidate.weekday() < 5:
            return candidate.strftime("%Y%m%d")

    return (base_date - timedelta(days=1)).strftime("%Y%m%d")


def _fdr_fetch(symbol: str, start: datetime, end: datetime) -> Optional[pd.DataFrame]:
    try:
        df = fdr.DataReader(symbol, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        if df is not None and not df.empty:
            return df
    except Exception as e:
        logger.warning(f"FDR fetch failed for {symbol}: {e}")
    return None


def get_market_summary(date_str: str) -> dict:
    end = datetime.strptime(date_str, "%Y%m%d")
    start = end - timedelta(days=14)
    result = {"date": date_str, "kospi": {}, "kosdaq": {}}

    for key, symbol in [("kospi", "KS11"), ("kosdaq", "KQ11")]:
        df = _fdr_fetch(symbol, start, end)
        if df is not None and len(df) >= 2:
            close = float(df["Close"].iloc[-1])
            prev_close = float(df["Close"].iloc[-2])
            change = close - prev_close
            result[key] = {
                "close": close,
                "change": change,
                "change_pct": change / prev_close * 100,
                "volume": int(df["Volume"].iloc[-1]) if "Volume" in df.columns else 0,
            }
        else:
            logger.warning(f"{key} data fetch failed")

    return result


def get_fx_and_gold(date_str: str) -> dict:
    end = datetime.strptime(date_str, "%Y%m%d")
    start = end - timedelta(days=14)
    result = {"usdkrw": {}, "gold": {}}

    for key, symbol in [("usdkrw", "USD/KRW"), ("gold", "GC=F")]:
        df = _fdr_fetch(symbol, start, end)
        if df is not None and len(df) >= 2:
            close = float(df["Close"].iloc[-1])
            prev_close = float(df["Close"].iloc[-2])
            change = close - prev_close
            result[key] = {
                "close": close,
                "change": change,
                "change_pct": change / prev_close * 100,
            }
        else:
            logger.warning(f"{key} data fetch failed")

    return result


def get_stock_data(date_str: str) -> list[dict]:
    end = datetime.strptime(date_str, "%Y%m%d")
    start = end - timedelta(days=14)
    rows = []

    for ticker, name in SHINSEGAE_TICKERS.items():
        row = {"ticker": ticker, "name": name,
               "close": None, "prev_close": None,
               "change": None, "change_pct": None,
               "volume": None, "per": None, "pbr": None}

        df = _fdr_fetch(ticker, start, end)
        if df is not None and len(df) >= 2:
            close = float(df["Close"].iloc[-1])
            prev_close = float(df["Close"].iloc[-2])
            change = close - prev_close
            row.update({
                "close": close,
                "prev_close": prev_close,
                "change": change,
                "change_pct": change / prev_close * 100,
                "volume": int(df["Volume"].iloc[-1]) if "Volume" in df.columns else None,
            })

        # PER/PBR: yfinance fallback
        try:
            import yfinance as yf
            info = yf.Ticker(f"{ticker}.KS").info
            per = info.get("trailingPE") or info.get("forwardPE")
            pbr = info.get("priceToBook")
            row["per"] = float(per) if per else None
            row["pbr"] = float(pbr) if pbr else None
        except Exception as e:
            logger.warning(f"yfinance PER/PBR fetch failed for {ticker}: {e}")

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
