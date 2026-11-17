# -*- coding: utf-8 -*-
"""生成 docs/check/ 测试三件套：样本 PDF + 手工录入 json。

执行：uv run python docs/check/生成测试样本.py
"""

from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

HERE = Path(__file__).resolve().parent

# 样本方剂内容（模拟一份"新录入的方剂资料"）
SAMPLE = [
    ("丹参饮", [
        "处方：丹参30克，檀香5克，砂仁5克。",
        "制法：水煎服。",
        "功能主治：活血祛瘀，行气止痛。主治心痛、胃脘诸痛。",
        "用法用量：每日一剂，分两次温服。",
        "摘录：《时方歌括》。",
    ]),
]

MANUAL_INPUT = [
    {
        "source": "doc",
        "title": "陈皮生姜饮",
        "content": "处方：陈皮10克，生姜3片。\n制法：水煎。\n功能主治：理气和胃，止呕。\n用法用量：代茶饮。\n摘录：民间验方。",
        "category": "偏方验方",
    },
    {
        "source": "doc",
        "title": "百合莲子羹",
        "content": "处方：百合30克，莲子30克，冰糖适量。\n制法：炖煮至烂。\n功能主治：养心安神，润肺止咳。\n用法用量：每日一次。\n摘录：食疗方。",
        "category": "养生保健",
    },
]


def make_pdf(path: Path) -> None:
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("STSong-Light", 18)
    c.drawString(80, 780, "中医药方剂资料（测试样本）")
    c.setFont("STSong-Light", 12)

    y = 730
    for title, lines in SAMPLE:
        c.setFont("STSong-Light", 14)
        c.drawString(80, y, title)
        y -= 28
        c.setFont("STSong-Light", 12)
        for line in lines:
            c.drawString(90, y, line)
            y -= 22
        y -= 20

    c.setFont("STSong-Light", 10)
    c.drawString(80, 120, "说明：本文件仅供上传流程测试使用（验证 MD5 秒传与解析入库）。")
    c.showPage()
    c.save()


def make_json(path: Path) -> None:
    path.write_text(json.dumps(MANUAL_INPUT, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    make_pdf(HERE / "样本方剂.pdf")
    make_json(HERE / "手工录入样本.json")
    print("已生成：样本方剂.pdf、手工录入样本.json")
