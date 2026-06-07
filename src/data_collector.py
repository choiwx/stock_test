"""Market data collection using FinanceDataReader."""
import logging
import re
import requests
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

_NAVER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://m.stock.naver.com/",
}

_NAVER_HTML_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://finance.naver.com/",
}


def _num(val) -> Optional[float]:
    if val is None:
        return None
    try:
        v = float(str(val).replace(",", "").replace("%", "").strip())
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
                logger.info(f"USD/KRW: close={close}")
        except Exception as e:
            logger.warning(f"USD/KRW 파싱 실패: {e}")
    else:
        logger.warning("USD/KRW 데이터 없음")

    # 금 시세 — 네이버 M04020000 (KRX 국내금 현물 KRW/g)
    def _parse_gold_price(p):
        v = str(p.get("closePrice", "") or p.get("close", "") or p.get("price", "") or "").replace(",", "")
        try:
            return float(v) or None
        except ValueError:
            return None

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
            r = requests.get(_gold_url, headers=_NAVER_HEADERS, timeout=10)
            r.raise_for_status()
            data = r.json()
            logger.info(f"Gold URL 성공: {_gold_url[:70]}")

            if isinstance(data, dict) and "closePrice" in data:
                close = _num(data.get("closePrice"))
                prev = data.get("previousClosePrice") or data.get("basePrice")
                prev_close = _num(prev)
                if close:
                    result["gold"] = {
                        "close": close,
                        "change": (close - prev_close) if prev_close else None,
                        "change_pct": ((close - prev_close) / prev_close * 100) if prev_close else None,
                        "unit": "KRW/g",
                    }
                    logger.info(f"Gold: {close:,.0f} KRW/g")
                    break

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
                    logger.info(f"Gold: {close:,.0f} KRW/g")
                    break
        except Exception as e:
            logger.warning(f"Gold URL 실패 ({_gold_url[:65]}): {e}")
    else:
        logger.warning("KRX 금 시세: 모든 엔드포인트 실패")

    return result


def _get_naver_per_pbr(ticker: str, name: str = "") -> tuple[Optional[float], Optional[float], str]:
    """
    네이버 증권 동일업종비교 표에서 lxml XPath로 PER/PBR 추출.
    PER → //table/tbody/tr[13]/td[1]
    PBR → //table/tbody/tr[14]/td[1]
    반환: (per, pbr, source_note)
    """
    try:
        from lxml import etree

        url = f"https://finance.naver.com/item/coinfo.naver?code={ticker}&target=compare"
        r = requests.get(url, headers=_NAVER_HTML_HEADERS, timeout=15)
        logger.info(f"{ticker} coinfo HTTP {r.status_code}, 응답 길이={len(r.content)}")

        tree = etree.HTML(r.content)

        # 진단: 모든 테이블과 행 수 로깅
        tables = tree.xpath("//table")
        logger.info(f"{ticker} 테이블 수={len(tables)}")
        for i, tbl in enumerate(tables[:3]):
            rows = tbl.xpath(".//tr")
            logger.info(f"{ticker} table[{i}] 행수={len(rows)}, 샘플행13={[''.join(c.itertext()).strip() for c in rows[12].xpath('td')][:4] if len(rows) > 12 else 'N/A'}")

        per_nodes = tree.xpath("//table/tbody/tr[13]/td[1]")
        pbr_nodes = tree.xpath("//table/tbody/tr[14]/td[1]")

        # tbody 없는 경우 fallback
        if not per_nodes:
            per_nodes = tree.xpath("//table/tr[13]/td[1]")
        if not pbr_nodes:
            pbr_nodes = tree.xpath("//table/tr[14]/td[1]")

        per_text = "".join(per_nodes[0].itertext()).strip() if per_nodes else None
        pbr_text = "".join(pbr_nodes[0].itertext()).strip() if pbr_nodes else None

        logger.info(f"{ticker} XPath raw → PER={per_text!r}, PBR={pbr_text!r}")

        per = _num(per_text)
        pbr = _num(pbr_text)

        if per is not None or pbr is not None:
            logger.info(f"{ticker} PER={per}, PBR={pbr} (동일업종비교 XPath)")
            return per, pbr, "네이버 증권 (동일업종비교)"

    except Exception as e:
        logger.warning(f"{ticker} XPath 크롤링 실패: {e}")

    return None, None, ""


def get_stock_data(date_str: str) -> list[dict]:
    """신세계그룹 종목 — FinanceDataReader + 네이버 PER/PBR."""
    rows = []
    per_pbr_source = ""

    for ticker, name in SHINSEGAE_TICKERS.items():
        row = {
            "ticker": ticker, "name": name,
            "close": None, "prev_close": None, "change": None,
            "change_pct": None, "volume": None, "per": None, "pbr": None,
        }

        # 시세 — FDR
        df = _get_recent_df(ticker, days_back=14)
        if df is None or df.empty:
            logger.warning(f"종목 {ticker} ({name}) 데이터 없음")
        else:
            try:
                last = df.iloc[-1]
                prev = df.iloc[-2] if len(df) >= 2 else None
                close = _num(last.get("Close"))
                prev_close = _num(prev.get("Close")) if prev is not None else None
                change = (close - prev_close) if (close and prev_close) else None
                change_pct = (change / prev_close * 100) if (change and prev_close) else None
                volume = _num(last.get("Volume"))
                row.update({
                    "close": close, "prev_close": prev_close,
                    "change": change, "change_pct": change_pct,
                    "volume": int(volume) if volume is not None else None,
                })
                logger.info(f"종목 {ticker}: close={close}, change_pct={change_pct:.2f}%" if change_pct else f"종목 {ticker}: close={close}")
            except Exception as e:
                logger.warning(f"종목 {ticker} 시세 파싱 실패: {e}")

        # PER/PBR — 네이버 동일업종비교 XPath
        per, pbr, src = _get_naver_per_pbr(ticker, name)
        row["per"] = per
        row["pbr"] = pbr
        if src and not per_pbr_source:
            per_pbr_source = src

        rows.append(row)

    for r in rows:
        r["_per_pbr_source"] = per_pbr_source

    return rows


def collect_all(date_str: Optional[str] = None) -> dict:
    if date_str is None:
        date_str = get_last_trading_day()
    logger.info(f"Collecting data for trading day: {date_str}")
    market = get_market_summary(date_str)
    fx_gold = get_fx_and_gold(date_str)
    stocks = get_stock_data(date_str)

    per_pbr_source = stocks[0].get("_per_pbr_source", "네이버 증권") if stocks else "네이버 증권"

    return {
        "date": date_str,
        "market": market,
        "fx_gold": fx_gold,
        "stocks": stocks,
        "per_pbr_source": per_pbr_source,
    }
