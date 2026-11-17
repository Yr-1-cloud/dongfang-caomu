"""后台管理业务逻辑。

状态机：review_status 0待复核 / 1已复核 / 2已拒绝；vector_status 0未入库 / 1已入库。
门禁：只有 review_status=1 才允许向量化（存量数据导入时已刷成 1，门禁只对新上传/录入生效）。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import torch  # noqa: F401  必须最先导入，避免 Windows 上 DLL 冲突段错误

from com.tcm.cfg.settings import settings
from com.tcm.db.conn import execute, get_conn, query_all, query_one
from com.tcm.rag import embedding

UPLOAD_DIR = Path(settings.CHROMA_DIR).parent / "uploads"


# ---------------------------------------------------------------- 门禁
def can_vectorize(review_status: int) -> bool:
    """入库门禁：已复核才允许进向量库。"""
    return review_status == 1


def add_task(kid: int, task_type: str) -> None:
    execute("INSERT INTO kb_task (kid, task_type) VALUES (%s, %s)", (kid, task_type))


def run_task(kid: int, task_type: str) -> bool:
    """同步执行任务（数据量小够用；量大时改 worker 轮询 kb_task）。"""
    try:
        if task_type == "revector":
            embedding.revector_one(kid)
        execute("UPDATE kb_task SET status=1 WHERE kid=%s AND task_type=%s AND status=0", (kid, task_type))
        return True
    except Exception:
        execute("UPDATE kb_task SET status=2 WHERE kid=%s AND task_type=%s", (kid, task_type))
        return False


# ---------------------------------------------------------------- 手工录入 / 删除 / 重向量化
def add_manual(title: str, content: str, category: str = "") -> dict:
    """手工录入：直接进待复核队列，复核通过才会向量化。"""
    import uuid
    execute(
        "INSERT INTO knowledge (source, src_fid, title, content, category, review_status, vector_status) "
        "VALUES ('manual', %s, %s, %s, %s, 0, 0)",
        (uuid.uuid4().hex[:12], title, content, category))
    return {"ok": True, "msg": "已录入，进入待复核队列"}


def delete_item(kid: int) -> dict:
    """软删 + 同步撤下向量，问答端立刻查不到。"""
    if not query_one("SELECT id FROM knowledge WHERE id=%s AND isDel=0", (kid,)):
        return {"ok": False, "msg": "记录不存在"}
    execute("UPDATE knowledge SET isDel=1, vector_status=0 WHERE id=%s", (kid,))
    try:
        embedding.get_collection().delete(where={"kid": kid})
    except Exception:
        pass
    return {"ok": True, "msg": "已删除，向量已同步撤下"}


def revector(kid: int) -> dict:
    """单条重新向量化（门禁：已复核）。"""
    item = query_one("SELECT review_status FROM knowledge WHERE id=%s AND isDel=0", (kid,))
    if not item:
        return {"ok": False, "msg": "记录不存在"}
    if not can_vectorize(item["review_status"]):
        return {"ok": False, "msg": "未复核，不允许向量化"}
    add_task(kid, "revector")
    ok = run_task(kid, "revector")
    return {"ok": ok, "msg": "已重新向量化" if ok else "向量化失败（任务已记录）"}


# ---------------------------------------------------------------- 统计与列表
def stats() -> dict:
    """顶部 4 张统计卡片。"""
    one = lambda sql: query_one(sql)["n"]
    return {
        "total": one("SELECT COUNT(*) n FROM knowledge WHERE isDel=0"),
        "vectorized": one("SELECT COUNT(*) n FROM knowledge WHERE isDel=0 AND vector_status=1"),
        "pending_review": one("SELECT COUNT(*) n FROM knowledge WHERE isDel=0 AND review_status=0"),
    }


def list_items(page: int = 1, size: int = 20, source: str = "", review_status: str = "",
               vector_status: str = "", keyword: str = "") -> dict:
    """分页列表 + 筛选，返回 {rows, total, page, size}。"""
    where, args = ["isDel=0"], []
    if source:
        where.append("source=%s"); args.append(source)
    if review_status != "":
        where.append("review_status=%s"); args.append(int(review_status))
    if vector_status != "":
        where.append("vector_status=%s"); args.append(int(vector_status))
    if keyword:
        where.append("title LIKE %s"); args.append(f"%{keyword}%")
    cond = " AND ".join(where)
    total = query_one(f"SELECT COUNT(*) n FROM knowledge WHERE {cond}", tuple(args))["n"]
    rows = query_all(
        f"SELECT id, source, src_fid, title, category, review_status, vector_status, "
        f"confidence, LEFT(content, 80) AS brief FROM knowledge WHERE {cond} "
        f"ORDER BY id DESC LIMIT %s OFFSET %s",
        tuple(args) + (size, (page - 1) * size),
    )
    return {"rows": rows, "total": total, "page": page, "size": size}


def review(kid: int, action: str) -> dict:
    """行内复核：pass → 已复核并触发向量化；reject → 已拒绝并撤下向量。"""
    item = query_one("SELECT id, review_status FROM knowledge WHERE id=%s", (kid,))
    if not item:
        return {"ok": False, "msg": "记录不存在"}
    if action == "pass":
        execute("UPDATE knowledge SET review_status=1 WHERE id=%s", (kid,))
        add_task(kid, "revector")
        ok = run_task(kid, "revector")
        return {"ok": ok, "msg": "已通过并向量化" if ok else "已通过，但向量化失败（任务已记录）"}
    if action == "reject":
        execute("UPDATE knowledge SET review_status=2, vector_status=0 WHERE id=%s", (kid,))
        return {"ok": True, "msg": "已拒绝，不进向量库"}
    return {"ok": False, "msg": "action 只能是 pass / reject"}


def save_edit(kid: int, title: str, content: str) -> dict:
    """编辑保存 → 置未入库 → 重算该条（增量同步）。"""
    item = query_one("SELECT review_status FROM knowledge WHERE id=%s", (kid,))
    if not item:
        return {"ok": False, "msg": "记录不存在"}
    execute("UPDATE knowledge SET title=%s, content=%s, vector_status=0 WHERE id=%s", (title, content, kid))
    if not can_vectorize(item["review_status"]):
        return {"ok": True, "msg": "已保存，但未复核，暂不进向量库", "vectorized": False}
    add_task(kid, "revector")
    ok = run_task(kid, "revector")
    return {"ok": ok, "msg": "已保存并同步到向量库（问答端立即可查）" if ok else "已保存，向量化失败",
            "vectorized": ok}


# ---------------------------------------------------------------- 上传（MD5 秒传）
def extract_text(path: Path, suffix: str) -> str:
    """PDF 用 pypdf 抽文本；txt/md 直接读；其它返回空。"""
    if suffix.lower() in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix.lower() == ".pdf":
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    return ""


def save_upload(filename: str, data: bytes) -> dict:
    """上传：算 MD5 → 命中直接秒传；未命中落盘 + 建知识条目（待复核）。"""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    md5 = hashlib.md5(data).hexdigest()
    hit = query_one("SELECT kid FROM kb_attachment WHERE file_md5=%s", (md5,))
    if hit:  # 秒传：不重复存、不重复解析
        return {"ok": True, "skipped": True, "kid": hit["kid"], "md5": md5, "msg": "文件已存在，秒传成功，未重复解析"}
    path = UPLOAD_DIR / f"{md5}{Path(filename).suffix}"
    path.write_bytes(data)
    text = extract_text(path, path.suffix)
    title = Path(filename).stem
    # 插入与取自增 id 必须在同一条连接上（连接池换连接会拿到错的 lastrowid）
    with get_conn(commit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO knowledge (source, src_fid, title, content, category, review_status, vector_status) "
                "VALUES ('doc', %s, %s, %s, '', 0, 0)",
                (md5, title, text or title),
            )
            kid = cur.lastrowid
            cur.execute(
                "INSERT INTO kb_attachment (file_md5, file_name, file_path, file_size, kid, source_module) "
                "VALUES (%s, %s, %s, %s, %s, 'doc')",
                (md5, filename, str(path), len(data), kid),
            )
    return {"ok": True, "skipped": False, "kid": kid, "md5": md5,
            "msg": "上传成功，已进入待复核队列（解析→抽取→分类→待复核）"}


