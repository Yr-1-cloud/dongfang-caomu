"""中文分词（jieba + 中医药术语词典）。

老师指定词典：docs/tcm_terms.txt，格式为 jieba 自定义词典标准格式：
    词语 词频 词性    例：一上散 100 nt

作用：让"阿魏麝香散""功能主治"这类中医术语不再被切碎，
     供 BM25 关键词检索与混合检索使用。
     向量检索不需要它（bge 模型自带 tokenizer）。
"""

from __future__ import annotations

from pathlib import Path

import jieba

BASE_DIR = Path(__file__).resolve().parents[3]      # com/tcm/rag/tokenizer.py -> 项目根
DICT_PATH = BASE_DIR / "docs" / "tcm_terms.txt"

# 检索时无意义的单字与标点（中医药场景下"散""丸"等单字保留，它们是剂型词）
STOPWORDS = {
    " ", "\t", "\n", "，", "。", "、", "；", "：", "？", "！",
    "（", "）", "《", "》", "“", "”", "的", "了", "和", "与", "或",
}

_loaded = False


def ensure_dict() -> None:
    """加载术语词典（只加载一次）。"""
    global _loaded
    if _loaded:
        return
    if DICT_PATH.exists():
        jieba.load_userdict(str(DICT_PATH))
    _loaded = True


def cut(text: str) -> list[str]:
    """分词：加载词典 → 精确模式切分 → 去停用词与空白。"""
    ensure_dict()
    return [w for w in jieba.lcut(text or "") if w.strip() and w not in STOPWORDS]


if __name__ == "__main__":
    import sys

    samples = sys.argv[1:] or ["阿魏麝香散功能主治痞块", "丹参饮的处方组成是什么", "清暑化湿用什么方"]
    print(f"词典：{DICT_PATH}（{'已找到' if DICT_PATH.exists() else '未找到'}）")
    for s in samples:
        print(f"  {s}  →  {' / '.join(cut(s))}")
