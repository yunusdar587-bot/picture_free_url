import duckdb

from config import DB_PATH


def get_connection(read_only: bool = True):
    return duckdb.connect(str(DB_PATH), read_only=read_only)
