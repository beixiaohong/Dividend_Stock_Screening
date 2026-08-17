"""多源股票数据获取模块。

为什么需要它：
原 stock_service.py 依赖 akshare / efinance 以及手写东方财富爬虫，
这些方案经常因为接口变动、Cookie/ut 过期、限流而整体失败。
本模块改为"直连多家稳定数据源 + 重试 + 降级 + 熔断"：

- 腾讯财经 gtimg（主，最稳定，无需 Cookie）
- 东方财富 push2（全市场快照 / K 线，偶发断连）
- 新浪财经（备用实时行情）

对外统一入口见 client.StockDataClient（在后续提交中实现）。
"""

from .models import (
    StockQuote,
    Kline,
    Market,
    market_of,
    normalize_code,
    StockDataError,
    ProviderError,
    AllProvidersFailed,
)
from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState
from .providers import (
    BaseProvider,
    TencentProvider,
    EastMoneyProvider,
    SinaProvider,
)
from .client import StockDataClient, get_client
from . import integration

__all__ = [
    "StockQuote",
    "Kline",
    "Market",
    "market_of",
    "normalize_code",
    "StockDataError",
    "ProviderError",
    "AllProvidersFailed",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitState",
    "BaseProvider",
    "TencentProvider",
    "EastMoneyProvider",
    "SinaProvider",
    "StockDataClient",
    "get_client",
    "integration",
]
