"""Market data collection using Naver Finance API only."""
import logging
from datetime import datetime, timedelta
from typing import Optional
import requests

logger = logging.getLogger(__name__)

SHINSEGAE_TICKERS = {
    "004170": "(주)신세계",
    "037710": "(주)광주신세계",
    "031430": "(주)신세계인터내셔날",
    "035510": "(주)신세계아이앤씨",
    "139480": "(주)이마트",
    "031440": "(주)신세계푸드",
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Referer": "https://m.stock.naver.com/",
}


def _get(url: str) -> dict | list:
    r = requests.get(url, headers=_HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def _num(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "").replace("%", "").strip())
    except (ValueError, AttributeError):
        return None


def _pct(close, prev) -> Optional[float]:
    if close is not None and prev and prev != 0:
        return (close - prev) / prev * 100
    return None


def get_last_trading_day(base_date: Optional[datetime] = None) -> str:
    if base_date is None:
        base_date = datetime.today()
    for delta in range(1, 14):
        candidate = base_date - timedelta(days=delta)
        if candidate.weekday() >= 5:
            continue
        try:
            data = _get("https://m.stock.naver.com/api/index/KOSPI/basic")
            if _num(data.get("closePrice")) is not None:
                return candidate.strftime("%Y%m%d")
        except Exception:
            continue
    return (base_date - timedelta(days=1)).strftime("%Y%m%d")


def get_market_summary(date_str: str) -> dict:
    result = {"date": date_str, "kospi": {}, "kosdaq": {}}
    for key, index_code in [("kospi", "KOSPI"), ("kosdaq", "KOSDAQ")]:
        try:
            data = _get(f"https://m.stock.naver.com/api/index/{index_code}/basic")
            close = _num(data.get("closePrice"))
            compare = data.get("compareToPreviousPrice", {})
            if isinstance(compare, dict):
                val = _num(compare.get("value"))
                code = str(compare.get("code", "1"))
                change = -abs(val) if (val and code in ("4", "5")) else val
            else:
                change = _num(compare)
            change_pct = _num(data.get("fluctuationsRatio"))
            if close is not None:
                result[key] = {"close": close, "change": change, "change_pct": change_pct}
        except Exception as e:
            logger.warning(f"{index_code} failed: {e}")
    return result


def _try_get_prices(urls_and_parsers: list) -> Optional[list]:
    """여러 URL을 순서대로 시도해서 가격 리스트를 반환."""
    for url in urls_and_parsers:
        try:
            data = _get(url)
            logger.info(f"Success: {url[:80]}")
            # 다양한 응답 구조 처리
            if isinstance(data, list):
                prices = data
            elif isinstance(data, dict):
                prices = (data.get("result") or data.get("prices") or
                          data.get("data") or data.get("items") or [])
                if isinstance(prices, dict):
                    prices = prices.get("prices", [])
            else:
                continue
            if prices:
                return prices
        except Exception as e:
            logger.info(f"Failed ({url[:60]}): {e}")
    return None


def get_fx_and_gold(date_str: str) -> dict:
    result = {"usdkrw": {}, "gold": {}}

    # 원/달러 환율 — 여러 엔드포인트 순서대로 시도
    usdkrw_urls = [
        "https://m.stock.naver.com/front-api/marketIndex/prices?category=exchange&reutersCode=FX_USDKRW&page=1&pageSize=5",
        "https://m.stock.naver.com/api/index/FX_USDKRW/prices?page=1&pageSize=5",
        "https://m.stock.naver.com/api/forex/FX_USDKRW/prices?page=1&pageSize=5",
        "https://finance.naver.com/marketindex/exchangeDailyQuote.nhn?marketindexCd=FX_USDKRW&page=1&count=5",
    ]
    prices = _try_get_prices(usdkrw_urls)
    if prices and len(prices) >= 2:
        try:
            close = _num(prices[0].get("closePrice") or prices[0].get("close") or prices[0].get("price"))
            prev_close = _num(prices[1].get("closePrice") or prices[1].get("close") or prices[1].get("price"))
            if close is not None:
                result["usdkrw"] = {
                    "close": close,
                    "change": (close - prev_close) if prev_close else None,
                    "change_pct": _pct(close, prev_close),
                }
        except Exception as e:
            logger.warning(f"USD/KRW parse error: {e}")
    else:
        logger.warning("USD/KRW: 모든 엔드포인트 실패")

    # 금 (KRX 국내금 g당 원화)
    gold_urls = [
        "https://m.stock.naver.com/front-api/marketIndex/prices?category=metals&reutersCode=M04020000&page=1&pageSize=10",
        "https://m.stock.naver.com/api/index/M04020000/prices?page=1&pageSize=5",
    ]
    prices = _try_get_prices(gold_urls)
    if prices and len(prices) >= 2:
        try:
            close = _num(prices[0].get("closePrice") or prices[0].get("close"))
            prev_close = _num(prices[1].get("closePrice") or prices[1].get("close"))
            if close is not None:
                result["gold"] = {
                    "close": close,
                    "change": (close - prev_close) if prev_close is not None else None,
                    "change_pct": _pct(close, prev_close),
                    "unit": "KRW/g",
                }
        except Exception as e:
            logger.warning(f"Gold parse error: {e}")
    else:
        logger.warning("Gold: 모든 엔드포인트 실패")

    return result


def get_stock_data(date_str: str) -> list[dict]:
    rows = []
    for ticker, name in SHINSEGAE_TICKERS.items():
        row = {
            "ticker": ticker, "name": name,
            "close": None, "prev_close": None, "change": None,
            "change_pct": None, "volume": None, "per": None, "pbr": None,
        }
        try:
            # /basic 엔드포인트 (이전에 작동 확인)
            data = _get(f"https://m.stock.naver.com/api/stock/{ticker}/basic")
            logger.info(f"Stock {ticker} API keys: {list(data.keys())[:15]}")

            close = _num(data.get("closePrice"))
            compare = data.get("compareToPreviousPrice", {})
            if isinstance(compare, dict):
                val = _num(compare.get("value"))
                code = str(compare.get("code", "1"))
                change = -abs(val) if (val and code in ("4", "5")) else val
            else:
                change = _num(compare)

            change_pct = _num(data.get("fluctuationsRatio"))
            if change is None and close is not None and change_pct is not None:
                prev_close_est = close / (1 + change_pct / 100)
                change = close - prev_close_est

            prev_close = (close - change) if (close is not None and change is not None) else None
            volume = _num(data.get("accumulatedTradingVolume"))

            per = _num(data.get("per") or data.get("trailingPE"))
            pbr = _num(data.get("pbr") or data.get("priceToBook"))

            for item in data.get("stockItemTotalInfos", []):
                if isinstance(item, dict):
                    code_field = str(item.get("code", "") or item.get("key", "") or "").upper()
                    val_str = item.get("value")
                    logger.info(f"  stockItemTotalInfos item: code={code_field}, value={val_str}")
                    if code_field == "PER" and per is None:
                        per = _num(val_str)
                    elif code_field == "PBR" and pbr is None:
                        pbr = _num(val_str)

            logger.info(f"Stock {ticker}: close={close}, per={per}, pbr={pbr}")

            row.update({
                "close": close, "prev_close": prev_close,
                "change": change, "change_pct": change_pct,
                "volume": int(volume) if volume is not None else None,
                "per": per, "pbr": pbr,
            })
        except Exception as e:
            logger.warning(f"Stock fetch failed for {ticker}: {e}")

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
