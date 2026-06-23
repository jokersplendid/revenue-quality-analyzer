# Revenue Quality Analyzer

一个面向收入质量分析的 Python MVP。它把传统收入底稿里的人工复核流程，抽象成可复用的数据分析 pipeline：收入模型识别、业务驱动拆解、收入质量分层、费率/计费复算、风险信号评分、关键洞察生成、高风险样本池，以及后续追问和资料清单输出。

当前 MVP 聚焦基金/资管业务中的手续费收入场景，包括申购费、赎回费、管理费、销售服务费和业绩报酬。

## 项目背景

收入分析不应该只停留在“抽几笔凭证看单据”。更有价值的问题是：收入增长来自稳定基础收入，还是来自一次性交易或期末大额确认？收入是否过度集中在少数产品、少数客户或高波动产品上？账面收入是否能被业务量、AUM、费率、回款和期后情况支撑？

所以这个项目的核心不是替代审计判断，而是把收入复核变成一套可解释、可复用、可扩展的数据分析框架。

## 分析流程

```text
收入明细数据 -> 数据口径校验 -> 收入模型识别 -> 业务驱动拆解 -> 收入质量分层 -> 费率/计费复算 -> 风险信号评分 -> 关键洞察与策略建议 -> 高风险样本池 -> 后续追问和资料清单 -> 中文 Markdown 报告
```

## 当前支持的收入模型

当前实现的是 `fund_fee` 基金/资管手续费收入模型。

| 费用类型 | 核心分母 | 复算逻辑 |
| --- | --- | --- |
| 申购费 | 申购金额 | 申购金额 x 合同费率 |
| 赎回费 | 赎回金额 | 赎回金额 x 合同费率 |
| 管理费 | 平均 AUM、计费天数 | 平均 AUM x 年费率 x 计费天数 / 365 |
| 销售服务费 | 对应份额 AUM、计费天数 | 对应 AUM x 年费率 x 计费天数 / 365 |
| 业绩报酬 | 超额收益或业绩报酬基数 | 满足门槛后按约定比例计提 |

## 关键分析内容

### 1. 数据口径校验

检查收入明细与总账/试算平衡表是否勾稽，识别期间差异、缺失字段、日期异常和负数收入。

### 2. 收入模型识别

先判断收入来自哪种商业模式，再选择对应的驱动因子和复算公式。比如基金手续费收入中，申购费看交易金额和费率，管理费看 AUM、年费率和计费天数，业绩报酬看门槛是否满足。

### 3. 收入质量分层

脚本会生成 `quality_segment`，把收入分为稳定基础收入、交易型收入、一次性/高不确定性收入、可疑增长收入。这个分层用于判断收入增长是否可持续，而不是只做描述性统计。

### 4. 产品画像与结构分析

项目会按费用类型、基金产品、产品类型、规模分层、风险暴露、渠道、客户类型拆解收入。比如 12 月收入大幅增长，但主要来自高波动产品、期末大额申购费和低回款样本，结论就不是“收入增长好”，而是“收入高点更像由非稳定增量贡献，需要优先验证”。

### 5. 费率与计费复算

- 复算收入：按业务模型和合同费率重新计算的理论收入。
- 实际费率：账面收入 / 对应业务量或 AUM 折算分母。
- 合同费率：合同、协议或费率表约定的费率。

当实际费率明显高于合同费率，或账面收入明显高于复算收入时，会被标记为后续验证重点。

### 6. 风险信号评分

当前覆盖大额收入、期末集中确认、收入复算偏差、合同费率偏差、缺少业务量/AUM 支撑、低回款覆盖、期后退款或冲回、新客户大额收入、关联方收入、业绩报酬门槛未满足、发票金额不一致、日期缺失或异常。

风险分数不是舞弊结论，而是后续测试优先级排序。

## LLM 洞察生成

项目支持两种洞察模式：

1. 默认规则模式：不需要 API key，完全本地运行，输出可解释的规则洞察。
2. LLM 模式：把结构化指标、高风险样本和业务画像发给 OpenAI-compatible API，让模型生成更自然、更接近业务分析报告的洞察、判断和行动建议。

API key 不写进代码，也不上传 GitHub。脚本只从环境变量读取。

```powershell
$env:LLM_API_KEY="你的_API_key"
$env:LLM_BASE_URL="https://api.openai.com/v1"
$env:LLM_MODEL="gpt-4.1-mini"
python scripts\analyze_revenue_quality.py --revenue assets\sample_fund_fee_revenue.csv --ledger assets\sample_revenue_ledger.csv --out-dir reports --use-llm
```

如果换成其他兼容 OpenAI 格式的模型服务，只需要改 `LLM_BASE_URL` 和 `LLM_MODEL`。如果没有设置 `LLM_API_KEY`，脚本会自动回退到规则洞察，并在报告里标注 `rule_fallback`。

## 项目结构

```text
revenue-quality-analyzer/
|-- SKILL.md
|-- README.md
|-- .gitignore
|-- agents/openai.yaml
|-- assets/sample_fund_fee_revenue.csv
|-- assets/sample_revenue_ledger.csv
|-- prompts/llm_insight_system_prompt.md
|-- references/revenue_model_router.md
|-- references/revenue_models/fund_fee.md
|-- scripts/analyze_revenue_quality.py
`-- reports/
    |-- revenue_quality_report.md
    |-- revenue_quality_insights.csv
    |-- risk_scored_revenue.csv
    |-- selected_revenue_pool.csv
    `-- management_questions.csv
```

## 如何运行

```powershell
python scripts\analyze_revenue_quality.py --revenue assets\sample_fund_fee_revenue.csv --ledger assets\sample_revenue_ledger.csv --out-dir reports
```

脚本只使用 Python 标准库，不需要额外安装依赖。

## 输出文件

| 文件 | 说明 |
| --- | --- |
| `reports/revenue_quality_report.md` | 中文收入质量分析报告 |
| `reports/revenue_quality_insights.csv` | 洞察、证据、判断、行动建议 |
| `reports/risk_scored_revenue.csv` | 每条收入记录的复算结果、质量分层、风险信号和风险分 |
| `reports/selected_revenue_pool.csv` | 高风险样本池 |
| `reports/management_questions.csv` | 针对高风险样本的追问问题和资料清单 |

