"""BM25 关键词检索 + RRF 混合检索（阶段：二期增强）。

- 语料来源 = MySQL 的 knowledge 表（已入库且未删除），用与向量化完全相同的
  chunk_item 切分，因此 chunk id 与向量路（Chroma）一致，RRF 才能按 id 融合。
- 为什么不直接读 Chroma：chromadb 的 get() 在常驻进程内有读取缓存，单条编辑
  upsert 后 get() 仍可能返回旧数据，导致 BM25 索引停在旧内容。MySQL 是编辑的
  唯一事实来源，读它最可靠，也彻底绕开 Chroma 缓存问题。
- 分词 = jieba + docs/tcm_terms.txt 中医药术语词典
- 融合 = RRF（Reciprocal Rank Fusion）：按"排名倒数"加权，不需要调权重

单独测试：uv run python -m com.tcm.rag.bm25 "痞块"
"""

from __future__ import annotations

import threading

from rank_bm25 import BM25Okapi

from com.tcm.rag import tokenizer

_RRF_K = 60          # RRF 常数，越小排名靠前的优势越大
_bm25 = None
_bm25_dirty = False   # 编辑/重向量化单条后置脏，强制下次重建（只看 chunk 数会漏掉"数量不变"的更新）
_corpus_rows = -1     # 建索引时的来源行数（增量判断用；注意 chunk 数 ≠ knowledge 行数，别拿它比较）
_corpus_ids: list[str] = []
_corpus_docs: list[str] = []
_corpus_metas: list[dict] = []
_build_lock = threading.Lock()   # 并发请求同时触发 build 时只建一次，避免重复几分钟的全量重建


def invalidate_bm25() -> None:
    """编辑/重向量化单条后调用：标记 BM25 缓存失效，下次检索自动重建到最新内容。"""
    global _bm25_dirty
    _bm25_dirty = True


def _load_chunks() -> tuple[list[dict], int]:
    """从 MySQL 拉全部已入库知识，用 chunk_item 切成与向量路同 id 的 chunk。

    返回 (chunks, 来源行数)：行数用于增量判断（判断内容有没有新增），
    不能拿 chunk 总数和行数比——两者天然不相等，会导致每次检索都全量重建。
    """
    from com.tcm.rag import embedding
    from com.tcm.db.conn import query_all
    all_chunks: list[dict] = []
    n_rows = 0
    page = 0
    while True:
        rows = query_all(
            "SELECT id, source, src_fid, title, content FROM knowledge "
            "WHERE isDel=0 AND vector_status=1 LIMIT 2000 OFFSET %s", (page * 2000,))
        if not rows:
            break
        n_rows += len(rows)
        for it in rows:
            all_chunks += embedding.chunk_item(it)
        page += 1
    return all_chunks, n_rows


def build(rebuild: bool = False) -> None:
    """从 MySQL 拉全部已入库 chunk 建 BM25 索引（首次 / 数据变 / 置脏时执行）。

    增量判断：当前表行数 == 建索引时的行数 且 未置脏 → 直接复用缓存。
    """
    global _bm25, _corpus_ids, _corpus_docs, _corpus_metas, _bm25_dirty, _corpus_rows
    if _bm25 is not None and not rebuild and not _bm25_dirty:
        from com.tcm.db.conn import query_one
        n = query_one("SELECT COUNT(*) n FROM knowledge WHERE isDel=0 AND vector_status=1")["n"]
        if n == _corpus_rows:
            return

    with _build_lock:
        # 拿到锁后再查一次：可能别的线程刚建完，直接复用
        if _bm25 is not None and not rebuild and not _bm25_dirty:
            from com.tcm.db.conn import query_one
            n = query_one("SELECT COUNT(*) n FROM knowledge WHERE isDel=0 AND vector_status=1")["n"]
            if n == _corpus_rows:
                return

        chunks, n_rows = _load_chunks()
        _corpus_ids = [c["id"] for c in chunks]
        _corpus_docs = [c["text"] for c in chunks]
        _corpus_metas = [c["meta"] for c in chunks]
        corpus = [tokenizer.cut(d) for d in _corpus_docs]
        _bm25 = BM25Okapi(corpus)
        _corpus_rows = n_rows
        _bm25_dirty = False


def search(query: str, top_k: int = 10) -> list[dict]:
    """BM25 检索，返回 [{'id','score','doc','meta'}]（score=0 的不要）。

    两条硬规则（防止"单字命中"污染结果、冲掉问答端的拒答阈值）：
    1. 只认 ≥2 字的词（单字如"天""气"没有区分度）
    2. 命中的原文里必须真的出现过该词（而不是靠 BM25 的统计权重）
    """
    build()
    if _bm25 is None or not _corpus_ids:
        return []

    terms = [t for t in tokenizer.cut(query) if len(t) >= 2]
    if not terms:
        return []

    scores = _bm25.get_scores(tokenizer.cut(query))
    ranked = sorted(range(len(scores)), key=lambda i: -scores[i])[:top_k]
    return [
        {"id": _corpus_ids[i], "score": float(scores[i]),
         "doc": _corpus_docs[i], "meta": _corpus_metas[i]}
        for i in ranked
        if scores[i] > 0 and any(t in _corpus_docs[i] for t in terms)
    ]


def rrf_fuse(vec_hits: list[dict], bm_hits: list[dict], top_k: int) -> list[dict]:
    """RRF 融合：score = Σ 1/(k + rank)，两路都命中会叠加。"""
    fused: dict[str, float] = {}
    for rank, h in enumerate(vec_hits, 1):
        fused[h["id"]] = fused.get(h["id"], 0.0) + 1.0 / (_RRF_K + rank)
    for rank, h in enumerate(bm_hits, 1):
        fused[h["id"]] = fused.get(h["id"], 0.0) + 1.0 / (_RRF_K + rank)

    vec_ids = {h["id"] for h in vec_hits}
    bm_ids = {h["id"] for h in bm_hits}
    by_id = {h["id"]: h for h in vec_hits}
    for h in bm_hits:
        if h["id"] not in by_id:          # 只有 BM25 命中的，没有向量分
            by_id[h["id"]] = {"id": h["id"], "score": None, "bm_score": h["score"],
                              "doc": h["doc"], "meta": h["meta"]}

    ranked = sorted(fused.items(), key=lambda kv: -kv[1])[:top_k]
    out = []
    for cid, fs in ranked:
        item = dict(by_id[cid])
        item["fused"] = round(fs, 6)
        item["from"] = "both" if (cid in vec_ids and cid in bm_ids) else ("vec" if cid in vec_ids else "bm25")
        out.append(item)
    return out


if __name__ == "__main__":
    import sys

    q = sys.argv[1] if len(sys.argv) > 1 else "痞块"
    build()
    print(f"语料 chunk 数：{len(_corpus_ids)}")
    for h in search(q, 5):
        print(f"  {h['score']:.3f}  {h['doc'][:60]}")
