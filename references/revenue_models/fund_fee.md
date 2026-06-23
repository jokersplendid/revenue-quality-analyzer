# Fund Fee Revenue Model

Use this reference for fund and asset-management fee income. The goal is to explain revenue quality from business drivers, not only to tick vouchers.

## Supported Fee Types

- `subscription_fee`:申购费. Usually based on subscription amount and subscription fee rate.
- `redemption_fee`:赎回费. Usually based on redemption amount and redemption fee rate.
- `management_fee`:管理费. Usually based on average AUM, annual management fee rate, and service days.
- `sales_service_fee`:销售服务费. Usually based on relevant share-class AUM, annual service fee rate, and service days.
- `performance_fee`:业绩报酬. Usually based on excess return or performance base after hurdle conditions are met.

## Core Formulas

Subscription fee:

```text
expected_revenue = subscription_amount x fee_rate_contract
actual_rate = recognized_revenue / subscription_amount
```

Redemption fee:

```text
expected_revenue = redemption_amount x fee_rate_contract
actual_rate = recognized_revenue / redemption_amount
```

Management fee and sales service fee:

```text
expected_revenue = average_aum x fee_rate_contract x service_days / 365
actual_rate = recognized_revenue / (average_aum x service_days / 365)
```

Performance fee:

```text
if performance_hurdle_met = true:
    expected_revenue = performance_base x fee_rate_contract
else:
    expected_revenue = 0
```

## Structure Analysis Dimensions

Common dimensions:

- Month.
- Fee type.
- Fund product.
- Fund type.
- Channel.
- Customer type.
- Share class.

Model-specific questions:

- Is revenue concentrated in a few products or channels?
- Did management fee revenue grow without AUM growth?
- Did transaction fee revenue grow because of higher subscription/redemption volume or a changed fee rate?
- Is channel mix changing toward higher-fee channels?
- Is performance fee recognized before hurdle evidence is clear?

## Risk Signals

High-priority signals:

- Recognized revenue materially exceeds recalculated expected revenue.
- Actual rate differs materially from contract rate.
- Management or sales service fee has revenue but no AUM or service-day support.
- Performance fee is recognized when hurdle condition is not met or not documented.
- Large revenue appears near period end.
- Large new customer or new product revenue appears without historical baseline.
- Revenue has low cash collection or later refund/reversal.
- Related-party revenue has abnormal pricing or weak business substance.

## Follow-up Documents

Ask for evidence based on the triggered signal:

- Fund contract and fee table.
- TA transaction report or subscription/redemption confirmation.
- AUM report by product/share class and service period.
- Fund accounting settlement statement.
- Invoice and bank receipt.
- Performance fee calculation sheet and hurdle evidence.
- Channel agreement or sales agency fee schedule.
- Subsequent refund/reversal list.

## Follow-up Question Style

Use concrete business questions:

- "这笔收入对应的费率为什么与合同费率不一致？是否存在折扣、减免或渠道分成安排？"
- "管理费收入增长是否由平均 AUM 增长驱动？请提供按产品和份额类别的 AUM 明细。"
- "这笔期末确认的申购/赎回费对应的 TA 交易确认日在什么时候？是否跨期？"
- "业绩报酬确认时是否已经满足计提门槛？请提供计算底稿和复核记录。"
- "期后退款/冲回对应的原始交易是什么？是否影响本期收入确认？"
