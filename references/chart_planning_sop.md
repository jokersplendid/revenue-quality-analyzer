# LLM Chart Planning SOP

## Purpose

Use this SOP when an LLM needs to decide how a revenue-quality report should use charts. The goal is not to force chart diversity by hard rules. The goal is to make each visual serve a specific analytical job, while Python keeps calculations deterministic and checks whether the chosen visual is valid.

## Core Principle

Do not ask the LLM to choose a chart type first. Ask it to identify the analytical expression task first.

Bad pattern:

- This insight needs a bar chart.
- Do not repeat bar charts.

Better pattern:

- What question does this insight need to make visible?
- Which dimensions and metrics prove that point?
- Is a visual necessary, or would text/table be clearer?
- Which visual grammar best expresses that evidence?

## Pipeline

1. Generate or collect report insights.
2. For each insight, classify the analytical expression task.
3. Decide whether the insight needs a visual, a table, or no visual.
4. If visual support is needed, output metric, dimension, breakdown, visual intent, and chart family.
5. Python validates fields, metrics, and chart feasibility.
6. Python renders charts with deterministic calculations.
7. Python checks visual redundancy across the report.
8. The final report displays only natural report content and images, not chart-planning rationale.

## Analytical Expression Tasks

| Task | Question It Answers | Revenue Example | Visual Families |
| --- | --- | --- | --- |
| trend_change | When did revenue move abnormally? | December revenue spiked sharply. | line, area, annotated trend |
| structure_mix | What is revenue made of? | Stable base revenue vs questionable growth revenue. | stacked bar, 100% stacked bar |
| growth_contribution | Who or what drove the movement? | A few funds explain most of the peak month. | contribution bar, Pareto, waterfall |
| cross_relationship | Which combinations concentrate revenue or risk? | Product x fee type concentration. | heatmap, matrix table |
| risk_distribution | Which risk signals dominate? | Low collection and cutoff signals dominate. | ranked bar, dot plot |
| calculation_comparison | Where do booked and recalculated amounts diverge? | Booked revenue differs from recomputed fee income. | variance bar, paired bar, scatter |
| sample_explanation | Which records require follow-up? | A related-party fee has rate deviation. | detail table, compact cards, no chart |

## LLM Output Contract

The LLM should return chart plans, not finished charts. Each planned visual should contain:

- insight_index: the insight this visual supports.
- needs_visual: true or false.
- analysis_task: controlled value such as trend_change or cross_relationship.
- visual_intent: one sentence describing what the reader should see.
- metric: validated numeric field or derived metric.
- dimension: validated categorical or time field.
- breakdown: optional second dimension.
- chart_family: controlled value such as line, stacked_bar, heatmap, ranked_bar, variance_bar, detail_table, none.
- priority: high, medium, or low.

Python should own the allowed vocabularies. The LLM can recommend, but Python validates.

## Validation Rules

Python should reject or repair a visual plan when:

- The metric does not exist or cannot be derived.
- The dimension does not exist.
- The chart family cannot express the analytical task.
- The visual duplicates another visual without adding a new metric, dimension, or task.
- The insight is clearer as a table or text.

Do not enforce superficial rules such as only one bar chart. Two bar charts may both be useful if one explains product concentration and another explains risk signal distribution. Three charts showing the same risk signal distribution are redundant.

## Redundancy Scoring

Score each planned visual against previous visuals:

- Same analysis_task: +0.30
- Same chart_family: +0.20
- Same metric: +0.20
- Same dimension: +0.20
- Same breakdown: +0.10

If similarity is high and the new visual does not support a different insight, Python should downgrade it to detail_table or request an alternate plan.

## Report Placement Rules

- Put visuals directly after the insight they support.
- Do not display chart reason, chart conclusion, LLM source, or prompt/process metadata in the final report.
- If a visual supports multiple insights, place it after the first relevant insight rather than duplicating it.
- Not every insight needs a chart.

## Revenue-Quality Examples

Period spike: use trend_change with period as dimension and recognized_revenue as metric. Use line or stacked trend if quality mix matters.

Questionable growth share: use structure_mix with quality_segment as dimension and recognized_revenue as metric. Use stacked composition or ranked bar depending on the question.

Product and fee concentration: use cross_relationship with fund_product and fee_type. Use heatmap or matrix.

Related-party rate deviation: use sample_explanation or calculation_comparison. Use detail table or variance bar only if the comparison adds clarity.

## Generic Chart Type Library

The chart planner should choose a generic chart type first, then specify fields. Avoid hard-coding business topics such as product-fee heatmap as chart IDs.

| Chart Type | Chinese Name | Best For | Required Spec |
| --- | --- | --- | --- |
| bar | 条形图 | Comparing numeric values across categories or groups. | metric + dimension |
| line | 折线图 | Showing change over time, trend, seasonality, or abnormal spikes. | metric + time_dimension |
| donut | 环形图 | Showing proportion of a small number of categories. | metric + dimension |
| stacked_bar | 堆叠条形图 | Showing composition by a second dimension across categories or time. | metric + dimension + breakdown |
| heatmap | 热力图 | Showing concentration or relationship across two categorical dimensions. | metric + dimension + breakdown |
| pareto | 帕累托图 | Showing head concentration with category contribution and cumulative share. | metric + dimension |
| waterfall | 瀑布图 | Showing what contributed to a movement, peak, or total. | metric + dimension |
| dot | 点图 | Showing ranked priority or relative strength with less visual weight than bars. | metric + dimension |
| scatter | 散点图 | Showing relationship between two numeric variables and outliers. | x_metric + y_metric |

Examples:

- Fund fee income: `chart_type=heatmap`, `metric=positive_revenue`, `dimension=fund_product`, `breakdown=fee_type`.
- SaaS subscription revenue: `chart_type=line`, `metric=renewal_revenue`, `time_dimension=month`.
- Ad revenue: `chart_type=pareto`, `metric=revenue`, `dimension=channel`.
- E-commerce GMV: `chart_type=stacked_bar`, `metric=gmv`, `dimension=month`, `breakdown=category`.

## MVP Renderer Families

- line: period trend.
- stacked_bar: composition by segment or fee type.
- contribution_bar: top contributors.
- heatmap: two categorical dimensions crossed by revenue.
- ranked_bar: top risk signals or products.
- variance_bar: booked vs recomputed difference.
- detail_table: high-risk sample details.

The renderer can grow later without changing the planning layer.
