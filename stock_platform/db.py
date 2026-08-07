from contextlib import contextmanager

import duckdb

from config import DB_PATH


class DatabaseUnavailable(RuntimeError):
    """库还没建好，或正被导入脚本独占写入。"""


def get_connection(read_only: bool = True):
    if read_only and not DB_PATH.exists():
        raise DatabaseUnavailable(
            f"数据库不存在: {DB_PATH}。请先运行 02_init_db.py 或 04_import_year.py 导入数据。"
        )
    try:
        return duckdb.connect(str(DB_PATH), read_only=read_only)
    except duckdb.IOException as exc:
        raise DatabaseUnavailable(
            f"无法打开数据库 {DB_PATH}：可能有导入脚本正在写入，请等它跑完再试。（{exc}）"
        ) from exc


@contextmanager
def connection(read_only: bool = True):
    """确保查询抛异常时连接也会被关闭。"""
    con = get_connection(read_only=read_only)
    try:
        yield con
    finally:
        con.close()
