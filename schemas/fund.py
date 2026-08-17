# schemas/fund.py
"""
基金领域 Pydantic 模型
适配自 founds/route_fund_screening.py 引用的 backend.schemas.fund_screening
使用 Pydantic v2（与本项目一致）
"""
from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import date, datetime


class FundWatchListAdd(BaseModel):
    """批量添加关注基金请求"""
    fund_codes: str = "600001, 600002"


class FundWatchListWithData(BaseModel):
    """关注列表（含最新净值）响应"""
    model_config = ConfigDict(from_attributes=True)

    fund_code: str
    fund_name: str
    added_at: Optional[datetime] = None
    net_worth: Optional[float] = None
    day_rate: Optional[float] = None
    update_time: Optional[int] = None


class FundHoldingCreate(BaseModel):
    """添加基金持仓请求"""
    fund_code: str
    fund_name: Optional[str] = None
    purchase_amount: float
    shares: float
    purchase_nav: float
    purchase_date: date
    commission: float = 0
    trade_note: Optional[str] = None


class FundHoldingUpdate(BaseModel):
    """更新基金持仓请求（全可选）"""
    fund_code: Optional[str] = None
    fund_name: Optional[str] = None
    purchase_amount: Optional[float] = None
    shares: Optional[float] = None
    purchase_nav: Optional[float] = None
    purchase_date: Optional[date] = None
    commission: Optional[float] = None
    current_nav: Optional[float] = None
    current_value: Optional[float] = None
    trade_note: Optional[str] = None
    is_active: Optional[bool] = None


class FundHoldingOut(BaseModel):
    """基金持仓输出"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    fund_code: str
    fund_name: Optional[str] = None
    purchase_amount: float
    shares: float
    purchase_nav: float
    purchase_date: date
    commission: float = 0
    total_cost: Optional[float] = None
    current_nav: Optional[float] = None
    current_value: Optional[float] = None
    profit_loss: Optional[float] = None
    profit_loss_pct: Optional[float] = None
    trade_note: Optional[str] = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


class FundHoldingsSummary(BaseModel):
    """基金持仓汇总响应"""
    model_config = ConfigDict(from_attributes=True)

    total_holdings: int
    total_cost: float
    total_value: float
    total_profit_loss: float
    total_profit_loss_pct: float
