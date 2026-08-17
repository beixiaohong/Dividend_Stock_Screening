# models/fund.py
"""
基金领域 SQLAlchemy 数据模型
============================

从外部 backend 项目并入并适配本项目约定：
- 模型原名为 ModFound / ModFoundData / ModFoundProfit（见 founds/model_found.py）
- user_id 由 String(36) UUID 改为与本项目的 users.user_id 一致的 Integer 外键

包含表：
- db_founds_info   基金基础信息   (FundInfo)
- db_founds_data   基金净值历史   (FundNetValue)
- db_founds_profit 基金分红记录   (FundDividend)
- db_user_fund_watch   用户关注基金 (UserFundWatch)
- db_user_fund_holdings 用户基金持仓 (UserFundHolding)
"""
from sqlalchemy import (
    Column, Integer, String, Float, BigInteger, DateTime, Date,
    Text, Boolean, ForeignKey, UniqueConstraint,
)
from sqlalchemy.sql import func
from datetime import datetime

from core.database import Base


class FundInfo(Base):
    """基金基础信息表 db_founds_info"""
    __tablename__ = "db_founds_info"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fs_code = Column(String(255), index=True, nullable=True, comment="基金代码")
    fs_name = Column(String(255), nullable=True, comment="基金名称")
    fs_type = Column(Integer, nullable=True, comment="基金类型 1=股票型 2=债券型 3=混合型")
    source_rate = Column(Float, nullable=True, comment="原费率")
    rate = Column(Float, nullable=True, comment="现费率(优惠后)")
    fund_minsg = Column(Float, nullable=True, comment="最小申购金额")
    stockcodes = Column(String(255), nullable=True, comment="持仓股票代码(逗号分隔)")
    zqcodes = Column(String(255), nullable=True, comment="持仓债券代码(逗号分隔)")
    syl_1n = Column(Float, nullable=True, comment="近一年收益率")
    syl_6y = Column(Float, nullable=True, comment="近6月收益率")
    syl_3y = Column(Float, nullable=True, comment="近3月收益率")
    syl_1y = Column(Float, nullable=True, comment="近1月收益率")
    update_time = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp())
    state = Column(Integer, nullable=True, comment="状态 1=无效 0/NULL=有效")


class FundNetValue(Base):
    """基金净值历史表 db_founds_data"""
    __tablename__ = "db_founds_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    founds_id = Column(String(50), index=True, nullable=False, comment="基金代码")
    update_time = Column(BigInteger, nullable=False, comment="更新时间戳(毫秒)")
    net_worth = Column(Float, nullable=True, comment="当日净值")
    day_rate = Column(Float, nullable=True, comment="当日收益率")
    rank = Column(Integer, nullable=True, comment="排名")
    total = Column(Integer, nullable=True, comment="排名总数")
    similar = Column(Float, nullable=True, comment="同类平均日收益")

    __table_args__ = (
        UniqueConstraint('founds_id', 'update_time', name='uix_founds_id_update_time'),
    )


class FundDividend(Base):
    """基金分红表 db_founds_profit"""
    __tablename__ = "db_founds_profit"

    id = Column(Integer, primary_key=True, autoincrement=True)
    time = Column(BigInteger, nullable=True, comment="分红时间戳(毫秒)")
    fs_code = Column(String(255), index=True, nullable=True, comment="基金代码")
    profit = Column(Float, nullable=True, comment="每份分红金额")


class UserFundWatch(Base):
    """用户关注基金表 db_user_fund_watch（用户隔离）"""
    __tablename__ = "db_user_fund_watch"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), index=True, nullable=False, comment="用户ID")
    fund_code = Column(String(10), index=True, nullable=False, comment="基金代码")
    added_at = Column(DateTime, default=datetime.utcnow, comment="添加时间")

    __table_args__ = (
        UniqueConstraint('user_id', 'fund_code', name='uix_user_fund'),
    )


class UserFundHolding(Base):
    """用户基金持仓表 db_user_fund_holdings（用户隔离）"""
    __tablename__ = "db_user_fund_holdings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), index=True, nullable=False, comment="用户ID")
    fund_code = Column(String(10), index=True, nullable=False, comment="基金代码")
    fund_name = Column(String(100), comment="基金名称")

    # 购买信息
    purchase_amount = Column(Float, nullable=False, comment="购买金额(元)")
    shares = Column(Float, nullable=False, comment="持有份额")
    purchase_nav = Column(Float, nullable=False, comment="购买时净值(元/份)")
    purchase_date = Column(Date, nullable=False, comment="购买日期")

    # 成本信息
    commission = Column(Float, default=0, comment="手续费(元)")
    total_cost = Column(Float, comment="总成本(元)")

    # 当前状态
    current_nav = Column(Float, comment="当前净值(元/份)")
    current_value = Column(Float, comment="当前市值(元)")

    # 盈亏信息
    profit_loss = Column(Float, comment="浮动盈亏(元)")
    profit_loss_pct = Column(Float, comment="盈亏比例(%)")

    # 交易备注与状态
    trade_note = Column(Text, comment="交易备注")
    is_active = Column(Boolean, default=True, comment="是否持有")

    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
