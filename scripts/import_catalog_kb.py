"""一次性脚本：把 catalog.json 中原始知识库缺失的三类内容（名医 / 故事 / 发展历程）
导入 knowledge 表。

- review_status=1 ：直接跳过人工审核（与"存量数据导入"一致）。
- vector_status=0 ：标记待向量化，随后由 com.tcm.rag.embedding 增量向量化。
- 按 src_fid 去重，可重复运行，不会重复插入。

用法：uv run python scripts/import_catalog_kb.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 让 `com` 包可从项目根被导入（脚本在 scripts/ 下运行时不自动加入根路径）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from com.tcm.db.conn import execute, query_one

CATALOG = Path(__file__).resolve().parents[1] / "static" / "data" / "catalog.json"


def build_content(head: dict, fields: list[dict]) -> str:
    """把 {name/pinyin/tag/summary} + fields[] 拼成 '标签：值' 文本，
    正好契合 embedding.chunk_item 按 '：' 分行的切块逻辑。"""
    lines = []
    if head.get("name"):
        lines.append(f"名称：{head['name']}")
    if head.get("pinyin"):
        lines.append(f"拼音：{head['pinyin']}")
    if head.get("tag"):
        lines.append(f"标签：{head['tag']}")
    if head.get("summary"):
        lines.append(f"简介：{head['summary']}")
    for f in fields:
        lines.append(f"{f['label']}：{f['value']}")
    return "\n".join(lines)


def insert(src_fid: str, title: str, content: str, category: str) -> None:
    if query_one("SELECT id FROM knowledge WHERE src_fid=%s", (src_fid,)):
        print(f"  跳过(已存在): {src_fid}")
        return
    execute(
        "INSERT INTO knowledge (source, src_fid, title, content, category, review_status, vector_status) "
        "VALUES ('catalog', %s, %s, %s, %s, 1, 0)",
        (src_fid, title, content, category),
    )
    print(f"  已导入: {src_fid} -> {title}")


def main() -> None:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))

    # 名医 / 故事：各条目已是 {name, pinyin, tag, summary, fields[]}
    for key in ("doctors", "stories"):
        for item in data.get(key, []):
            insert(item["id"], item["name"],
                   build_content(item, item.get("fields", [])), item["type"])

    # 发展历程：6 个纪元拆成 6 条独立记录，召回粒度更细
    for i, era in enumerate(data.get("history", []), 1):
        fid = f"history-{i}"
        title = f"中医药发展历程：{era['era']}"
        content = (
            f"名称：{title}\n"
            f"时期：{era['era']}\n"
            f"主题：{era['title']}\n"
            f"内容：{era['desc']}"
        )
        insert(fid, title, content, "history")

    print("\n导入完成。下一步运行：uv run python -m com.tcm.rag.embedding --limit 0")


if __name__ == "__main__":
    main()
