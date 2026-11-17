"""FastAPI 启动入口（阶段 0.5 / 4.3）。

启动：uv run uvicorn com.tcm.main:app --reload
首页：http://127.0.0.1:8000/qa/
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from com.tcm.qa.api import router as qa_router
from com.tcm.admin.api import router as admin_router
from com.tcm.system import auth
from com.tcm.system.api import router as sys_router

BASE_DIR = Path(__file__).resolve().parents[2]   # com/tcm/main.py -> 项目根

app = FastAPI(title="东方草木", version="0.1.0")


@app.on_event("startup")
def warm_rag() -> None:
    """启动后台线程预热检索链路：加载向量模型（1.3GB）+ 构建 BM25 索引（46 万 chunk）。

    不预热的话，服务每次重启后的第一条提问要把这几分钟全吃进去。
    后台线程执行，不阻塞服务启动；预热期间来提问也无妨（bm25.build 有锁，只会建一次）。
    """
    import threading

    def _warm():
        try:
            from com.tcm.rag import bm25, retriever
            bm25.build()
            retriever.get_model()
            print("[warmup] RAG 检索预热完成：BM25 索引 + 向量模型就绪")
        except Exception as e:
            print("[warmup] 预热失败（不影响服务，首次提问会自动重建）:", e)

    threading.Thread(target=_warm, daemon=True).start()


@app.middleware("http")
async def oper_log_mw(request: Request, call_next):
    """操作日志：写操作（非 GET）统一落库；SSE 流式接口跳过，避免缓冲破坏流。"""
    if request.method in ("POST", "PUT", "DELETE") and request.url.path.startswith("/api") \
            and not request.url.path.startswith("/api/qa/ask"):
        body = (await request.body())[:500].decode("utf-8", "ignore")
        response = await call_next(request)
        try:
            from com.tcm.db.conn import execute
            execute(
                "INSERT INTO oper_log (username, method, path, params, result, status) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (auth.user_of(request.headers.get("x-token", "")) or "-",
                 request.method, request.url.path, body, str(response.status_code), response.status_code))
        except Exception:
            pass
        return response
    return await call_next(request)


@app.get("/api/health")
def health():
    """统一响应格式：code / msg / data"""
    return {"code": 0, "msg": "ok", "data": {"service": "tcm"}}


app.include_router(qa_router)
app.include_router(admin_router)
app.include_router(sys_router)

# 静态页面：/qa/ 问答页，/admin/ 后台管理页，/ 根目录兜底
app.mount("/qa", StaticFiles(directory=str(BASE_DIR / "static" / "qa"), html=True), name="qa")
app.mount("/admin", StaticFiles(directory=str(BASE_DIR / "static" / "admin"), html=True), name="admin")
app.mount("/", StaticFiles(directory=str(BASE_DIR / "static"), html=True), name="static")
