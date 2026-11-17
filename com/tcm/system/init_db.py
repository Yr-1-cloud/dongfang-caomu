"""系统管理表初始化（幂等，可重复执行）。

建 sys_* 表 + 种子数据（默认账号 admin/admin123、角色、部门、菜单、字典、参数）。
执行：uv run python -m com.tcm.system.init_db
"""

from __future__ import annotations

from com.tcm.db.conn import execute, query_one
from com.tcm.system.auth import hash_pwd

DDL = [
    """CREATE TABLE IF NOT EXISTS sys_dept (
        id INT AUTO_INCREMENT PRIMARY KEY,
        parent_id INT NOT NULL DEFAULT 0,
        name VARCHAR(50) NOT NULL,
        sort INT NOT NULL DEFAULT 0,
        isDel TINYINT NOT NULL DEFAULT 0
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS sys_role (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(50) NOT NULL,
        remark VARCHAR(200) DEFAULT '',
        status TINYINT NOT NULL DEFAULT 1
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS sys_user (
        id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(50) NOT NULL UNIQUE,
        nickname VARCHAR(50) DEFAULT '',
        phone VARCHAR(20) DEFAULT '',
        dept_id INT NOT NULL DEFAULT 0,
        role_id INT NOT NULL DEFAULT 0,
        password CHAR(64) NOT NULL,
        status TINYINT NOT NULL DEFAULT 1,
        isDel TINYINT NOT NULL DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS sys_menu (
        id INT AUTO_INCREMENT PRIMARY KEY,
        parent_id INT NOT NULL DEFAULT 0,
        name VARCHAR(50) NOT NULL,
        type VARCHAR(10) NOT NULL DEFAULT '菜单',
        perm VARCHAR(100) DEFAULT '',
        sort INT NOT NULL DEFAULT 0,
        visible TINYINT NOT NULL DEFAULT 1
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS sys_role_menu (
        role_id INT NOT NULL,
        menu_id INT NOT NULL,
        UNIQUE KEY uk (role_id, menu_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS sys_dict_type (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(50) NOT NULL,
        code VARCHAR(50) NOT NULL UNIQUE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS sys_dict_item (
        id INT AUTO_INCREMENT PRIMARY KEY,
        type_code VARCHAR(50) NOT NULL,
        label VARCHAR(50) NOT NULL,
        value VARCHAR(100) NOT NULL,
        sort INT NOT NULL DEFAULT 0
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS sys_config (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(50) NOT NULL,
        cfg_key VARCHAR(100) NOT NULL UNIQUE,
        cfg_value VARCHAR(500) DEFAULT '',
        builtin TINYINT NOT NULL DEFAULT 0
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS login_log (
        id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(50) DEFAULT '',
        ip VARCHAR(50) DEFAULT '',
        ok TINYINT NOT NULL DEFAULT 0,
        msg VARCHAR(200) DEFAULT '',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS oper_log (
        id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(50) DEFAULT '',
        method VARCHAR(10) DEFAULT '',
        path VARCHAR(200) DEFAULT '',
        params TEXT,
        result VARCHAR(500) DEFAULT '',
        status INT DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]

# 一级目录（分组）：(perm, name)
DIRS = [
    ("dir:kb", "知识管理"), ("dir:sys", "系统管理"), ("dir:log", "日志监控"),
]

# 二级菜单：(name, perm, 所属目录 perm) —— 与前端模块一一对应
MENUS = [
    ("结构化数据", "kb:data", "dir:kb"), ("文档管理", "kb:doc", "dir:kb"),
    ("用户管理", "sys:user", "dir:sys"), ("角色管理", "sys:role", "dir:sys"),
    ("部门管理", "sys:dept", "dir:sys"), ("菜单管理", "sys:menu", "dir:sys"),
    ("字典管理", "sys:dict", "dir:sys"), ("附件管理", "sys:attach", "dir:sys"),
    ("参数配置", "sys:config", "dir:sys"),
    ("问答日志", "qa:log", "dir:log"), ("登录日志", "sys:loginlog", "dir:log"),
    ("操作日志", "sys:operlog", "dir:log"),
]

CONFIGS = [
    ("站点名称", "sys.site.name", "东方草木", 1),
    ("拒答阈值", "qa.refuse.score", "0.5", 1),
    ("检索条数", "qa.topk", "5", 1),
    ("每页条数", "sys.page.size", "20", 0),
]


def _seed_once(sql_check: str, args: tuple, sql_insert: str, insert_args: tuple) -> None:
    """存在即跳过，保证幂等。"""
    if not query_one(sql_check, args):
        execute(sql_insert, insert_args)


def run() -> None:
    for ddl in DDL:
        execute(ddl)

    # ---- kb_attachment 补 source_module（资料解析预留"来源模块"字段）----
    col = query_one(
        "SELECT COUNT(*) n FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='kb_attachment' AND COLUMN_NAME='source_module'")
    if not col["n"]:
        execute("ALTER TABLE kb_attachment ADD COLUMN source_module VARCHAR(30) DEFAULT '' AFTER kid")

    # ---- 种子：部门 / 角色 / 用户 / 菜单 / 字典 / 参数 ----
    for did, parent, name in [(1, 0, "总公司"), (2, 1, "知识运营部"), (3, 1, "技术部")]:
        _seed_once("SELECT id FROM sys_dept WHERE id=%s", (did,),
                   "INSERT INTO sys_dept (id, parent_id, name) VALUES (%s,%s,%s)", (did, parent, name))

    _seed_once("SELECT id FROM sys_role WHERE id=%s", (1,),
               "INSERT INTO sys_role (id, name, remark) VALUES (1,'超级管理员','全部权限')", ())
    _seed_once("SELECT id FROM sys_role WHERE id=%s", (2,),
               "INSERT INTO sys_role (id, name, remark) VALUES (2,'知识运营','知识库相关')", ())
    _seed_once("SELECT id FROM sys_role WHERE id=%s", (3,),
               "INSERT INTO sys_role (id, name, remark) VALUES (3,'普通用户','仅前台，无后台权限')", ())

    _seed_once("SELECT id FROM sys_user WHERE username=%s", ("admin",),
               "INSERT INTO sys_user (username, nickname, dept_id, role_id, password) "
               "VALUES ('admin','管理员',1,1,%s)", (hash_pwd("admin123"),))
    _seed_once("SELECT id FROM sys_user WHERE username=%s", ("user",),
               "INSERT INTO sys_user (username, nickname, dept_id, role_id, password) "
               "VALUES ('user','普通用户',1,3,%s)", (hash_pwd("user123"),))

    # 一级目录：admin 全给（id 自增，按 perm 幂等）
    for i, (perm, name) in enumerate(DIRS, 1):
        _seed_once("SELECT id FROM sys_menu WHERE perm=%s", (perm,),
                   "INSERT INTO sys_menu (name, type, perm, sort) VALUES (%s,'目录',%s,%s)",
                   (name, perm, i))
        did = query_one("SELECT id FROM sys_menu WHERE perm=%s", (perm,))["id"]
        _seed_once("SELECT menu_id FROM sys_role_menu WHERE role_id=1 AND menu_id=%s", (did,),
                   "INSERT INTO sys_role_menu (role_id, menu_id) VALUES (1,%s)", (did,))
    dir_id = {p: query_one("SELECT id FROM sys_menu WHERE perm=%s", (p,))["id"] for p, _ in DIRS}

    # 二级菜单：挂到目录下；老库里已存在的行自动补 parent_id（仅当还挂在根上，不覆盖手动调整）
    for i, (name, perm, parent) in enumerate(MENUS, 1):
        _seed_once("SELECT id FROM sys_menu WHERE perm=%s", (perm,),
                   "INSERT INTO sys_menu (name, type, perm, sort, parent_id) VALUES (%s,'菜单',%s,%s,%s)",
                   (name, perm, i, dir_id[parent]))
        mid = query_one("SELECT id FROM sys_menu WHERE perm=%s", (perm,))["id"]
        _seed_once("SELECT menu_id FROM sys_role_menu WHERE role_id=1 AND menu_id=%s", (mid,),
                   "INSERT INTO sys_role_menu (role_id, menu_id) VALUES (1,%s)", (mid,))
        execute("UPDATE sys_menu SET parent_id=%s WHERE perm=%s AND parent_id=0", (dir_id[parent], perm))

    # 知识运营角色：知识库菜单 + 对应两个目录
    for perm in ("dir:kb", "dir:log", "kb:data", "kb:doc", "qa:log"):
        mid = query_one("SELECT id FROM sys_menu WHERE perm=%s", (perm,))["id"]
        _seed_once("SELECT menu_id FROM sys_role_menu WHERE role_id=2 AND menu_id=%s", (mid,),
                   "INSERT INTO sys_role_menu (role_id, menu_id) VALUES (2,%s)", (mid,))

    for code, name, items in [
        ("source", "知识来源", [("方剂", "fangji"), ("中药材", "zhongyao"), ("偏方", "pianfang"), ("上传文档", "doc")]),
        ("category", "知识类目", [("方剂", "方剂"), ("中药材", "中药材"), ("偏方验方", "偏方验方"), ("养生保健", "养生保健"), ("其他", "其他")]),
    ]:
        _seed_once("SELECT id FROM sys_dict_type WHERE code=%s", (code,),
                   "INSERT INTO sys_dict_type (name, code) VALUES (%s,%s)", (name, code))
        for s, (label, value) in enumerate(items):
            _seed_once("SELECT id FROM sys_dict_item WHERE type_code=%s AND value=%s", (code, value),
                       "INSERT INTO sys_dict_item (type_code, label, value, sort) VALUES (%s,%s,%s,%s)",
                       (code, label, value, s))

    for name, key, value, builtin in CONFIGS:
        _seed_once("SELECT id FROM sys_config WHERE cfg_key=%s", (key,),
                   "INSERT INTO sys_config (name, cfg_key, cfg_value, builtin) VALUES (%s,%s,%s,%s)",
                   (name, key, value, builtin))

    print("系统表初始化完成：管理员 admin / admin123，普通用户 user / user123")


if __name__ == "__main__":
    run()
