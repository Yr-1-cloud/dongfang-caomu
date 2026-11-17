# -*- coding: utf-8 -*-
"""一键演示：上传 → 复核 → 向量化 → 问答带引用（阶段 6.4）。

两种用法：
1. 自动跑完整链路（录屏前先确认能跑通）：
      uv run python docs/check/一键演示.py
2. 只打印演示步骤（照着在页面上操作录屏）：
      uv run python docs/check/一键演示.py --steps
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))   # 让 com.tcm 可导入

import torch  # noqa: E402  ⚠️ 必须最先导入，见 graph.py 的说明

from com.tcm.db.conn import query_one
from com.tcm.qa import graph
from com.tcm.admin import service

DEMO_FILE = HERE / "样本方剂.pdf"


def auto() -> None:
    print("=" * 62)
    print("一键演示：上传 → 复核 → 向量化 → 问答带引用")
    print("=" * 62)

    # 1. 上传（MD5 秒传）
    print("\n[1/5] 上传文档（PDF）")
    r = service.save_upload(DEMO_FILE.name, DEMO_FILE.read_bytes())
    print("      ", r["msg"], "| kid =", r["kid"])
    kid = r["kid"]

    print("\n[2/5] 再传同一个文件（验证 MD5 秒传）")
    r2 = service.save_upload(DEMO_FILE.name, DEMO_FILE.read_bytes())
    print("      ", r2["msg"])

    # 3. 看状态：新上传的知识处于"待复核"，未进向量库
    print("\n[3/5] 查看状态机")
    st = query_one("SELECT review_status, vector_status FROM knowledge WHERE id = %s", (kid,))
    print("       复核状态:", {0: "待复核", 1: "已复核", 2: "已拒绝"}[st["review_status"]],
          "| 向量状态:", {0: "未入库", 1: "已入库"}[st["vector_status"]])
    print("       → 门禁生效：未复核的知识不会进向量库")

    # 4. 人工复核通过 → 自动向量化
    print("\n[4/5] 人工复核：通过")
    print("      ", service.review(kid, "pass")["msg"])
    st = query_one("SELECT review_status, vector_status FROM knowledge WHERE id = %s", (kid,))
    print("       复核状态:", {0: "待复核", 1: "已复核", 2: "已拒绝"}[st["review_status"]],
          "| 向量状态:", {0: "未入库", 1: "已入库"}[st["vector_status"]])

    # 5. 问答：应该能查到刚入库的"丹参饮"
    print("\n[5/5] 问答端提问（应能命中刚入库的内容）")
    result = graph.ask("丹参饮的处方组成是什么？")
    print("       问题：丹参饮的处方组成是什么？")
    print("       回答：", result["answer"][:200])
    print("       引用：")
    for i, c in enumerate(result["chunks"], 1):
        print(f"         [{i}] {c['source']} fid={c['fid']} {c['title']}（相似度 {c['score']}）")

    print("\n" + "=" * 62)
    print("演示完成 ✅")
    print("=" * 62)


def steps() -> None:
    print("""页面演示步骤（录屏用）：

1. 打开管理页 http://127.0.0.1:8000/rag/
   - 看顶部四张统计卡片（总量 / 已入库 / 待复核 / 未分类）
2. 上传 docs/check/样本方剂.pdf
   - 提示"上传成功，已进入待复核队列"
   - 再传一次同一文件 → 提示"文件已存在，秒传成功，未重复解析"
3. 在列表里筛"待复核"，找到刚上传的条目
   - 状态徽章：待复核 + 未入库
4. 点"通过"
   - 状态变为：已复核 + 已入库（触发向量化）
5. 打开问答页 http://127.0.0.1:8000/qa/
   - 问"丹参饮主治什么？" → 回答逐字显示，带引用与相似度
   - 再问"今天北京天气怎么样" → 验证拒答不编造
6. 回到管理页点"编辑"改一下正文，保存
   - 再回问答页问同样的问题 → 答案已更新（增量同步）
""")


if __name__ == "__main__":
    steps() if "--steps" in sys.argv else auto()
