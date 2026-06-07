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


def _get(url: str) -> dict | list:
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


def _signed_change(compare_field) -> Optional[float]:
    """
    네이버 API compareToPreviousPrice 파싱.
    dict 형태: {"code":"4","text":"하락","value":"9,000"}
    code: 1=보합, 2=상승, 3=상한, 4=하락, 5=하한
    """
    if isinstance(compare_field, dict):
        val = _num(compare_field.get("value"))
        if val is None:
            return None
        code = str(compare_field.get("code", "1"))
        return -abs(val) if code in ("4", "5") else abs(val)
    return _num(compare_field)


def _pct(close, prev) -> Optional[float]:
    if close is not None and prev and prev != 0:
        return (close - prev) / prev * 100
    return None


def _naver_prices(category: str, reuters_code: str, page_size: int = 5) -> list:
    """
    네이버 front-api marketIndex/prices 공통 호출.
    금(M04020000), 외환(FX_USDKRW) 등에 사용.
    """
    url = (
        "https://m.stock.naver.com/front-api/marketIndex/prices"
        f"?category={category}&reutersCode={reuters_code}&page=1&pageSize={page_size}"
    )
    data = _get(url)
    prices = data.get("result") or data.get("prices") or []
    if isinstance(prices, dict):
        prices = prices.get("prices", [])
    return prices


def get_last_trading_day(base_date: Optional[datetime] = None) -> str:
    """가장 최근 KRX 거래일(YYYYMMDD) — 네이버 KOSPI 데이터 기반."""
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
    """KOSPI / KOSDAQ 지수 — 네이버 /api/index/{code}/basic."""
    result = {"date": date_str, "kospi": {}, "kosdaq": {}}

    for key, index_code in [("kospi", "KOSPI"), ("kosdaq", "KOSDAQ")]:
        try:
            data = _get(f"https://m.stock.naver.com/api/index/{index_code}/basic")
            close = _num(data.get("closePrice"))
            change = _signed_change(data.get("compareToPreviousPrice"))
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
    원/달러: 네이버 front-api (FX_USDKRW) — 금 API와 동일한 방식.
    금: KRX 금시장 국내금 g당 원화 — 네이버 front-api (M04020000).
    """
    result = {"usdkrw": {}, "gold": {}}

    # ── 원/달러 환율 ──────────────────────────────────────────────
    try:
        prices = _naver_prices("exchange", "FX_USDKRW", page_size=5)
        if len(prices) >= 2:
            close = _num(prices[0].get("closePrice"))
            prev_close = _num(prices[1].get("closePrice"))
            if close is not None:
                result["usdkrw"] = {
                    "close": close,
                    "change": (close - prev_close) if prev_close is not None else None,
                    "change_pct": _pct(close, prev_close),
                }
    except Exception as e:
        logger.warning(f"USD/KRW (Naver front-api) fetch failed: {e}")
        # Fallback: /api/forex endpoint
        try:
            data = _get("https://m.stock.naver.com/api/forex/FX_USDKRW/basic")
            close = _num(data.get("closePrice") or data.get("basePrice"))
            change = _signed_change(data.get("compareToPreviousPrice"))
            change_pct = _num(data.get("fluctuationsRatio") or data.get("changeRate"))
            if close is not None:
                result["usdkrw"] = {
                    "close": close,
                    "change": change,
                    "change_pct": change_pct,
                }
        except Exception as e2:
            logger.warning(f"USD/KRW fallback fetch failed: {e2}")

    # ── KRX 국내금 현물 (KRW/g) ──────────────────────────────────
    try:
        prices = _naver_prices("metals", "M04020000", page_size=10)
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
    신세계그룹 종목 — 네이버 /api/stock/{code}/basic.

    실제 응답 구조:
      closePrice: "650,000"                          ← 종가
      compareToPreviousPrice: {"code":"4","value":"9,000"}  ← 전일대비
      fluctuationsRatio: "-1.37"                     ← 등락률
      accumulatedTradingVolume: "12,345"             ← 거래량
      stockItemTotalInfos: [                         ← PER, PBR 등 지표 목록
        {"code":"PER", "value":"15.23", ...},
        {"code":"PBR", "value":"0.85", ...},
      ]
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
            change = _signed_change(data.get("compareToPreviousPrice"))

            change_pct = _num(data.get("fluctuationsRatio"))
            if change is None and close is not None and change_pct is not None:
                prev_close_est = close / (1 + change_pct / 100)
                change = close - prev_close_est

            prev_close = (close - change) if (close is not None and change is not None) else None
            volume = _num(data.get("accumulatedTradingVolume") or data.get("tradingVolume"))

            # PER / PBR — stockItemTotalInfos 배열에서 추출
            per, pbr = None, None
            for item in data.get("stockItemTotalInfos", []):
                code = str(item.get("code", "") or item.get("key", "") or "")
                val = item.get("value")
                if code.upper() == "PER":
                    per = _num(val)
                elif code.upper() == "PBR":
                    pbr = _num(val)
            if per is None:
                per = _num(data.get("per"))
            if pbr is None:
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
