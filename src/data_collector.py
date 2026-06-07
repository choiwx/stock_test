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

            # /basic 엔드포인트: 단일 객체 응답
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
                    logger.info(f"Gold: {close:,.0f} KRW/g")
                    break
        except Exception as e:
            logger.warning(f"Gold URL 실패 ({_gold_url[:65]}): {e}")
    else:
        logger.warning("KRX 금 시세: 모든 엔드포인트 실패")

    return result


def _get_naver_per_pbr(ticker: str) -> tuple[Optional[float], Optional[float], str]:
    """
    네이버 증권 동일업종비교 표(coinfo iframe)에서 해당 종목의 PER, PBR 추출.
    실패 시 모바일 API /basic fallback.
    반환: (per, pbr, source_note)
    """
    per, pbr = None, None

    # ── 1단계: coinfo 동일업종비교 iframe ──────────────────────────
    try:
        from bs4 import BeautifulSoup

        # 동일업종비교 표는 main.naver에서 JS로 동적 로드되므로 iframe URL 직접 호출
        r = requests.get(
            f"https://finance.naver.com/item/coinfo.naver?code={ticker}&target=compare",
            headers=_NAVER_HTML_HEADERS, timeout=15,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        target_table = None
        for tbl in soup.find_all("table"):
            ths_text = [th.get_text(strip=True) for th in tbl.find_all("th")]
            # "PER"과 "PBR" 정확히 일치하는 헤더가 있는 테이블
            if "PER" in ths_text and "PBR" in ths_text:
                target_table = tbl
                break
            # "업종PER" 포함하는 경우도 허용 (PBR은 정확 일치)
            if any(h == "PER" or h == "업종PER" for h in ths_text) and "PBR" in ths_text:
                target_table = tbl
                break

        if target_table is not None:
            # 모든 헤더 행을 합쳐서 열 이름 목록 구성 (rowspan 대응)
            all_header_cells = []
            for row in target_table.find_all("tr"):
                cells = row.find_all("th")
                if cells:
                    all_header_cells = [c.get_text(strip=True) for c in cells]

            per_idx = next((i for i, h in enumerate(all_header_cells) if h == "PER"), None)
            pbr_idx = next((i for i, h in enumerate(all_header_cells) if h == "PBR"), None)
            logger.info(f"{ticker} 동일업종비교 헤더: {all_header_cells}, PER={per_idx}, PBR={pbr_idx}")

            if per_idx is not None or pbr_idx is not None:
                # 데이터 행: td만 있는 첫 번째 tr = 해당 종목 본인
                for row in target_table.find_all("tr"):
                    tds = row.find_all("td")
                    if not tds:
                        continue
                    if per_idx is not None and per_idx < len(tds):
                        per = _num(tds[per_idx].get_text(strip=True))
                    if pbr_idx is not None and pbr_idx < len(tds):
                        pbr = _num(tds[pbr_idx].get_text(strip=True))
                    break

            logger.info(f"{ticker} PER={per}, PBR={pbr} (동일업종비교)")
            if per is not None or pbr is not None:
                return per, pbr, "네이버 증권 (동일업종비교)"

    except ImportError:
        logger.warning("beautifulsoup4 미설치 — PER/PBR 수집 불가")
        return None, None, ""
    except Exception as e:
        logger.warning(f"{ticker} 동일업종비교 파싱 실패: {e}")

    # ── 2단계: 모바일 API fallback ─────────────────────────────────
    try:
        r = requests.get(
            f"https://m.stock.naver.com/api/stock/{ticker}/basic",
            headers=_NAVER_HEADERS, timeout=10,
        )
        r.raise_for_status()
        data = r.json()

        per = _num(data.get("per") or data.get("trailingPE"))
        pbr = _num(data.get("pbr") or data.get("priceToBook"))

        for item in data.get("stockItemTotalInfos", []):
            code_field = str(item.get("code", "") or item.get("key", "") or "").upper()
            val = item.get("value")
            if code_field == "PER" and per is None:
                per = _num(val)
            elif code_field == "PBR" and pbr is None:
                pbr = _num(val)

        if per is not None or pbr is not None:
            logger.info(f"{ticker} PER={per}, PBR={pbr} (모바일 API fallback)")
            return per, pbr, "네이버 증권 API"
    except Exception as e:
        logger.info(f"{ticker} 모바일 API 실패: {e}")

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

        # PER/PBR — 네이버 증권
        per, pbr, src = _get_naver_per_pbr(ticker)
        row["per"] = per
        row["pbr"] = pbr
        if src and not per_pbr_source:
            per_pbr_source = src

        rows.append(row)

    # 출처 메타 정보를 rows에 첨부 (report_generator에서 사용)
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
