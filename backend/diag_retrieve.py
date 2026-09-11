"""一次性诊断 v2：分离「RRF 融合分」与「重排 sigmoid 分」，并做对照实验判断重排模型好坏。

用法（backend 目录下）：
    python diag_retrieve.py
跑完删掉即可。
"""

from __future__ import annotations

import asyncio
import time
import uuid

from app.config import get_settings
from app.core.rag_engine import RAGEngine
from app.db.database import get_session_factory

KB_ID = uuid.UUID("95428936-cd21-4541-8e7e-b85f402c29ca")

# ① 你实际问的归纳类问题
Q_SUMMARY = "帮我总结一下文档的核心要点"
# ② 对照：直接引用文档里的原文片段（若模型正常，这条必须拿高分）
Q_VERBATIM = "陈默推开那扇掉漆的木门时，铰链发出一声沉闷的呻吟"
# ③ 对照：关键词型问题
Q_KEYWORD = "聊斋 剧本大纲 片名"


async def run_one(engine, factory, q: str, label: str) -> None:
    print("\n" + "=" * 70)
    print("【%s】query = %s" % (label, q))

    async with factory() as db:
        emb = await engine._embed_query(q)
        fused = await engine._retrieve_chunks(db, KB_ID, emb, q)

    print("  -- RRF 融合后（score=归一化值, fused=原始分, 命中通道）--")
    for i, c in enumerate(fused[:5], 1):
        print("     #%d score=%.4f fused=%.6f ch=%s  %s" % (
            i, c.score, c.fused_score, ",".join(c.channels),
            c.text[:30].replace("\n", " ")))

    async with factory() as db:
        t = time.time()
        reranked = await engine._rerank_chunks(q, fused)
        cost = time.time() - t

    print("  -- 重排后（sigmoid；logit 为原始分）--  耗时 %.1fs" % cost)
    for i, c in enumerate(reranked[:5], 1):
        print("     #%d sigmoid=%.6f logit=%s  %s" % (
            i, c.score,
            "%.3f" % c.reranker_logit if c.reranker_logit is not None else "n/a",
            c.text[:30].replace("\n", " ")))
    s = get_settings()
    # 拒答判据必须与 rag_engine 保持一致：召回为空 ⇒ 拒答；绝对阈值仅在开关打开时参与
    refused = (not reranked) or (
        s.confidence_gate_enabled
        and reranked[0].score < s.confidence_threshold
    )
    print("     -> top1 sigmoid=%.6f | 绝对阈值门控=%s | 最终拒答=%s" % (
        reranked[0].score if reranked else 0.0,
        s.confidence_gate_enabled,
        "是" if refused else "否",
    ))


async def main() -> None:
    settings = get_settings()
    print("配置: confidence_threshold=%s | rerank_enabled=%s | rrf_k=%s | top_k=%s | rerank_top_n=%s"
          % (settings.confidence_threshold, settings.rerank_enabled, settings.rrf_k,
             settings.similarity_top_k, settings.rerank_top_n))

    engine = RAGEngine()
    factory = get_session_factory()

    await run_one(engine, factory, Q_SUMMARY, "归纳类问题")
    await run_one(engine, factory, Q_VERBATIM, "对照A：引用原文")
    await run_one(engine, factory, Q_KEYWORD, "对照B：关键词")

    print("\n" + "=" * 70)
    print("[怎么读] 修复后的预期表现（2026-09-10 之后）")
    print("  1) 三条通道应重新出现在 ch= 里（lexical/fulltext），而不是只有 vector。")
    print("     修前：词法 0 命中、全文 0 命中，融合退化成纯向量。")
    print("     修后：全文逐字 OR + 词法 word_similarity，关键词类 query 应能命中。")
    print("  2) 「归纳类」的 sigmoid 依旧很低（0.002~0.005）且 logit 为负 —— 这是正常的：")
    print("     cross-encoder 打的是『这段能否回答该问题』，而总结类问题没有单个片段能回答。")
    print("     所以拒答不能靠绝对阈值，只能靠『召回是否为空』。")
    print("  3) 判读：只要 拒答=否 且 ch 里有多通道命中，检索链路就是健康的。")


if __name__ == "__main__":
    asyncio.run(main())
