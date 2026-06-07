"""Market data collection using Naver Finance API."""
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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://m.stock.naver.com/",
}


def _get(url: str) -> dict:
    r = requests.get(url, headers=_HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def _num(val) -> Optional[float]:
    """문자열·숫자 → float, 없거나 파싱 불가면 None."""
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "").replace("%", "").strip())
    except (ValueError, AttributeError):
        return None


def _extract_change(compare_dict) -> Optional[float]:
    """
    네이버 API의 compareToPreviousPrice 필드 파싱.
    {"code": "2", "text": "상승", "value": "1,234.00"} 형태.
    code: 1=보합, 2=상승, 3=상한, 4=하락, 5=하한
    """
    if not isinstance(compare_dict, dict):
        return _num(compare_dict)
    val = _num(compare_dict.get("value"))
    if val is None:
        return None
    code = str(compare_dict.get("code", "1"))
    if code in ("4", "5"):
        return -abs(val)
    return abs(val)


def _pct(close, prev) -> Optional[float]:
    if close is not None and prev and prev != 0:
        return (close - prev) / prev * 100
    return None


def get_last_trading_day(base_date: Optional[datetime] = None) -> str:
    """가장 최근 KRX 거래일(YYYYMMDD) 반환 — 네이버 KOSPI 데이터 기반."""
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
    """KOSPI / KOSDAQ 지수 — 네이버 증권 지수 API."""
    result = {"date": date_str, "kospi": {}, "kosdaq": {}}

    for key, index_code in [("kospi", "KOSPI"), ("kosdaq", "KOSDAQ")]:
        try:
            data = _get(f"https://m.stock.naver.com/api/index/{index_code}/basic")
            close = _num(data.get("closePrice"))
            change = _extract_change(data.get("compareToPreviousPrice"))
            change_pct = _num(data.get("fluctuationsRatio"))
            if close is not None:
                result[key] = {
                    "close": close,
                    "change": change,
                    "change_pct": change_pct,
                }
        except Exception as e:
            logger.warning(f"{index_code} fetch failed: {e}")

    return result


def get_fx_and_gold(date_str: str) -> dict:
    """
    원/달러: 네이버 외환 API (FX_USDKRW).
    금: KRX 금시장 현물 g당 원화 — 네이버 금시세 API (M04020000).
    """
    result = {"usdkrw": {}, "gold": {}}

    # ── 원/달러 환율 ──────────────────────────────────────────────
    try:
        data = _get("https://m.stock.naver.com/api/forex/FX_USDKRW/basic")
        close = _num(data.get("closePrice") or data.get("basePrice"))
        change = _extract_change(data.get("compareToPreviousPrice"))
        change_pct = _num(data.get("fluctuationsRatio") or data.get("changeRate"))
        if close is not None:
            result["usdkrw"] = {
                "close": close,
                "change": change,
                "change_pct": change_pct,
            }
    except Exception as e:
        logger.warning(f"USD/KRW (Naver) fetch failed: {e}")

    # ── KRX 금시장 금현물 (KRW/g) ─────────────────────────────────
    try:
        url = (
            "https://m.stock.naver.com/front-api/marketIndex/prices"
            "?category=metals&reutersCode=M04020000&page=1&pageSize=10"
        )
        data = _get(url)
        prices = data.get("result") or data.get("prices") or []
        if isinstance(prices, dict):
            prices = prices.get("prices", [])
        if len(prices) >= 2:
            close = _num(prices[0].get("closePrice"))
            prev_close = _num(prices[1].get("closePrice"))
            if close is not None:
                result["gold"] = {
                    "close": close,
                    "change": (close - prev_close) if prev_close is not None else None,
                    "change_pct": _pct(close, prev_close),
                    "unit": "KRW/g",
                }
    except Exception as e:
        logger.warning(f"KRX gold (Naver) fetch failed: {e}")

    return result


def get_stock_data(date_str: str) -> list[dict]:
    """
    신세계그룹 종목 종가·등락·PER·PBR — 네이버 증권 종목 API.
    응답 예시:
      closePrice: "650,000"
      compareToPreviousPrice: {"code":"4","text":"하락","value":"9,000"}
      fluctuationsRatio: "-1.37"
      per: "15.23"
      pbr: "0.85"
      accumulatedTradingVolume: "12,345"
    """
    rows = []

    for ticker, name in SHINSEGAE_TICKERS.items():
        row = {
            "ticker": ticker, "name": name,
            "close": None, "prev_close": None, "change": None,
            "change_pct": None, "volume": None, "per": None, "pbr": None,
        }
        try:
            data = _get(f"https://m.stock.naver.com/api/stock/{ticker}/basic")

            close = _num(data.get("closePrice"))
            change = _extract_change(data.get("compareToPreviousPrice"))
            change_pct = _num(data.get("fluctuationsRatio"))
            prev_close = (close - change) if (close is not None and change is not None) else None
            volume = _num(data.get("accumulatedTradingVolume") or data.get("tradingVolume"))
            per = _num(data.get("per"))
            pbr = _num(data.get("pbr"))

            row.update({
                "close": close,
                "prev_close": prev_close,
                "change": change,
                "change_pct": change_pct,
                "volume": int(volume) if volume is not None else None,
                "per": per,
                "pbr": pbr,
            })
        except Exception as e:
            logger.warning(f"Stock fetch failed for {ticker} ({name}): {e}")

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
