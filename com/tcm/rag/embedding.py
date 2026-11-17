"""切片 + 向量化（阶段 3）。

用法：
    uv run python -m com.tcm.rag.embedding --limit 500    # 批量向量化（默认 500 条）
    uv run python -m com.tcm.rag.embedding --limit 0      # 0 = 不限，跑到没有未入库的为止

设计要点：
1. 切片：knowledge.content 每行一段（"标签：文本"），按行切，拼 title，带段落类型
2. 批量编码：攒够 BATCH_SEG 段再一次性 encode（embed_documents 批量接口），比逐条快 2~3 倍
3. 断点续跑：只处理 vector_status=0 的记录，处理完回写 1；中断重跑自动接着来
4. 增量：revector_one(item_id) 单条重算，供管理端编辑后调用
"""

from __future__ import annotations

# ⚠️ 必须最先导入 torch，避免 Windows 上 sentence_transformers 懒加载时 DLL 冲突段错误
import torch  # noqa: F401

import argparse
import time
from typing import Iterable

import chromadb
from sentence_transformers import SentenceTransformer

from com.tcm.cfg.settings import settings
from com.tcm.db.conn import execute, query_all, query_one
from com.tcm.rag import bm25

BATCH_SEG = 64   # 一批多少"段"一起送进模型

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


def chunk_item(item: dict) -> list[dict]:
    """一条知识 → 若干 chunk（一行一段，天然语义边界）。

    没有"标签："的行（PDF 标题、说明行等）不单独成块，而是并入下一段，
    避免出现"只有标题、没有信息量"的无效 chunk。
    """
    chunks: list[dict] = []
    pending = ""
    for i, line in enumerate(item["content"].split("\n")):
        line = line.strip()
        if not line:
            continue
        if "：" not in line:
            pending = f"{pending} {line}".strip()
            continue
        label = line.split("：", 1)[0]
        chunks.append({
            "id": f"{item['id']}-{i}",
            "text": f"{item['title']}｜{pending} {line}".strip() if pending else f"{item['title']}｜{line}",
            "meta": {
                "kid": item["id"],
                "source": item["source"],
                "src_fid": item["src_fid"],
                "title": item["title"],
                "seg": label[:20],
            },
        })
        pending = ""

    if pending:   # 结尾剩余的无标签行，兜底成一块
        chunks.append({
            "id": f"{item['id']}-tail",
            "text": f"{item['title']}｜{pending}",
            "meta": {"kid": item["id"], "source": item["source"], "src_fid": item["src_fid"],
                     "title": item["title"], "seg": "正文"},
        })
    return chunks


def _upsert(chunks: list[dict]) -> None:
    """批量编码 + 写入 Chroma。"""
    if not chunks:
        return
    model = get_model()
    texts = [c["text"] for c in chunks]
    embs = model.encode(texts, batch_size=BATCH_SEG, normalize_embeddings=True)
    get_collection().upsert(
        ids=[c["id"] for c in chunks],
        embeddings=embs.tolist(),
        documents=texts,
        metadatas=[c["meta"] for c in chunks],
    )


def fetch_pending(limit: int) -> list[dict]:
    sql = ("SELECT id, source, src_fid, title, content FROM knowledge "
           "WHERE review_status = 1 AND vector_status = 0 ORDER BY id")
    if limit > 0:
        sql += " LIMIT %s"
        return query_all(sql, (limit,))
    return query_all(sql)


def run(limit: int = 500) -> None:
    rows = fetch_pending(limit)
    if not rows:
        print("没有待向量化的记录（全部已入库）")
        return
    print(f"待向量化：{len(rows)} 条，加载模型…")
    get_model()

    buf: list[dict] = []
    pending_ids: list[int] = []
    done = 0
    t0 = time.time()

    for item in rows:
        chunks = chunk_item(item)
        pending_ids.append(item["id"])
        buf.extend(chunks)
        if len(buf) >= BATCH_SEG:
            _flush(buf, pending_ids)
            buf, pending_ids = [], []
        done += 1
        if done % 50 == 0:
            _progress(done, len(rows), t0)

    _flush(buf, pending_ids)
    _progress(done, len(rows), t0)
    print(f"Chroma 当前共 {get_collection().count()} 个 chunk")


def _flush(buf: list[dict], pending_ids: list[int]) -> None:
    """写一批：先写向量，再回写 vector_status（保证中断也不重复算）。"""
    if not pending_ids:
        return
    _upsert([c for c in buf if c["meta"]["kid"] in set(pending_ids)])
    for kid in pending_ids:
        execute("UPDATE knowledge SET vector_status = 1 WHERE id = %s", (kid,))


def _progress(done: int, total: int, t0: float) -> None:
    used = time.time() - t0
    speed = done / used if used > 0 else 0
    left = (total - done) / speed if speed > 0 else 0
    print(f"  已完成 {done}/{total}　用时 {used:.0f}s　速度 {speed:.2f} 条/秒　预计剩余 {left/60:.1f} 分钟")


def revector_one(item_id: int) -> bool:
    """增量：单条知识重算向量（管理端编辑后调用）。

    先按 kid 删掉这条的旧 chunk，再重新切片写入，最后回写 vector_status=1。
    """
    item = query_one(
        "SELECT id, source, src_fid, title, content FROM knowledge WHERE id = %s", (item_id,)
    )
    if item is None:
        return False

    col = get_collection()
    old = col.get(where={"kid": item_id})
    if old and old["ids"]:
        col.delete(ids=old["ids"])

    chunks = chunk_item(item)
    if not chunks:
        execute("UPDATE knowledge SET vector_status = 1 WHERE id = %s", (item_id,))
        bm25.invalidate_bm25()
        return True

    _upsert(chunks)
    execute("UPDATE knowledge SET vector_status = 1 WHERE id = %s", (item_id,))
    bm25.invalidate_bm25()
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="切片 + 向量化（批量 / 增量）")
    ap.add_argument("--limit", type=int, default=500, help="本次处理多少条，0 表示不限")
    ap.add_argument("--one", type=int, default=0, help="只重算指定 id 这一条（增量）")
    args = ap.parse_args()

    if args.one:
        ok = revector_one(args.one)
        print(f"增量重算 id={args.one}：{'成功' if ok else '记录不存在'}")
    else:
        run(args.limit)
