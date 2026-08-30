"""Retrieval evaluation harness — proves (and improves) whether the pipeline
retrieves the right chunks.

用法（在 backend 目录下、使用已配置 EMBEDDING_* 与 DB_* 的环境）::

    # 用样例文档新建临时知识库并跑完整评测
    python -m evals.run_eval --cases evals/golden_qa.example.json --docs-dir evals/sample_docs

    # 对照实验：关闭多轮查询改写（观察多轮追问用例的指标变化）
    python -m evals.run_eval --cases evals/golden_qa.example.json --docs-dir evals/sample_docs --no-rewrite

    # 针对已有知识库评测（expected_sources 需与其中的文件名对应）
    python -m evals.run_eval --cases my_cases.json --kb-id <uuid>

    # 输出 JSON 报告 / 保留评测用知识库
    python -m evals.run_eval ... --json-out eval_report.json --keep-kb

指标:
    hit@k / recall@k / MRR —— 以 expected_sources（文件名）为相关集
    keyword_coverage        —— 期望关键词在召回 chunk 文本中的覆盖率
    top_score 分布          —— 按 hit/miss 分组，用于拒答阈值 (confidence_threshold) 校准
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

from evals.compute_metrics import (
    hit_at_k,
    keyword_coverage,
    percentile,
    recall_at_k,
    reciprocal_rank,
)

MIME_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
    ".txt": "text/plain",
    ".csv": "text/csv",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run retrieval evaluation against a knowledge base.")
    p.add_argument("--cases", required=True, help="评测用例 JSON 文件路径")
    p.add_argument("--docs-dir", help="待灌入的文档目录（与 --kb-id 二选一）")
    p.add_argument("--kb-id", help="已有知识库 UUID（与 --docs-dir 二选一，不做清理）")
    p.add_argument("--top-k", type=int, default=5, help="参与命中判定的结果数（默认 5）")
    p.add_argument("--no-rewrite", action="store_true", help="禁用多轮查询改写（对照组）")
    p.add_argument("--keep-kb", action="store_true", help="保留临时创建的知识库")
    p.add_argument("--json-out", help="将完整报告写入该 JSON 文件")
    return p.parse_args()


async def ingest_docs(session, docs_dir: Path, kb_id: uuid.UUID) -> dict[str, str]:
    """Synchronously parse -> chunk -> embed -> insert. Mirrors workers.tasks."""
    import mimetypes

    from sqlalchemy import text

    from app.config import get_settings
    from app.core.chunking import TextChunker
    from app.core.document_parser import DocumentParser
    from app.core.embedding import get_embedding_provider
    from app.core.index_manager import VectorIndexManager

    settings = get_settings()
    parser = DocumentParser()
    chunker = TextChunker(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
    provider = get_embedding_provider()
    table = VectorIndexManager.table_name_from_str(str(kb_id))

    insert_sql = f"""
        INSERT INTO {table} (chunk_id, doc_id, kb_id, text, metadata, embedding)
        VALUES (:chunk_id, :doc_id, :kb_id, :text,
                CAST(:metadata AS jsonb), CAST(:embedding AS vector))
    """

    filename_to_doc: dict[str, str] = {}
    for path in sorted(docs_dir.iterdir()):
        if not path.is_file():
            continue
        mime = MIME_BY_SUFFIX.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0]
        if not mime:
            print(f"  [跳过] 未知类型: {path.name}")
            continue
        parsed = parser.parse(str(path), mime)
        chunks = chunker.chunk_text(
            parsed.text,
            metadata={"filename": path.name, "source": path.name},
        )
        if not chunks:
            print(f"  [跳过] 无可提取文本: {path.name}")
            continue
        doc_id = str(uuid.uuid4())
        filename_to_doc[path.name] = doc_id
        embeddings = provider.get_embeddings([c.text for c in chunks])
        for chunk, emb in zip(chunks, embeddings, strict=True):
            await session.execute(
                text(insert_sql),
                {
                    "chunk_id": str(uuid.uuid4()),
                    "doc_id": doc_id,
                    "kb_id": str(kb_id),
                    "text": chunk.text,
                    "metadata": json.dumps(chunk.metadata, ensure_ascii=False),
                    "embedding": "[" + ",".join(str(v) for v in emb) + "]",
                },
            )
        await session.commit()
        print(f"  [灌入] {path.name}: {len(chunks)} chunks")
    return filename_to_doc


async def run_case(session, engine, case: dict, kb_id: uuid.UUID, top_k: int, use_rewrite: bool) -> dict:
    """Run one eval case through the retrieval pipeline and score it."""
    from app.config import get_settings

    settings = get_settings()
    question: str = case["question"]
    history = case.get("history")
    expected = set(case.get("expected_sources", []))
    keywords = case.get("expected_keywords", [])

    retrieve_query = question
    if history and use_rewrite:
        retrieve_query = await engine.rewrite_query(question, history)

    t0 = time.perf_counter()
    chunks = await engine.retrieve(session, kb_id, retrieve_query)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    retrieved_sources = [c.source for c in chunks[:top_k]]
    top_score = float(chunks[0].score) if chunks else 0.0

    result = {
        "id": case.get("id", question[:20]),
        "question": question,
        "retrieve_query": retrieve_query,
        "rewritten": bool(history) and retrieve_query != question,
        "retrieved": retrieved_sources,
        "top_score": round(top_score, 4),
        "latency_ms": latency_ms,
        "hit": hit_at_k(retrieved_sources, expected, top_k) if expected else False,
        "recall": recall_at_k(retrieved_sources, expected, top_k) if expected else 0.0,
        "rr": reciprocal_rank(retrieved_sources, expected) if expected else 0.0,
        "keyword_coverage": keyword_coverage([c.text for c in chunks[:top_k]], keywords),
        "expect_refusal": bool(case.get("expect_refusal")),
    }
    if result["expect_refusal"]:
        result["refusal_correct"] = (not chunks) or top_score < settings.confidence_threshold
    return result


def print_report(results: list[dict], top_k: int) -> dict:
    """Print a human-readable report; return the aggregate section."""
    print(f"\n{'用例':<28} {'改写':<4} {'hit':<5} {'recall':<7} {'rr':<5} "
          f"{'top分':<7} {'耗时':<8} 检索结果")
    print("-" * 100)
    for r in results:
        flag = "✓" if (r["hit"] or (r["expect_refusal"] and r.get("refusal_correct"))) else "✗"
        rw = "是" if r["rewritten"] else "-"
        print(f"{flag} {r['id']:<25} {rw:<4} {str(r['hit']):<5} "
              f"{r['recall']:<7.2f} {r['rr']:<5.2f} {r['top_score']:<7.3f} "
              f"{str(r['latency_ms']) + 'ms':<8} {', '.join(r['retrieved'][:3]) or '(无结果)'}")

    retrievable = [r for r in results if not r["expect_refusal"]]
    refusals = [r for r in results if r["expect_refusal"]]
    hits = [r for r in retrievable if r["hit"]]
    misses = [r for r in retrievable if not r["hit"]]

    aggregate = {
        "top_k": top_k,
        "cases": len(results),
        "hit_rate": round(sum(r["hit"] for r in retrievable) / len(retrievable), 4) if retrievable else 0.0,
        "mean_recall": round(sum(r["recall"] for r in retrievable) / len(retrievable), 4) if retrievable else 0.0,
        "mrr": round(sum(r["rr"] for r in retrievable) / len(retrievable), 4) if retrievable else 0.0,
        "mean_keyword_coverage": round(sum(r["keyword_coverage"] for r in retrievable) / len(retrievable), 4)
        if retrievable else 0.0,
        "avg_latency_ms": round(sum(r["latency_ms"] for r in results) / len(results), 1) if results else 0,
        "refusal_correct_rate": round(
            sum(1 for r in refusals if r.get("refusal_correct")) / len(refusals), 4
        ) if refusals else None,
        "score_calibration": {
            "hit_top_scores": {
                "min": percentile([r["top_score"] for r in hits], 0),
                "p50": percentile([r["top_score"] for r in hits], 50),
                "max": percentile([r["top_score"] for r in hits], 100),
            },
            "miss_top_scores": {
                "min": percentile([r["top_score"] for r in misses], 0),
                "p50": percentile([r["top_score"] for r in misses], 50),
                "max": percentile([r["top_score"] for r in misses], 100),
            },
        },
    }

    print("\n===== 汇总 =====")
    print(f"hit@{aggregate['top_k']}: {aggregate['hit_rate']:.2%}   "
          f"mean_recall: {aggregate['mean_recall']:.2%}   MRR: {aggregate['mrr']:.3f}   "
          f"关键词覆盖: {aggregate['mean_keyword_coverage']:.2%}")
    print(f"平均检索耗时: {aggregate['avg_latency_ms']}ms   "
          f"拒答正确率: {aggregate['refusal_correct_rate'] if aggregate['refusal_correct_rate'] is not None else 'n/a'}")
    cal = aggregate["score_calibration"]
    print("top_score 分布（拒答阈值校准参考）:")
    print(f"  命中组:  min={cal['hit_top_scores']['min']:.3f}  "
          f"p50={cal['hit_top_scores']['p50']:.3f}  max={cal['hit_top_scores']['max']:.3f}")
    print(f"  未中组:  min={cal['miss_top_scores']['min']:.3f}  "
          f"p50={cal['miss_top_scores']['p50']:.3f}  max={cal['miss_top_scores']['max']:.3f}")
    return aggregate


async def main() -> int:
    args = parse_args()
    if bool(args.docs_dir) == bool(args.kb_id):
        print("--docs-dir 与 --kb-id 必须二选一", file=sys.stderr)
        return 2

    try:
        if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
            sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    cases_doc = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    cases: list[dict] = cases_doc["cases"]
    print(f"加载 {len(cases)} 条评测用例（rewrite={'开' if not args.no_rewrite else '关'}）")

    from app.config import get_settings
    from app.core.rag_engine import RAGEngine
    from app.db.database import close_db, get_session_factory
    from app.db.repositories.user_repo import UserRepository
    from app.services.kb_service import KBService

    get_settings()  # fail fast on bad config
    engine = RAGEngine()
    factory = get_session_factory()
    created_user_id: uuid.UUID | None = None
    created_kb_id: uuid.UUID | None = None

    async with factory() as session:
        kb_service = KBService(session)
        if args.kb_id:
            kb_id = uuid.UUID(args.kb_id)
            kb = await kb_service.get_kb(kb_id)
            if not kb:
                print(f"知识库不存在: {kb_id}", file=sys.stderr)
                return 2
            print(f"评测目标: 已有知识库 {kb.name} ({kb_id})")
        else:
            suffix = time.strftime("%m%d%H%M%S")
            user = await UserRepository(session).create(
                email=f"eval-{suffix}@eval.local", hashed_password="not-a-login-hash"
            )
            kb = await kb_service.create_kb(
                owner_id=user.id, name=f"eval-{suffix}", description="评测临时知识库"
            )
            await session.commit()
            created_user_id, created_kb_id = user.id, kb.id
            print(f"已创建临时知识库: {kb.name} ({kb.id})")

        if args.docs_dir:
            docs_dir = Path(args.docs_dir)
            if not docs_dir.is_dir():
                print(f"文档目录不存在: {docs_dir}", file=sys.stderr)
                return 2
            print(f"灌入文档: {docs_dir}")
            await ingest_docs(session, docs_dir, kb.id)

        results = []
        for case in cases:
            try:
                results.append(
                    await run_case(
                        session, engine, case, kb.id, args.top_k, use_rewrite=not args.no_rewrite
                    )
                )
            except Exception as e:
                print(f"  [用例失败] {case.get('id')}: {e}", file=sys.stderr)

        aggregate = print_report(results, args.top_k)

        if args.json_out:
            report = {"config": vars(args) | {"kb_id": str(kb.id)}, "aggregate": aggregate,
                      "cases": results}
            Path(args.json_out).write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"\n报告已写入: {args.json_out}")

        if created_kb_id and not args.keep_kb:
            await kb_service.delete_kb(created_kb_id)
            await UserRepository(session).delete(created_user_id)
            await session.commit()
            print("已清理临时知识库与评测账号（--keep-kb 可保留）")

    await close_db()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
