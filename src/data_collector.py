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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://m.stock.naver.com/",
}


def _get(url: str) -> dict | list:
    r = requests.get(url, headers=_HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def _num(val) -> Optional[float]:
    """문자열·숫자 → float."""
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
    """가장 최근 KRX 거래일."""
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
    """KOSPI / KOSDAQ 지수 — 네이버 API."""
    result = {"date": date_str, "kospi": {}, "kosdaq": {}}

    for key, index_code in [("kospi", "KOSPI"), ("kosdaq", "KOSDAQ")]:
        try:
            data = _get(f"https://m.stock.naver.com/api/index/{index_code}/basic")
            close = _num(data.get("closePrice"))

            # compareToPreviousPrice 파싱 (dict 형태)
            compare = data.get("compareToPreviousPrice", {})
            if isinstance(compare, dict):
                val = _num(compare.get("value"))
                code = str(compare.get("code", "1"))
                change = -abs(val) if (val and code in ("4", "5")) else val
            else:
                change = _num(compare)

            change_pct = _num(data.get("fluctuationsRatio"))

            if close is not None:
                result[key] = {
                    "close": close,
                    "change": change,
                    "change_pct": change_pct,
                }
        except Exception as e:
            logger.warning(f"{index_code} failed: {e}")

    return result


def _naver_front_prices(category: str, reuters_code: str, page_size: int = 5) -> list:
    """네이버 front-api marketIndex/prices (금, 환율 등)."""
    try:
        url = (
            "https://m.stock.naver.com/front-api/marketIndex/prices"
            f"?category={category}&reutersCode={reuters_code}&page=1&pageSize={page_size}"
        )
        data = _get(url)
        prices = data.get("result") or data.get("prices") or []
        if isinstance(prices, dict):
            prices = prices.get("prices", [])
        return prices
    except Exception as e:
        logger.warning(f"front-api {category}/{reuters_code} failed: {e}")
        return []


def get_fx_and_gold(date_str: str) -> dict:
    """
    원/달러: 네이버 front-api (환전고시환율 매매기준율).
    금: 네이버 front-api (KRX 국내금 g당 원화).
    """
    result = {"usdkrw": {}, "gold": {}}

    # ── 원/달러 환율 (환전고시환율) — front-api 사용 ────────────
    try:
        prices = _naver_front_prices("exchange", "FX_USDKRW", page_size=5)
        if len(prices) >= 2:
            close = _num(prices[0].get("closePrice"))
            prev_close = _num(prices[1].get("closePrice"))
            if close is not None:
                result["usdkrw"] = {
                    "close": close,
                    "change": (close - prev_close) if prev_close else None,
                    "change_pct": _pct(close, prev_close),
                }
    except Exception as e:
        logger.warning(f"USD/KRW front-api failed: {e}")

    # ── 금 (KRX 국내금 현물 g당 원화) ────────────────────────────
    try:
        prices = _naver_front_prices("metals", "M04020000", page_size=10)
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
        logger.warning(f"KRX gold failed: {e}")

    return result


def get_stock_data(date_str: str) -> list[dict]:
    """신세계그룹 종목 — 네이버 API."""
    rows = []

    for ticker, name in SHINSEGAE_TICKERS.items():
        row = {
            "ticker": ticker, "name": name,
            "close": None, "prev_close": None, "change": None,
            "change_pct": None, "volume": None, "per": None, "pbr": None,
        }

        try:
            # /api/stock/{code}로 통합 정보 조회
            data = _get(f"https://m.stock.naver.com/api/stock/{ticker}")
            all_keys = list(data.keys()) if isinstance(data, dict) else []
            logger.info(f"Stock {ticker} ({name}) - All API keys: {all_keys}")

            # Log entire response for first ticker for debugging
            if ticker == "004170":
                logger.info(f"Full response for {ticker}: {data}")

            close = _num(data.get("closePrice"))

            # compareToPreviousPrice 파싱
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

            # PER / PBR — 다양한 필드명 시도
            per = _num(data.get("per") or data.get("trailingPE") or data.get("trailingPEX"))
            pbr = _num(data.get("pbr") or data.get("priceToBook"))

            logger.info(f"Stock {ticker} - PER from direct fields: {per}, PBR: {pbr}")

            # stockItemTotalInfos 또는 fundamentals 배열에서 추출
            for item in data.get("stockItemTotalInfos", []) + data.get("fundamentals", []):
                if isinstance(item, dict):
                    code_field = str(item.get("code", "") or item.get("key", "") or "").upper()
                    val = item.get("value")
                    logger.debug(f"Stock {ticker} - Array item code_field: {code_field}, value: {val}")
                    if code_field == "PER":
                        per = per or _num(val)
                    elif code_field == "PBR":
                        pbr = pbr or _num(val)

            logger.info(f"Stock {ticker} - After array extraction: PER={per}, PBR={pbr}")

            # /api/stock/{code}/summary에서 추가 시도 (PER/PBR이 없으면)
            if per is None or pbr is None:
                try:
                    summary = _get(f"https://m.stock.naver.com/api/stock/{ticker}/summary")
                    summary_keys = list(summary.keys()) if isinstance(summary, dict) else []
                    logger.info(f"Stock {ticker} - summary API keys: {summary_keys}")

                    if per is None:
                        per = _num(summary.get("per") or summary.get("trailingPE"))
                        logger.info(f"Stock {ticker} - PER from summary: {per}")
                    if pbr is None:
                        pbr = _num(summary.get("pbr") or summary.get("priceToBook"))
                        logger.info(f"Stock {ticker} - PBR from summary: {pbr}")
                except Exception as e:
                    logger.info(f"Stock {ticker} - summary API failed: {e}")

            logger.info(f"Stock {ticker} - Final PER: {per}, PBR: {pbr}")

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
            logger.warning(f"Stock fetch failed for {ticker}: {e}")

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
