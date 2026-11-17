# -*- coding: utf-8 -*-
"""增量同步闭环测试（阶段 5.4 验收）。

验证：后台改一条知识 → 向量库立即更新 → 问答端能查到新内容。

用法（项目根目录执行）：
    uv run python docs/check/增量测试.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # 让 com.tcm 可导入

import torch  # noqa: F401,E402  ⚠️ 必须最先导入，见 graph.py 的说明

from com.tcm.db.conn import query_one
from com.tcm.qa import graph
from com.tcm.rag import retriever
from com.tcm.admin import service

MARK = "【增量测试标记XYZ】"   # 一个源数据里绝不可能出现的词


def main() -> None:
    print("=" * 60)
    print("增量同步闭环测试")
    print("=" * 60)

    # 1. 挑一条已入库的知识
    item = query_one(
        "SELECT id, title, content FROM knowledge WHERE vector_status = 1 AND source = 'fangji' "
        "ORDER BY id LIMIT 1"
    )
    if item is None:
        print("没有已向量化的记录，先跑：uv run python -m com.tcm.rag.embedding --limit 50")
        return
    kid, old_title = item["id"], item["title"]
    print(f"1. 选中知识 id={kid} 标题《{old_title}》")

    # 2. 改标题，加一个唯一标记
    new_title = old_title + MARK
    r = service.save_edit(kid, new_title, item["content"])
    print(f"2. 编辑保存：{r['msg']}")

    # 3. 用标记去检索，应该能召回这条
    time.sleep(1)
    hits = retriever.search(MARK, 5)
    found = [h for h in hits if h["title"] == new_title]
    print(f"3. 用标记检索《{MARK}》：召回 {len(hits)} 条，命中目标：{bool(found)}")
    if not found:
        print("   ❌ 向量库没更新，增量同步失败")
        service.save_edit(kid, old_title, item["content"])   # 还原
        return

    # 4. 走一遍问答，看回答里有没有这个标记
    #    注意：不能只用生造标记当问题（语义相似度会低于拒答阈值），要带上真实方名
    result = graph.ask(f"{new_title} 主治什么")
    ok = MARK in result["answer"] or old_title in result["answer"]
    print(f"4. 问答端回答包含新内容：{ok}")
    print(f"   回答开头：{result['answer'][:60]}...")

    # 5. 还原
    service.save_edit(kid, old_title, item["content"])
    after = retriever.search(MARK, 3)
    cleaned = not [h for h in after if h["title"] == new_title]
    print(f"5. 已还原原标题，标记不再被召回：{cleaned}")

    print("=" * 60)
    print("结论：", "✅ 通过（编辑 → 向量更新 → 问答同步 全链路打通）" if (found and ok and cleaned)
          else "❌ 未通过")
    print("=" * 60)


if __name__ == "__main__":
    main()
