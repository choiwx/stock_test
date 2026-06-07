"""AI-powered analysis sections using Gemini API (google-genai SDK)."""
import logging
import os

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

PREFERRED_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-flash-latest",
    "gemini-2.0-flash-001",
    "gemini-1.5-flash",
]
_cached_model = None


def _resolve_model(client) -> str:
    global _cached_model
    if _cached_model:
        return _cached_model
    available = []
    for m in client.models.list():
        actions = getattr(m, "supported_actions", None) or []
        if not actions or "generateContent" in actions:
            available.append(m.name.replace("models/", ""))
    for pref in PREFERRED_MODELS:
        if pref in available:
            _cached_model = pref
            return pref
    if available:
        _cached_model = available[0]
        return available[0]
    raise RuntimeError("사용 가능한 Gemini 모델이 없습니다.")


def _generate(client, model, prompt, max_tokens, disable_thinking):
    cfg_args = {"max_output_tokens": max_tokens, "temperature": 0.7}
    if disable_thinking:
        cfg_args["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    return client.models.generate_content(
        model=model, contents=prompt,
        config=types.GenerateContentConfig(**cfg_args),
    )


def _call(prompt: str, max_tokens: int = 4096) -> str:
    try:
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        model = _resolve_model(client)
        try:
            response = _generate(client, model, prompt, max_tokens, True)
        except Exception:
            response = _generate(client, model, prompt, max_tokens, False)
        text = (response.text or "").strip()
        return text if text else "(AI 분석 결과가 비어 있습니다.)"
    except Exception as e:
        logger.error(f"Gemini API call failed: {e}")
        return f"(AI 분석을 불러오지 못했습니다. 오류: {e})"


def market_summary_analysis(data: dict) -> str:
    """Generate KOSPI/KOSDAQ/환율/금 등락 원인 요약."""
    kospi = data["market"].get("kospi", {})
    kosdaq = data["market"].get("kosdaq", {})
    usdkrw = data["fx_gold"].get("usdkrw", {})
    gold = data["fx_gold"].get("gold", {})

    def fmt(val, spec):
        return format(val, spec) if isinstance(val, (int, float)) else 'N/A'

    prompt = f"""당신은 한국 증권시장 전문 애널리스트입니다.
아래 전일 시장 데이터를 바탕으로 시장 요약 코멘트를 한국어로 3~4문장으로 작성하세요.
전문적이고 간결하게, 주요 등락 원인과 배경을 설명해 주세요.
[주의] 제목, 날짜, 머릿말을 절대 추가하지 마세요. 본문만 바로 작성하세요.

데이터:
- KOSPI 종가: {fmt(kospi.get('close'), ',.2f')} ({fmt(kospi.get('change_pct'), '+.2f')}%)
- KOSDAQ 종가: {fmt(kosdaq.get('close'), ',.2f')} ({fmt(kosdaq.get('change_pct'), '+.2f')}%)
- USD/KRW: {fmt(usdkrw.get('close'), ',.2f')}원 ({fmt(usdkrw.get('change_pct'), '+.2f')}%)
- 금 (KRX 금시장, 원/g): {fmt(gold.get('close'), ',.0f')} ({fmt(gold.get('change_pct'), '+.2f')}%)

주요 등락 원인과 국내외 거시경제 배경을 중심으로 요약해 주세요.
"""
    return _call(prompt, max_tokens=2048)


def shinsegae_analysis(data: dict) -> str:
    """Generate (주)신세계 주가 요인 분석."""
    stocks = data["stocks"]
    shinsegae = next((s for s in stocks if s["ticker"] == "004170"), {})
    report_date = data.get("date", "")

    close = shinsegae.get("close")
    change_pct = shinsegae.get("change_pct")
    per = shinsegae.get("per")
    pbr = shinsegae.get("pbr")

    def fmt(val, spec):
        return format(val, spec) if isinstance(val, (int, float)) else 'N/A'

    prompt = f"""당신은 한국 유통/소매 섹터 전문 증권 애널리스트입니다.
아래 (주)신세계 전일 주가 데이터({report_date} 기준)를 바탕으로 주가 요인 분석을 한국어로 작성하세요.
4~5문장으로 전문적이고 구체적으로 작성해 주세요.

[주의] 제목, 날짜, 머릿말을 절대 추가하지 마세요. 본문 분석 내용만 바로 작성하세요.

데이터:
- 기준일: {report_date}
- 종가: {fmt(close, ',.0f') + '원' if isinstance(close, (int, float)) else 'N/A'}
- 전일대비 등락률: {fmt(change_pct, '+.2f') + '%' if isinstance(change_pct, (int, float)) else 'N/A'}
- PER: {fmt(per, '.2f')}
- PBR: {fmt(pbr, '.2f')}

분석에 포함할 내용:
1. 주가 등락의 주요 원인 (기업 실적, 업황, 거시경제 요인 등)
2. 밸류에이션 평가 (PER/PBR 기준 저평가/고평가 여부)
3. 단기 주가 전망 및 투자자 참고 사항
"""
    return _call(prompt, max_tokens=2048)


def retail_sector_issues(report_date: str = "") -> tuple[str, list[str]]:
    """Generate retail sector issues and return (analysis_text, reference_urls)."""
    date_context = f"기준일: {report_date}" if report_date else ""
    prompt = f"""당신은 한국 유통/소매 섹터 전문 애널리스트입니다.
{date_context}

아래 지침에 따라 국내외 유통 섹터 주요 이슈를 한국어로 작성하세요.

[작성 지침]
- 제목, 날짜, 머릿말을 절대 추가하지 마세요. 형식 항목부터 바로 작성하세요.
- 반드시 해당 기준일 전후로 실제 보도된 뉴스 기사 또는 국내 증권사 리포트(한국투자증권, 미래에셋, KB증권, NH투자증권, 삼성증권 등)에 근거한 내용만 작성하세요.
- 근거 없는 내용, 가상의 전문가 인용, 일반론적 서술은 포함하지 마세요.
- 실제 보도/리포트 내용을 기반으로 구체적인 기업명, 수치, 정책명을 포함해 작성하세요.
- 확인되지 않은 내용은 "보도에 따르면", "~로 알려졌습니다" 등의 표현으로 유보적으로 서술하세요.

[형식]
1. 국내 유통 섹터 주요 이슈 (2~3가지, 각 2~3문장, 출처 언론사/증권사명 병기)
2. 해외 유통 섹터 동향 (1~2가지, 각 2문장, 출처 병기)
"""
    analysis = _call(prompt, max_tokens=3000)

    refs = [
        "https://www.hankyung.com/economy",
        "https://www.mk.co.kr/news/stock",
        "https://finance.naver.com/sise/sise_index.naver?code=KOSPI",
        "https://www.investing.com/indices/kospi",
        "https://finance.naver.com/item/main.naver?code=004170",
    ]

    return analysis, refs
