"""检索：问题 → bge 编码 → Chroma 向量召回 TopK → 返回带溯源的片段。

这是 1.3 冻结的契约实现，返回结构全组统一：
    {"source", "fid", "title", "seg"(段落类型), "text", "score"}

用法：
    uv run python -m com.tcm.rag.retriever "治痞块的方子" 5
"""

from __future__ import annotations

import sys

import chromadb
from sentence_transformers import SentenceTransformer

from com.tcm.cfg.settings import settings
from com.tcm.rag import bm25

# 模块级缓存：模型只加载一次，别每次检索都重载 1.3GB
_model: SentenceTransformer | None = None
_col = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(settings.EMBED_MODEL_PATH, device="cpu")
    return _model


def get_collection():
    global _col
    if _col is None:
        client = chromadb.PersistentClient(path=settings.CHROMA_DIR)
        _col = client.get_or_create_collection("tcm_knowledge", metadata={"hnsw:space": "cosine"})
    return _col


def search(question: str, top_k: int = 5, hybrid: bool = True) -> list[dict]:
    """检索：默认混合（向量语义 + BM25 关键词，RRF 融合）。

    hybrid=False 时退回纯向量检索。返回结构保持契约：
        {"source", "fid", "title", "seg", "text", "score"}
    另附 "fused"（融合分）与 "from"（vec / bm25 / both）便于排查。
    """
    vec = get_model().encode([question], normalize_embeddings=True)
    res = get_collection().query(query_embeddings=vec.tolist(), n_results=max(top_k * 2, 10))

    vec_hits = []
    for i in range(len(res["ids"][0])):
        vec_hits.append({
            "id": res["ids"][0][i],
            "score": round(1 - res["distances"][0][i], 4),
            "doc": res["documents"][0][i],
            "meta": res["metadatas"][0][i],
        })

    if not hybrid:
        merged = vec_hits[:top_k]
    else:
        bm_hits = bm25.search(question, top_k=10)
        merged = bm25.rrf_fuse(vec_hits, bm_hits, top_k)
        # BM25 单独命中的没有向量分，按 BM25 分归一化映射到 0.5~0.8，
        # 保证能越过问答端的 0.5 拒答阈值（关键词命中同样算"找到了"）
        if bm_hits:
            top_bm = max(h["score"] for h in bm_hits)
            for h in merged:
                if h.get("score") is None:      # 只有 BM25 命中：把 BM25 分归一化后映射
                    raw = h.get("bm_score") or 0
                    h["score"] = round(0.5 + 0.3 * (raw / top_bm if top_bm else 0), 4)

    out = []
    for h in merged:
        meta = h["meta"]
        out.append({
            "source": meta.get("source", ""),
            "fid": meta.get("src_fid", ""),
            "title": meta.get("title", ""),
            "seg": meta.get("seg", ""),
            "text": h["doc"],
            "score": h["score"],
            "fused": h.get("fused"),
            "from": h.get("from", "vec"),
        })
    return out


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "治痞块的方子"
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    print(f"问题：{q}（召回 {k}）")
    print("-" * 60)
    for i, hit in enumerate(search(q, k), 1):
        print(f"{i}. [{hit['source']}/{hit['seg']}] {hit['title']}  相似度 {hit['score']}")
        print(f"   {hit['text'][:100]}")
        print(f"   溯源：source={hit['source']} fid={hit['fid']}")
