"""MySQL 连接池（DBUtils.PooledDB）+ 三个薄封装。

约定（全项目遵守）：
1. SQL 里的"值"一律用 %s 占位，通过参数传入，不做字符串拼接 —— 防注入。
2. 表名/列名无法参数化（占位符只能替值），必须走白名单校验后再拼 —— 见 safe_table / safe_column。
3. 连接用 get_conn() 上下文管理器借还：异常自动回滚，finally 一定归还。
4. conn.close() 是"归还给池"，不是真关闭；忘了还 = 连接泄漏。
"""

from __future__ import annotations
from contextlib import contextmanager
from typing import Iterator
import pymysql
from dbutils.pooled_db import PooledDB
from com.tcm.cfg.settings import settings

# ---------------------------------------------------------------- 白名单
# 允许出现在 SQL 里的表名 / 列名。新增表时在这里登记，别在业务代码里直接拼。
ALLOWED_TABLES = {
    "knowledge",   # 统一知识表
    "qa_log",      # 问答日志
}
ALLOWED_COLUMNS = {
    "id", "source", "src_fid", "title", "content", "category",
    "summary", "keywords", "state", "isDel",
    "review_status", "vector_status", "confidence", "classify_reason",
}


def safe_table(name: str) -> str:
    """校验表名，通过才允许拼进 SQL。"""
    if name not in ALLOWED_TABLES:
        raise ValueError(f"非法表名（未在白名单登记）: {name}")
    return name


def safe_column(name: str) -> str:
    """校验列名，通过才允许拼进 SQL。"""
    if name not in ALLOWED_COLUMNS:
        raise ValueError(f"非法列名（未在白名单登记）: {name}")
    return name


# ---------------------------------------------------------------- 连接池
# 惰性建池：import 本模块时不去连数据库，第一次真正用才连。
# 这样没配 .env / 数据库没起时，import 不会直接炸，方便命令行脚本导入。
_POOL: PooledDB | None = None


def get_pool() -> PooledDB:
    global _POOL
    if _POOL is None:
        _POOL = PooledDB(
            creator=pymysql,
            maxconnections=settings.DB_POOL_MAX,   # 池上限
            mincached=settings.DB_POOL_MIN,        # 启动时先备几条
            blocking=True,                         # 池满时等待，而不是抛错
            ping=1,                                # 每次借出先 ping，防 "server has gone away"
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            database=settings.DB_NAME,
            charset=settings.DB_CHARSET,
            cursorclass=pymysql.cursors.DictCursor,  # 结果是 dict，不用记下标
            autocommit=False,                        # 写入需显式 commit
        )
    return _POOL


@contextmanager
def get_conn(commit: bool = False) -> Iterator[pymysql.connections.Connection]:
    """借一条连接。

    :param commit: True 时正常退出自动提交；任何异常都会 rollback。
    """
    conn = get_pool().connection()
    try:
        yield conn
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()  # 归还给池，不是真关闭


# ---------------------------------------------------------------- 薄封装
def query_all(sql: str, args: tuple = ()) -> list[dict]:
    """查多条，返回 dict 列表；没有结果返回空列表。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchall()


def query_one(sql: str, args: tuple = ()) -> dict | None:
    """查一条，没有结果返回 None。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchone()


def execute(sql: str, args: tuple = ()) -> int:
    """写入（INSERT/UPDATE/DELETE），自动提交，返回影响行数。"""
    with get_conn(commit=True) as conn:
        with conn.cursor() as cur:
            return cur.execute(sql, args)


def executemany(sql: str, seq: list[tuple]) -> int:
    """批量写入，自动提交。3.7 万条入库用这个，比一条一条 execute 快很多。"""
    with get_conn(commit=True) as conn:
        with conn.cursor() as cur:
            return cur.executemany(sql, seq)


def ping() -> dict | None:
    """连通性自检：SELECT 1。"""
    return query_one("SELECT 1 AS ok")


if __name__ == "__main__":
    # 验收：uv run python -m com.tcm.db.conn
    print("SELECT 1 =>", ping())
