"""Market data collection using FinanceDataReader."""
import logging
from datetime import datetime, timedelta
from typing import Optional
import FinanceDataReader as fdr
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


def _num(val) -> Optional[float]:
    if val is None:
        return None
    try:
        v = float(val)
        return None if pd.isna(v) else v
    except (ValueError, TypeError):
        return None


def _get_recent_df(code: str, days_back: int = 10) -> Optional[pd.DataFrame]:
    end = datetime.today()
    start = end - timedelta(days=days_back)
    try:
        df = fdr.DataReader(code, start, end)
        if df is None or df.empty:
            logger.warning(f"FDR: {code} 데이터 없음")
            return None
        df = df.dropna(how="all")
        return df if not df.empty else None
    except Exception as e:
        logger.warning(f"FDR: {code} 조회 실패 — {e}")
        return None


def get_last_trading_day(base_date: Optional[datetime] = None) -> str:
    if base_date is None:
        base_date = datetime.today()
    df = _get_recent_df("KS11", days_back=14)
    if df is not None and not df.empty:
        return df.index[-1].strftime("%Y%m%d")
    for delta in range(1, 14):
        candidate = base_date - timedelta(days=delta)
        if candidate.weekday() < 5:
            return candidate.strftime("%Y%m%d")
    return (base_date - timedelta(days=1)).strftime("%Y%m%d")


def get_market_summary(date_str: str) -> dict:
    """KOSPI / KOSDAQ 지수."""
    result = {"date": date_str, "kospi": {}, "kosdaq": {}}

    for key, code in [("kospi", "KS11"), ("kosdaq", "KQ11")]:
        df = _get_recent_df(code, days_back=14)
        if df is None or len(df) < 1:
            logger.warning(f"{code} 데이터 없음")
            continue
        try:
            row = df.iloc[-1]
            close = _num(row.get("Close"))
            change = _num(row.get("Comp"))
            change_pct_raw = _num(row.get("Change"))
            change_pct = change_pct_raw * 100 if change_pct_raw is not None else None
            if close is not None:
                result[key] = {"close": close, "change": change, "change_pct": change_pct}
                logger.info(f"{code}: close={close}, change={change}, change_pct={change_pct:.2f}%")
        except Exception as e:
            logger.warning(f"{code} 파싱 실패: {e}")

    return result


def get_fx_and_gold(date_str: str) -> dict:
    """원/달러 환율 및 금 시세."""
    result = {"usdkrw": {}, "gold": {}}

    # 원/달러 환율
    df = _get_recent_df("USD/KRW", days_back=14)
    if df is not None and len(df) >= 2:
        try:
            close = _num(df["Close"].iloc[-1])
            prev_close = _num(df["Close"].iloc[-2])
            if close is not None:
                change = (close - prev_close) if prev_close else None
                change_pct = ((close - prev_close) / prev_close * 100) if prev_close else None
                result["usdkrw"] = {"close": close, "change": change, "change_pct": change_pct}
                logger.info(f"USD/KRW: close={close}, change_pct={change_pct:.2f}%" if change_pct else f"USD/KRW: close={close}")
        except Exception as e:
            logger.warning(f"USD/KRW 파싱 실패: {e}")
    else:
        logger.warning("USD/KRW 데이터 없음 (Yahoo Finance 차단 가능)")

    # 금 시세 — 네이버 M04020000 (KRX 국내금 현물 KRW/g)
    import requests as _req

    def _parse_gold_price(p):
        v = str(p.get("closePrice", "") or p.get("close", "") or p.get("price", "") or "").replace(",", "")
        try:
            return float(v) or None
        except ValueError:
            return None

    _gold_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://m.stock.naver.com/",
    }
    _gold_urls = [
        "https://m.stock.naver.com/front-api/marketIndex/prices?category=metals&reutersCode=M04020000",
        "https://m.stock.naver.com/front-api/marketIndex/prices?category=metals&reutersCode=M04020000&count=5",
        "https://m.stock.naver.com/front-api/marketIndex/prices?category=gold&reutersCode=M04020000&page=1&pageSize=5",
        "https://m.stock.naver.com/front-api/marketIndex/M04020000/prices",
        "https://m.stock.naver.com/api/index/M04020000/basic",
        "https://m.stock.naver.com/front-api/marketIndex/prices?category=metals&reutersCode=M04020000&page=1&pageSize=5",
    ]
    for _gold_url in _gold_urls:
        try:
            r = _req.get(_gold_url, headers=_gold_headers, timeout=10)
            r.raise_for_status()
            data = r.json()
            logger.info(f"Gold URL 성공: {_gold_url[:70]}, keys={list(data.keys()) if isinstance(data, dict) else type(data)}")

            # /basic 엔드포인트: 단일 객체 응답
            if isinstance(data, dict) and "closePrice" in data:
                close = _parse_gold_price(data)
                prev = data.get("previousClosePrice") or data.get("basePrice")
                prev_close = float(str(prev).replace(",", "")) if prev else None
                if close:
                    result["gold"] = {
                        "close": close,
                        "change": (close - prev_close) if prev_close else None,
                        "change_pct": ((close - prev_close) / prev_close * 100) if prev_close else None,
                        "unit": "KRW/g",
                    }
                    logger.info(f"Gold (KRX M04020000): {close:,.0f} KRW/g")
                    break

            # prices 배열 응답
            prices = data.get("result") or data.get("prices") or data.get("data") or []
            if isinstance(prices, dict):
                prices = prices.get("prices", [])
            if isinstance(prices, list) and len(prices) >= 2:
                close = _parse_gold_price(prices[0])
                prev_close = _parse_gold_price(prices[1])
                if close:
                    result["gold"] = {
                        "close": close,
                        "change": (close - prev_close) if prev_close else None,
                        "change_pct": ((close - prev_close) / prev_close * 100) if prev_close else None,
                        "unit": "KRW/g",
                    }
                    logger.info(f"Gold (KRX M04020000): {close:,.0f} KRW/g")
                    break
        except Exception as e:
            logger.warning(f"Gold URL 실패 ({_gold_url[:65]}): {e}")
    else:
        logger.warning("KRX 금 시세: 모든 엔드포인트 실패")

    return result


def get_stock_data(date_str: str) -> list[dict]:
    """신세계그룹 종목 — FinanceDataReader."""
    rows = []

    for ticker, name in SHINSEGAE_TICKERS.items():
        row = {
            "ticker": ticker, "name": name,
            "close": None, "prev_close": None, "change": None,
            "change_pct": None, "volume": None, "per": None, "pbr": None,
        }

        df = _get_recent_df(ticker, days_back=14)
        if df is None or df.empty:
            logger.warning(f"종목 {ticker} ({name}) 데이터 없음")
            rows.append(row)
            continue

        try:
            logger.info(f"종목 {ticker} 컬럼: {list(df.columns)}, 최근 {len(df)}일")
            last = df.iloc[-1]
            prev = df.iloc[-2] if len(df) >= 2 else None

            close = _num(last.get("Close"))
            prev_close = _num(prev.get("Close")) if prev is not None else None
            change = (close - prev_close) if (close and prev_close) else None
            change_pct = (change / prev_close * 100) if (change and prev_close) else None
            volume = _num(last.get("Volume"))

            row.update({
                "close": close,
                "prev_close": prev_close,
                "change": change,
                "change_pct": change_pct,
                "volume": int(volume) if volume is not None else None,
                "per": None,
                "pbr": None,
            })
            logger.info(f"종목 {ticker}: close={close}, change={change}, change_pct={change_pct}")
        except Exception as e:
            logger.warning(f"종목 {ticker} 파싱 실패: {e}")

        rows.append(row)

    return rows


def collect_all(date_str: Optional[str] = None) -> dict:
    if date_str is None:
        date_str = get_last_trading_day()
    logger.info(f"Collecting data for trading day: {date_str}")
    market = get_market_summary(date_str)
    fx_gold = get_fx_and_gold(date_str)
    stocks = get_stock_data(date_str)
    return {"date": date_str, "market": market, "fx_gold": fx_gold, "stocks": stocks}
