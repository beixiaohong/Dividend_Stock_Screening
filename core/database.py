# database.py

import os
from urllib.parse import urlsplit, urlunsplit
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import QueuePool

# ==========================
# 加载环境变量
# ==========================
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
SSL_CA = os.getenv("SSL_CA", "./isrgrootx1.pem")
# 是否启用 SSL 连接（本地 MySQL 默认关闭；云库/TiDB 需设 DB_SSL=1 并提供 SSL_CA）
DB_SSL = os.getenv("DB_SSL", "0").lower() in ("1", "true", "yes")

if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL 未设置，请检查 .env 文件")


def _mysql_parts(url: str):
    """解析 MySQL URL -> (server_url, dbname)。server_url 不含库名，用于服务器级连接。"""
    s = urlsplit(url)
    dbname = s.path.lstrip("/")
    server_url = urlunsplit((s.scheme, s.netloc, "", "", ""))
    return server_url, dbname


def _connect_args():
    args = {"charset": "utf8mb4"}
    if DB_SSL:
        args["ssl"] = {"ca": SSL_CA}
    return args


def ensure_database_exists(url: str = DATABASE_URL):
    """数据库不存在则自动创建（幂等，库已存在时无副作用）。

    - MySQL: 以「服务器级」连接（不指定库名，避免 1049），
      执行 CREATE DATABASE IF NOT EXISTS ... CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci。
    - SQLite: 确保数据库文件所在目录存在。
    """
    if url.startswith("mysql"):
        server_url, dbname = _mysql_parts(url)
        if not dbname:
            raise ValueError(
                "❌ DATABASE_URL 缺少数据库名，例如 mysql+pymysql://user:pass@host:3306/mydb"
            )
        tmp_engine = create_engine(server_url, connect_args=_connect_args(), pool_pre_ping=True)
        try:
            with tmp_engine.connect() as conn:
                safe = dbname.replace("`", "``")
                conn.execute(
                    text(
                        f"CREATE DATABASE IF NOT EXISTS `{safe}` "
                        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                    )
                )
                conn.commit()
        finally:
            tmp_engine.dispose()
    elif url.startswith("sqlite"):
        dbpath = url.replace("sqlite:///", "", 1)
        if dbpath and dbpath != ":memory:":
            d = os.path.dirname(dbpath)
            if d:
                os.makedirs(d, exist_ok=True)


# ==========================
# 启动即确保数据库存在（幂等）
# ==========================
ensure_database_exists(DATABASE_URL)

# ==========================
# 创建 Engine
# ==========================
if DATABASE_URL.startswith("mysql"):

    engine = create_engine(
        DATABASE_URL,
        poolclass=QueuePool,
        pool_size=10,           # 基础连接池大小
        max_overflow=20,        # 最大溢出连接
        pool_pre_ping=True,     # 自动检测失效连接
        pool_recycle=3600,      # 1小时回收（防止云端断连）
        echo=False,             # 生产环境建议 False
        connect_args=_connect_args(),
    )

else:
    # SQLite 备用（开发环境）
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=False
    )

# ==========================
# Session & Base
# ==========================
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()

# ==========================
# FastAPI 依赖
# ==========================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==========================
# 启动时测试连接
# ==========================
def test_connection():
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            print("✅ 数据库连接成功:", result.scalar())

            if DATABASE_URL.startswith("mysql"):
                # 检查是否启用 SSL
                ssl_check = conn.execute(text("SHOW STATUS LIKE 'Ssl_cipher'"))
                print("🔐 SSL 状态:", ssl_check.fetchall())

    except Exception as e:
        print("❌ 数据库连接失败:", e)
        raise

# 如果你希望启动时自动检测
if __name__ == "__main__":
    test_connection()
