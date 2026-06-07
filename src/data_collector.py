"""Market data collection using FinanceDataReader."""
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


def _fetch_fdr(symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
    import FinanceDataReader as fdr
    return fdr.DataReader(symbol, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))


def _latest_two_rows(df: pd.DataFrame) -> Optional[tuple]:
    """Return (latest_row, prev_row) or None if insufficient data."""
    if df is None or df.empty or len(df) < 2:
        return None
    return df.iloc[-1], df.iloc[-2]


def _pct(close, prev):
    if prev and prev != 0:
        return (close - prev) / prev * 100
    return None


def get_last_trading_day(base_date: Optional[datetime] = None) -> str:
    """Return the most recent KRX trading day (YYYYMMDD) using actual data availability."""
    import FinanceDataReader as fdr
    if base_date is None:
        base_date = datetime.today()

    for delta in range(1, 14):
        candidate = base_date - timedelta(days=delta)
        # Skip weekends early (KRX never trades Sat/Sun)
        if candidate.weekday() >= 5:
            continue
        date_str = candidate.strftime("%Y-%m-%d")
        try:
            df = fdr.DataReader("KS11", date_str, date_str)
            if not df.empty:
                return candidate.strftime("%Y%m%d")
        except Exception:
            continue

    return (base_date - timedelta(days=1)).strftime("%Y%m%d")


def get_market_summary(date_str: str) -> dict:
    """
    KOSPI/KOSDAQ: KRX 정규장 종가 (FDR KS11/KQ11).
    Fetches up to 14 days back to get at least 2 trading days for change calculation.
    """
    end = datetime.strptime(date_str, "%Y%m%d")
    start = end - timedelta(days=14)
    result = {"date": date_str, "kospi": {}, "kosdaq": {}}

    for key, symbol in [("kospi", "KS11"), ("kosdaq", "KQ11")]:
        try:
            df = _fetch_fdr(symbol, start, end)
            pair = _latest_two_rows(df)
            if pair:
                latest, prev = pair
                close = float(latest["Close"])
                prev_close = float(prev["Close"])
                result[key] = {
                    "close": close,
                    "change": close - prev_close,
                    "change_pct": _pct(close, prev_close),
                    "volume": int(latest.get("Volume", 0)),
                }
        except Exception as e:
            logger.warning(f"{symbol} fetch failed: {e}")

    return result


def get_fx_and_gold(date_str: str) -> dict:
    """
    원/달러: 서울외국환중개 기준 — FDR USD/KRW (매매기준율, 서울외환시장 종가 반영)
    금: KRX 금시장 1kg 현물 g당 종가 — FDR KRX/GOLD
         KRX/GOLD 미지원 시 국제 금 선물(GC=F) * USD/KRW / 31.1035 로 KRW/g 환산
    """
    end = datetime.strptime(date_str, "%Y%m%d")
    start = end - timedelta(days=14)
    result = {"usdkrw": {}, "gold": {}}

    # ── 원/달러 환율 ──────────────────────────────────────────────
    try:
        df = _fetch_fdr("USD/KRW", start, end)
        pair = _latest_two_rows(df)
        if pair:
            latest, prev = pair
            close = float(latest["Close"])
            prev_close = float(prev["Close"])
            result["usdkrw"] = {
                "close": close,
                "change": close - prev_close,
                "change_pct": _pct(close, prev_close),
            }
    except Exception as e:
        logger.warning(f"USD/KRW fetch failed: {e}")

    # ── KRX 금현물 (g당 원화) ─────────────────────────────────────
    krx_gold_ok = False
    try:
        df = _fetch_fdr("KRX/GOLD", start, end)
        pair = _latest_two_rows(df)
        if pair:
            latest, prev = pair
            close = float(latest["Close"])
            prev_close = float(prev["Close"])
            result["gold"] = {
                "close": close,
                "change": close - prev_close,
                "change_pct": _pct(close, prev_close),
                "unit": "KRW/g",
            }
            krx_gold_ok = True
    except Exception as e:
        logger.warning(f"KRX/GOLD fetch failed: {e}")

    if not krx_gold_ok:
        # Fallback: 국제 금 선물 (USD/troy-oz) → KRW/g
        try:
            df_gc = _fetch_fdr("GC=F", start, end)
            usd_krw = result["usdkrw"].get("close")
            pair = _latest_two_rows(df_gc)
            if pair and usd_krw:
                latest, prev = pair
                close_usd = float(latest["Close"])
                prev_usd = float(prev["Close"])
                TROY_OZ_TO_G = 31.1035
                close = close_usd * usd_krw / TROY_OZ_TO_G
                prev_close = prev_usd * usd_krw / TROY_OZ_TO_G
                result["gold"] = {
                    "close": close,
                    "change": close - prev_close,
                    "change_pct": _pct(close, prev_close),
                    "unit": "KRW/g (환산)",
                }
        except Exception as e:
            logger.warning(f"Gold fallback (GC=F) fetch failed: {e}")

    return result


def get_stock_data(date_str: str) -> list[dict]:
    """
    신세계그룹 종목 OHLCV: FDR 종목코드
    PER/PBR: yfinance .KS suffix
    """
    end = datetime.strptime(date_str, "%Y%m%d")
    start = end - timedelta(days=14)
    rows = []

    for ticker, name in SHINSEGAE_TICKERS.items():
        row = {"ticker": ticker, "name": name}
        row.update({"close": None, "prev_close": None, "change": None, "change_pct": None,
                    "volume": None, "per": None, "pbr": None})

        # ── OHLCV ──
        try:
            import FinanceDataReader as fdr
            df = fdr.DataReader(ticker, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
            pair = _latest_two_rows(df)
            if pair:
                latest, prev = pair
                close = float(latest["Close"])
                prev_close = float(prev["Close"])
                row["close"] = close
                row["prev_close"] = prev_close
                row["change"] = close - prev_close
                row["change_pct"] = _pct(close, prev_close)
                row["volume"] = int(latest.get("Volume", 0))
        except Exception as e:
            logger.warning(f"OHLCV fetch failed for {ticker}: {e}")

        # ── PER / PBR ──
        try:
            import yfinance as yf
            info = yf.Ticker(f"{ticker}.KS").info
            per = info.get("trailingPE") or info.get("forwardPE")
            pbr = info.get("priceToBook")
            row["per"] = float(per) if per else None
            row["pbr"] = float(pbr) if pbr else None
        except Exception as e:
            logger.warning(f"PER/PBR fetch failed for {ticker}: {e}")

        rows.append(row)

    return rows


def collect_all(date_str: Optional[str] = None) -> dict:
    """Collect all data needed for the report."""
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
