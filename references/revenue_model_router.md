# Revenue Model Router

This reference turns revenue review into a routing problem. The first question is not "which vouchers should we inspect", but "what economic model generates this revenue". The model determines the denominator, formula, risk rules, and follow-up questions.

## Common Routing Fields

Use these fields when available:

- `revenue_model`: declared model, such as `fund_fee`, `subscription`, `marketplace`, `advertising`, `project_service`.
- `fee_type` or `product_type`: subscription fee, redemption fee, management fee, sales service fee, performance fee, SaaS subscription, commission, ads, project milestone.
- `business_volume`: transaction amount, GMV, AUM, order amount, ad spend, service milestone amount.
- `fee_rate_contract`: contract rate, take rate, commission rate, annual management rate, or price list rate.
- `recognition_date`, `settlement_date`, `cash_collected`, `refund_after_period`: timing and collectability evidence.

## Why Model Recognition Matters

The revenue model changes four things:

1. Formula
   - Fund subscription fee: transaction amount x fee rate.
   - Fund management fee: average AUM x annual rate x service days / 365.
   - Marketplace commission: GMV x take rate.
   - SaaS subscription: contract value recognized over service period.

2. Driver analysis
   - Fund fees explain movement through AUM, subscription/redemption volume, fee rate, channel mix, and product mix.
   - SaaS explains movement through new MRR, expansion, contraction, churn, renewal, and discount.
   - Marketplace explains movement through orders, GMV, AOV, take rate, refund rate, and subsidy.

3. Risk signals
   - Fund fees: fee-rate mismatch, revenue without AUM/transaction support, performance fee without hurdle, channel concentration.
   - SaaS: annual contract pulled forward, churn hidden by discounts, service period mismatch.
   - Marketplace: gross vs net presentation, refund/subsidy masking, abnormal take rate.

4. Follow-up evidence
   - Fund fees: fund contract, fee table, AUM report, TA transaction report, settlement statement, bank receipt.
   - SaaS: contract, service period, billing schedule, usage/activation data, renewal/churn list.
   - Marketplace: order ledger, settlement report, refund data, commission rules, merchant agreement.

## MVP Routing Rule

If `revenue_model` equals `fund_fee`, or `fee_type` is one of `subscription_fee`, `redemption_fee`, `management_fee`, `sales_service_fee`, `performance_fee`, use `references/revenue_models/fund_fee.md`.

If no specific model matches, use common checks only:

- Period-end concentration.
- High-value or round-number records.
- Low cash collection.
- Subsequent refund or reversal.
- New customer large revenue.
- Related-party revenue.
- Missing or inconsistent dates.
- Missing business volume or contract rate.
