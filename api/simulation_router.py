# api/simulation_router.py
"""
模拟盘交易 API 路由
====================
账户、个股/基金(场内·场外)买卖、持仓、流水、汇总、重置。
所有端点均用户隔离（依赖 JWT get_current_user）。
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.database import get_db
from core.auth_dependency import get_current_user
from models.user import User

import crud.simulation as crud_sim
from services import simulation_service as svc
from schemas.simulation import (
    AccountOut, StockTradeIn, FundTradeIn, ResetAccountIn,
    StockPositionOut, FundPositionOut, TradeOut, PortfolioSummary,
)

router = APIRouter(prefix="/sim", tags=["模拟盘"])


def _account_out(db: Session, user_id: int) -> AccountOut:
    acc = crud_sim.ensure_account(db, user_id, crud_sim.get_initial_capital(db))
    return AccountOut.model_validate(acc)


@router.get("/account", response_model=AccountOut, summary="获取模拟账户")
def get_account(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取当前用户的模拟账户（不存在则自动开户，使用系统默认初始资金）。"""
    return _account_out(db, current_user.user_id)


@router.post("/reset", response_model=AccountOut, summary="重置模拟账户")
def reset_account(
    payload: ResetAccountIn, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """清空所有持仓与流水，重置为指定初始资金（默认用系统参数）。"""
    capital = payload.initial_capital or crud_sim.get_initial_capital(db)
    # 清空持仓与流水
    for p in crud_sim.get_stock_positions(db, current_user.user_id, active_only=False):
        db.delete(p)
    for p in crud_sim.get_fund_positions(db, current_user.user_id, active_only=False):
        db.delete(p)
    for t in crud_sim.get_trades(db, current_user.user_id, limit=100000):
        db.delete(t)
    db.commit()
    acc = crud_sim.reset_account(db, current_user.user_id, capital)
    return AccountOut.model_validate(acc)


@router.post("/stock/buy", response_model=StockPositionOut, summary="模拟买入个股")
def buy_stock(
    payload: StockTradeIn, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        pos = svc.buy_stock(
            db, current_user.user_id, payload.stock_code, payload.stock_name,
            payload.shares, payload.price, payload.fee_rate or 0.0003,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return StockPositionOut.model_validate(pos)


@router.post("/stock/sell", response_model=StockPositionOut, summary="模拟卖出个股")
def sell_stock(
    payload: StockTradeIn, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        pos = svc.sell_stock(
            db, current_user.user_id, payload.stock_code,
            payload.shares, payload.price, payload.fee_rate or 0.0003,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return StockPositionOut.model_validate(pos)


@router.post("/fund/buy", response_model=FundPositionOut, summary="模拟买入基金")
def buy_fund(
    payload: FundTradeIn, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        pos = svc.buy_fund(
            db, current_user.user_id, payload.fund_code, payload.market_type,
            payload.fund_name, payload.shares, payload.amount,
            payload.price, payload.fee_rate or 0.0015,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return FundPositionOut.model_validate(pos)


@router.post("/fund/sell", response_model=FundPositionOut, summary="模拟卖出基金")
def sell_fund(
    payload: FundTradeIn, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        pos = svc.sell_fund(
            db, current_user.user_id, payload.fund_code,
            payload.shares, payload.amount,
            payload.price, payload.fee_rate or 0.0015,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return FundPositionOut.model_validate(pos)


@router.get("/positions", summary="获取我的持仓")
def get_positions(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """返回当前用户的个股与基金持仓（已先实时估值）。"""
    svc.revalue(db, current_user.user_id)
    stocks = crud_sim.get_stock_positions(db, current_user.user_id, active_only=True)
    funds = crud_sim.get_fund_positions(db, current_user.user_id, active_only=True)
    return {
        "stocks": [StockPositionOut.model_validate(p) for p in stocks],
        "funds": [FundPositionOut.model_validate(p) for p in funds],
    }


@router.get("/trades", response_model=List[TradeOut], summary="获取交易流水")
def get_trades(
    limit: int = 100, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    trades = crud_sim.get_trades(db, current_user.user_id, limit=limit)
    return trades


@router.get("/summary", response_model=PortfolioSummary, summary="账户与持仓汇总")
def get_summary(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """返回账户总资产、收益及全部持仓（含实时估值）。"""
    return svc.get_summary(db, current_user.user_id)
