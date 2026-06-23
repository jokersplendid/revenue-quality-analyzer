#!/usr/bin/env python3
"""Revenue quality analyzer MVP for fund fee income.

This script uses only the Python standard library so the MVP can run in a fresh
environment without dependency installation.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import os
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Dict, Iterable, List, Optional, Tuple

REQUIRED_COLUMNS = [
    "record_id",
    "period",
    "recognition_date",
    "fund_product",
    "fee_type",
    "channel",
    "customer_type",
    "customer_name",
    "revenue_model",
    "recognized_revenue",
    "fee_rate_contract",
    "cash_collected",
    "invoice_amount",
    "is_new_customer",
    "is_related_party",
    "refund_after_period",
    "performance_hurdle_met",
]

PROFILE_COLUMNS = ["fund_category", "aum_size_band", "risk_exposure", "income_stability_type"]

RISK_WEIGHTS = {
    "大额收入": 20,
    "期末集中确认": 15,
    "收入复算偏差": 25,
    "合同费率偏差": 20,
    "缺少业务量/AUM支撑": 25,
    "低回款覆盖": 15,
    "期后退款或冲回": 20,
    "新客户大额收入": 15,
    "关联方收入": 20,
    "业绩报酬门槛未满足": 30,
    "发票金额不一致": 10,
    "日期缺失或异常": 10,
}

DOCUMENT_MAP = {
    "subscription_fee": "基金合同/费率表、TA申购确认、销售渠道结算单、发票、银行回单",
    "redemption_fee": "基金合同/费率表、TA赎回确认、赎回费计算表、发票、银行回单、期后退款明细",
    "management_fee": "基金合同/管理费条款、按产品/份额类别AUM明细、计费天数、基金会计结算单、银行回单",
    "sales_service_fee": "销售服务协议、C类份额AUM明细、服务费率表、渠道结算单、发票、银行回单",
    "performance_fee": "业绩报酬条款、业绩基准/门槛证明、超额收益计算表、复核记录、结算单",
}

QUESTION_MAP = {
    "收入复算偏差": "该笔收入复算金额与账面确认金额不一致，请说明差异来源，是费率优惠、渠道分成、补提还是计算口径差异？",
    "合同费率偏差": "实际费率与合同费率存在偏差，请提供费率表、补充协议或审批记录。",
    "缺少业务量/AUM支撑": "这笔收入缺少对应交易金额、平均AUM或计费天数支撑，请补充业务量明细和计算过程。",
    "期末集中确认": "该笔收入在期末确认，请说明对应交易确认日/服务期间/结算日，是否存在跨期确认风险？",
    "低回款覆盖": "该笔收入回款覆盖较低，请说明截至报告日的回款状态、未回款原因和后续收款安排。",
    "期后退款或冲回": "该笔收入期后发生退款或冲回，请说明原始交易、退款原因以及是否影响本期收入确认。",
    "新客户大额收入": "新客户首笔收入金额较大，请提供客户背景、合同、交易确认和回款证据。",
    "关联方收入": "该笔收入涉及关联方，请说明定价是否公允、交易是否具有商业实质以及是否需要抵销或披露。",
    "业绩报酬门槛未满足": "业绩报酬确认前是否已经满足计提门槛？请提供业绩基准、超额收益计算表和复核记录。",
    "发票金额不一致": "发票金额与收入确认金额不一致，请说明差异原因及后续处理。",
    "日期缺失或异常": "该笔收入关键日期缺失或异常，请补充确认日期、结算日期和服务期间证据。",
}

QUALITY_RISK_FLAGS = {
    "收入复算偏差",
    "合同费率偏差",
    "缺少业务量/AUM支撑",
    "低回款覆盖",
    "期后退款或冲回",
    "新客户大额收入",
    "关联方收入",
    "业绩报酬门槛未满足",
    "发票金额不一致",
}


@dataclass
class RevenueRecord:
    raw: Dict[str, str]
    recognized_revenue: float = 0.0
    expected_revenue: float = 0.0
    actual_rate: Optional[float] = None
    expected_variance: float = 0.0
    rate_diff: Optional[float] = None
    cash_collection_ratio: Optional[float] = None
    quality_segment: str = "未分类"
    risk_flags: List[str] = field(default_factory=list)
    risk_score: int = 0
    suggested_documents: str = ""
    follow_up_questions: str = ""

    @property
    def record_id(self) -> str:
        return self.raw.get("record_id", "")

    @property
    def fee_type(self) -> str:
        return self.raw.get("fee_type", "").strip()

    @property
    def period(self) -> str:
        return self.raw.get("period", "")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze revenue quality for fund fee income.")
    parser.add_argument("--revenue", required=True, help="Revenue detail CSV path")
    parser.add_argument("--ledger", help="Optional ledger CSV path with period,ledger_revenue")
    parser.add_argument("--out-dir", default="reports", help="Output directory")
    parser.add_argument("--top-n", type=int, default=8, help="Number of high-risk samples to select")
    parser.add_argument("--use-llm", action="store_true", help="Use an OpenAI-compatible LLM to generate insight narratives")
    parser.add_argument("--llm-base-url", default=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"), help="OpenAI-compatible API base URL")
    parser.add_argument("--llm-model", default=os.getenv("LLM_MODEL", "gpt-4.1-mini"), help="LLM model name")
    parser.add_argument("--llm-api-key-env", default="LLM_API_KEY", help="Environment variable that stores the LLM API key")
    parser.add_argument("--llm-timeout", type=int, default=60, help="LLM request timeout seconds")
    return parser.parse_args()


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_prompt(skill_root: Path) -> str:
    prompt_path = skill_root / "prompts" / "llm_insight_system_prompt.md"
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8-sig")
    return (
        "????????????????????????????"
        "???????? insight?evidence?judgment?action?"
    )


def compact_record(record: RevenueRecord) -> Dict[str, object]:
    return {
        "record_id": record.record_id,
        "period": record.period,
        "fund_product": record.raw.get("fund_product", ""),
        "fund_category": record.raw.get("fund_category", ""),
        "aum_size_band": record.raw.get("aum_size_band", ""),
        "risk_exposure": record.raw.get("risk_exposure", ""),
        "fee_type": record.fee_type,
        "recognized_revenue": round(record.recognized_revenue, 2),
        "expected_revenue": round(record.expected_revenue, 2),
        "expected_variance": round(record.expected_variance, 2),
        "cash_collection_ratio": record.cash_collection_ratio,
        "quality_segment": record.quality_segment,
        "risk_score": record.risk_score,
        "risk_flags": record.risk_flags,
    }


def build_llm_payload(records: List[RevenueRecord], selected: List[RevenueRecord]) -> Dict[str, object]:
    positive_total = sum(positive_amount(r) for r in records)
    products = group_sum(records, "fund_product", positive_only=True)
    top3_product_ratio = safe_div(sum(amount for _, amount in products[:3]), positive_total) or 0.0
    segments = dict(group_segment_sum(records))
    growth = build_growth_diagnosis(records)
    contributors: List[RevenueRecord] = growth["top_contributors"]  # type: ignore[assignment]

    metrics = {
        "total_revenue": round(sum(r.recognized_revenue for r in records), 2),
        "positive_revenue": round(positive_total, 2),
        "expected_revenue": round(sum(r.expected_revenue for r in records), 2),
        "cash_collected": round(sum(to_float(r.raw.get("cash_collected")) for r in records), 2),
        "cash_collection_ratio": safe_div(sum(to_float(r.raw.get("cash_collected")) for r in records), sum(r.recognized_revenue for r in records)),
        "top3_product_ratio": top3_product_ratio,
        "top_products": [{"name": name, "revenue": round(amount, 2), "ratio": safe_div(amount, positive_total)} for name, amount in products[:5]],
        "quality_segments": [{"segment": name, "revenue": round(amount, 2), "ratio": safe_div(amount, positive_total)} for name, amount in group_segment_sum(records)],
        "fund_category_mix": [{"category": name, "revenue": round(amount, 2), "ratio": safe_div(amount, positive_total)} for name, amount in group_sum(records, "fund_category", positive_only=True)],
        "risk_exposure_mix": [{"exposure": name, "revenue": round(amount, 2), "ratio": safe_div(amount, positive_total)} for name, amount in group_sum(records, "risk_exposure", positive_only=True)],
        "peak_period": growth.get("period"),
        "peak_period_revenue": round(float(growth.get("period_amount", 0.0)), 2),
        "previous_period": growth.get("previous_period"),
        "peak_period_growth": round(float(growth.get("growth", 0.0)), 2),
    }

    return {
        "task": "Generate decision-oriented revenue quality insights from structured audit/business analysis metrics.",
        "output_language": "Chinese",
        "metrics": metrics,
        "top_peak_contributors": [compact_record(r) for r in contributors[:5]],
        "high_risk_samples": [compact_record(r) for r in selected],
        "instructions": [
            "????????????????????????",
            "????????????????????????????????????",
            "?? JSON?{\"insights\":[{\"insight\":...,\"evidence\":...,\"judgment\":...,\"action\":...}]}",
            "?? 4 ? 6 ????",
        ],
    }


def extract_json_object(text: str) -> Dict[str, object]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def normalize_insights(raw: object) -> List[Dict[str, str]]:
    if not isinstance(raw, list):
        return []
    insights: List[Dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        insight = {
            "insight": str(item.get("insight", "")).strip(),
            "evidence": str(item.get("evidence", "")).strip(),
            "judgment": str(item.get("judgment", "")).strip(),
            "action": str(item.get("action", "")).strip(),
        }
        if all(insight.values()):
            insights.append(insight)
    return insights


def call_llm_json(
    *,
    base_url: str,
    model: str,
    api_key: str,
    system_prompt: str,
    payload: Dict[str, object],
    timeout: int,
    temperature: float = 0.2,
) -> Dict[str, object]:
    endpoint = base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM API HTTP {exc.code}: {detail}") from exc

    choices = result.get("choices", [])
    if not choices:
        raise RuntimeError("LLM API returned no choices")
    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    content = message.get("content", "") if isinstance(message, dict) else ""
    parsed = extract_json_object(str(content))
    if not isinstance(parsed, dict):
        raise RuntimeError("LLM response was not a JSON object")
    return parsed


def call_openai_compatible_llm(
    *,
    base_url: str,
    model: str,
    api_key: str,
    system_prompt: str,
    payload: Dict[str, object],
    timeout: int,
) -> List[Dict[str, str]]:
    parsed = call_llm_json(
        base_url=base_url,
        model=model,
        api_key=api_key,
        system_prompt=system_prompt,
        payload=payload,
        timeout=timeout,
    )
    insights = normalize_insights(parsed.get("insights"))
    if not insights:
        raise RuntimeError("LLM response did not contain valid insights")
    return insights


def generate_insights(
    records: List[RevenueRecord],
    selected: List[RevenueRecord],
    args: argparse.Namespace,
    skill_root: Path,
) -> Tuple[List[Dict[str, str]], str, str]:
    fallback = build_insights(records)
    if not args.use_llm:
        return fallback, "rule", "未启用 LLM，使用规则洞察。"

    api_key = os.getenv(args.llm_api_key_env)
    if not api_key:
        return fallback, "rule_fallback", f"未检测到环境变量 {args.llm_api_key_env}，已回退到规则洞察。"

    try:
        llm_insights = call_openai_compatible_llm(
            base_url=args.llm_base_url,
            model=args.llm_model,
            api_key=api_key,
            system_prompt=load_prompt(skill_root),
            payload=build_llm_payload(records, selected),
            timeout=args.llm_timeout,
        )
        return llm_insights, "llm", f"已调用 LLM 生成洞察：model={args.llm_model}, base_url={args.llm_base_url}。"
    except Exception as exc:
        return fallback, "rule_fallback", f"LLM 调用失败，已回退到规则洞察：{exc}"


def to_float(value: str | None) -> float:
    if value is None:
        return 0.0
    text = str(value).replace(",", "").strip()
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def to_bool(value: str | None) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y", "是"}


def parse_date(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def safe_div(num: float, denom: float) -> Optional[float]:
    if abs(denom) < 1e-9:
        return None
    return num / denom


def positive_amount(record: RevenueRecord) -> float:
    return max(0.0, record.recognized_revenue)


def percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * pct) - 1))
    return ordered[idx]


def calc_expected(row: Dict[str, str]) -> Tuple[float, Optional[float], Optional[float]]:
    fee_type = row.get("fee_type", "")
    recognized = to_float(row.get("recognized_revenue"))
    rate = to_float(row.get("fee_rate_contract"))
    business_volume = to_float(row.get("business_volume"))
    subscription_amount = to_float(row.get("subscription_amount")) or business_volume
    redemption_amount = to_float(row.get("redemption_amount")) or business_volume
    average_aum = to_float(row.get("average_aum"))
    performance_base = to_float(row.get("performance_base")) or business_volume
    service_days = to_float(row.get("service_days"))
    hurdle_met = to_bool(row.get("performance_hurdle_met"))

    expected = 0.0
    actual_rate = None

    if fee_type == "subscription_fee":
        expected = subscription_amount * rate
        actual_rate = safe_div(recognized, subscription_amount)
    elif fee_type == "redemption_fee":
        expected = redemption_amount * rate
        actual_rate = safe_div(recognized, redemption_amount)
    elif fee_type in {"management_fee", "sales_service_fee"}:
        denominator = average_aum * service_days / 365 if service_days else 0.0
        expected = denominator * rate
        actual_rate = safe_div(recognized, denominator)
    elif fee_type == "performance_fee":
        expected = performance_base * rate if hurdle_met else 0.0
        actual_rate = safe_div(recognized, performance_base)
    else:
        expected = business_volume * rate
        actual_rate = safe_div(recognized, business_volume)

    rate_diff = None if actual_rate is None else actual_rate - rate
    return expected, actual_rate, rate_diff


def validate_columns(rows: List[Dict[str, str]]) -> List[str]:
    if not rows:
        return ["收入明细为空，无法执行分析。"]
    missing = [col for col in REQUIRED_COLUMNS if col not in rows[0]]
    messages = []
    if missing:
        messages.append("收入明细缺少必需字段：" + ", ".join(missing))
    missing_profiles = [col for col in PROFILE_COLUMNS if col not in rows[0]]
    if missing_profiles:
        messages.append("收入明细缺少产品画像字段，将无法生成部分洞察：" + ", ".join(missing_profiles))
    return messages


def classify_quality_segment(record: RevenueRecord) -> str:
    flags = set(record.risk_flags)
    declared = record.raw.get("income_stability_type", "").strip()

    if flags & QUALITY_RISK_FLAGS:
        return "可疑增长收入"
    if "一次性" in declared or record.fee_type == "performance_fee":
        return "一次性/高不确定性收入"
    if record.fee_type in {"subscription_fee", "redemption_fee"}:
        return "交易型收入"
    if record.fee_type in {"management_fee", "sales_service_fee"}:
        return "稳定基础收入"
    return declared or "未分类收入"


def score_records(rows: List[Dict[str, str]]) -> List[RevenueRecord]:
    amounts = [abs(to_float(r.get("recognized_revenue"))) for r in rows]
    high_value_threshold = max(percentile(amounts, 0.85), median(amounts) * 2 if amounts else 0)
    records: List[RevenueRecord] = []

    for row in rows:
        record = RevenueRecord(raw=row)
        recognized = to_float(row.get("recognized_revenue"))
        record.recognized_revenue = recognized
        expected, actual_rate, rate_diff = calc_expected(row)
        record.expected_revenue = expected
        record.expected_variance = recognized - expected
        record.actual_rate = actual_rate
        record.rate_diff = rate_diff
        cash_collected = to_float(row.get("cash_collected"))
        invoice_amount = to_float(row.get("invoice_amount"))
        record.cash_collection_ratio = safe_div(cash_collected, recognized) if recognized > 0 else None

        recognition_date = parse_date(row.get("recognition_date"))
        fee_type = row.get("fee_type", "")
        business_volume = to_float(row.get("business_volume"))
        subscription_amount = to_float(row.get("subscription_amount"))
        redemption_amount = to_float(row.get("redemption_amount"))
        average_aum = to_float(row.get("average_aum"))
        service_days = to_float(row.get("service_days"))

        if abs(recognized) >= high_value_threshold and recognized > 0:
            record.risk_flags.append("大额收入")
        if recognition_date is None:
            record.risk_flags.append("日期缺失或异常")
        elif recognition_date.month == 12 or recognition_date.day >= 25:
            record.risk_flags.append("期末集中确认")

        tolerance = max(abs(expected) * 0.05, 10000.0)
        if expected != 0 and abs(record.expected_variance) > tolerance:
            record.risk_flags.append("收入复算偏差")
        if actual_rate is not None and rate_diff is not None and abs(rate_diff) > max(abs(to_float(row.get("fee_rate_contract"))) * 0.1, 0.0005):
            record.risk_flags.append("合同费率偏差")

        if fee_type in {"subscription_fee", "redemption_fee"} and recognized > 0 and max(business_volume, subscription_amount, redemption_amount) <= 0:
            record.risk_flags.append("缺少业务量/AUM支撑")
        if fee_type in {"management_fee", "sales_service_fee"} and recognized > 0 and (average_aum <= 0 or service_days <= 0):
            record.risk_flags.append("缺少业务量/AUM支撑")
        if fee_type == "performance_fee" and recognized > 0 and not to_bool(row.get("performance_hurdle_met")):
            record.risk_flags.append("业绩报酬门槛未满足")

        if record.cash_collection_ratio is not None and record.cash_collection_ratio < 0.5:
            record.risk_flags.append("低回款覆盖")
        if to_float(row.get("refund_after_period")) > 0:
            record.risk_flags.append("期后退款或冲回")
        if to_bool(row.get("is_new_customer")) and recognized >= high_value_threshold * 0.8:
            record.risk_flags.append("新客户大额收入")
        if to_bool(row.get("is_related_party")):
            record.risk_flags.append("关联方收入")
        if invoice_amount and abs(invoice_amount - recognized) > max(abs(recognized) * 0.03, 10000.0):
            record.risk_flags.append("发票金额不一致")

        record.risk_score = sum(RISK_WEIGHTS.get(flag, 5) for flag in record.risk_flags)
        record.quality_segment = classify_quality_segment(record)
        record.suggested_documents = DOCUMENT_MAP.get(fee_type, "合同、结算单、发票、银行回单、业务发生证明")
        questions = [QUESTION_MAP[flag] for flag in record.risk_flags if flag in QUESTION_MAP]
        record.follow_up_questions = "；".join(questions)
        records.append(record)

    return sorted(records, key=lambda r: (r.risk_score, abs(r.recognized_revenue)), reverse=True)


def reconcile_ledger(rows: List[Dict[str, str]], ledger_rows: List[Dict[str, str]]) -> List[Dict[str, float | str]]:
    detail_by_period: Dict[str, float] = defaultdict(float)
    for row in rows:
        detail_by_period[row.get("period", "")] += to_float(row.get("recognized_revenue"))

    reconciled = []
    for row in ledger_rows:
        period = row.get("period", "")
        ledger_amount = to_float(row.get("ledger_revenue"))
        detail_amount = detail_by_period.get(period, 0.0)
        reconciled.append({"period": period, "detail_revenue": detail_amount, "ledger_revenue": ledger_amount, "difference": detail_amount - ledger_amount})
    return reconciled


def group_sum(rows: Iterable[RevenueRecord], field: str, positive_only: bool = False) -> List[Tuple[str, float]]:
    totals: Dict[str, float] = defaultdict(float)
    for record in rows:
        key = record.raw.get(field, "未填写") or "未填写"
        totals[key] += positive_amount(record) if positive_only else record.recognized_revenue
    return sorted(totals.items(), key=lambda x: abs(x[1]), reverse=True)


def group_segment_sum(records: Iterable[RevenueRecord]) -> List[Tuple[str, float]]:
    totals: Dict[str, float] = defaultdict(float)
    for record in records:
        totals[record.quality_segment] += positive_amount(record)
    return sorted(totals.items(), key=lambda x: x[1], reverse=True)


def period_totals(records: Iterable[RevenueRecord]) -> List[Tuple[str, float]]:
    totals: Dict[str, float] = defaultdict(float)
    for record in records:
        totals[record.period] += record.recognized_revenue
    return sorted(totals.items(), key=lambda x: x[0])


def write_csv(path: Path, rows: List[Dict[str, object]], fieldnames: List[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def fmt_money(value: float) -> str:
    return f"{value:,.2f}"


def fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return "NA"
    return f"{value * 100:.2f}%"


def build_growth_diagnosis(records: List[RevenueRecord]) -> Dict[str, object]:
    totals = period_totals(records)
    if not totals:
        return {"period": "", "previous_period": "", "growth": 0.0, "top_contributors": []}

    max_period, max_amount = max(totals, key=lambda x: x[1])
    idx = [p for p, _ in totals].index(max_period)
    previous_period, previous_amount = totals[idx - 1] if idx > 0 else ("", 0.0)
    contributors = sorted([r for r in records if r.period == max_period and r.recognized_revenue > 0], key=lambda r: r.recognized_revenue, reverse=True)[:5]
    return {
        "period": max_period,
        "period_amount": max_amount,
        "previous_period": previous_period,
        "previous_amount": previous_amount,
        "growth": max_amount - previous_amount,
        "top_contributors": contributors,
    }




CHART_TYPES = {
    "bar": {
        "name": "条形图",
        "best_for": "比较不同类别、组别或样本的数值大小，适合 Top N 排名。",
        "requires": ["metric", "dimension"],
    },
    "line": {
        "name": "折线图",
        "best_for": "展示指标随时间变化的趋势、波动和异常高点。",
        "requires": ["metric", "time_dimension"],
    },
    "donut": {
        "name": "环形图",
        "best_for": "展示少数类别的结构占比，适合 3-6 个分类。",
        "requires": ["metric", "dimension"],
    },
    "stacked_bar": {
        "name": "堆叠条形图",
        "best_for": "在一个主维度下拆分第二维度，展示结构变化或构成差异。",
        "requires": ["metric", "dimension", "breakdown"],
    },
    "heatmap": {
        "name": "热力图",
        "best_for": "展示两个分类维度之间的交叉集中度或异常组合。",
        "requires": ["metric", "dimension", "breakdown"],
    },
    "pareto": {
        "name": "帕累托图",
        "best_for": "展示头部集中度，结合类别贡献和累计占比。",
        "requires": ["metric", "dimension"],
    },
    "waterfall": {
        "name": "瀑布图",
        "best_for": "展示增长、变化或高点由哪些项目贡献。",
        "requires": ["metric", "dimension"],
    },
    "dot": {
        "name": "点图",
        "best_for": "展示优先级排序或风险信号强弱，比条形图更轻量。",
        "requires": ["metric", "dimension"],
    },
    "scatter": {
        "name": "散点图",
        "best_for": "展示两个数值变量之间的关系，并识别离群点。",
        "requires": ["x_metric", "y_metric"],
    },
}

FIELD_LABELS = {
    "record_id": "记录",
    "period": "期间",
    "recognition_date": "确认日期",
    "fund_product": "产品",
    "fee_type": "费用类型",
    "channel": "渠道",
    "customer_type": "客户类型",
    "customer_name": "客户",
    "revenue_model": "收入模型",
    "fund_category": "产品类型",
    "aum_size_band": "规模分层",
    "risk_exposure": "风险暴露",
    "income_stability_type": "收入稳定性类型",
    "quality_segment": "收入质量分层",
    "risk_flag": "风险信号",
    "recognized_revenue": "账面收入",
    "positive_revenue": "正向收入",
    "expected_revenue": "复算收入",
    "expected_variance": "复算差异",
    "cash_collected": "回款金额",
    "invoice_amount": "发票金额",
    "business_volume": "业务量",
    "subscription_amount": "申购金额",
    "redemption_amount": "赎回金额",
    "average_aum": "平均 AUM",
    "risk_score": "风险分",
    "count": "记录数",
    "cash_collection_ratio": "回款率",
}

ADDITIVE_METRICS = {
    "recognized_revenue",
    "positive_revenue",
    "expected_revenue",
    "expected_variance",
    "cash_collected",
    "invoice_amount",
    "business_volume",
    "subscription_amount",
    "redemption_amount",
    "average_aum",
    "risk_score",
    "count",
}

RATIO_METRICS = {"cash_collection_ratio"}

LEGACY_CHART_MAP = {
    "quality_segment_bar": {"chart_type": "donut", "metric": "positive_revenue", "dimension": "quality_segment", "title": "收入质量分层"},
    "monthly_trend_line": {"chart_type": "line", "metric": "recognized_revenue", "time_dimension": "period", "title": "月度收入趋势"},
    "risk_signal_bar": {"chart_type": "dot", "metric": "count", "dimension": "risk_flag", "title": "风险信号分布"},
    "product_mix_bar": {"chart_type": "pareto", "metric": "positive_revenue", "dimension": "fund_product", "title": "产品收入集中度"},
    "fee_type_bar": {"chart_type": "bar", "metric": "positive_revenue", "dimension": "fee_type", "title": "费用类型结构"},
    "monthly_segment_stacked": {"chart_type": "stacked_bar", "metric": "positive_revenue", "dimension": "period", "breakdown": "quality_segment", "title": "月度收入质量堆叠"},
    "fee_type_segment_stacked": {"chart_type": "stacked_bar", "metric": "positive_revenue", "dimension": "fee_type", "breakdown": "quality_segment", "title": "费用类型 x 收入质量"},
    "growth_contribution_bar": {"chart_type": "waterfall", "metric": "positive_revenue", "dimension": "fund_product", "title": "收入高点贡献拆解"},
    "product_fee_heatmap": {"chart_type": "heatmap", "metric": "positive_revenue", "dimension": "fund_product", "breakdown": "fee_type", "title": "产品 x 费用类型热力图"},
}

DEFAULT_CHART_PLAN = [
    {"insight_index": "1", "chart_type": "pareto", "metric": "positive_revenue", "dimension": "fund_product", "title": "产品收入集中度"},
    {"insight_index": "2", "chart_type": "donut", "metric": "positive_revenue", "dimension": "quality_segment", "title": "收入质量结构"},
    {"insight_index": "3", "chart_type": "stacked_bar", "metric": "positive_revenue", "dimension": "period", "breakdown": "quality_segment", "title": "月度收入质量变化"},
    {"insight_index": "4", "chart_type": "heatmap", "metric": "positive_revenue", "dimension": "fund_product", "breakdown": "fee_type", "title": "产品与收费路径交叉集中度"},
    {"insight_index": "", "chart_type": "line", "metric": "recognized_revenue", "time_dimension": "period", "title": "月度收入趋势"},
]

CHART_PALETTE = {
    "primary": "#2f5f8f",
    "primary_light": "#dbe7f3",
    "secondary": "#5f7f9f",
    "accent": "#8aa6c1",
    "muted": "#eef3f7",
    "grid": "#d7e0e8",
    "text": "#263238",
    "subtext": "#667085",
    "risk": "#486581",
    "soft": "#f6f8fb",
}

SEGMENT_COLORS = {
    "可疑增长收入": "#486581",
    "稳定基础收入": "#2f5f8f",
    "交易型收入": "#7da0bd",
    "一次性/高不确定性收入": "#a8bfd3",
}

SERIES_COLORS = ["#2f5f8f", "#5f7f9f", "#8aa6c1", "#486581", "#b8c9da", "#d5e0ea"]
CHART_FONT = "Microsoft YaHei, Segoe UI, Arial, sans-serif"


def top_items(mapping: Dict[str, float], limit: int = 8) -> List[Dict[str, object]]:
    total = sum(mapping.values()) or 1.0
    return [
        {"name": name, "amount": round(amount, 2), "share": round(amount / total, 4)}
        for name, amount in sorted(mapping.items(), key=lambda item: item[1], reverse=True)[:limit]
    ]


def label_for(field: str) -> str:
    return FIELD_LABELS.get(field, field)


def available_dimensions(records: List[RevenueRecord]) -> List[str]:
    raw_fields = sorted({key for record in records for key in record.raw.keys()})
    derived = ["quality_segment", "risk_flag"]
    blocked = set(ADDITIVE_METRICS) | RATIO_METRICS
    return [field for field in derived + raw_fields if field and field not in blocked]


def available_metrics(records: List[RevenueRecord]) -> List[str]:
    raw_fields = {key for record in records for key in record.raw.keys()}
    numeric_raw = [field for field in raw_fields if any(to_float(record.raw.get(field)) != 0 for record in records)]
    metrics = ["recognized_revenue", "positive_revenue", "expected_revenue", "expected_variance", "cash_collected", "invoice_amount", "risk_score", "count", "cash_collection_ratio"]
    for field in numeric_raw:
        if field not in metrics:
            metrics.append(field)
    return metrics


def metric_value(record: RevenueRecord, metric: str) -> float:
    if metric == "recognized_revenue":
        return record.recognized_revenue
    if metric == "positive_revenue":
        return positive_amount(record)
    if metric == "expected_revenue":
        return record.expected_revenue
    if metric == "expected_variance":
        return record.expected_variance
    if metric == "risk_score":
        return float(record.risk_score)
    if metric == "cash_collection_ratio":
        return record.cash_collection_ratio or 0.0
    if metric == "count":
        return 1.0
    return to_float(record.raw.get(metric))


def dimension_values(record: RevenueRecord, dimension: str) -> List[str]:
    if dimension == "quality_segment":
        return [record.quality_segment or "未填写"]
    if dimension == "risk_flag":
        return record.risk_flags or ["未触发风险信号"]
    if dimension == "period":
        return [record.period or "未填写"]
    if dimension == "fee_type":
        return [record.fee_type or "未填写"]
    if dimension == "record_id":
        return [record.record_id or "未填写"]
    value = record.raw.get(dimension, "") or "未填写"
    return [value]


def aggregate_dimension(records: List[RevenueRecord], dimension: str, metric: str, *, limit: int = 10, positive_only: bool = False) -> List[Tuple[str, float]]:
    totals: Dict[str, float] = defaultdict(float)
    counts: Dict[str, int] = defaultdict(int)
    for record in records:
        value = metric_value(record, metric)
        if positive_only and value <= 0:
            continue
        for key in dimension_values(record, dimension):
            totals[key] += value
            counts[key] += 1
    if metric in RATIO_METRICS:
        totals = {key: safe_div(total, counts[key]) or 0.0 for key, total in totals.items()}
    items = sorted(totals.items(), key=lambda x: abs(x[1]), reverse=True)
    if dimension == "period":
        items = sorted(totals.items(), key=lambda x: x[0])
    return items[:limit]


def aggregate_matrix(records: List[RevenueRecord], dimension: str, breakdown: str, metric: str, *, limit_x: int = 8, limit_y: int = 6) -> Tuple[List[str], List[str], Dict[str, Dict[str, float]]]:
    x_totals: Dict[str, float] = defaultdict(float)
    y_totals: Dict[str, float] = defaultdict(float)
    matrix: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for record in records:
        value = metric_value(record, metric)
        for x in dimension_values(record, dimension):
            for y in dimension_values(record, breakdown):
                matrix[x][y] += value
                x_totals[x] += value
                y_totals[y] += value
    xs = [key for key, _ in sorted(x_totals.items(), key=lambda item: abs(item[1]), reverse=True)[:limit_x]]
    ys = [key for key, _ in sorted(y_totals.items(), key=lambda item: abs(item[1]), reverse=True)[:limit_y]]
    if dimension == "period":
        xs = sorted(xs)
    if breakdown == "period":
        ys = sorted(ys)
    return xs, ys, matrix


def build_chart_payload(records: List[RevenueRecord], insights: List[Dict[str, str]]) -> Dict[str, object]:
    positive_total = sum(positive_amount(r) for r in records) or 1.0
    growth = build_growth_diagnosis(records)
    field_examples = {}
    for field in available_dimensions(records):
        values: List[str] = []
        for record in records:
            for value in dimension_values(record, field):
                if value not in values:
                    values.append(value)
                if len(values) >= 5:
                    break
            if len(values) >= 5:
                break
        field_examples[field] = values

    return {
        "business_context": "收入质量分析。数据样例是基金/资管手续费收入，但选图逻辑必须保持通用，不能绑定某一种业务主题。",
        "chart_design_rule": "先判断洞察的表达任务，再选择通用图表类型。不要返回固定业务主题图。Python 会按 metric、dimension、breakdown、time_dimension 做确定性聚合和 SVG 渲染。",
        "chart_types": [{"chart_type": key, **value} for key, value in CHART_TYPES.items()],
        "available_metrics": [{"metric": field, "label": label_for(field)} for field in available_metrics(records)],
        "available_dimensions": [{"dimension": field, "label": label_for(field), "examples": field_examples.get(field, [])} for field in available_dimensions(records)],
        "insights_to_visualize": [{"insight_index": idx, "insight": item.get("insight", ""), "evidence": item.get("evidence", ""), "judgment": item.get("judgment", ""), "action": item.get("action", "")} for idx, item in enumerate(insights, 1)],
        "data_summary": {
            "quality_segments": [{"segment": name, "amount": round(amount, 2), "share": round(amount / positive_total, 4)} for name, amount in group_segment_sum(records)],
            "monthly_revenue": [{"period": period, "amount": round(amount, 2)} for period, amount in period_totals(records)],
            "risk_signal_counts": dict(Counter(flag for r in records for flag in r.risk_flags).most_common()),
            "top_products": top_items(dict(group_sum(records, "fund_product", positive_only=True))),
            "top_fee_types": top_items(dict(group_sum(records, "fee_type", positive_only=True))),
            "growth_diagnosis": {
                "peak_period": growth.get("period"),
                "peak_period_amount": round(float(growth.get("period_amount", 0.0)), 2),
                "previous_period": growth.get("previous_period"),
                "growth_amount": round(float(growth.get("growth", 0.0)), 2),
                "top_contributors": [{"record_id": r.record_id, "product": r.raw.get("fund_product", ""), "fee_type": r.fee_type, "amount": round(r.recognized_revenue, 2), "quality_segment": r.quality_segment} for r in growth.get("top_contributors", [])[:6]],
            },
        },
        "required_output": {
            "charts": [{
                "insight_index": "integer or empty string",
                "analysis_task": "trend_change | structure_mix | concentration | growth_contribution | cross_relationship | risk_distribution | calculation_comparison | outlier_relationship",
                "chart_type": "one of chart_types",
                "title": "Chinese chart title",
                "metric": "one of available_metrics",
                "dimension": "one of available_dimensions; required for bar/donut/stacked_bar/heatmap/pareto/waterfall/dot",
                "breakdown": "optional second dimension for stacked_bar/heatmap",
                "time_dimension": "time field for line; usually period",
                "x_metric": "numeric field for scatter",
                "y_metric": "numeric field for scatter",
            }]
        },
    }


def legacy_chart_to_spec(item: Dict[str, object]) -> Dict[str, str]:
    chart_id = str(item.get("chart_id", "")).strip()
    spec = dict(LEGACY_CHART_MAP.get(chart_id, {}))
    spec.update({k: str(v).strip() for k, v in item.items() if v is not None and str(v).strip()})
    if "chart_id" in spec:
        spec.pop("chart_id", None)
    return spec


def normalize_chart_plan(raw: object, max_insight_index: int, records: Optional[List[RevenueRecord]] = None) -> List[Dict[str, str]]:
    raw_charts = raw.get("charts", []) if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    valid_dimensions = set(available_dimensions(records or [])) if records is not None else set(FIELD_LABELS)
    valid_metrics = set(available_metrics(records or [])) if records is not None else set(FIELD_LABELS) | ADDITIVE_METRICS | RATIO_METRICS
    plan: List[Dict[str, str]] = []
    used_signature = set()
    used_insights = set()

    for raw_item in raw_charts:
        if not isinstance(raw_item, dict):
            continue
        item = legacy_chart_to_spec(raw_item) if raw_item.get("chart_id") else {k: str(v).strip() for k, v in raw_item.items() if v is not None and str(v).strip()}
        chart_type = item.get("chart_type", "")
        if chart_type not in CHART_TYPES:
            continue

        metric = item.get("metric", "")
        dimension = item.get("dimension", "")
        breakdown = item.get("breakdown", "")
        time_dimension = item.get("time_dimension", "")
        x_metric = item.get("x_metric", "")
        y_metric = item.get("y_metric", "")

        if chart_type == "line":
            if not time_dimension:
                time_dimension = dimension or "period"
            dimension = time_dimension
        elif chart_type == "scatter":
            if x_metric not in valid_metrics or y_metric not in valid_metrics:
                continue
        else:
            if not dimension:
                continue

        if metric and metric not in valid_metrics and chart_type != "scatter":
            continue
        if dimension and dimension not in valid_dimensions:
            continue
        if breakdown and breakdown not in valid_dimensions:
            breakdown = ""
        if chart_type in {"stacked_bar", "heatmap"} and not breakdown:
            continue

        try:
            insight_index = int(item.get("insight_index", "") or 0)
        except ValueError:
            insight_index = 0
        if insight_index < 1 or insight_index > max_insight_index or insight_index in used_insights:
            insight_index = 0
        if insight_index:
            used_insights.add(insight_index)

        signature = (chart_type, metric, dimension, breakdown, x_metric, y_metric)
        if signature in used_signature:
            continue
        used_signature.add(signature)

        title = item.get("title") or auto_chart_title(chart_type, metric or y_metric, dimension or time_dimension, breakdown)
        plan.append({
            "insight_index": str(insight_index) if insight_index else "",
            "analysis_task": item.get("analysis_task", ""),
            "chart_type": chart_type,
            "metric": metric,
            "dimension": dimension,
            "breakdown": breakdown,
            "time_dimension": time_dimension,
            "x_metric": x_metric,
            "y_metric": y_metric,
            "title": title,
            "reason": item.get("reason", ""),
            "takeaway": item.get("takeaway", ""),
        })
        if len(plan) >= 6:
            break

    for fallback in DEFAULT_CHART_PLAN:
        if len(plan) >= 5:
            break
        normalized = normalize_chart_plan([fallback], max_insight_index, records)
        if not normalized:
            continue
        candidate = normalized[0]
        signature = (candidate.get("chart_type"), candidate.get("metric"), candidate.get("dimension"), candidate.get("breakdown"), candidate.get("x_metric"), candidate.get("y_metric"))
        if signature in used_signature:
            continue
        if candidate.get("insight_index") in used_insights:
            candidate["insight_index"] = ""
        used_signature.add(signature)
        plan.append(candidate)

    return plan[:5]


def generate_chart_plan(records: List[RevenueRecord], insights: List[Dict[str, str]], args: argparse.Namespace) -> Tuple[List[Dict[str, str]], str, str]:
    if not args.use_llm:
        return normalize_chart_plan(DEFAULT_CHART_PLAN, len(insights), records), "规则兜底", "未启用 LLM 选图，使用通用图表规格兜底。"
    api_key = os.environ.get(args.llm_api_key_env, "")
    if not api_key:
        return normalize_chart_plan(DEFAULT_CHART_PLAN, len(insights), records), "规则兜底", f"未检测到环境变量 {args.llm_api_key_env}，使用通用图表规格兜底。"
    system_prompt = (
        "你是数据分析报告的可视化编辑。你的任务不是选择固定业务主题图，而是为每条洞察设计通用图表规格。"
        "先判断洞察需要表达趋势、结构、集中度、贡献归因、交叉关系、风险分布还是异常关系；"
        "再从 chart_types 中选择 chart_type，并从 available_metrics / available_dimensions 中选择字段。"
        "不要发明字段，不要重算金额，只返回 JSON：{\"charts\":[...]}。"
        "不是每条洞察都必须配图，优先选择最能支撑结论的 3-5 张图。"
    )
    try:
        raw = call_llm_json(base_url=args.llm_base_url, model=args.llm_model, api_key=api_key, system_prompt=system_prompt, payload=build_chart_payload(records, insights), timeout=args.llm_timeout, temperature=0.15)
        return normalize_chart_plan(raw, len(insights), records), "LLM 通用图表规格", "LLM 输出 chart_type、metric、dimension 等通用图表规格，Python 负责校验字段、聚合数据和绘制 SVG。"
    except Exception as exc:
        return normalize_chart_plan(DEFAULT_CHART_PLAN, len(insights), records), "规则兜底", f"LLM 图表规格生成失败，已回退到通用默认图表；错误摘要：{exc}"


def svg_text(value: object) -> str:
    return html.escape(str(value))


def chart_money(value: float) -> str:
    return f"{value / 10000:.1f}万"


def fmt_metric_value(value: float, metric: str) -> str:
    if metric in RATIO_METRICS:
        return fmt_pct(value)
    if metric == "count":
        return f"{int(round(value))} 条"
    if abs(value) >= 10000:
        return chart_money(value)
    return f"{value:,.0f}"


def svg_header(width: int, height: int, title: str, subtitle: str = "") -> List[str]:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text x="32" y="38" font-family="{CHART_FONT}" font-size="22" font-weight="700" fill="{CHART_PALETTE["text"]}">{svg_text(title)}</text>',
    ]
    if subtitle:
        parts.append(f'<text x="32" y="64" font-family="{CHART_FONT}" font-size="13" fill="{CHART_PALETTE["subtext"]}">{svg_text(subtitle)}</text>')
    return parts


def write_svg(path: Path, parts: List[str]) -> None:
    parts.append("</svg>")
    path.write_text("\n".join(p for p in parts if p), encoding="utf-8")


def auto_chart_title(chart_type: str, metric: str, dimension: str, breakdown: str = "") -> str:
    if chart_type == "line":
        return f"{label_for(metric)}趋势"
    if chart_type == "heatmap":
        return f"{label_for(dimension)} x {label_for(breakdown)}"
    if chart_type == "stacked_bar":
        return f"{label_for(dimension)}按{label_for(breakdown)}拆解"
    if chart_type == "pareto":
        return f"{label_for(dimension)}集中度"
    if chart_type == "waterfall":
        return f"{label_for(dimension)}贡献拆解"
    if chart_type == "donut":
        return f"{label_for(dimension)}占比结构"
    return f"{label_for(dimension)}与{label_for(metric)}"


def chart_filename(spec: Dict[str, str], index: int) -> str:
    raw = "_".join([str(index), spec.get("chart_type", "chart"), spec.get("dimension", ""), spec.get("breakdown", ""), spec.get("metric", "")])
    safe = "".join(ch.lower() if ch.isalnum() else "_" for ch in raw)
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip("_")[:80] + ".svg"


def color_for(label: str, index: int = 0) -> str:
    return SEGMENT_COLORS.get(label, SERIES_COLORS[index % len(SERIES_COLORS)])


def render_bar_spec(path: Path, spec: Dict[str, str], records: List[RevenueRecord]) -> None:
    metric = spec.get("metric", "positive_revenue")
    dimension = spec.get("dimension", "quality_segment")
    rows = [(k, v) for k, v in aggregate_dimension(records, dimension, metric, limit=10) if v > 0]
    width = 920
    height = max(320, 116 + len(rows[:8]) * 48)
    max_v = max([v for _, v in rows] or [1.0])
    parts = svg_header(width, height, spec.get("title", auto_chart_title("bar", metric, dimension)), f"{label_for(dimension)}对比 {label_for(metric)}")
    x0, y0, scale_w = 250, 92, 530
    for idx, (label, value) in enumerate(rows[:8]):
        y = y0 + idx * 48
        w = max(3, value / max_v * scale_w)
        parts.extend([
            f'<text x="32" y="{y + 21}" font-family="{CHART_FONT}" font-size="14" fill="{CHART_PALETTE["text"]}">{svg_text(label[:28])}</text>',
            f'<rect x="{x0}" y="{y}" width="{scale_w}" height="30" rx="5" fill="{CHART_PALETTE["muted"]}"/>',
            f'<rect x="{x0}" y="{y}" width="{w:.1f}" height="30" rx="5" fill="{color_for(label, idx)}"/>',
            f'<text x="{x0 + w + 10:.1f}" y="{y + 21}" font-family="{CHART_FONT}" font-size="13" fill="{CHART_PALETTE["text"]}">{svg_text(fmt_metric_value(value, metric))}</text>',
        ])
    write_svg(path, parts)


def render_dot_spec(path: Path, spec: Dict[str, str], records: List[RevenueRecord]) -> None:
    metric = spec.get("metric", "count")
    dimension = spec.get("dimension", "risk_flag")
    rows = [(k, v) for k, v in aggregate_dimension(records, dimension, metric, limit=10) if v > 0]
    width = 920
    height = max(320, 116 + len(rows[:8]) * 44)
    max_v = max([v for _, v in rows] or [1.0])
    parts = svg_header(width, height, spec.get("title", auto_chart_title("dot", metric, dimension)), f"用点图展示{label_for(dimension)}的相对强弱")
    x0, y0, scale_w = 250, 96, 530
    for idx, (label, value) in enumerate(rows[:8]):
        y = y0 + idx * 44
        x = x0 + value / max_v * scale_w
        parts.extend([
            f'<text x="32" y="{y + 5}" font-family="{CHART_FONT}" font-size="14" fill="{CHART_PALETTE["text"]}">{svg_text(label[:28])}</text>',
            f'<line x1="{x0}" y1="{y}" x2="{x0 + scale_w}" y2="{y}" stroke="{CHART_PALETTE["grid"]}" stroke-width="2"/>',
            f'<circle cx="{x:.1f}" cy="{y}" r="8" fill="{color_for(label, idx)}"/>',
            f'<text x="{x + 14:.1f}" y="{y + 5}" font-family="{CHART_FONT}" font-size="13" fill="{CHART_PALETTE["text"]}">{svg_text(fmt_metric_value(value, metric))}</text>',
        ])
    write_svg(path, parts)


def render_line_spec(path: Path, spec: Dict[str, str], records: List[RevenueRecord]) -> None:
    metric = spec.get("metric", "recognized_revenue")
    dimension = spec.get("time_dimension") or spec.get("dimension") or "period"
    points = aggregate_dimension(records, dimension, metric, limit=36)
    width, height = 940, 420
    parts = svg_header(width, height, spec.get("title", auto_chart_title("line", metric, dimension)), f"{label_for(metric)}随{label_for(dimension)}变化")
    if not points:
        write_svg(path, parts)
        return
    x0, y0, chart_w, chart_h = 72, 104, 805, 230
    max_v = max(v for _, v in points)
    min_v = min(0.0, min(v for _, v in points))
    rng = max(max_v - min_v, 1.0)
    parts.extend([
        f'<line x1="{x0}" y1="{y0 + chart_h}" x2="{x0 + chart_w}" y2="{y0 + chart_h}" stroke="{CHART_PALETTE["grid"]}"/>',
        f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y0 + chart_h}" stroke="{CHART_PALETTE["grid"]}"/>',
    ])
    coords = []
    for idx, (label, value) in enumerate(points):
        x = x0 + chart_w * idx / max(1, len(points) - 1)
        y = y0 + chart_h - ((value - min_v) / rng * chart_h)
        coords.append((x, y, label, value))
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in coords)
    area = f"{coords[0][0]:.1f},{y0 + chart_h} " + poly + f" {coords[-1][0]:.1f},{y0 + chart_h}"
    parts.extend([
        f'<polygon points="{area}" fill="{CHART_PALETTE["primary_light"]}" opacity="0.9"/>',
        f'<polyline points="{poly}" fill="none" stroke="{CHART_PALETTE["primary"]}" stroke-width="3"/>',
    ])
    for x, y, label, value in coords:
        show = value == max_v or value == min_v or value < 0
        parts.extend([
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{CHART_PALETTE["primary"]}"/>',
            f'<text x="{x:.1f}" y="{y - 10:.1f}" text-anchor="middle" font-family="{CHART_FONT}" font-size="11" fill="{CHART_PALETTE["text"]}">{svg_text(fmt_metric_value(value, metric))}</text>' if show else "",
            f'<text x="{x:.1f}" y="{y0 + chart_h + 24}" text-anchor="middle" font-family="{CHART_FONT}" font-size="10" fill="{CHART_PALETTE["subtext"]}" transform="rotate(35 {x:.1f},{y0 + chart_h + 24})">{svg_text(label)}</text>',
        ])
    write_svg(path, parts)


def donut_path(cx: float, cy: float, r_outer: float, r_inner: float, start: float, end: float) -> str:
    large = 1 if end - start > math.pi else 0
    x1, y1 = cx + r_outer * math.cos(start), cy + r_outer * math.sin(start)
    x2, y2 = cx + r_outer * math.cos(end), cy + r_outer * math.sin(end)
    x3, y3 = cx + r_inner * math.cos(end), cy + r_inner * math.sin(end)
    x4, y4 = cx + r_inner * math.cos(start), cy + r_inner * math.sin(start)
    return f"M {x1:.2f} {y1:.2f} A {r_outer} {r_outer} 0 {large} 1 {x2:.2f} {y2:.2f} L {x3:.2f} {y3:.2f} A {r_inner} {r_inner} 0 {large} 0 {x4:.2f} {y4:.2f} Z"


def render_donut_spec(path: Path, spec: Dict[str, str], records: List[RevenueRecord]) -> None:
    metric = spec.get("metric", "positive_revenue")
    dimension = spec.get("dimension", "quality_segment")
    rows = [(k, v) for k, v in aggregate_dimension(records, dimension, metric, limit=6) if v > 0]
    total = sum(v for _, v in rows) or 1.0
    width, height = 880, 420
    parts = svg_header(width, height, spec.get("title", auto_chart_title("donut", metric, dimension)), f"{label_for(dimension)}占比结构")
    cx, cy, ro, ri = 260, 230, 120, 68
    angle = -math.pi / 2
    for idx, (label, value) in enumerate(rows):
        span = value / total * math.pi * 2
        if span <= 0:
            continue
        parts.append(f'<path d="{donut_path(cx, cy, ro, ri, angle, angle + span)}" fill="{color_for(label, idx)}"/>')
        angle += span
    parts.append(f'<text x="{cx}" y="{cy - 4}" text-anchor="middle" font-family="{CHART_FONT}" font-size="21" font-weight="700" fill="{CHART_PALETTE["text"]}">{svg_text(fmt_metric_value(total, metric))}</text>')
    parts.append(f'<text x="{cx}" y="{cy + 22}" text-anchor="middle" font-family="{CHART_FONT}" font-size="12" fill="{CHART_PALETTE["subtext"]}">合计</text>')
    for idx, (label, value) in enumerate(rows):
        y = 126 + idx * 42
        parts.extend([
            f'<rect x="470" y="{y - 13}" width="14" height="14" rx="3" fill="{color_for(label, idx)}"/>',
            f'<text x="494" y="{y}" font-family="{CHART_FONT}" font-size="14" fill="{CHART_PALETTE["text"]}">{svg_text(label[:26])}</text>',
            f'<text x="760" y="{y}" text-anchor="end" font-family="{CHART_FONT}" font-size="13" fill="{CHART_PALETTE["subtext"]}">{svg_text(fmt_pct(value / total))}</text>',
        ])
    write_svg(path, parts)


def render_stacked_spec(path: Path, spec: Dict[str, str], records: List[RevenueRecord]) -> None:
    metric = spec.get("metric", "positive_revenue")
    dimension = spec.get("dimension", "period")
    breakdown = spec.get("breakdown", "quality_segment")
    categories, stacks, values = aggregate_matrix(records, dimension, breakdown, metric, limit_x=9, limit_y=5)
    width, height = 960, max(390, 118 + len(categories) * 44)
    parts = svg_header(width, height, spec.get("title", auto_chart_title("stacked_bar", metric, dimension, breakdown)), f"{label_for(dimension)}按{label_for(breakdown)}拆解")
    if not categories or not stacks:
        write_svg(path, parts)
        return
    x0, y0, scale_w = 225, 106, 555
    totals = {cat: sum(max(0, values.get(cat, {}).get(stack, 0.0)) for stack in stacks) for cat in categories}
    max_total = max(totals.values() or [1.0]) or 1.0
    for idx, stack in enumerate(stacks):
        lx = 32 + idx * 170
        parts.extend([f'<rect x="{lx}" y="72" width="12" height="12" rx="2" fill="{color_for(stack, idx)}"/>', f'<text x="{lx + 18}" y="83" font-family="{CHART_FONT}" font-size="12" fill="{CHART_PALETTE["subtext"]}">{svg_text(stack[:16])}</text>'])
    for idx, category in enumerate(categories):
        y = y0 + idx * 44
        parts.append(f'<text x="32" y="{y + 20}" font-family="{CHART_FONT}" font-size="13" fill="{CHART_PALETTE["text"]}">{svg_text(category[:26])}</text>')
        parts.append(f'<rect x="{x0}" y="{y}" width="{scale_w}" height="28" rx="5" fill="{CHART_PALETTE["muted"]}"/>')
        cursor = x0
        for s_idx, stack in enumerate(stacks):
            value = max(0, values.get(category, {}).get(stack, 0.0))
            if value <= 0:
                continue
            w = value / max_total * scale_w
            parts.append(f'<rect x="{cursor:.1f}" y="{y}" width="{max(1.5, w):.1f}" height="28" fill="{color_for(stack, s_idx)}"/>')
            cursor += w
        parts.append(f'<text x="{x0 + min(scale_w + 8, totals[category] / max_total * scale_w + 8):.1f}" y="{y + 20}" font-family="{CHART_FONT}" font-size="12" fill="{CHART_PALETTE["text"]}">{svg_text(fmt_metric_value(totals[category], metric))}</text>')
    write_svg(path, parts)


def render_heatmap_spec(path: Path, spec: Dict[str, str], records: List[RevenueRecord]) -> None:
    metric = spec.get("metric", "positive_revenue")
    dimension = spec.get("dimension", "fund_product")
    breakdown = spec.get("breakdown", "fee_type")
    xs, ys, matrix = aggregate_matrix(records, dimension, breakdown, metric, limit_x=6, limit_y=6)
    width = max(860, 250 + len(ys) * 128 + 60)
    height = max(360, 106 + len(xs) * 42 + 40)
    parts = svg_header(width, height, spec.get("title", auto_chart_title("heatmap", metric, dimension, breakdown)), f"{label_for(dimension)}与{label_for(breakdown)}的交叉关系")
    max_v = max([matrix.get(x, {}).get(y, 0.0) for x in xs for y in ys] or [1.0]) or 1.0
    x0, y0, cell_w, cell_h = 245, 104, 128, 40
    for c_idx, y_label in enumerate(ys):
        x = x0 + c_idx * cell_w
        parts.append(f'<text x="{x + cell_w / 2}" y="86" text-anchor="middle" font-family="{CHART_FONT}" font-size="12" fill="{CHART_PALETTE["subtext"]}">{svg_text(y_label[:14])}</text>')
    for r_idx, x_label in enumerate(xs):
        y = y0 + r_idx * cell_h
        parts.append(f'<text x="32" y="{y + 25}" font-family="{CHART_FONT}" font-size="13" fill="{CHART_PALETTE["text"]}">{svg_text(x_label[:28])}</text>')
        for c_idx, y_label in enumerate(ys):
            x = x0 + c_idx * cell_w
            value = matrix.get(x_label, {}).get(y_label, 0.0)
            opacity = 0.10 + 0.82 * (value / max_v if max_v else 0.0)
            parts.append(f'<rect x="{x}" y="{y}" width="{cell_w - 8}" height="{cell_h - 8}" rx="5" fill="{CHART_PALETTE["primary"]}" opacity="{opacity:.2f}"/>')
            if value:
                parts.append(f'<text x="{x + (cell_w - 8) / 2}" y="{y + 22}" text-anchor="middle" font-family="{CHART_FONT}" font-size="11" fill="#ffffff">{svg_text(fmt_metric_value(value, metric))}</text>')
    write_svg(path, parts)


def render_pareto_spec(path: Path, spec: Dict[str, str], records: List[RevenueRecord]) -> None:
    metric = spec.get("metric", "positive_revenue")
    dimension = spec.get("dimension", "fund_product")
    rows = [(k, v) for k, v in aggregate_dimension(records, dimension, metric, limit=8) if v > 0]
    total = sum(v for _, v in rows) or 1.0
    width, height = 940, 460
    parts = svg_header(width, height, spec.get("title", auto_chart_title("pareto", metric, dimension)), f"柱表示贡献，折线表示累计占比")
    if not rows:
        write_svg(path, parts)
        return
    x0, y0, chart_w, chart_h = 76, 104, 790, 235
    bar_w = chart_w / max(1, len(rows)) * 0.58
    max_v = max(v for _, v in rows)
    cumulative = 0.0
    line_points = []
    parts.extend([f'<line x1="{x0}" y1="{y0 + chart_h}" x2="{x0 + chart_w}" y2="{y0 + chart_h}" stroke="{CHART_PALETTE["grid"]}"/>'])
    for idx, (label, value) in enumerate(rows):
        x = x0 + idx * chart_w / len(rows) + bar_w * 0.35
        h = value / max_v * chart_h
        y = y0 + chart_h - h
        cumulative += value
        cy = y0 + chart_h - (cumulative / total * chart_h)
        cx = x + bar_w / 2
        line_points.append((cx, cy))
        parts.extend([
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" rx="4" fill="{color_for(label, idx)}"/>',
            f'<text x="{cx:.1f}" y="{y - 8:.1f}" text-anchor="middle" font-family="{CHART_FONT}" font-size="11" fill="{CHART_PALETTE["text"]}">{svg_text(fmt_metric_value(value, metric))}</text>',
            f'<text x="{cx:.1f}" y="{y0 + chart_h + 24}" text-anchor="middle" font-family="{CHART_FONT}" font-size="10" fill="{CHART_PALETTE["subtext"]}" transform="rotate(35 {cx:.1f},{y0 + chart_h + 24})">{svg_text(label[:14])}</text>',
        ])
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in line_points)
    parts.append(f'<polyline points="{poly}" fill="none" stroke="{CHART_PALETTE["risk"]}" stroke-width="3"/>')
    for x, y in line_points:
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{CHART_PALETTE["risk"]}"/>')
    write_svg(path, parts)


def render_waterfall_spec(path: Path, spec: Dict[str, str], records: List[RevenueRecord]) -> None:
    metric = spec.get("metric", "positive_revenue")
    dimension = spec.get("dimension", "fund_product")
    rows = [(k, v) for k, v in aggregate_dimension(records, dimension, metric, limit=6) if v > 0]
    width, height = 940, 455
    parts = svg_header(width, height, spec.get("title", auto_chart_title("waterfall", metric, dimension)), f"展示{label_for(dimension)}对{label_for(metric)}的累计贡献")
    if not rows:
        write_svg(path, parts)
        return
    total = sum(v for _, v in rows)
    x0, y0, chart_w, chart_h = 70, 104, 805, 235
    step_w = chart_w / (len(rows) + 1)
    running = 0.0
    parts.append(f'<line x1="{x0}" y1="{y0 + chart_h}" x2="{x0 + chart_w}" y2="{y0 + chart_h}" stroke="{CHART_PALETTE["grid"]}"/>')
    for idx, (label, value) in enumerate(rows):
        prev = running
        running += value
        y_top = y0 + chart_h - running / total * chart_h
        y_prev = y0 + chart_h - prev / total * chart_h
        h = max(2, y_prev - y_top)
        x = x0 + idx * step_w + 18
        parts.extend([
            f'<rect x="{x:.1f}" y="{y_top:.1f}" width="{step_w * 0.58:.1f}" height="{h:.1f}" rx="4" fill="{color_for(label, idx)}"/>',
            f'<line x1="{x + step_w * 0.58:.1f}" y1="{y_top:.1f}" x2="{x0 + (idx + 1) * step_w + 18:.1f}" y2="{y_top:.1f}" stroke="{CHART_PALETTE["grid"]}" stroke-dasharray="4 4"/>',
            f'<text x="{x + step_w * 0.29:.1f}" y="{y_top - 8:.1f}" text-anchor="middle" font-family="{CHART_FONT}" font-size="11" fill="{CHART_PALETTE["text"]}">{svg_text(fmt_metric_value(value, metric))}</text>',
            f'<text x="{x + step_w * 0.29:.1f}" y="{y0 + chart_h + 24}" text-anchor="middle" font-family="{CHART_FONT}" font-size="10" fill="{CHART_PALETTE["subtext"]}" transform="rotate(35 {x + step_w * 0.29:.1f},{y0 + chart_h + 24})">{svg_text(label[:14])}</text>',
        ])
    x = x0 + len(rows) * step_w + 18
    parts.extend([
        f'<rect x="{x:.1f}" y="{y0:.1f}" width="{step_w * 0.58:.1f}" height="{chart_h:.1f}" rx="4" fill="{CHART_PALETTE["risk"]}" opacity="0.9"/>',
        f'<text x="{x + step_w * 0.29:.1f}" y="{y0 - 8:.1f}" text-anchor="middle" font-family="{CHART_FONT}" font-size="11" fill="{CHART_PALETTE["text"]}">{svg_text(fmt_metric_value(total, metric))}</text>',
        f'<text x="{x + step_w * 0.29:.1f}" y="{y0 + chart_h + 24}" text-anchor="middle" font-family="{CHART_FONT}" font-size="10" fill="{CHART_PALETTE["subtext"]}">合计</text>',
    ])
    write_svg(path, parts)


def render_scatter_spec(path: Path, spec: Dict[str, str], records: List[RevenueRecord]) -> None:
    x_metric = spec.get("x_metric", "recognized_revenue")
    y_metric = spec.get("y_metric", "risk_score")
    width, height = 900, 460
    parts = svg_header(width, height, spec.get("title", f"{label_for(x_metric)}与{label_for(y_metric)}关系"), f"每个点代表一条收入记录")
    points = [(metric_value(r, x_metric), metric_value(r, y_metric), r.record_id) for r in records]
    if not points:
        write_svg(path, parts)
        return
    x0, y0, chart_w, chart_h = 80, 100, 740, 260
    max_x = max(x for x, _, _ in points) or 1.0
    max_y = max(y for _, y, _ in points) or 1.0
    parts.extend([
        f'<line x1="{x0}" y1="{y0 + chart_h}" x2="{x0 + chart_w}" y2="{y0 + chart_h}" stroke="{CHART_PALETTE["grid"]}"/>',
        f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y0 + chart_h}" stroke="{CHART_PALETTE["grid"]}"/>',
        f'<text x="{x0 + chart_w / 2}" y="{height - 38}" text-anchor="middle" font-family="{CHART_FONT}" font-size="12" fill="{CHART_PALETTE["subtext"]}">{svg_text(label_for(x_metric))}</text>',
        f'<text x="22" y="{y0 + chart_h / 2}" text-anchor="middle" font-family="{CHART_FONT}" font-size="12" fill="{CHART_PALETTE["subtext"]}" transform="rotate(-90 22,{y0 + chart_h / 2})">{svg_text(label_for(y_metric))}</text>',
    ])
    for idx, (x_value, y_value, label) in enumerate(points):
        x = x0 + x_value / max_x * chart_w
        y = y0 + chart_h - y_value / max_y * chart_h
        r = 5 + min(9, abs(x_value) / max_x * 8)
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{SERIES_COLORS[idx % len(SERIES_COLORS)]}" opacity="0.78"><title>{svg_text(label)}</title></circle>')
    write_svg(path, parts)


def render_chart_by_spec(spec: Dict[str, str], path: Path, records: List[RevenueRecord]) -> None:
    chart_type = spec.get("chart_type", "")
    if chart_type == "bar":
        render_bar_spec(path, spec, records)
    elif chart_type == "line":
        render_line_spec(path, spec, records)
    elif chart_type == "donut":
        render_donut_spec(path, spec, records)
    elif chart_type == "stacked_bar":
        render_stacked_spec(path, spec, records)
    elif chart_type == "heatmap":
        render_heatmap_spec(path, spec, records)
    elif chart_type == "pareto":
        render_pareto_spec(path, spec, records)
    elif chart_type == "waterfall":
        render_waterfall_spec(path, spec, records)
    elif chart_type == "dot":
        render_dot_spec(path, spec, records)
    elif chart_type == "scatter":
        render_scatter_spec(path, spec, records)
    else:
        raise ValueError(f"Unsupported chart_type: {chart_type}")


def generate_charts(out_dir: Path, records: List[RevenueRecord], chart_plan: List[Dict[str, str]]) -> List[Dict[str, str]]:
    chart_dir = out_dir / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)
    rendered: List[Dict[str, str]] = []
    used_names: Counter[str] = Counter()
    for idx, spec in enumerate(chart_plan, 1):
        chart_type = spec.get("chart_type", "")
        if chart_type not in CHART_TYPES:
            continue
        base_name = chart_filename(spec, idx)
        used_names[base_name] += 1
        if used_names[base_name] > 1:
            stem, suffix = base_name.rsplit(".", 1)
            base_name = f"{stem}_{used_names[base_name]}.{suffix}"
        path = chart_dir / base_name
        render_chart_by_spec(spec, path, records)
        rendered.append({
            "insight_index": spec.get("insight_index", ""),
            "chart_type": chart_type,
            "metric": spec.get("metric", ""),
            "dimension": spec.get("dimension", ""),
            "breakdown": spec.get("breakdown", ""),
            "title": spec.get("title") or auto_chart_title(chart_type, spec.get("metric", ""), spec.get("dimension", ""), spec.get("breakdown", "")),
            "path": path.relative_to(out_dir).as_posix(),
            "reason": spec.get("reason", ""),
            "takeaway": spec.get("takeaway", ""),
        })
    return rendered


def build_insights(records: List[RevenueRecord]) -> List[Dict[str, str]]:
    positive_total = sum(positive_amount(r) for r in records)
    if positive_total <= 0:
        return []

    insights: List[Dict[str, str]] = []
    products = group_sum(records, "fund_product", positive_only=True)
    top3_amount = sum(amount for _, amount in products[:3])
    top3_ratio = safe_div(top3_amount, positive_total) or 0.0
    top_product, top_product_amount = products[0] if products else ("", 0.0)

    segments = dict(group_segment_sum(records))
    stable_ratio = safe_div(segments.get("稳定基础收入", 0.0), positive_total) or 0.0
    suspicious_ratio = safe_div(segments.get("可疑增长收入", 0.0), positive_total) or 0.0
    oneoff_declared_amount = sum(positive_amount(r) for r in records if "一次性" in r.raw.get("income_stability_type", "") or r.fee_type == "performance_fee")
    oneoff_ratio = safe_div(oneoff_declared_amount, positive_total) or 0.0
    transaction_ratio = safe_div(segments.get("交易型收入", 0.0), positive_total) or 0.0

    high_vol_amount = sum(positive_amount(r) for r in records if r.raw.get("risk_exposure") == "高波动")
    high_vol_ratio = safe_div(high_vol_amount, positive_total) or 0.0
    low_cash_amount = sum(positive_amount(r) for r in records if "低回款覆盖" in r.risk_flags)
    low_cash_ratio = safe_div(low_cash_amount, positive_total) or 0.0

    growth = build_growth_diagnosis(records)
    top_contributors: List[RevenueRecord] = growth["top_contributors"]  # type: ignore[assignment]
    high_uncertain_contrib = sum(positive_amount(r) for r in top_contributors if r.quality_segment in {"可疑增长收入", "一次性/高不确定性收入"})
    top_contrib_amount = sum(positive_amount(r) for r in top_contributors)
    high_uncertain_contrib_ratio = safe_div(high_uncertain_contrib, top_contrib_amount) or 0.0

    if top3_ratio >= 0.6:
        insights.append({
            "insight": "收入集中于少数产品，单一产品波动会放大整体收入波动。",
            "evidence": f"Top 3 产品贡献 {fmt_pct(top3_ratio)} 的正向收入，其中 {top_product} 单品贡献 {fmt_money(top_product_amount)}。",
            "judgment": "收入增长并不是均匀来自产品矩阵，而是对少数产品依赖较高，后续需要关注这些产品的规模留存、赎回和费率变化。",
            "action": "将 Top 产品单独列为收入质量跟踪对象，拆分其 AUM、交易金额、费率和期后退款情况。",
        })

    if suspicious_ratio >= 0.25:
        insights.append({
            "insight": "低质量或待验证收入占比较高，账面增长的可持续性需要谨慎判断。",
            "evidence": f"可疑增长收入占正向收入 {fmt_pct(suspicious_ratio)}，主要信号包括复算偏差、低回款、期末确认、关联方或期后退款。",
            "judgment": "这类收入可能拉高当期表现，但其确认依据、计价准确性或现金回收仍需进一步验证。",
            "action": "优先验证可疑增长收入样本，将其与稳定基础收入分开展示，避免一次性或低质量增量掩盖基础收入表现。",
        })

    if stable_ratio < 0.5:
        insights.append({
            "insight": "稳定基础收入占比不足，收入结构偏交易驱动或一次性驱动。",
            "evidence": f"稳定基础收入占正向收入 {fmt_pct(stable_ratio)}，交易型收入占 {fmt_pct(transaction_ratio)}，一次性/高不确定性收入占 {fmt_pct(oneoff_ratio)}。",
            "judgment": "如果收入主要来自申赎费、业绩报酬或期末大额交易，增长更依赖市场活跃度和单笔交易，持续性弱于 AUM 稳定增长带来的管理费。",
            "action": "建立收入分层口径：稳定基础收入、交易型收入、一次性/高不确定性收入、可疑增长收入，并分别跟踪趋势。",
        })

    if high_vol_ratio >= 0.5:
        insights.append({
            "insight": "收入暴露在高波动产品上，后续受市场行情和客户申赎行为影响更大。",
            "evidence": f"高波动产品贡献 {fmt_pct(high_vol_ratio)} 的正向收入。",
            "judgment": "偏股、FOF、私募/专户等产品可能带来较高费率或业绩报酬，但收入稳定性弱于货币/债券等低波动产品。",
            "action": "对高波动产品收入单独评估：跟踪期后规模、赎回、业绩报酬门槛和回款情况。",
        })

    if low_cash_ratio >= 0.15:
        insights.append({
            "insight": "部分收入现金回收弱，收入确认质量需要后续验证。",
            "evidence": f"低回款收入占正向收入 {fmt_pct(low_cash_ratio)}。",
            "judgment": "低回款收入即使账面已确认，也需要关注是否存在结算延迟、客户争议、期后冲回或收入确认提前。",
            "action": "对低回款样本执行期后回款跟踪，并把回款状态作为收入质量监控指标。",
        })

    if top_contributors and high_uncertain_contrib_ratio >= 0.5:
        names = "、".join(f"{r.record_id}/{r.raw.get('fund_product')}" for r in top_contributors[:3])
        insights.append({
            "insight": f"{growth['period']} 的收入高点主要由非稳定增量贡献。",
            "evidence": f"{growth['period']} 收入为 {fmt_money(float(growth['period_amount']))}，较 {growth['previous_period'] or '前期'} 增加 {fmt_money(float(growth['growth']))}；核心贡献样本包括 {names}。",
            "judgment": "收入高点更像由期末大额交易、业绩报酬或待验证收入拉动，而不是稳定管理费自然增长。",
            "action": "将该期间收入拆成常规基础收入与非经常性增量，优先验证贡献最大的非稳定样本。",
        })

    return insights[:6]


def build_report(records: List[RevenueRecord], validation_messages: List[str], ledger_recon: List[Dict[str, float | str]], selected: List[RevenueRecord], insights: List[Dict[str, str]], insight_source: str, insight_note: str, chart_refs: Optional[List[Dict[str, str]]] = None, chart_source: str = "rule", chart_note: str = "") -> str:
    total_revenue = sum(r.recognized_revenue for r in records)
    positive_total = sum(positive_amount(r) for r in records)
    total_expected = sum(r.expected_revenue for r in records)
    total_cash = sum(to_float(r.raw.get("cash_collected")) for r in records)
    risky = [r for r in records if r.risk_score > 0]
    model_counter = Counter(r.raw.get("revenue_model", "未填写") for r in records)
    flag_counter = Counter(flag for r in records for flag in r.risk_flags)
    growth = build_growth_diagnosis(records)

    lines = [
        "# 收入质量分析报告",
        "",
        "## 1. 分析结论摘要",
        "",
        f"- 收入明细记录数：{len(records)} 条。",
        f"- 账面确认收入合计：{fmt_money(total_revenue)}。",
        f"- 按模型复算收入合计：{fmt_money(total_expected)}。",
        f"- 回款金额合计：{fmt_money(total_cash)}，整体回款覆盖率：{fmt_pct(safe_div(total_cash, total_revenue))}。",
        f"- 触发至少一项风险信号的记录：{len(risky)} 条。",
        f"- 本次选入高风险样本池：{len(selected)} 条。",
        "",
        "> 说明：本报告用于收入质量诊断、风险初筛和后续测试优先级排序，不直接等同于错报或舞弊结论。",
        "",
    ]

    linked_chart_indexes = set()
    for chart in chart_refs or []:
        try:
            idx = int(chart.get("insight_index", "") or 0)
        except ValueError:
            idx = 0
        if 1 <= idx <= len(insights):
            linked_chart_indexes.add(id(chart))

    summary_charts = [chart for chart in (chart_refs or []) if id(chart) not in linked_chart_indexes]
    if summary_charts:
        lines.extend(["## 2. 可视化摘要", ""])
        for chart in summary_charts:
            chart_title = chart.get("title", "图表")
            chart_path = chart.get("path", "")
            lines.extend([f"### {chart_title}", "", f"![{chart_title}]({chart_path})", ""])

    lines.extend([
        "## 3. 关键洞察与策略建议",
        "",
    ])

    if insights:
        for idx, item in enumerate(insights, 1):
            lines.extend([
                f"### 洞察 {idx}：{item['insight']}",
                f"- 证据：{item['evidence']}",
                f"- 判断：{item['judgment']}",
                f"- 建议：{item['action']}",
            ])
            for chart in chart_refs or []:
                try:
                    chart_idx = int(chart.get("insight_index", "") or 0)
                except ValueError:
                    chart_idx = 0
                if chart_idx == idx:
                    chart_title = chart.get("title", "图表")
                    chart_path = chart.get("path", "")
                    lines.extend(["", f"![{chart_title}]({chart_path})"])
            lines.append("")
    else:
        lines.append("- 暂未形成显著结构性洞察，建议补充更长期间或更多业务维度数据。")

    lines.extend(["## 4. 收入质量分层", "", "| 收入分层 | 收入金额 | 占正向收入比例 | 业务含义 |", "| --- | ---: | ---: | --- |"])
    segment_meaning = {
        "稳定基础收入": "主要由 AUM 和计费天数驱动，通常更可持续。",
        "交易型收入": "由申购/赎回交易驱动，受客户行为和市场活跃度影响。",
        "一次性/高不确定性收入": "通常来自业绩报酬或特殊交易，可持续性较弱。",
        "可疑增长收入": "同时触发计价、回款、期后或关联方等质量信号，需要优先验证。",
    }
    for segment, amount in group_segment_sum(records):
        lines.append(f"| {segment} | {fmt_money(amount)} | {fmt_pct(safe_div(amount, positive_total))} | {segment_meaning.get(segment, '')} |")

    lines.extend(["", "## 5. 增长质量归因", ""])
    contributors: List[RevenueRecord] = growth["top_contributors"]  # type: ignore[assignment]
    lines.append(f"- 收入最高期间：{growth['period']}，收入金额 {fmt_money(float(growth['period_amount']))}。")
    if growth["previous_period"]:
        lines.append(f"- 相比 {growth['previous_period']} 变化：{fmt_money(float(growth['growth']))}。")
    lines.append("- 主要贡献样本：")
    lines.extend(["", "| 记录 | 产品 | 产品类型 | 风险暴露 | 收入分层 | 收入金额 | 质量判断 |", "| --- | --- | --- | --- | --- | ---: | --- |"])
    for r in contributors:
        judgment = "稳定贡献" if r.quality_segment == "稳定基础收入" else "需单独验证"
        lines.append(f"| {r.record_id} | {r.raw.get('fund_product', '')} | {r.raw.get('fund_category', '')} | {r.raw.get('risk_exposure', '')} | {r.quality_segment} | {fmt_money(r.recognized_revenue)} | {judgment} |")

    lines.extend(["", "## 6. 数据口径与勾稽检查", ""])
    if validation_messages:
        lines.extend(f"- {msg}" for msg in validation_messages)
    else:
        lines.append("- 必需字段完整，收入明细可执行模型识别、复算、分层和风险评分。")

    if ledger_recon:
        lines.extend(["", "| 期间 | 明细收入 | 总账收入 | 差异 |", "| --- | ---: | ---: | ---: |"])
        for row in ledger_recon:
            lines.append(f"| {row['period']} | {fmt_money(float(row['detail_revenue']))} | {fmt_money(float(row['ledger_revenue']))} | {fmt_money(float(row['difference']))} |")

    lines.extend(["", "## 7. 收入模型识别", ""])
    for model, count in model_counter.items():
        lines.append(f"- {model}：{count} 条记录。")
    lines.append("- 本 MVP 使用基金/资管手续费收入路径：按申购费、赎回费、管理费、销售服务费、业绩报酬分别选择复算公式和风险信号。")

    lines.extend(["", "## 8. 收入结构与产品画像", ""])
    for title, field in [("费用类型", "fee_type"), ("基金产品", "fund_product"), ("产品类型", "fund_category"), ("规模分层", "aum_size_band"), ("风险暴露", "risk_exposure"), ("渠道", "channel"), ("客户类型", "customer_type")]:
        lines.extend([f"### {title}", "", "| 维度 | 收入金额 | 占比 |", "| --- | ---: | ---: |"])
        for key, amount in group_sum(records, field)[:8]:
            lines.append(f"| {key} | {fmt_money(amount)} | {fmt_pct(safe_div(amount, total_revenue))} |")
        lines.append("")

    lines.extend(["## 9. 费率与计费复算", ""])
    material_variances = [r for r in records if "收入复算偏差" in r.risk_flags or "合同费率偏差" in r.risk_flags]
    if material_variances:
        lines.extend(["| 记录 | 费用类型 | 账面收入 | 复算收入 | 差异 | 合同费率 | 实际费率 |", "| --- | --- | ---: | ---: | ---: | ---: | ---: |"])
        for r in material_variances[:10]:
            lines.append(f"| {r.record_id} | {r.fee_type} | {fmt_money(r.recognized_revenue)} | {fmt_money(r.expected_revenue)} | {fmt_money(r.expected_variance)} | {fmt_pct(to_float(r.raw.get('fee_rate_contract')))} | {fmt_pct(r.actual_rate)} |")
    else:
        lines.append("- 未发现重大复算偏差或合同费率偏差。")

    lines.extend(["", "## 10. 收入质量信号分布", ""])
    if flag_counter:
        lines.extend(["| 风险信号 | 记录数 |", "| --- | ---: |"])
        for flag, count in flag_counter.most_common():
            lines.append(f"| {flag} | {count} |")
    else:
        lines.append("- 未触发风险信号。")

    lines.extend(["", "## 11. 高风险样本池", ""])
    lines.extend(["| 记录 | 期间 | 产品 | 收入分层 | 收入金额 | 风险分 | 主要原因 |", "| --- | --- | --- | --- | ---: | ---: | --- |"])
    for r in selected:
        lines.append(f"| {r.record_id} | {r.period} | {r.raw.get('fund_product', '')} | {r.quality_segment} | {fmt_money(r.recognized_revenue)} | {r.risk_score} | {'、'.join(r.risk_flags)} |")

    lines.extend(["", "## 12. 后续处理建议", ""])
    for r in selected:
        lines.append(f"### {r.record_id} - {r.raw.get('fund_product', '')} / {r.fee_type}")
        lines.append(f"- 收入质量判断：{r.quality_segment}。")
        lines.append(f"- 建议获取资料：{r.suggested_documents}。")
        if r.follow_up_questions:
            lines.append(f"- 建议追问：{r.follow_up_questions}")
        else:
            lines.append("- 建议追问：请结合合同、结算单、发票和回款记录确认收入确认依据。")
        lines.append("")

    lines.extend([
        "## 13. 可用于面试的讲法",
        "",
        "我把收入分析从简单抽样升级成收入质量诊断：先识别收入模型，再加入产品类型、规模分层、风险暴露和收入稳定性分类，判断收入增长到底来自稳定基础收入，还是来自一次性交易、期末大额或待验证收入。然后我用复算差异、费率偏差、回款、期后退款、关联方和新客户等信号生成风险评分，并进一步输出洞察和行动建议。这样项目不只是筛高风险样本，而是能解释收入增长的质量、可持续性和下一步验证重点。",
    ])

    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    revenue_path = Path(args.revenue)
    ledger_path = Path(args.ledger) if args.ledger else None
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = read_csv(revenue_path)
    validation_messages = validate_columns(rows)
    records = score_records(rows)

    ledger_recon: List[Dict[str, float | str]] = []
    if ledger_path and ledger_path.exists():
        ledger_recon = reconcile_ledger(rows, read_csv(ledger_path))
        unreconciled = [r for r in ledger_recon if abs(float(r["difference"])) > 1.0]
        if unreconciled:
            validation_messages.append(f"发现 {len(unreconciled)} 个期间收入明细与总账存在差异，请优先核对口径。")

    selected = [r for r in records if r.risk_score > 0][: args.top_n]
    skill_root = Path(__file__).resolve().parents[1]
    insights, insight_source, insight_note = generate_insights(records, selected, args, skill_root)
    chart_plan, chart_source, chart_note = generate_chart_plan(records, insights, args)

    scored_rows = []
    for r in records:
        scored_rows.append({
            **r.raw,
            "expected_revenue": f"{r.expected_revenue:.2f}",
            "expected_variance": f"{r.expected_variance:.2f}",
            "actual_rate": "" if r.actual_rate is None else f"{r.actual_rate:.8f}",
            "rate_diff": "" if r.rate_diff is None else f"{r.rate_diff:.8f}",
            "cash_collection_ratio": "" if r.cash_collection_ratio is None else f"{r.cash_collection_ratio:.4f}",
            "quality_segment": r.quality_segment,
            "risk_score": r.risk_score,
            "risk_flags": "；".join(r.risk_flags),
            "suggested_documents": r.suggested_documents,
            "follow_up_questions": r.follow_up_questions,
        })

    output_fields = list(scored_rows[0].keys()) if scored_rows else []
    write_csv(out_dir / "risk_scored_revenue.csv", scored_rows, output_fields)
    write_csv(out_dir / "selected_revenue_pool.csv", [row for row in scored_rows if int(row["risk_score"]) > 0][: args.top_n], output_fields)

    question_rows = [{
        "record_id": r.record_id,
        "risk_score": r.risk_score,
        "quality_segment": r.quality_segment,
        "risk_flags": "；".join(r.risk_flags),
        "suggested_documents": r.suggested_documents,
        "follow_up_questions": r.follow_up_questions,
    } for r in selected]
    write_csv(out_dir / "management_questions.csv", question_rows, ["record_id", "risk_score", "quality_segment", "risk_flags", "suggested_documents", "follow_up_questions"])

    insight_rows = [{"source": insight_source, "insight": i["insight"], "evidence": i["evidence"], "judgment": i["judgment"], "action": i["action"]} for i in insights]
    write_csv(out_dir / "revenue_quality_insights.csv", insight_rows, ["source", "insight", "evidence", "judgment", "action"])

    chart_refs = generate_charts(out_dir, records, chart_plan)
    report = build_report(records, validation_messages, ledger_recon, selected, insights, insight_source, insight_note, chart_refs, chart_source, chart_note)
    (out_dir / "revenue_quality_report.md").write_text(report, encoding="utf-8-sig")
    run_metadata = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "revenue_input": str(revenue_path),
        "ledger_input": str(ledger_path) if ledger_path else "",
        "out_dir": str(out_dir),
        "llm_requested": bool(args.use_llm),
        "llm_model": args.llm_model if args.use_llm else "",
        "insight_source": insight_source,
        "chart_source": chart_source,
        "record_count": len(records),
        "selected_sample_count": len(selected),
        "charts": [
            {
                "title": chart.get("title", ""),
                "chart_type": chart.get("chart_type", ""),
                "metric": chart.get("metric", ""),
                "dimension": chart.get("dimension", ""),
                "breakdown": chart.get("breakdown", ""),
                "path": chart.get("path", ""),
                "insight_index": chart.get("insight_index", ""),
            }
            for chart in chart_refs
        ],
    }
    (out_dir / "run_metadata.json").write_text(json.dumps(run_metadata, ensure_ascii=False, indent=2), encoding="utf-8-sig")

    print(f"Wrote {out_dir / 'revenue_quality_report.md'}")
    print(f"Wrote {out_dir / 'risk_scored_revenue.csv'}")
    print(f"Wrote {out_dir / 'selected_revenue_pool.csv'}")
    print(f"Wrote {out_dir / 'management_questions.csv'}")
    print(f"Wrote {out_dir / 'revenue_quality_insights.csv'}")
    print(f"Wrote {out_dir / 'run_metadata.json'}")
    print(f"Wrote {out_dir / 'charts'}")


if __name__ == "__main__":
    main()

