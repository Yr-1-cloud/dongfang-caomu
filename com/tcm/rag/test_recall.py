"""召回测试用例（阶段 4.1 验收）。

用 10 个自然语言问题检验：目标知识能不能进 Top5。
验收标准：**至少 8 题命中**。不达标时先回头改清洗/切片，别急着调检索参数。

用法：uv run python -m com.tcm.rag.test_recall
"""

from __future__ import annotations

# ⚠️ 同 graph.py：先加载 torch，避免 Windows 上 DLL 冲突段错误
import torch  # noqa: F401

from com.tcm.rag import retriever

# (问题, 期望在 Top5 里出现的关键词)
CASES = [
    ("治痞块的方子", "痞"),
    ("阿魏麝香散治什么", "阿魏麝香散"),
    ("肠覃诸积用什么方", "阿魏"),
    ("艾叶相关的方剂有哪些", "艾"),
    ("鹌鹑蛋有什么功效", "鹌鹑蛋"),
    ("解酒的小偏方", "解酒"),
    ("治疗打嗝的验方", "打嗝"),
    ("保护牙齿的偏方", "齿"),
    ("清暑化湿用什么方", "清暑"),
    ("阿尔泰瑞香是什么", "阿尔泰瑞香"),
]

TOP_K = 5
PASS_LINE = 8   # 命中多少题算通过


def main() -> None:
    hit = 0
    print(f"召回测试：{len(CASES)} 题，Top{TOP_K}，通过线 {PASS_LINE} 题")
    print("=" * 66)

    for i, (q, keyword) in enumerate(CASES, 1):
        hits = retriever.search(q, TOP_K)
        titles = [h["title"] for h in hits]
        ok = any(keyword in t for t in titles)
        hit += ok
        mark = "命中" if ok else "未中"
        top1 = f"{titles[0]}（{hits[0]['score']}）" if hits else "无结果"
        print(f"{i:>2}. [{mark}] {q}")
        print(f"      Top1: {top1}")

    print("=" * 66)
    print(f"命中 {hit}/{len(CASES)} —— {'通过 ✅' if hit >= PASS_LINE else '未达标 ❌（先查清洗/切片）'}")


if __name__ == "__main__":
    main()
