"""系统管理接口：登录 + 用户/角色/部门/菜单/字典/参数/附件/日志。

路由全部 def（同步）：连接池是同步的。统一返回 {code, msg, data}。
"""

from __future__ import annotations

import torch  # noqa: F401  必须最先导入，避免 Windows 段错误

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from com.tcm.db.conn import query_all, query_one
from com.tcm.system import auth, service

router = APIRouter(prefix="/api/sys", tags=["sys"])


def ok(data=None, msg: str = "ok"):
    return {"code": 0, "msg": msg, "data": data}


def need_login(request: Request, x_token: str = Header("")):
    """除登录外全部接口的守卫：没 token / token 失效一律 401。

    预览/下载是 window.open 直接打开 URL，带不上 X-Token 请求头，允许 ?token= 兜底。
    """
    username = auth.user_of(x_token or request.query_params.get("token", ""))
    if not username:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    return username


def need_admin(request: Request, x_token: str = Header("")):
    """管理员守卫：超级管理员(1) 与 知识运营(2) 放行，普通用户(3) 拒绝。"""
    token = x_token or request.query_params.get("token", "")
    username = auth.user_of(token)
    if not username:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    if auth.role_of(token) not in (1, 2):
        raise HTTPException(status_code=403, detail="无权限：需要管理员角色")
    return username


def csv_response(text: str, filename: str) -> Response:
    """带 BOM 的 CSV，Excel 打开不乱码。"""
    return Response("\ufeff" + text, media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


class LoginIn(BaseModel):
    username: str
    password: str


class RegisterIn(BaseModel):
    username: str
    password: str
    nickname: str = ""
    phone: str = ""


class DictIn(BaseModel):
    id: int | None = None
    name: str = ""
    code: str = ""
    type_code: str = ""
    label: str = ""
    value: str = ""
    sort: int = 0


class IdIn(BaseModel):
    id: int


@router.post("/login")
def login(body: LoginIn, request: Request):
    ip = request.client.host if request.client else ""
    token = auth.login(body.username, body.password, ip)
    if not token:
        return {"code": 1, "msg": "用户名或密码错误"}
    return ok({"token": token, "role": auth.role_of(token)}, "登录成功")


@router.post("/register")
def register(body: RegisterIn, request: Request):
    """开放注册：只允许建普通用户(role 3)，成功即登录并跳前台。"""
    username = body.username.strip()
    password = body.password
    if not (3 <= len(username) <= 50):
        return {"code": 1, "msg": "用户名长度需为 3–50 个字符"}
    if len(password) < 6:
        return {"code": 1, "msg": "密码至少 6 位"}
    ip = request.client.host if request.client else ""
    token = auth.register_user(username, password, body.nickname.strip(), body.phone.strip(), ip)
    if not token:
        return {"code": 1, "msg": "用户名已存在"}
    return ok({"token": token, "role": 3}, "注册成功")


@router.post("/logout")
def logout(x_token: str = Header("")):
    auth.logout(x_token)
    return ok(msg="已退出")


@router.get("/me")
def me(username: str = Depends(need_login)):
    """当前用户 + 按角色过滤出的菜单（侧边栏数据源）。"""
    u = query_one("SELECT role_id FROM sys_user WHERE username=%s", (username,))
    menus = query_all(
        "SELECT m.id, m.name, m.perm, m.parent_id, m.type FROM sys_menu m "
        "JOIN sys_role_menu rm ON rm.menu_id=m.id "
        "JOIN sys_user u ON u.role_id=rm.role_id "
        "WHERE u.username=%s AND m.visible=1 ORDER BY m.sort", (username,))
    return ok({"username": username, "role": u["role_id"], "menus": menus})


# ---------------------------------------------------------------- 用户
@router.get("/user/list")
def user_list(keyword: str = "", page: int = 1, size: int = 20, _: str = Depends(need_admin)):
    return ok(service.user_list(keyword, page, size))


class UserIn(BaseModel):
    id: int | None = None
    username: str = ""
    nickname: str = ""
    phone: str = ""
    dept_id: int = 0
    role_id: int = 0
    status: int = 1
    password: str = ""


@router.post("/user/save")
def user_save(body: UserIn, _: str = Depends(need_admin)):
    return ok(msg=service.user_save(body.model_dump()))


class PwdIn(BaseModel):
    id: int
    password: str


@router.post("/user/resetPwd")
def user_reset_pwd(body: PwdIn, _: str = Depends(need_admin)):
    return ok(msg=service.user_reset_pwd(body.id, body.password))


class StatusIn(BaseModel):
    id: int
    status: int


@router.post("/user/status")
def user_status(body: StatusIn, _: str = Depends(need_admin)):
    return ok(msg=service.user_status(body.id, body.status))


@router.post("/user/delete")
def user_delete(body: IdIn, _: str = Depends(need_admin)):
    return ok(msg=service.user_delete(body.id))


@router.get("/user/export")
def user_export(_: str = Depends(need_admin)):
    return csv_response(service.user_export(), "users.csv")


# ---------------------------------------------------------------- 角色
@router.get("/role/list")
def role_list(_: str = Depends(need_admin)):
    return ok(service.role_list())


class RoleIn(BaseModel):
    id: int | None = None
    name: str
    remark: str = ""
    status: int = 1


@router.post("/role/save")
def role_save(body: RoleIn, _: str = Depends(need_admin)):
    return ok(msg=service.role_save(body.model_dump()))


@router.post("/role/delete")
def role_delete(body: IdIn, _: str = Depends(need_admin)):
    return ok(msg=service.role_delete(body.id))


@router.get("/role/menus")
def role_menus(role_id: int, _: str = Depends(need_admin)):
    return ok({"ids": service.role_menu_ids(role_id), "tree": service.menu_tree()})


class RoleMenusIn(BaseModel):
    role_id: int
    menu_ids: list[int]


@router.post("/role/saveMenus")
def role_save_menus(body: RoleMenusIn, _: str = Depends(need_admin)):
    return ok(msg=service.role_save_menus(body.role_id, body.menu_ids))


# ---------------------------------------------------------------- 部门 / 菜单
@router.get("/dept/tree")
def dept_tree(_: str = Depends(need_admin)):
    return ok(service.dept_tree())


class DeptIn(BaseModel):
    id: int | None = None
    parent_id: int = 0
    name: str
    sort: int = 0


@router.post("/dept/save")
def dept_save(body: DeptIn, _: str = Depends(need_admin)):
    return ok(msg=service.dept_save(body.model_dump()))


@router.post("/dept/delete")
def dept_delete(body: IdIn, _: str = Depends(need_admin)):
    return ok(msg=service.dept_delete(body.id))


@router.get("/menu/tree")
def menu_tree(_: str = Depends(need_admin)):
    return ok(service.menu_tree())


class MenuIn(BaseModel):
    id: int | None = None
    parent_id: int = 0
    name: str
    type: str = "菜单"
    perm: str = ""
    sort: int = 0
    visible: int = 1


@router.post("/menu/save")
def menu_save(body: MenuIn, _: str = Depends(need_admin)):
    return ok(msg=service.menu_save(body.model_dump()))


@router.post("/menu/delete")
def menu_delete(body: IdIn, _: str = Depends(need_admin)):
    return ok(msg=service.menu_delete(body.id))


# ---------------------------------------------------------------- 字典
@router.get("/dict/types")
def dict_types(_: str = Depends(need_admin)):
    return ok(service.dict_types())


@router.get("/dict/items")
def dict_items(code: str, _: str = Depends(need_admin)):
    return ok(service.dict_items(code))


@router.post("/dict/typeSave")
def dict_type_save(body: DictIn, _: str = Depends(need_admin)):
    return ok(msg=service.dict_type_save(body.model_dump()))


@router.post("/dict/typeDelete")
def dict_type_delete(body: dict, _: str = Depends(need_admin)):
    return ok(msg=service.dict_type_delete(body["code"]))


@router.post("/dict/itemSave")
def dict_item_save(body: DictIn, _: str = Depends(need_admin)):
    return ok(msg=service.dict_item_save(body.model_dump()))


@router.post("/dict/itemDelete")
def dict_item_delete(body: IdIn, _: str = Depends(need_admin)):
    return ok(msg=service.dict_item_delete(body.id))


# ---------------------------------------------------------------- 参数配置
@router.get("/config/list")
def config_list(_: str = Depends(need_admin)):
    return ok(service.config_list())


class ConfigIn(BaseModel):
    id: int | None = None
    name: str
    cfg_key: str
    cfg_value: str = ""


@router.post("/config/save")
def config_save(body: ConfigIn, _: str = Depends(need_admin)):
    return ok(msg=service.config_save(body.model_dump()))


@router.post("/config/delete")
def config_delete(body: IdIn, _: str = Depends(need_admin)):
    return ok(msg=service.config_delete(body.id))


# ---------------------------------------------------------------- 附件管理
@router.get("/attach/list")
def attach_list(page: int = 1, size: int = 20, keyword: str = "", module: str = "",
                _: str = Depends(need_admin)):
    return ok(service.attach_list(page, size, keyword, module))


class AttachModuleIn(BaseModel):
    id: int
    module: str


@router.post("/attach/setModule")
def attach_set_module(body: AttachModuleIn, _: str = Depends(need_admin)):
    return ok(msg=service.attach_set_module(body.id, body.module))


@router.post("/attach/delete")
def attach_delete(body: IdIn, _: str = Depends(need_admin)):
    return ok(msg=service.attach_delete(body.id))


@router.get("/attach/download")
def attach_download(id: int, _: str = Depends(need_admin)):
    """预览与下载共用：浏览器能直接打开的就预览，否则下载。"""
    from com.tcm.db.conn import query_one
    a = query_one("SELECT file_path, file_name FROM kb_attachment WHERE id=%s", (id,))
    if not a:
        raise HTTPException(404, "附件不存在")
    return FileResponse(a["file_path"], filename=a["file_name"])


# ---------------------------------------------------------------- 日志
@router.get("/loginlog/list")
def loginlog_list(page: int = 1, size: int = 20, _: str = Depends(need_admin)):
    return ok(service.loginlog_list(page, size))


@router.post("/loginlog/clear")
def loginlog_clear(_: str = Depends(need_admin)):
    return ok(msg=service.loginlog_clear())


@router.get("/loginlog/export")
def loginlog_export(_: str = Depends(need_admin)):
    return csv_response(service.loginlog_export(), "login_logs.csv")


@router.get("/operlog/list")
def operlog_list(page: int = 1, size: int = 20, keyword: str = "", _: str = Depends(need_admin)):
    return ok(service.operlog_list(page, size, keyword))


@router.get("/operlog/detail")
def operlog_detail(id: int, _: str = Depends(need_admin)):
    return ok(service.operlog_detail(id))
