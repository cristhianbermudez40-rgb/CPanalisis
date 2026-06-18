from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional

import mysql.connector
from mysql.connector.pooling import MySQLConnectionPool

from app.config import MYSQL_CONFIG


class MySQLDatabase:
    def __init__(self) -> None:
        self._pool: Optional[MySQLConnectionPool] = None

    def _build_pool(self) -> MySQLConnectionPool:
        if self._pool is None:
            import os, time
            host     = os.getenv("MYSQL_HOST",     MYSQL_CONFIG.host)
            port     = int(os.getenv("MYSQL_PORT", str(MYSQL_CONFIG.port)))
            user     = os.getenv("MYSQL_USER",     MYSQL_CONFIG.user)
            password = os.getenv("MYSQL_PASSWORD", MYSQL_CONFIG.password)
            database = os.getenv("MYSQL_DATABASE", MYSQL_CONFIG.database)

            # Usar nombre de pool único por sesión para evitar
            # PoolError "pool already exists" cuando se reintentan credenciales
            pool_name = f"avista_pool_{int(time.time() * 1000) % 100000}"
            self._pool = MySQLConnectionPool(
                pool_name=pool_name,
                pool_size=8,
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                autocommit=False,
                auth_plugin="caching_sha2_password",
            )
        return self._pool

    @contextmanager
    def connection(self):
        pool = self._build_pool()
        conn = pool.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(self, query: str, params: Optional[Iterable[Any]] = None) -> None:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)

    def executemany(self, query: str, params: List[Iterable[Any]]) -> int:
        if not params:
            return 0
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(query, params)
                return int(cursor.rowcount)

    def fetch_all(self, query: str, params: Optional[Iterable[Any]] = None) -> List[Dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(query, params)
                return cursor.fetchall()

    def fetch_one(self, query: str, params: Optional[Iterable[Any]] = None) -> Optional[Dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(query, params)
                return cursor.fetchone()


DB = MySQLDatabase()
