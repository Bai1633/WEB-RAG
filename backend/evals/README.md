# 检索评测闭环（RAG Eval Harness）

回答"**你怎么知道你的检索是好的**"：用一组带标准答案的 QA 用例跑真实检索管道，量化
hit@k / recall / MRR / 关键词覆盖，并输出 **top_score 分布**作为拒答阈值
（`CONFIDENCE_THRESHOLD`）的校准依据。支持开关多轮查询改写做对照实验。

## 运行前置

- PostgreSQL 可用（`DB_*` 配置）；Embedding 端点可用（`EMBEDDING_*` 配置）
- 在 `backend/` 目录下执行（脚本通过 `python -m` 以包方式运行）

## 快速开始

```bash
# 1. 用样例文档新建临时知识库 → 灌入 → 跑 9 条用例 → 输出报告 → 自动清理
python -m evals.run_eval --cases evals/golden_qa.example.json --docs-dir evals/sample_docs

# 2. 对照实验：关闭多轮查询改写，观察两个 followup 用例的 hit/recall 变化
python -m evals.run_eval --cases evals/golden_qa.example.json \
    --docs-dir evals/sample_docs --no-rewrite

# 3. 针对已有知识库评测（用例里的 expected_sources 要写该库中的文件名）
python -m evals.run_eval --cases my_cases.json --kb-id <uuid> --json-out report.json

# 4. 无 Embedding 端点时跑通全链路（确定性哈希向量，CI smoke 用；
#    相似度只反映词面重叠，指标不代表真实语义质量）
EMBEDDING_PROVIDER=mock EMBEDDING_DIM=384 \
    python -m evals.run_eval --cases evals/golden_qa.example.json --docs-dir evals/sample_docs
```

## 用例格式（JSON）

```jsonc
{
  "cases": [
    {
      "id": "case-1",
      "question": "独立完整的问题",
      "expected_sources": ["文件名.md"],     // 相关集，参与 hit/recall/MRR
      "expected_keywords": ["关键词"],        // 召回文本中的关键词覆盖率
      "history": [ ... ],                    // 可选：多轮追问用例（配合改写开关做对照）
      "expect_refusal": true                 // 可选：拒答用例，判定 top_score 是否低于阈值
    }
  ]
}
```

## 指标含义

| 指标 | 含义 |
|---|---|
| hit@k | top-k 中是否出现任一期望来源文档 |
| recall@k | top-k 覆盖期望来源文档的比例 |
| MRR | 首个期望来源的排名倒数均值（衡量排序质量） |
| keyword_coverage | 期望关键词在召回 chunk 原文中的覆盖率 |
| score_calibration | 命中组 / 未中组的 top_score 分布——**两组分得越开，拒答阈值越好定** |

## 纳入新领域的评测

1. 准备文档目录 + 按文档内容手写 20~100 条用例（直接问题、多轮追问、应拒答各留一些）
2. 跑基线 → 调整分块/检索参数/阈值 → 复跑对比（`--json-out` 保留每次报告）
3. 每次改动检索相关代码后复跑，防止质量回退（可接入 CI 作门禁）
