# models/simulation.py
"""
模拟盘（纸面交易）系统 SQLAlchemy 数据模型
==========================================

独立于现有手工记账体系（user_stock_holdings / user_fund_holdings），
在本项目"数据获取体系 + 记账范式"之上新建一套虚拟资金交易系统：

- sim_accounts         每个用户一个模拟账户（可用资金 / 初始资金 / 总资产 / 收益）
- sim_stock_positions  个股持仓（股数 / 加权成本 / 实时市值 / 浮动·已实现盈亏）
- sim_fund_positions   基金持仓（含 market_type 区分 场内 on / 场外 off）
- sim_trades           成交流水（每笔买卖记录，含成交后现金余额，供复盘）
- hot_lists            主页热门标的（后台可维护：股票/基金/指数/ETF）
- system_settings      系统参数（如默认初始资金）

命名约定、用户隔离方式（user_id 为 Integer 外键）与现有模型保持一致。
"""
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Date,
    Text, Boolean, ForeignKey, UniqueConstraint,
)
from sqlalchemy.sql import func
from datetime import datetime

from core.database import Base


class SimAccount(Base):
    """模拟账户表 sim_accounts（每个用户一条）"""
    __tablename__ = "sim_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), unique=True, index=True, nullable=False,
                     comment="用户ID")
    cash_balance = Column(Float, default=0.0, comment="可用资金(元)")
    frozen_amount = Column(Float, default=0.0, comment="冻结资金(元)")
    initial_capital = Column(Float, default=1000000.0, comment="初始虚拟资金(元)")
    total_asset = Column(Float, default=0.0, comment="总资产(可用资金+持仓市值)")
    total_pnl = Column(Float, default=0.0, comment="总盈亏(总资产-初始资金)")
    total_pnl_pct = Column(Float, default=0.0, comment="总收益率(%)")
    position_count = Column(Integer, default=0, comment="当前持仓数量")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")


class SimStockPosition(Base):
    """模拟个股持仓表 sim_stock_positions（用户隔离）"""
    __tablename__ = "sim_stock_positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), index=True, nullable=False, comment="用户ID")
    stock_code = Column(String(10), index=True, nullable=False, comment="股票代码(6位)")
    stock_name = Column(String(50), comment="股票名称")
    shares = Column(Integer, default=0, comment="持仓股数")
    avg_cost = Column(Float, default=0.0, comment="加权成本价(元/股, 含费用)")
    current_price = Column(Float, default=0.0, comment="当前价(元)")
    market_value = Column(Float, default=0.0, comment="当前市值(元)")
    floating_pnl = Column(Float, default=0.0, comment="浮动盈亏(元)")
    floating_pnl_pct = Column(Float, default=0.0, comment="浮动盈亏比例(%)")
    realized_pnl = Column(Float, default=0.0, comment="累计已实现盈亏(元)")
    is_active = Column(Boolean, default=True, comment="是否持有中")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    __table_args__ = (
        UniqueConstraint('user_id', 'stock_code', name='uix_sim_stock'),
    )


class SimFundPosition(Base):
    """模拟基金持仓表 sim_fund_positions（用户隔离，含场内/场外）"""
    __tablename__ = "sim_fund_positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), index=True, nullable=False, comment="用户ID")
    fund_code = Column(String(10), index=True, nullable=False, comment="基金代码(6位)")
    fund_name = Column(String(100), comment="基金名称")
    market_type = Column(String(10), default='off', comment="on=场内(ETF/LOF) off=场外(开放式)")
    shares = Column(Float, default=0.0, comment="持有份额")
    avg_cost = Column(Float, default=0.0, comment="成本价(元/份, 含费用)")
    current_price = Column(Float, default=0.0, comment="当前价/净值(元/份)")
    market_value = Column(Float, default=0.0, comment="当前市值(元)")
    floating_pnl = Column(Float, default=0.0, comment="浮动盈亏(元)")
    floating_pnl_pct = Column(Float, default=0.0, comment="浮动盈亏比例(%)")
    realized_pnl = Column(Float, default=0.0, comment="累计已实现盈亏(元)")
    is_active = Column(Boolean, default=True, comment="是否持有中")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    __table_args__ = (
        UniqueConstraint('user_id', 'fund_code', name='uix_sim_fund'),
    )


class SimTrade(Base):
    """模拟成交流水表 sim_trades（用户隔离，复盘用）"""
    __tablename__ = "sim_trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), index=True, nullable=False, comment="用户ID")
    asset_type = Column(String(10), comment="stock=个股 fund=基金")
    side = Column(String(10), comment="buy=买入 sell=卖出")
    code = Column(String(10), index=True, nullable=False, comment="代码(6位)")
    name = Column(String(100), comment="名称")
    market_type = Column(String(10), default='', comment="基金: on/off；个股为空")
    price = Column(Float, comment="成交价/净值(元)")
    shares = Column(Float, comment="成交股数/份额")
    amount = Column(Float, comment="成交额(元)")
    fee = Column(Float, default=0.0, comment="手续费(元)")
    cash_after = Column(Float, comment="成交后可用资金余额(元)")
    created_at = Column(DateTime, default=datetime.utcnow, index=True, comment="成交时间")


class HotList(Base):
    """主页热门标的表 hot_lists（后台可维护）"""
    __tablename__ = "hot_lists"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String(20), index=True, nullable=False, comment="stock=股票 index=指数 etf=ETF fund=基金")
    code = Column(String(20), index=True, nullable=False, comment="6位代码(基金同)")
    name = Column(String(100), comment="名称")
    symbol = Column(String(20), comment="带前缀行情代码(股票/指数/ETF), 如 sh000001; 基金可为空")
    market_type = Column(String(10), default='off', comment="基金: on=场内 off=场外; 其余为空")
    sort_order = Column(Integer, default=0, comment="排序(越小越靠前)")
    is_active = Column(Boolean, default=True, comment="是否展示")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")

    __table_args__ = (
        UniqueConstraint('category', 'code', name='uix_hot'),
    )


class SystemSetting(Base):
    """系统参数表 system_settings（键值对）"""
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(50), unique=True, index=True, nullable=False, comment="参数键")
    value = Column(String(255), comment="参数值")
    description = Column(String(255), comment="说明")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
