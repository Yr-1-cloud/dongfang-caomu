"""登录鉴权：token 放内存（重启即失效，够课程演示用），密码 sha256 加盐。"""

from __future__ import annotations

import hashlib
import secrets

from com.tcm.db.conn import execute, query_one

_tokens: dict[str, dict] = {}   # token -> {"username":..., "role_id":...}
SALT = "tcm$"


def hash_pwd(pwd: str) -> str:
    return hashlib.sha256((SALT + pwd).encode()).hexdigest()


def login(username: str, password: str, ip: str = "") -> str | None:
    """登录成功返回 token；失败统一提示，不泄露账号是否存在。"""
    u = query_one("SELECT * FROM sys_user WHERE username=%s AND isDel=0", (username,))
    ok = bool(u) and u["password"] == hash_pwd(password) and u["status"] == 1
    execute("INSERT INTO login_log (username, ip, ok, msg) VALUES (%s,%s,%s,%s)",
            (username, ip, 1 if ok else 0, "登录成功" if ok else "用户名或密码错误，或账号已停用"))
    if not ok:
        return None
    token = secrets.token_hex(16)
    _tokens[token] = {"username": username, "role_id": u["role_id"]}
    return token


def register_user(username: str, password: str, nickname: str = "", phone: str = "",
                  ip: str = "") -> str | None:
    """自助注册：角色固定为普通用户(3)，不接受外部传入 role_id。

    成功返回 token（顺带完成登录），用户名已存在返回 None。
    """
    if query_one("SELECT id FROM sys_user WHERE username=%s", (username,)):
        return None
    execute(
        "INSERT INTO sys_user (username, nickname, phone, dept_id, role_id, password) "
        "VALUES (%s,%s,%s,%s,3,%s)",
        (username, nickname or username, phone, 0, hash_pwd(password)))
    return login(username, password, ip)


def user_of(token: str) -> str | None:
    d = _tokens.get(token or "")
    return d["username"] if d else None


def role_of(token: str) -> int | None:
    d = _tokens.get(token or "")
    return d["role_id"] if d else None


def logout(token: str) -> None:
    _tokens.pop(token or "", None)
