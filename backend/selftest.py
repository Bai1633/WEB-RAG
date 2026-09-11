import asyncio, time
from app.config import get_settings
from app.core.embedding import get_embedding_provider
from app.core.reranker import rerank, reranker_enabled
from app.core.llm import get_llm_provider

s = get_settings()
print("配置: rerank=%s | llm=%s @ %s | emb=%s @ %s dim=%s" % (
    s.rerank_enabled, s.llm_model_name, s.llm_base_url,
    s.embedding_model_name, s.embedding_base_url, s.embedding_dim))

t = time.time()
try:
    v = get_embedding_provider().get_embeddings(["测试文本"])
    print("[1] embedding 成功 dim=%d，耗时 %.2fs" % (len(v[0]), time.time() - t))
except Exception as e:
    print("[1] embedding 失败，耗时 %.2fs -> %r" % (time.time() - t, e))

async def test_llm():
    t = time.time()
    try:
        text, _ = await get_llm_provider().chat([{"role": "user", "content": "只回复两个字：收到"}])
        print("[2] LLM 成功，耗时 %.2fs -> %r" % (time.time() - t, text[:50]))
    except Exception as e:
        print("[2] LLM 失败，耗时 %.2fs -> %r" % (time.time() - t, e))

asyncio.run(test_llm())

if reranker_enabled():
    t = time.time()
    try:
        rerank("测试问题", [{"text": "测试段落", "score": 0.5}])
        print("[3] 重排加载成功，耗时 %.2fs" % (time.time() - t))
    except Exception as e:
        print("[3] 重排失败，耗时 %.2fs -> %r" % (time.time() - t, e))
else:
    print("[3] 重排已关闭")
