"""
client.py — Read-only access to the Idra MySQL database (idra_db).

PyMySQL is synchronous: every call is run in a worker thread with
asyncio.to_thread so it never blocks the FastAPI event loop.
A fresh connection is opened per call: ingestion runs rarely and reads
everything in one go, so a pool is not worth it.
"""
import asyncio
import logging
import os
from typing import Any, Dict, List

from dotenv import load_dotenv

from app.observability import otel

load_dotenv()

logger = logging.getLogger(__name__)

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "idra_db")
MYSQL_CONNECT_TIMEOUT = int(os.getenv("MYSQL_CONNECT_TIMEOUT", "10"))
MYSQL_READ_TIMEOUT = int(os.getenv("MYSQL_READ_TIMEOUT", "300"))


def _connect():
    import pymysql  # imported lazily: only needed when the mysql source is enabled

    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=MYSQL_CONNECT_TIMEOUT,
        read_timeout=MYSQL_READ_TIMEOUT,
        autocommit=True,
    )


def _fetch_many_sync(queries: Dict[str, str]) -> Dict[str, List[Dict[str, Any]]]:
    conn = _connect()
    try:
        out: Dict[str, List[Dict[str, Any]]] = {}
        with conn.cursor() as cur:
            for name, sql in queries.items():
                cur.execute(sql)
                out[name] = list(cur.fetchall())
                logger.debug(f"[mysql] {name}: {len(out[name])} rows")
        return out
    finally:
        conn.close()


@otel.traced_db("fetch_many", "mysql", namespace=MYSQL_DATABASE)
async def fetch_many(queries: Dict[str, str]) -> Dict[str, List[Dict[str, Any]]]:
    """Run several SELECTs on one connection. Returns {name: rows}."""
    return await asyncio.to_thread(_fetch_many_sync, queries)


@otel.traced_db_sync("ping", "mysql", namespace=MYSQL_DATABASE)
def ping_sync() -> bool:
    try:
        conn = _connect()
        try:
            conn.ping(reconnect=False)
            return True
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - health check must never raise
        logger.debug(f"[mysql] ping failed: {exc}")
        return False
