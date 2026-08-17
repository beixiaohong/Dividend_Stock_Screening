# crud/simulation.py
"""
模拟盘系统 CRUD 层
====================
账户 / 持仓 / 流水 / 热门标的 / 系统参数 的读写，全部用户隔离（除热门标的与系统参数）。
"""
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from models.simulation import (
    SimAccount, SimStockPosition, SimFundPosition, SimTrade, HotList, SystemSetting,
    SimEquitySnapshot,
)


# ============================================================
# 账户
# ============================================================
def get_account(db: Session, user_id: int) -> Optional[SimAccount]:
    return db.query(SimAccount).filter(SimAccount.user_id == user_id).first()


def ensure_account(db: Session, user_id: int, initial_capital: float = 1000000.0) -> SimAccount:
    acc = get_account(db, user_id)
    if acc:
        return acc
    acc = SimAccount(
        user_id=user_id,
        cash_balance=initial_capital,
        initial_capital=initial_capital,
        total_asset=initial_capital,
        total_pnl=0.0,
        total_pnl_pct=0.0,
        position_count=0,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


def reset_account(db: Session, user_id: int, initial_capital: float) -> SimAccount:
    acc = get_account(db, user_id)
    if acc:
        acc.cash_balance = initial_capital
        acc.frozen_amount = 0.0
        acc.initial_capital = initial_capital
        acc.total_asset = initial_capital
        acc.total_pnl = 0.0
        acc.total_pnl_pct = 0.0
        acc.position_count = 0
    else:
        acc = SimAccount(
            user_id=user_id,
            cash_balance=initial_capital,
            initial_capital=initial_capital,
            total_asset=initial_capital,
        )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


def list_all_accounts(db: Session) -> List[SimAccount]:
    """列出全部模拟账户（每日净值快照任务用）。"""
    return db.query(SimAccount).all()


def snapshot_equity(
    db: Session, user_id: int,
    total_asset: float, total_pnl: float, total_pnl_pct: float,
    cash_balance: float, market_value: float,
    snap_date=None,
) -> SimEquitySnapshot:
    """写入/更新某日净值快照（同一天幂等）。"""
    from datetime import date
    snap_date = snap_date or date.today()
    existing = db.query(SimEquitySnapshot).filter(
        SimEquitySnapshot.user_id == user_id,
        SimEquitySnapshot.snap_date == snap_date,
    ).first()
    if existing:
        existing.total_asset = total_asset
        existing.cash_balance = cash_balance
        existing.market_value = market_value
        existing.total_pnl = total_pnl
        existing.total_pnl_pct = total_pnl_pct
    else:
        existing = SimEquitySnapshot(
            user_id=user_id, snap_date=snap_date,
            total_asset=total_asset, cash_balance=cash_balance,
            market_value=market_value, total_pnl=total_pnl, total_pnl_pct=total_pnl_pct,
        )
        db.add(existing)
    db.commit()
    db.refresh(existing)
    return existing


def get_equity_series(db: Session, user_id: int, days: int = 90) -> List[Dict[str, Any]]:
    """返回最近 days 天的净值序列（升序），用于资产走势曲线。"""
    from datetime import date, timedelta
    cutoff = date.today() - timedelta(days=max(days, 1))
    rows = db.query(SimEquitySnapshot).filter(
        SimEquitySnapshot.user_id == user_id,
        SimEquitySnapshot.snap_date >= cutoff,
    ).order_by(SimEquitySnapshot.snap_date).all()
    return [{
        "date": r.snap_date.isoformat(),
        "total_asset": r.total_asset,
        "cash_balance": r.cash_balance,
        "market_value": r.market_value,
        "total_pnl": r.total_pnl,
        "total_pnl_pct": r.total_pnl_pct,
    } for r in rows]


def update_account(db: Session, acc: SimAccount) -> SimAccount:
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


# ============================================================
# 个股持仓
# ============================================================
def get_stock_position(db: Session, user_id: int, stock_code: str) -> Optional[SimStockPosition]:
    return db.query(SimStockPosition).filter(
        SimStockPosition.user_id == user_id,
        SimStockPosition.stock_code == stock_code,
    ).first()


def get_stock_positions(db: Session, user_id: int, active_only: bool = True) -> List[SimStockPosition]:
    q = db.query(SimStockPosition).filter(SimStockPosition.user_id == user_id)
    if active_only:
        q = q.filter(SimStockPosition.is_active == True)  # noqa: E712
    return q.order_by(desc(SimStockPosition.market_value)).all()


def upsert_stock_position(db: Session, user_id: int, data: Dict[str, Any]) -> SimStockPosition:
    pos = get_stock_position(db, user_id, data["stock_code"])
    if pos:
        for k, v in data.items():
            if v is not None and hasattr(pos, k):
                setattr(pos, k, v)
    else:
        pos = SimStockPosition(user_id=user_id, **{
            k: v for k, v in data.items() if hasattr(SimStockPosition, k)
        })
        db.add(pos)
    db.commit()
    db.refresh(pos)
    return pos


def delete_stock_position(db: Session, user_id: int, stock_code: str) -> bool:
    pos = get_stock_position(db, user_id, stock_code)
    if pos:
        db.delete(pos)
        db.commit()
        return True
    return False


# ============================================================
# 基金持仓
# ============================================================
def get_fund_position(db: Session, user_id: int, fund_code: str) -> Optional[SimFundPosition]:
    return db.query(SimFundPosition).filter(
        SimFundPosition.user_id == user_id,
        SimFundPosition.fund_code == fund_code,
    ).first()


def get_fund_positions(db: Session, user_id: int, active_only: bool = True) -> List[SimFundPosition]:
    q = db.query(SimFundPosition).filter(SimFundPosition.user_id == user_id)
    if active_only:
        q = q.filter(SimFundPosition.is_active == True)  # noqa: E712
    return q.order_by(desc(SimFundPosition.market_value)).all()


def upsert_fund_position(db: Session, user_id: int, data: Dict[str, Any]) -> SimFundPosition:
    pos = get_fund_position(db, user_id, data["fund_code"])
    if pos:
        for k, v in data.items():
            if v is not None and hasattr(pos, k):
                setattr(pos, k, v)
    else:
        pos = SimFundPosition(user_id=user_id, **{
            k: v for k, v in data.items() if hasattr(SimFundPosition, k)
        })
        db.add(pos)
    db.commit()
    db.refresh(pos)
    return pos


def delete_fund_position(db: Session, user_id: int, fund_code: str) -> bool:
    pos = get_fund_position(db, user_id, fund_code)
    if pos:
        db.delete(pos)
        db.commit()
        return True
    return False


# ============================================================
# 交易流水
# ============================================================
def add_trade(db: Session, user_id: int, data: Dict[str, Any]) -> SimTrade:
    trade = SimTrade(user_id=user_id, **{
        k: v for k, v in data.items() if hasattr(SimTrade, k)
    })
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade


def get_trades(db: Session, user_id: int, limit: int = 100) -> List[SimTrade]:
    return db.query(SimTrade).filter(SimTrade.user_id == user_id).order_by(
        desc(SimTrade.created_at)
    ).limit(limit).all()


# ============================================================
# 热门标的 hot_lists
# ============================================================
def list_hot_lists(db: Session, active_only: bool = False) -> List[HotList]:
    q = db.query(HotList)
    if active_only:
        q = q.filter(HotList.is_active == True)  # noqa: E712
    return q.order_by(HotList.category, HotList.sort_order, HotList.id).all()


def get_hot_list(db: Session, hot_id: int) -> Optional[HotList]:
    return db.query(HotList).filter(HotList.id == hot_id).first()


def add_hot_list(db: Session, data: Dict[str, Any]) -> HotList:
    # 同 category+code 已存在则更新
    existing = db.query(HotList).filter(
        HotList.category == data["category"],
        HotList.code == data["code"],
    ).first()
    if existing:
        for k, v in data.items():
            if v is not None and hasattr(existing, k):
                setattr(existing, k, v)
        db.commit()
        db.refresh(existing)
        return existing
    obj = HotList(**{k: v for k, v in data.items() if hasattr(HotList, k)})
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update_hot_list(db: Session, hot_id: int, data: Dict[str, Any]) -> Optional[HotList]:
    obj = get_hot_list(db, hot_id)
    if not obj:
        return None
    for k, v in data.items():
        if v is not None and hasattr(obj, k):
            setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


def delete_hot_list(db: Session, hot_id: int) -> bool:
    obj = get_hot_list(db, hot_id)
    if obj:
        db.delete(obj)
        db.commit()
        return True
    return False


# ============================================================
# 系统参数 system_settings
# ============================================================
def get_setting(db: Session, key: str) -> Optional[SystemSetting]:
    return db.query(SystemSetting).filter(SystemSetting.key == key).first()


def get_setting_value(db: Session, key: str, default: str = "") -> str:
    s = get_setting(db, key)
    return s.value if s else default


def set_setting(db: Session, key: str, value: str, description: Optional[str] = None) -> SystemSetting:
    s = get_setting(db, key)
    if s:
        s.value = value
        if description is not None:
            s.description = description
    else:
        s = SystemSetting(key=key, value=value, description=description)
        db.add(s)
    db.commit()
    db.refresh(s)
    return s


def get_initial_capital(db: Session, default: float = 1000000.0) -> float:
    v = get_setting_value(db, "initial_capital", str(default))
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


# ============================================================
# 默认数据播种（热门标的 + 初始资金参数）
# ============================================================
_DEFAULT_HOT = [
    # 指数（symbol 带前缀，规避指数代码前缀歧义）
    ("index", "000001", "上证指数", "sh000001", "", 10),
    ("index", "399001", "深证成指", "sz399001", "", 20),
    ("index", "399006", "创业板指", "sz399006", "", 30),
    ("index", "000300", "沪深300", "sh000300", "", 40),
    ("index", "000688", "科创50", "sh000688", "", 50),
    ("index", "000016", "上证50", "sh000016", "", 60),
    # 股票
    ("stock", "600519", "贵州茅台", "sh600519", "", 10),
    ("stock", "601318", "中国平安", "sh601318", "", 20),
    ("stock", "600036", "招商银行", "sh600036", "", 30),
    ("stock", "000858", "五粮液", "sz000858", "", 40),
    ("stock", "300750", "宁德时代", "sz300750", "", 50),
    ("stock", "600276", "恒瑞医药", "sh600276", "", 60),
    # ETF（场内，symbol 带前缀；ETF 前缀不能套用普通股票规则）
    ("etf", "510300", "沪深300ETF", "sh510300", "", 10),
    ("etf", "159915", "创业板ETF", "sz159915", "", 20),
    ("etf", "518880", "黄金ETF", "sh518880", "", 30),
    ("etf", "512010", "医药ETF", "sh512010", "", 40),
    ("etf", "510500", "中证500ETF", "sh510500", "", 50),
    # 场外基金（按最新净值计价；初始无净值数据则主页显示 --）
    ("fund", "110011", "易方达中小盘混合", "", "off", 10),
    ("fund", "161725", "招商中证白酒指数", "", "off", 20),
    ("fund", "005827", "易方达蓝筹精选混合", "", "off", 30),
    ("fund", "320007", "诺安成长混合", "", "off", 40),
    # 场内基金（LOF，按市价成交）
    ("fund", "163406", "兴全合润LOF", "sz163406", "on", 50),
    ("fund", "161226", "国投白银LOF", "sz161226", "on", 60),
]


def seed_default_data(db: Session, initial_capital: float = 1000000.0) -> Dict[str, int]:
    """播种默认热门标的与初始资金参数（仅在表为空时）。"""
    hot_count = 0
    if db.query(HotList).count() == 0:
        for category, code, name, symbol, market_type, sort_order in _DEFAULT_HOT:
            db.add(HotList(
                category=category, code=code, name=name, symbol=symbol,
                market_type=market_type, sort_order=sort_order, is_active=True,
            ))
            hot_count += 1
        db.commit()

    setting_count = 0
    if get_setting(db, "initial_capital") is None:
        set_setting(db, "initial_capital", str(initial_capital), "模拟盘默认初始虚拟资金(元)")
        setting_count = 1

    return {"hot_added": hot_count, "setting_added": setting_count}
