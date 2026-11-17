"""智能体问答：LangGraph 两节点图 retrieve → generate（阶段 4.2 / 4.3 / 4.5）。

State 契约（开工前冻结的三个契约之一）：
    question: str          用户问题
    chunks : list[dict]    检索片段 [{source, fid, title, seg, text, score}]
    answer : str           带引用的回答

对外提供三个入口：
    ask(question)                —— 一次性返回（命令行/测试用）
    iter_answer(question)        —— 流式生成（('sources'|'token'|'done', payload)）
    build_graph()                —— LangGraph 图对象

用法：
    uv run python -m com.tcm.qa.graph "治痞块用什么方"
"""

from __future__ import annotations

import sys
import time

# ⚠️ 这两行导入顺序不能改，是踩过坑的：
# 1) sentence_transformers 是"懒加载"，真正 import torch 发生在第一次用模型时；
# 2) 若让 torch 在 langchain/langgraph 之后加载，Windows 上会 DLL 冲突
#    → 进程直接段错误崩溃，而且一个字都不打印（极难排查）。
# 所以这里显式提前加载 torch，保证它排在所有 langchain/langgraph 之前。
import torch  # noqa: F401

from com.tcm.cfg.settings import settings
from com.tcm.db.conn import execute
from com.tcm.rag import retriever

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_deepseek import ChatDeepSeek
from langgraph.graph import END, START, StateGraph
from typing import TypedDict

TOP_K = 5
MIN_SCORE = 0.5   # 最高相似度低于它就拒答，防硬编
REFUSE = "知识库中没有找到相关内容，无法回答。建议咨询专业医师。"

SYS_PROMPT = (
    "你是「东方草木」中医药知识助手。规则：\n"
    "1. 只依据下面的资料片段回答，禁止使用资料之外的知识；\n"
    "2. 回答中引用到的信息在句尾标注片段编号，如 [1]；\n"
    "3. 资料不足以回答时，明确说\"知识库中没有找到相关内容\"，不要编造；\n"
    "4. 涉及用药的内容提醒用户咨询医师。"
)


class QAState(TypedDict):
    question: str
    chunks: list
    answer: str


def build_llm() -> ChatDeepSeek:
    return ChatDeepSeek(
        api_key=settings.DEEPSEEK_API_KEY,
        api_base=settings.DEEPSEEK_BASE_URL,
        model=settings.DEEPSEEK_MODEL_CHAT,
        temperature=0.3,
    )


def build_prompt(chunks: list[dict], question: str) -> str:
    """把片段编成带编号的资料块，让模型能按 [n] 引用。"""
    lines = [
        f"[{i}]（{c['source']} fid={c['fid']} {c['title']}·{c['seg']}）{c['text']}"
        for i, c in enumerate(chunks, 1)
    ]
    return f"资料片段：\n" + "\n".join(lines) + f"\n\n问题：{question}"


def node_retrieve(state: QAState) -> dict:
    """节点一：向量召回。"""
    return {"chunks": retriever.search(state["question"], TOP_K)}


def node_generate(state: QAState) -> dict:
    """节点二：拼提示词 → DeepSeek 生成带引用回答；资料不足就拒答。"""
    chunks = state["chunks"]
    if not chunks or max(c["score"] for c in chunks) < MIN_SCORE:
        return {"answer": REFUSE}

    resp = build_llm().invoke([
        SystemMessage(SYS_PROMPT),
        HumanMessage(build_prompt(chunks, state["question"])),
    ])
    return {"answer": resp.content}


def build_graph():
    g = StateGraph(QAState)
    g.add_node("retrieve", node_retrieve)
    g.add_node("generate", node_generate)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "generate")
    g.add_edge("generate", END)
    return g.compile()


def save_log(question: str, chunks: list[dict], answer: str, elapsed_ms: int) -> None:
    """4.5 问答日志落库：问题 / 命中数 / 来源 / 耗时。"""
    sources = ",".join(sorted({c["source"] for c in chunks}))
    top_score = max(c["score"] for c in chunks) if chunks else 0
    execute(
        "INSERT INTO qa_log (question, hit_count, sources, top_score, elapsed_ms, answer) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (question, len(chunks), sources, top_score, elapsed_ms, answer),
    )


def ask(question: str) -> dict:
    """非流式：跑一遍图，返回 {question, chunks, answer}。"""
    t0 = time.time()
    result = build_graph().invoke({"question": question, "chunks": [], "answer": ""})
    save_log(question, result["chunks"], result["answer"], int((time.time() - t0) * 1000))
    return result


def iter_answer(question: str):
    """4.3 流式：先吐引用片段，再逐 token 吐回答。

    产出 ('sources', chunks) → 若干 ('token', 文本) → ('done', None)
    用同步 generator，配合 FastAPI 的 def 路由 + StreamingResponse。
    """
    t0 = time.time()
    chunks = retriever.search(question, TOP_K)
    yield ("sources", chunks)

    if not chunks or max(c["score"] for c in chunks) < MIN_SCORE:
        yield ("token", REFUSE)
        yield ("done", None)
        save_log(question, chunks, REFUSE, int((time.time() - t0) * 1000))
        return

    buf = []
    for piece in build_llm().stream([
        SystemMessage(SYS_PROMPT),
        HumanMessage(build_prompt(chunks, question)),
    ]):
        if piece.content:
            buf.append(piece.content)
            yield ("token", piece.content)

    answer = "".join(buf)
    save_log(question, chunks, answer, int((time.time() - t0) * 1000))
    yield ("done", None)


if __name__ == "__main__":
    question = sys.argv[1] if len(sys.argv) > 1 else "治痞块用什么方"
    result = ask(question)

    print(f"问题：{question}")
    print("=" * 60)
    print(result["answer"])
    print("=" * 60)
    print("引用片段：")
    for i, c in enumerate(result["chunks"], 1):
        print(f"  [{i}] {c['source']} fid={c['fid']} {c['title']}（相似度 {c['score']}）")
