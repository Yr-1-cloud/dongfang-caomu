"""系统管理业务逻辑：用户 / 角色 / 部门 / 菜单 / 字典 / 参数 / 附件 / 日志。"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from com.tcm.db.conn import execute, query_all, query_one
from com.tcm.system.auth import hash_pwd


# ---------------------------------------------------------------- 公共
def _page(table: str, cols: str, where: list[str], args: list,
          order: str = "id DESC", page_no: int = 1, size: int = 20) -> dict:
    """通用分页：返回 {rows, total}。"""
    cond = " AND ".join(where) if where else "1=1"
    total = query_one(f"SELECT COUNT(*) n FROM {table} WHERE {cond}", tuple(args))["n"]
    rows = query_all(
        f"SELECT {cols} FROM {table} WHERE {cond} ORDER BY {order} LIMIT %s OFFSET %s",
        tuple(args) + (size, (page_no - 1) * size))
    return {"rows": rows, "total": total}


def _tree(rows: list[dict]) -> list[dict]:
    """平表 → 嵌套树（部门 / 菜单共用）。"""
    nodes = {r["id"]: {**r, "children": []} for r in rows}
    root: list = []
    for n in nodes.values():
        p = nodes.get(n["parent_id"])
        (p["children"] if p else root).append(n)
    return root


def _csv(headers: list[str], rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    w.writerows([list(r.values()) for r in rows])
    return buf.getvalue()


# ---------------------------------------------------------------- 用户
def user_list(keyword: str = "", page_no: int = 1, size: int = 20) -> dict:
    where, args = ["u.isDel=0"], []
    if keyword:
        where.append("(u.username LIKE %s OR u.nickname LIKE %s OR u.phone LIKE %s)")
        args += [f"%{keyword}%"] * 3
    return _page(
        "sys_user u LEFT JOIN sys_dept d ON u.dept_id=d.id LEFT JOIN sys_role r ON u.role_id=r.id",
        "u.id, u.username, u.nickname, u.phone, u.dept_id, u.role_id, u.status, u.created_at, "
        "IFNULL(d.name,'') dept_name, IFNULL(r.name,'') role_name",
        where, args, "u.id", page_no, size)


def user_save(d: dict) -> str:
    if d.get("id"):
        execute("UPDATE sys_user SET nickname=%s, phone=%s, dept_id=%s, role_id=%s, status=%s WHERE id=%s",
                (d.get("nickname", ""), d.get("phone", ""), d.get("dept_id", 0),
                 d.get("role_id", 0), d.get("status", 1), d["id"]))
        return "已保存"
    if query_one("SELECT id FROM sys_user WHERE username=%s", (d["username"],)):
        return "用户名已存在"
    execute("INSERT INTO sys_user (username, nickname, phone, dept_id, role_id, password) VALUES (%s,%s,%s,%s,%s,%s)",
            (d["username"], d.get("nickname", ""), d.get("phone", ""),
             d.get("dept_id", 0), d.get("role_id", 0), hash_pwd(d.get("password") or "123456")))
    return "已新增（默认密码 123456）"


def user_reset_pwd(uid: int, password: str) -> str:
    execute("UPDATE sys_user SET password=%s WHERE id=%s", (hash_pwd(password), uid))
    return "密码已重置"


def user_status(uid: int, status: int) -> str:
    execute("UPDATE sys_user SET status=%s WHERE id=%s", (status, uid))
    return "已" + ("启用" if status == 1 else "停用")


def user_delete(uid: int) -> str:
    execute("UPDATE sys_user SET isDel=1 WHERE id=%s", (uid,))
    return "已删除"


def user_export() -> str:
    rows = query_all(
        "SELECT u.id, u.username, u.nickname, u.phone, IFNULL(d.name,'') dept_name, "
        "IFNULL(r.name,'') role_name, IF(u.status=1,'启用','停用') status "
        "FROM sys_user u LEFT JOIN sys_dept d ON u.dept_id=d.id "
        "LEFT JOIN sys_role r ON u.role_id=r.id WHERE u.isDel=0 ORDER BY u.id")
    return _csv(["ID", "用户名", "昵称", "手机", "部门", "角色", "状态"], rows)


# ---------------------------------------------------------------- 角色
def role_list() -> list:
    return query_all("SELECT * FROM sys_role ORDER BY id")


def role_save(d: dict) -> str:
    if d.get("id"):
        execute("UPDATE sys_role SET name=%s, remark=%s, status=%s WHERE id=%s",
                (d["name"], d.get("remark", ""), d.get("status", 1), d["id"]))
    else:
        execute("INSERT INTO sys_role (name, remark) VALUES (%s,%s)", (d["name"], d.get("remark", "")))
    return "已保存"


def role_delete(rid: int) -> str:
    if query_one("SELECT id FROM sys_user WHERE role_id=%s AND isDel=0", (rid,)):
        return "该角色下还有用户，不能删除"
    execute("DELETE FROM sys_role WHERE id=%s", (rid,))
    execute("DELETE FROM sys_role_menu WHERE role_id=%s", (rid,))
    return "已删除"


def role_menu_ids(rid: int) -> list:
    return [r["menu_id"] for r in query_all("SELECT menu_id FROM sys_role_menu WHERE role_id=%s", (rid,))]


def role_save_menus(rid: int, menu_ids: list[int]) -> str:
    execute("DELETE FROM sys_role_menu WHERE role_id=%s", (rid,))
    for mid in menu_ids:
        execute("INSERT INTO sys_role_menu (role_id, menu_id) VALUES (%s,%s)", (rid, mid))
    return "权限已分配"


# ---------------------------------------------------------------- 部门
def dept_tree() -> list:
    return _tree(query_all("SELECT * FROM sys_dept WHERE isDel=0 ORDER BY sort, id"))


def dept_save(d: dict) -> str:
    if d.get("id"):
        execute("UPDATE sys_dept SET parent_id=%s, name=%s, sort=%s WHERE id=%s",
                (d.get("parent_id", 0), d["name"], d.get("sort", 0), d["id"]))
    else:
        execute("INSERT INTO sys_dept (parent_id, name, sort) VALUES (%s,%s,%s)",
                (d.get("parent_id", 0), d["name"], d.get("sort", 0)))
    return "已保存"


def dept_delete(did: int) -> str:
    if query_one("SELECT id FROM sys_dept WHERE parent_id=%s AND isDel=0", (did,)):
        return "存在子部门，不能删除"
    if query_one("SELECT id FROM sys_user WHERE dept_id=%s AND isDel=0", (did,)):
        return "部门下还有用户，不能删除"
    execute("UPDATE sys_dept SET isDel=1 WHERE id=%s", (did,))
    return "已删除"


# ---------------------------------------------------------------- 菜单
def menu_tree() -> list:
    return _tree(query_all("SELECT * FROM sys_menu ORDER BY sort, id"))


def menu_save(d: dict) -> str:
    if d.get("id"):
        execute("UPDATE sys_menu SET parent_id=%s, name=%s, type=%s, perm=%s, sort=%s, visible=%s WHERE id=%s",
                (d.get("parent_id", 0), d["name"], d.get("type", "菜单"),
                 d.get("perm", ""), d.get("sort", 0), d.get("visible", 1), d["id"]))
    else:
        execute("INSERT INTO sys_menu (parent_id, name, type, perm, sort, visible) VALUES (%s,%s,%s,%s,%s,%s)",
                (d.get("parent_id", 0), d["name"], d.get("type", "菜单"),
                 d.get("perm", ""), d.get("sort", 0), d.get("visible", 1)))
    return "已保存"


def menu_delete(mid: int) -> str:
    if query_one("SELECT id FROM sys_menu WHERE parent_id=%s", (mid,)):
        return "存在子菜单，不能删除"
    execute("DELETE FROM sys_menu WHERE id=%s", (mid,))
    execute("DELETE FROM sys_role_menu WHERE menu_id=%s", (mid,))
    return "已删除"


# ---------------------------------------------------------------- 字典
def dict_types() -> list:
    return query_all("SELECT * FROM sys_dict_type ORDER BY id")


def dict_type_save(d: dict) -> str:
    if d.get("id"):
        execute("UPDATE sys_dict_type SET name=%s, code=%s WHERE id=%s", (d["name"], d["code"], d["id"]))
    elif query_one("SELECT id FROM sys_dict_type WHERE code=%s", (d["code"],)):
        return "类型编码已存在"
    else:
        execute("INSERT INTO sys_dict_type (name, code) VALUES (%s,%s)", (d["name"], d["code"]))
    return "已保存"


def dict_type_delete(code: str) -> str:
    execute("DELETE FROM sys_dict_type WHERE code=%s", (code,))
    execute("DELETE FROM sys_dict_item WHERE type_code=%s", (code,))
    return "已删除（含字典项）"


def dict_items(code: str) -> list:
    return query_all("SELECT * FROM sys_dict_item WHERE type_code=%s ORDER BY sort, id", (code,))


def dict_item_save(d: dict) -> str:
    if d.get("id"):
        execute("UPDATE sys_dict_item SET type_code=%s, label=%s, value=%s, sort=%s WHERE id=%s",
                (d["type_code"], d["label"], d["value"], d.get("sort", 0), d["id"]))
    else:
        execute("INSERT INTO sys_dict_item (type_code, label, value, sort) VALUES (%s,%s,%s,%s)",
                (d["type_code"], d["label"], d["value"], d.get("sort", 0)))
    return "已保存"


def dict_item_delete(iid: int) -> str:
    execute("DELETE FROM sys_dict_item WHERE id=%s", (iid,))
    return "已删除"


# ---------------------------------------------------------------- 参数配置
def config_list() -> list:
    return query_all("SELECT * FROM sys_config ORDER BY id")


def config_save(d: dict) -> str:
    if d.get("id"):
        execute("UPDATE sys_config SET name=%s, cfg_key=%s, cfg_value=%s WHERE id=%s",
                (d["name"], d["cfg_key"], d["cfg_value"], d["id"]))
    elif query_one("SELECT id FROM sys_config WHERE cfg_key=%s", (d["cfg_key"],)):
        return "参数键已存在"
    else:
        execute("INSERT INTO sys_config (name, cfg_key, cfg_value) VALUES (%s,%s,%s)",
                (d["name"], d["cfg_key"], d.get("cfg_value", "")))
    return "已保存"


def config_delete(cid: int) -> str:
    row = query_one("SELECT builtin FROM sys_config WHERE id=%s", (cid,))
    if not row:
        return "记录不存在"
    if row["builtin"]:
        return "内置项不可删除"
    execute("DELETE FROM sys_config WHERE id=%s", (cid,))
    return "已删除"


# ---------------------------------------------------------------- 附件管理
def attach_list(page_no: int = 1, size: int = 20, keyword: str = "", module: str = "") -> dict:
    where, args = ["1=1"], []
    if keyword:
        where.append("a.file_name LIKE %s"); args.append(f"%{keyword}%")
    if module:
        where.append("a.source_module=%s"); args.append(module)
    cond = " AND ".join(where)
    total = query_one(f"SELECT COUNT(*) n FROM kb_attachment a WHERE {cond}", tuple(args))["n"]
    rows = query_all(
        f"SELECT a.id, a.file_name, a.file_size, a.file_md5, a.source_module, a.created_at, a.kid, "
        f"k.title, k.review_status, k.vector_status "
        f"FROM kb_attachment a LEFT JOIN knowledge k ON a.kid=k.id WHERE {cond} "
        f"ORDER BY a.id DESC LIMIT %s OFFSET %s",
        tuple(args) + (size, (page_no - 1) * size))
    return {"rows": rows, "total": total}


def attach_set_module(aid: int, module: str) -> str:
    execute("UPDATE kb_attachment SET source_module=%s WHERE id=%s", (module, aid))
    return "来源模块已更新"


def attach_delete(aid: int) -> str:
    row = query_one("SELECT file_path FROM kb_attachment WHERE id=%s", (aid,))
    if not row:
        return "记录不存在"
    execute("DELETE FROM kb_attachment WHERE id=%s", (aid,))
    try:
        Path(row["file_path"]).unlink(missing_ok=True)  # 落盘文件一并清理
    except OSError:
        pass
    return "已删除"


# ---------------------------------------------------------------- 日志
def loginlog_list(page_no: int = 1, size: int = 20) -> dict:
    return _page("login_log", "*", [], [], "id DESC", page_no, size)


def loginlog_clear() -> str:
    execute("TRUNCATE TABLE login_log")
    return "已清空"


def loginlog_export() -> str:
    rows = query_all("SELECT id, username, ip, IF(ok=1,'成功','失败') ok, msg, created_at "
                     "FROM login_log ORDER BY id")
    return _csv(["ID", "用户名", "IP", "结果", "说明", "时间"], rows)


def operlog_list(page_no: int = 1, size: int = 20, keyword: str = "") -> dict:
    where, args = [], []
    if keyword:
        where.append("(path LIKE %s OR username LIKE %s)")
        args += [f"%{keyword}%"] * 2
    return _page("oper_log", "id, username, method, path, status, created_at",
                 where, args, "id DESC", page_no, size)


def operlog_detail(oid: int):
    return query_one("SELECT * FROM oper_log WHERE id=%s", (oid,))
