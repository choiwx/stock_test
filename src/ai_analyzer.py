"""AI-powered analysis sections using Gemini API."""
import logging
import os

import google.generativeai as genai

logger = logging.getLogger(__name__)

MODEL = "gemini-1.5-flash"


def _call(prompt: str, max_tokens: int = 1024) -> str:
    try:
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
        model = genai.GenerativeModel(
            MODEL,
            generation_config=genai.types.GenerationConfig(max_output_tokens=max_tokens),
        )
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"Gemini API call failed: {e}")
        return "(AI 분석을 불러오지 못했습니다.)"


def market_summary_analysis(data: dict) -> str:
    kospi = data["market"].get("kospi", {})
    kosdaq = data["market"].get("kosdaq", {})
    usdkrw = data["fx_gold"].get("usdkrw", {})
    gold = data["fx_gold"].get("gold", {})

    prompt = f"""당신은 한국 증권시장 전문 애널리스트입니다.
아래 전일 시장 데이터를 바탕으로 시장 요약 코멘트를 한국어로 3~4문장으로 작성하세요.
전문적이고 간결하게, 주요 등락 원인과 배경을 설명해 주세요.

데이터:
- KOSPI 종가: {kospi.get('close', 'N/A'):,.2f} ({kospi.get('change_pct', 0):+.2f}%)
- KOSDAQ 종가: {kosdaq.get('close', 'N/A'):,.2f} ({kosdaq.get('change_pct', 0):+.2f}%)
- USD/KRW: {usdkrw.get('close', 'N/A'):,.2f}원 ({usdkrw.get('change_pct', 0):+.2f}%)
- 금 선물(USD/oz): {gold.get('close', 'N/A'):,.2f} ({gold.get('change_pct', 0):+.2f}%)

주요 등락 원인과 국내외 거시경제 배경을 중심으로 요약해 주세요.
"""
    return _call(prompt, max_tokens=512)


def shinsegae_analysis(data: dict) -> str:
    stocks = data["stocks"]
    shinsegae = next((s for s in stocks if s["ticker"] == "004170"), {})

    close = shinsegae.get("close")
    change_pct = shinsegae.get("change_pct")
    per = shinsegae.get("per")
    pbr = shinsegae.get("pbr")

    prompt = f"""당신은 한국 유통/소매 섹터 전문 증권 애널리스트입니다.
아래 (주)신세계 전일 주가 데이터를 바탕으로 주가 요인 분석을 한국어로 작성하세요.
4~5문장으로 전문적이고 구체적으로 작성해 주세요.

데이터:
- 종가: {f'{close:,.0f}원' if close else 'N/A'}
- 전일대비 등락률: {f'{change_pct:+.2f}%' if change_pct is not None else 'N/A'}
- PER: {f'{per:.2f}' if per else 'N/A'}
- PBR: {f'{pbr:.2f}' if pbr else 'N/A'}

분석에 포함할 내용:
1. 주가 등락의 주요 원인 (기업 실적, 업황, 거시경제 요인 등)
2. 밸류에이션 평가 (PER/PBR 기준 저평가/고평가 여부)
3. 단기 주가 전망 및 투자자 참고 사항
"""
    return _call(prompt, max_tokens=600)


def retail_sector_issues() -> tuple[str, list[str]]:
    prompt = """당신은 한국 유통/소매 섹터 전문 애널리스트입니다.
최근 국내외 유통 섹터의 주요 이슈와 동향을 한국어로 작성하세요.

다음 형식으로 작성해 주세요:
1. 국내 유통 섹터 주요 이슈 (2~3가지, 각 2~3문장)
2. 해외 유통 섹터 동향 (1~2가지, 각 2문장)
3. 전문가 의견 (가상의 전문가 인용구 1~2개, "OO증권 OO 애널리스트" 형식)

전문적이고 실제 리포트처럼 작성해 주세요.
"""
    analysis = _call(prompt, max_tokens=800)

    refs = [
        "https://www.hankyung.com/economy",
        "https://www.mk.co.kr/news/stock",
        "https://finance.naver.com/sise/sise_index.naver?code=KOSPI",
        "https://www.investing.com/indices/kospi",
        "https://finance.naver.com/item/main.naver?code=004170",
    ]

    return analysis, refs
