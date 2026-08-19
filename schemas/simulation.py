# schemas/simulation.py
"""
模拟盘系统 Pydantic 模型（Pydantic v2，与项目一致）
"""
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List
from datetime import date, datetime


# ============================================================
# 账户
# ============================================================
class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    cash_balance: float
    frozen_amount: float
    initial_capital: float
    total_asset: float
    total_pnl: float
    total_pnl_pct: float
    position_count: int
    created_at: datetime
    updated_at: datetime


class ResetAccountIn(BaseModel):
    initial_capital: Optional[float] = Field(None, gt=0, description="重置后的初始资金，不填则用系统默认")


# ============================================================
# 交易请求
# ============================================================
class StockTradeIn(BaseModel):
    """个股买卖请求"""
    stock_code: str = Field(..., description="6位股票代码")
    stock_name: Optional[str] = Field(None, description="名称(可选，自动补)")
    shares: int = Field(..., gt=0, description="交易股数(100的整数倍由前端校验)")
    price: Optional[float] = Field(None, gt=0, description="指定成交价；不填则取实时价")
    fee_rate: Optional[float] = Field(None, ge=0, description="手续费率(如0.0003)，不填用默认")


class FundTradeIn(BaseModel):
    """基金买卖请求（场内按份额/市价，场外按金额/净值）"""
    fund_code: str = Field(..., description="6位基金代码")
    fund_name: Optional[str] = Field(None, description="名称(可选)")
    market_type: str = Field(..., description="on=场内 off=场外")
    # 买入：场内传 shares，场外传 amount；卖出：传 shares(赎回份额)
    shares: Optional[float] = Field(None, gt=0, description="交易份额(场内买入/卖出, 或场外卖出)")
    amount: Optional[float] = Field(None, gt=0, description="申购金额(场外买入)")
    price: Optional[float] = Field(None, gt=0, description="指定成交价/净值；不填则取实时价或最新净值")
    fee_rate: Optional[float] = Field(None, ge=0, description="申购/赎回费率；不填用默认")


# ============================================================
# 持仓 / 流水 输出
# ============================================================
class StockPositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    stock_code: str
    stock_name: Optional[str]
    shares: int
    avg_cost: float
    current_price: float
    market_value: float
    floating_pnl: float
    floating_pnl_pct: float
    realized_pnl: float
    is_active: bool
    updated_at: datetime


class FundPositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    fund_code: str
    fund_name: Optional[str]
    market_type: str
    shares: float
    avg_cost: float
    current_price: float
    market_value: float
    floating_pnl: float
    floating_pnl_pct: float
    realized_pnl: float
    is_active: bool
    updated_at: datetime


class TradeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    asset_type: str
    side: str
    code: str
    name: Optional[str]
    market_type: str
    price: float
    shares: float
    amount: float
    fee: float
    cash_after: float
    created_at: datetime
    # 场外基金申赎的净值确认日（T日/T+1）；股票与场内基金为 null
    settle_date: Optional[date] = None


class PortfolioSummary(BaseModel):
    """账户 + 持仓汇总"""
    account: AccountOut
    stock_positions: List[StockPositionOut]
    fund_positions: List[FundPositionOut]
    realtime_available: bool = True


# ============================================================
# 主页行情
# ============================================================
class HotListItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    category: str
    code: str
    name: Optional[str]
    symbol: Optional[str]
    market_type: str
    sort_order: int


class HomeQuote(BaseModel):
    """主页单条行情"""
    category: str
    code: str
    name: str
    symbol: Optional[str] = None
    market_type: str = ""
    price: Optional[float] = None
    prev_close: Optional[float] = None
    change_amount: Optional[float] = None
    change_pct: Optional[float] = None
    is_active: bool = True


class HomeData(BaseModel):
    realtime_available: bool = True
    updated_at: Optional[str] = None
    indices: List[HomeQuote] = []
    stocks: List[HomeQuote] = []
    etfs: List[HomeQuote] = []
    funds: List[HomeQuote] = []


# ============================================================
# 后台：热门标的 / 参数
# ============================================================
class HotListIn(BaseModel):
    category: str = Field(..., description="stock/index/etf/fund")
    code: str = Field(..., description="6位代码")
    name: Optional[str] = None
    symbol: Optional[str] = Field(None, description="带前缀行情代码(股票/指数/ETF)；基金可不填")
    market_type: str = Field("off", description="基金: on/off；其余填空")
    sort_order: int = 0
    is_active: bool = True


class HotListUpdate(BaseModel):
    name: Optional[str] = None
    symbol: Optional[str] = None
    market_type: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class SettingIn(BaseModel):
    value: str = Field(..., description="参数值")
    description: Optional[str] = None
