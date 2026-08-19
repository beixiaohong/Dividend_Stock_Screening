# 数据库
# SQLite（开发环境）
# DATABASE_URL=sqlite:///./stock_advanced_system.db
# MySQL（推荐）：库不存在会自动创建（utf8mb4），表在启动时自动建
DATABASE_URL=mysql+pymysql://root:yourpassword@127.0.0.1:3306/stodb?charset=utf8mb4
# 云库（TiDB 等）需要 SSL 时：DB_SSL=1 并配置 SSL_CA（默认 ./isrgrootx1.pem）
DB_SSL=0
# SSL_CA=./isrgrootx1.pem

# 安全
SECRET_KEY=yoursecretkey_change_me
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# 邮件服务器配置 (以QQ/网易为例)
SMTP_SERVER=smtp.qq.com
SMTP_PORT=465
SMTP_USER=your_email@qq.com
SMTP_PASSWORD=your_email_auth_code
SENDER_NAME=价值分析系统


CONCURRENT_LIMIT=2  # 降低并发数减少网络压力
FETCH_DELAY_MIN=10.0  # 增加最小延迟
FETCH_DELAY_MAX=40.0  # 增加最大延迟

# 网络相关配置
NETWORK_RETRY_COUNT=5
NETWORK_BASE_DELAY=3
NETWORK_TIMEOUT=30
ENABLE_KLINE_FALLBACK=true

# 请求头优化
USER_AGENT=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36


# K线获取策略
KLINE_PRIMARY_ENABLED=true
KLINE_AKSHARE_BACKUP=true
KLINE_LOCAL_FALLBACK=true
KLINE_MIN_DATA_REQUIRED=30  # 至少需要30条数据

# 降低对K线的依赖
ANALYSIS_REQUIRE_KLINE=false  # 分析时不强制需要K线数据


# 临时配置 - 降低对K线的依赖
REQUIRE_KLINE_DATA=false
KLINE_RETRY_COUNT=1
KLINE_TIMEOUT=20