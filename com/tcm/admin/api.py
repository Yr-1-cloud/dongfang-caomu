"""后台管理接口。路由用 def（同步）：连接池与向量检索都是同步的。"""

from __future__ import annotations

import torch  # noqa: F401  必须最先导入，避免 Windows 段错误

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel
from com.tcm.db.conn import query_all, query_one
from com.tcm.admin import service
from com.tcm.system.api import need_admin

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(need_admin)])


def ok(data=None, msg: str = "ok"):
    return {"code": 0, "msg": msg, "data": data}


class ReviewIn(BaseModel):
    id: int
    action: str          # pass / reject


class EditIn(BaseModel):
    id: int
    title: str
    content: str


class AddIn(BaseModel):
    title: str
    content: str
    category: str = ""


class KidIn(BaseModel):
    id: int


@router.get("/stats")
def stats():
    """顶部 4 张统计卡片。"""
    return ok(service.stats())


@router.get("/list")
def list_items(page: int = 1, size: int = 20, source: str = "", review_status: str = "",
               vector_status: str = "", keyword: str = ""):
    """列表 + 筛选（分页）。"""
    return ok(service.list_items(page, size, source, review_status, vector_status, keyword))


@router.get("/detail")
def detail(id: int):
    """单条详情（编辑时用）。"""
    item = query_one(
        "SELECT id, source, src_fid, title, content, category, review_status, vector_status, "
        "confidence, classify_reason FROM knowledge WHERE id=%s", (id,))
    return ok(item) if item else {"code": 1, "msg": "记录不存在"}


@router.post("/review")
def review(body: ReviewIn):
    """行内复核：通过 / 拒绝。"""
    r = service.review(body.id, body.action)
    return ok(r, r["msg"]) if r["ok"] else {"code": 1, "msg": r["msg"]}


@router.post("/edit")
def edit(body: EditIn):
    """编辑保存 → 置未入库 → 重算该条（增量同步）。"""
    r = service.save_edit(body.id, body.title, body.content)
    return ok(r, r["msg"]) if r["ok"] else {"code": 1, "msg": r["msg"]}


@router.post("/add")
def add(body: AddIn):
    """手工录入：进待复核队列。"""
    r = service.add_manual(body.title, body.content, body.category)
    return ok(r, r["msg"])


@router.post("/delete")
def delete(body: KidIn):
    """软删 + 撤下向量。"""
    r = service.delete_item(body.id)
    return ok(r, r["msg"]) if r["ok"] else {"code": 1, "msg": r["msg"]}


@router.post("/revector")
def revector(body: KidIn):
    """单条重新向量化。"""
    r = service.revector(body.id)
    return ok(r, r["msg"]) if r["ok"] else {"code": 1, "msg": r["msg"]}


@router.post("/upload")
def upload(file: UploadFile = File(...)):
    """上传：MD5 秒传 + 进待复核队列。"""
    r = service.save_upload(file.filename, file.file.read())
    return ok(r, r["msg"])


@router.get("/tasks")
def tasks(limit: int = 20):
    """任务表（增量向量化 / 分类）最近记录。"""
    return ok(query_all("SELECT * FROM kb_task ORDER BY id DESC LIMIT %s", (limit,)))
