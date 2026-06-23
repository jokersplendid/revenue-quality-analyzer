---
name: revenue-quality-analyzer
description: Use this skill when analyzing revenue quality, fee/service income, revenue models, growth drivers, pricing/fee-rate reasonableness, cutoff risk, subsequent collection/refund signals, and high-risk revenue samples. The MVP is optimized for fund and asset-management fee income such as subscription fees, redemption fees, management fees, sales service fees, and performance fees.
---

# Revenue Quality Analyzer

## Overview

Revenue Quality Analyzer turns an audit-style revenue review into a business analysis workflow: identify the revenue model, choose model-specific drivers, explain revenue movement, score quality signals, generate insights, and produce a focused follow-up sample pool.

The MVP supports fund and asset-management fee income. It can be extended to SaaS, marketplace, advertising, project/service, and other revenue models by adding model reference files and routing rules.

## When To Use

Use this skill when the user needs to:

- Analyze revenue quality rather than only checking vouchers.
- Review fee or service income, especially fund product fees.
- Explain revenue movement by product, customer, channel, fee type, AUM, transaction volume, fee rate, or collection/refund signals.
- Separate stable base revenue from transaction-driven, one-off, or questionable growth revenue.
- Build a high-risk revenue testing pool with explainable reasons.
- Draft follow-up questions and document requests for finance or business teams.
- Convert a revenue audit workpaper SOP into a reusable data analysis pipeline.

## Workflow

1. Validate data scope and reconciliation.
2. Identify the revenue model.
3. Select model-specific drivers.
4. Run structure and movement analysis.
5. Run pricing and calculation checks.
6. Score revenue-quality signals.
7. Generate insights and outputs.

## Running The MVP

```powershell
python scripts\analyze_revenue_quality.py --revenue assets\sample_fund_fee_revenue.csv --ledger assets\sample_revenue_ledger.csv --out-dir reports
```

Expected outputs:

- `reports/revenue_quality_report.md`
- `reports/revenue_quality_insights.csv`
- `reports/risk_scored_revenue.csv`
- `reports/selected_revenue_pool.csv`
- `reports/management_questions.csv`

## Optional LLM Insight Mode

The script can optionally call an OpenAI-compatible chat completions API to generate less rigid business insights. API keys must stay outside the repository.

```powershell
$env:LLM_API_KEY="your_api_key"
$env:LLM_BASE_URL="https://api.openai.com/v1"
$env:LLM_MODEL="gpt-4.1-mini"
python scripts\analyze_revenue_quality.py --revenue assets\sample_fund_fee_revenue.csv --ledger assets\sample_revenue_ledger.csv --out-dir reports --use-llm
```

If `LLM_API_KEY` is missing or the API call fails, the script falls back to deterministic rule insights and records the source in the report.

## Interview Framing

> 我把传统收入底稿里的人工复核，抽象成了一个收入质量分析框架。第一步先识别收入模型，因为不同收入模型的驱动因子不同；然后基于模型复算收入、拆解结构和增长驱动，再把费率偏差、期末集中确认、低回款、期后退款、新客户大额、关联方等信号做成可解释评分，输出高风险样本池和后续追问清单。这个项目不只是筛风险样本，还能解释收入增长的质量和可持续性。

## References

- `references/revenue_model_router.md`: common routing logic and extension pattern.
- `references/revenue_models/fund_fee.md`: MVP fund fee income model, formulas, risk signals, and follow-up questions.
- `references/chart_planning_sop.md`: LLM chart-planning SOP for mapping insights to analytical expression tasks and avoiding redundant visuals.
- `prompts/llm_insight_system_prompt.md`: optional LLM prompt for business insight generation.
