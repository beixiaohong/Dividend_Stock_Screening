# crud/fund.py
"""
基金领域 CRUD 层
================

从外部 backend 项目并入并适配本项目约定（user_id 为 Integer）：
- 用户关注 / 持仓 CRUD 来自 founds/crud_fund_screening.py（逻辑完整保留）
- 基金基础信息 / 净值 / 分红读写为本地精简实现
  （原 founds/found/ 下 CRUD 依赖缺失的 backend.public / backend.mailserver 等模块，
   仅保留与数据库直接相关的部分，爬取/推送逻辑不并入）

所有用户相关函数第一个参数均为 user_id，严格用户隔离。
"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_


from models.fund import (
    FundInfo, FundNetValue, FundDividend, UserFundWatch, UserFundHolding,
)


# ============================================================
# 基金关注 CRUD（用户隔离）
# ============================================================

def add_to_fund_watchlist(db: Session, user_id: int, fund_code: str) -> bool:
    """添加单只基金到关注列表（已存在也返回 True）"""
    existing = db.query(UserFundWatch).filter(
        UserFundWatch.user_id == user_id,
        UserFundWatch.fund_code == fund_code,
    ).first()
    if existing:
        return True
    record = UserFundWatch(user_id=user_id, fund_code=fund_code)
    db.add(record)
    db.commit()
    return True


def add_multiple_to_fund_watchlist(db: Session, user_id: int, fund_codes: List[str]) -> Dict[str, Any]:
    """批量添加基金到关注列表，返回成功/失败/需爬取统计"""
    success_count = 0
    failed_codes = []
    needs_crawl_codes = []

    for code in fund_codes:
        try:
            if add_to_fund_watchlist(db, user_id, code):
                success_count += 1
                has_data = db.query(FundNetValue).filter(
                    FundNetValue.founds_id == code
                ).first()
                if not has_data:
                    needs_crawl_codes.append(code)
            else:
                failed_codes.append(code)
        except Exception as e:
            failed_codes.append(f"{code}({str(e)})")

    return {
        "success_count": success_count,
        "failed_count": len(failed_codes),
        "failed_codes": failed_codes,
        "needs_crawl_codes": needs_crawl_codes,
    }


def get_user_fund_watchlist(db: Session, user_id: int) -> List[UserFundWatch]:
    return db.query(UserFundWatch).filter(
        UserFundWatch.user_id == user_id
    ).order_by(desc(UserFundWatch.added_at)).all()


def remove_from_fund_watchlist(db: Session, user_id: int, fund_code: str) -> bool:
    record = db.query(UserFundWatch).filter(
        UserFundWatch.user_id == user_id,
        UserFundWatch.fund_code == fund_code,
    ).first()
    if record:
        db.delete(record)
        db.commit()
        return True
    return False


def get_user_fund_watchlist_with_data(db: Session, user_id: int) -> List[Dict[str, Any]]:
    """获取用户关注列表及最新净值数据"""
    watches = get_user_fund_watchlist(db, user_id)
    if not watches:
        return []

    results = []
    for w in watches:
        code = w.fund_code
        fund_info = db.query(FundInfo).filter(FundInfo.fs_code == code).first()
        latest_data = db.query(FundNetValue).filter(
            FundNetValue.founds_id == code
        ).order_by(desc(FundNetValue.update_time)).first()

        results.append({
            "fund_code": code,
            "fund_name": fund_info.fs_name if fund_info else code,
            "added_at": w.added_at,
            "net_worth": latest_data.net_worth if latest_data else None,
            "day_rate": latest_data.day_rate if latest_data else None,
            "update_time": latest_data.update_time if latest_data else None,
        })
    return results


# ============================================================
# 基金持仓 CRUD（用户隔离）
# ============================================================

def create_fund_holding(db: Session, user_id: int, holding_data: Dict[str, Any]) -> UserFundHolding:
    """创建基金持仓记录，自动计算 total_cost = purchase_amount + commission"""
    holding_data['user_id'] = user_id
    holding_data['total_cost'] = holding_data['purchase_amount'] + holding_data.get('commission', 0)

    db_holding = UserFundHolding(**holding_data)
    db.add(db_holding)
    db.commit()
    db.refresh(db_holding)
    return db_holding


def get_user_fund_holdings(db: Session, user_id: int, active_only: bool = True) -> List[UserFundHolding]:
    query = db.query(UserFundHolding).filter(UserFundHolding.user_id == user_id)
    if active_only:
        query = query.filter(UserFundHolding.is_active == True)  # noqa: E712
    return query.order_by(desc(UserFundHolding.created_at)).all()


def update_fund_holding(db: Session, user_id: int, holding_id: int, data: Dict[str, Any]) -> Optional[UserFundHolding]:
    """更新基金持仓（只更新非 None 字段），并重算总成本"""
    holding = db.query(UserFundHolding).filter(
        UserFundHolding.id == holding_id,
        UserFundHolding.user_id == user_id,
    ).first()
    if not holding:
        return None

    for key, value in data.items():
        if value is not None and hasattr(holding, key):
            setattr(holding, key, value)

    if 'purchase_amount' in data or 'commission' in data:
        holding.total_cost = (holding.purchase_amount or 0) + (holding.commission or 0)

    db.commit()
    db.refresh(holding)
    return holding


def delete_fund_holding(db: Session, user_id: int, holding_id: int) -> bool:
    holding = db.query(UserFundHolding).filter(
        UserFundHolding.id == holding_id,
        UserFundHolding.user_id == user_id,
    ).first()
    if holding:
        db.delete(holding)
        db.commit()
        return True
    return False


def close_fund_holding(db: Session, user_id: int, holding_id: int) -> Optional[UserFundHolding]:
    """平仓（设 is_active=False）"""
    holding = db.query(UserFundHolding).filter(
        UserFundHolding.id == holding_id,
        UserFundHolding.user_id == user_id,
    ).first()
    if holding:
        holding.is_active = False
        db.commit()
        db.refresh(holding)
    return holding


def update_fund_holding_nav(db: Session, user_id: int, fund_code: str, current_nav: float) -> bool:
    """
    更新持仓当前净值并重算盈亏：
        current_value = shares * current_nav
        profit_loss = current_value - total_cost
        profit_loss_pct = (current_nav - purchase_nav) / purchase_nav * 100
    """
    holdings = db.query(UserFundHolding).filter(
        UserFundHolding.user_id == user_id,
        UserFundHolding.fund_code == fund_code,
        UserFundHolding.is_active == True,  # noqa: E712
    ).all()

    for h in holdings:
        h.current_nav = current_nav
        h.current_value = h.shares * current_nav
        h.profit_loss = h.current_value - (h.total_cost or 0)
        if h.purchase_nav and h.purchase_nav > 0:
            h.profit_loss_pct = round((current_nav - h.purchase_nav) / h.purchase_nav * 100, 2)

    db.commit()
    return len(holdings) > 0


def get_user_fund_holdings_summary(db: Session, user_id: int) -> Dict[str, Any]:
    holdings = get_user_fund_holdings(db, user_id, active_only=True)
    total_cost = sum(h.total_cost or 0 for h in holdings)
    total_value = sum(h.current_value or 0 for h in holdings)
    total_profit_loss = total_value - total_cost
    total_profit_loss_pct = round((total_profit_loss / total_cost * 100), 2) if total_cost > 0 else 0

    return {
        "total_holdings": len(holdings),
        "total_cost": round(total_cost, 2),
        "total_value": round(total_value, 2),
        "total_profit_loss": round(total_profit_loss, 2),
        "total_profit_loss_pct": total_profit_loss_pct,
    }


def get_all_watched_fund_codes(db: Session) -> List[str]:
    """获取所有用户关注的基金代码（去重），用于定时任务"""
    results = db.query(UserFundWatch.fund_code).distinct().all()
    return [r[0] for r in results]


# ============================================================
# 基金基础信息 / 净值 / 分红读写
# ============================================================

def search_fund_info(db: Session, keyword: str, limit: int = 20) -> List[FundInfo]:
    """按基金代码或名称模糊搜索"""
    return db.query(FundInfo).filter(
        or_(
            FundInfo.fs_code.contains(keyword),
            FundInfo.fs_name.contains(keyword),
        ),
        FundInfo.fs_code.isnot(None),
        FundInfo.fs_code != '',
    ).limit(limit).all()


def get_fund_info(db: Session, fund_code: str) -> Optional[FundInfo]:
    return db.query(FundInfo).filter(FundInfo.fs_code == fund_code).first()


def upsert_fund_info(db: Session, info: Dict[str, Any]) -> FundInfo:
    """新增或更新基金基础信息（按 fs_code 去重）"""
    code = info.get("fs_code")
    existing = db.query(FundInfo).filter(FundInfo.fs_code == code).first()
    if existing:
        for k, v in info.items():
            if v is not None and hasattr(existing, k):
                setattr(existing, k, v)
        db.commit()
        db.refresh(existing)
        return existing
    obj = FundInfo(**{k: v for k, v in info.items() if hasattr(FundInfo, k)})
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def save_fund_nav_batch(db: Session, data_list: List[Dict[str, Any]]) -> int:
    """批量写入基金净值（按 founds_id + update_time 去重更新）"""
    count = 0
    for d in data_list:
        existing = db.query(FundNetValue).filter(
            FundNetValue.founds_id == d.get("founds_id"),
            FundNetValue.update_time == d.get("update_time"),
        ).first()
        if existing:
            for k, v in d.items():
                if v is not None and hasattr(existing, k):
                    setattr(existing, k, v)
        else:
            obj = FundNetValue(**{k: v for k, v in d.items() if hasattr(FundNetValue, k)})
            db.add(obj)
            count += 1
    db.commit()
    return count


def get_fund_latest_nav(db: Session, fund_code: str) -> Optional[FundNetValue]:
    return db.query(FundNetValue).filter(
        FundNetValue.founds_id == fund_code
    ).order_by(desc(FundNetValue.update_time)).first()


def get_fund_nav_history(db: Session, fund_code: str, limit: int = 30) -> List[FundNetValue]:
    return db.query(FundNetValue).filter(
        FundNetValue.founds_id == fund_code
    ).order_by(desc(FundNetValue.update_time)).limit(limit).all()


def save_fund_dividend(db: Session, fs_code: str, profit: float, time: Optional[int] = None) -> FundDividend:
    obj = FundDividend(fs_code=fs_code, profit=profit, time=time)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj
