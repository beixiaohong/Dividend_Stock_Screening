"""股票数据获取 - 归一化数据模型与异常定义。

本模块完全基于 Python 标准库，不依赖 akshare / efinance 等易碎的第三方封装，
目的是让"股票/基金行情获取经常失败"的问题通过"多源 + 重试 + 降级 + 熔断"
得到根本性改善。

所有 Provider 抓取到的原始数据，都会归一化成下面两个 dataclass：
- StockQuote：单只股票的实时/盘口行情
- Kline：单根 K 线（日/周/月）
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional
from datetime import datetime


class Market(str, Enum):
    """交易市场前缀。腾讯 / 新浪接口需要带市场前缀（sh / sz）。"""

    SH = "sh"  # 上交所：60/68/90 开头
    SZ = "sz"  # 深交所：00/30/20 开头


def market_of(code: str) -> Market:
    """根据 6 位股票代码推断市场前缀。

    规则（覆盖 A 股常见前缀）：
    - 60 / 68 / 69 / 90 开头 -> 上交所 (sh)
    - 其余（00 / 30 / 20 / 15 / 12 等）-> 深交所 (sz)
    """
    code = (code or "").strip()
    if code[:2] in ("60", "68", "69", "90") or code.startswith("900") or code.startswith("589"):
        return Market.SH
    return Market.SZ


def normalize_code(code: str) -> str:
    """把任意形态的代码（可能带 sh/sz 前缀、大小写、空格）规整为 6 位纯数字代码。"""
    if code is None:
        return ""
    code = code.strip().lower()
    # 去掉 sh / sz 前缀
    for prefix in ("sh", "sz"):
        if code.startswith(prefix):
            code = code[len(prefix):]
    # 去掉可能的点号/空格
    code = code.replace(".", "").replace(" ", "")
    return code


@dataclass
class StockQuote:
    """归一化后的单只股票行情。

    字段命名与 backend.model.model_stock_screening.DailyMarketData 的列式尽量对齐，
    方便直接落库。成交量统一为"手"（1 手 = 100 股），成交额单位为"元"。
    """

    code: str                                   # 6 位代码，如 "600036"
    name: str = ""                              # 股票名称
    market: str = ""                            # "sh" / "sz"
    price: Optional[float] = None               # 最新价
    prev_close: Optional[float] = None          # 昨收
    open: Optional[float] = None                # 今开
    high: Optional[float] = None                # 最高
    low: Optional[float] = None                 # 最低
    change_amount: Optional[float] = None       # 涨跌额
    change_pct: Optional[float] = None          # 涨跌幅（%）
    volume: Optional[float] = None              # 成交量（手）
    amount: Optional[float] = None              # 成交额（元）
    amplitude: Optional[float] = None           # 振幅（%）
    turnover_rate: Optional[float] = None       # 换手率（%）
    pe: Optional[float] = None                  # 市盈率（动态 / TTM，None 表示亏损或无数据）
    pb: Optional[float] = None                  # 市净率
    total_market_cap: Optional[float] = None    # 总市值（元）
    circ_market_cap: Optional[float] = None     # 流通市值（元）
    timestamp: Optional[datetime] = None        # 行情时间戳
    source: str = ""                            # 数据来源（Provider 名称）

    def to_dict(self) -> dict:
        d = asdict(self)
        if isinstance(d.get("timestamp"), datetime):
            d["timestamp"] = d["timestamp"].isoformat()
        return d


@dataclass
class Kline:
    """单根 K 线。"""

    code: str
    date: str                                   # "YYYY-MM-DD"
    open: float
    close: float
    high: float
    low: float
    volume: float = 0.0                          # 成交量（手）
    source: str = ""


# =========================================================================
# 异常体系
# =========================================================================

class StockDataError(Exception):
    """所有股票数据获取错误的基类。"""


class ProviderError(StockDataError):
    """单个数据源不可用（网络、解析、HTTP 错误等）。"""

    def __init__(self, provider: str, message: str, *, cause: Exception | None = None):
        self.provider = provider
        self.message = message
        self.cause = cause
        super().__init__(f"[{provider}] {message}")


class AllProvidersFailed(StockDataError):
    """所有数据源都不可用。"""

    def __init__(self, message: str = "所有数据源均不可用"):
        self.message = message
        super().__init__(message)
