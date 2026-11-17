"""ETL 清洗：三张源表 → 去重 → 去 HTML → 按 class 段落提取 → 批量写入 knowledge。

用法：
    uv run python -m com.tcm.etl.clean --limit 100   # 先跑 100 条验证
    uv run python -m com.tcm.etl.clean               # 全量

幂等：knowledge 上有 (source, src_fid) 唯一约束，重复跑走
     ON DUPLICATE KEY UPDATE，结果不变，可随时重跑。
"""

from __future__ import annotations

import argparse
import html
import re

from com.tcm.db.conn import executemany, query_all

# ------------------------------------------------------------ 清洗规则
# 段落：<p class="drug cf"><span class="fieldname">处方</span>...</p>
P_PAT = re.compile(
    r'<p class="drug (\w+)">\s*<span class="fieldname">(.*?)</span>(.*?)</p>',
    re.S,
)

# 三张源表：库名.表名 → knowledge.source 值（库名.表名是常量，不走白名单）
SOURCES = [
    {"table": "fangji.fangji",   "source": "fangji"},
    {"table": "fangji.zhongyao", "source": "zhongyao"},
    {"table": "fangji.pianfang", "source": "pianfang", "has_channel": True},
]

INSERT_SQL = """
INSERT INTO knowledge
    (source, src_fid, title, content, category, summary, keywords,
     review_status, vector_status, confidence, classify_reason)
VALUES (%s, %s, %s, %s, %s, %s, %s, 1, 0, %s, %s)
ON DUPLICATE KEY UPDATE
    title    = VALUES(title),
    content  = VALUES(content),
    category = VALUES(category),
    summary  = VALUES(summary),
    keywords = VALUES(keywords)
"""


def strip_tags(s: str) -> str:
    """去 HTML 标签 → 实体还原 → 压缩空白。"""
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def parse_content(raw: str) -> list[dict]:
    """HTML 正文 → [{'code','label','text'}, ...]，匹配不到段落返回空列表。"""
    return [
        {"code": code, "label": strip_tags(label), "text": strip_tags(body)}
        for code, label, body in P_PAT.findall(raw)
    ]


FALLBACK_PAT = re.compile(r"【([^】]+)】([^【]+)")


def parse_fallback(raw: str) -> list[dict]:
    """兜底规则（pianfang 等无 class 结构的正文）：

    1. 优先按 【标签】正文 的方括号段落拆；
    2. 连方括号都没有，整篇算一段"正文"。
    """
    text = strip_tags(raw)
    pairs = FALLBACK_PAT.findall(text)
    if pairs:
        return [{"code": "", "label": label.strip(), "text": body.strip()} for label, body in pairs]
    if text:
        return [{"code": "", "label": "正文", "text": text}]
    return []


def clean_row(row: dict, source: str, has_channel: bool) -> dict | None:
    """一条源记录 → 一条 knowledge 记录；解析不出段落返回 None（计入过滤）。"""
    segs = parse_content(row["content"] or "") or parse_fallback(row["content"] or "")
    if not segs:
        return None

    # 摘要优先取"功能主治"，没有就取第一段
    summary = next((s["text"] for s in segs if s["code"] == "gnzz"), segs[0]["text"])
    # 清洗后正文：各段落拼 "标签：文本"
    content = "\n".join(f"{s['label']}：{s['text']}" for s in segs)

    category, confidence, reason = "", None, None
    if has_channel and row.get("channelId"):
        # 偏方自带栏目 ID：暂存 ID，等拿到栏目名称映射再更新
        category = str(row["channelId"])
        confidence = 100
        reason = "源数据自带栏目ID（channelId），自动通过"

    return {
        "source": source,
        "src_fid": str(row["fid"]),
        "title": (row["title"] or "").strip(),
        "content": content,
        "category": category,
        "summary": summary[:1000],
        "keywords": (row["keywords"] or "").strip(),
        "confidence": confidence,
        "classify_reason": reason,
    }


def iter_rows(table: str, with_channel: bool, batch: int = 500):
    """按 fid 游标分批取数，不把 3 万条 longtext 一次性拉进内存。"""
    cols = "fid, title, keywords, content, state, isDel" + (", channelId" if with_channel else "")
    last = 0
    while True:
        rows = query_all(
            f"SELECT {cols} FROM {table} WHERE fid > %s ORDER BY fid LIMIT %s",
            (last, batch),
        )
        if not rows:
            return
        yield from rows
        last = rows[-1]["fid"]


def run_source(table: str, source: str, has_channel: bool, limit: int | None) -> dict:
    """清洗一张源表，返回清洗报告（输入/过滤/入库 三个数）。"""
    stat = {"输入": 0, "过滤": 0, "入库": 0}
    buf: list[tuple] = []

    def flush():
        nonlocal buf
        if not buf:
            return
        executemany(INSERT_SQL, buf)
        stat["入库"] += len(buf)
        buf = []

    for row in iter_rows(table, has_channel):
        if limit is not None and stat["输入"] >= limit:
            break
        stat["输入"] += 1
        if row["state"] != 1 or row["isDel"] != 0:
            stat["过滤"] += 1
            continue
        item = clean_row(row, source, has_channel)
        if item is None:
            stat["过滤"] += 1
            continue
        buf.append((
            item["source"], item["src_fid"], item["title"], item["content"],
            item["category"], item["summary"], item["keywords"],
            item["confidence"], item["classify_reason"],
        ))
        if len(buf) >= 500:
            flush()
    flush()
    return stat


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="三源清洗入库")
    ap.add_argument("--limit", type=int, default=None, help="每张表最多处理多少条（测试用）")
    args = ap.parse_args()

    total = {"输入": 0, "过滤": 0, "入库": 0}
    for src in SOURCES:
        stat = run_source(src["table"], src["source"], src.get("has_channel", False), args.limit)
        print(f"[{src['source']:>9}] 输入 {stat['输入']:>6} | 过滤 {stat['过滤']:>5} | 入库 {stat['入库']:>6}")
        for k in total:
            total[k] += stat[k]
    print("-" * 46)
    print(f"[合计     ] 输入 {total['输入']:>6} | 过滤 {total['过滤']:>5} | 入库 {total['入库']:>6}")
    print("清洗报告：源表保持只读，重跑本脚本结果不变（幂等）。")
