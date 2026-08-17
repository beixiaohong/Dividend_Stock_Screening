# api/market_router.py
"""
市场行情 API 路由（主页实时数据）
================================
- GET /market/home  主页热门标的实时行情（股票/指数/ETF/基金），东财式行情板
- GET /market/quote 任意代码实时行情（带前缀 symbol，如 sh600519）
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import datetime

from core.database import get_db
from services import simulation_service as svc
from services.stock_data import get_client
from services.stock_data.models import normalize_code
import crud.fund as crud_fund

from schemas.simulation import HomeData

router = APIRouter(prefix="/market", tags=["市场行情"])


@router.get("/home", response_model=HomeData, summary="主页热门标的事实时行情")
def home(db: Session = Depends(get_db)):
    """读取 hot_lists（后台可维护），聚合实时行情返回分类行情板。

    股票/指数/ETF/场内基金取实时价；场外基金取最新净值（无盘中实时净值）。
    """
    return svc.get_home_data(db)


@router.get("/quote", summary="单标的实时行情")
def quote(
    symbol: str = Query(..., description="带前缀行情代码，如 sh600519 / sz399006 / sh000001"),
    db: Session = Depends(get_db),
):
    """查询单个标的的实时行情（归一化 StockQuote 字段）。"""
    client = get_client()
    try:
        q = client.get_realtime_one(symbol)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"行情源不可用: {e}")
    if not q or q.price is None:
        raise HTTPException(status_code=404, detail="未获取到行情数据")
    return {
        "code": normalize_code(symbol),
        "name": q.name,
        "price": q.price,
        "prev_close": q.prev_close,
        "open": q.open,
        "high": q.high,
        "low": q.low,
        "change_amount": q.change_amount,
        "change_pct": q.change_pct,
        "volume": q.volume,
        "amount": q.amount,
        "turnover_rate": q.turnover_rate,
        "pe": q.pe,
        "pb": q.pb,
        "source": q.source,
    }


@router.get("/fund/{code}", summary="基金最新净值与业绩（缺失时自动补抓）")
def fund_nav(code: str, db: Session = Depends(get_db)):
    """查询开放式/场内基金的最新单位净值、日收益率与近1月/3月/6月/1年业绩。

    若库中暂无数据，则尝试实时补抓一次（best-effort），用于模拟盘基金定价与详情页展示。
    """
    nav = crud_fund.get_fund_latest_nav(db, code)
    info = crud_fund.get_fund_info(db, code)
    if not nav or not nav.net_worth:
        try:
            from services.fund_nav import fetch_and_store
            fetch_and_store(db, [code])
            nav = crud_fund.get_fund_latest_nav(db, code)
            info = crud_fund.get_fund_info(db, code) or info
        except Exception:
            pass
    if not nav or not nav.net_worth:
        raise HTTPException(status_code=404, detail="暂无该基金净值数据")
    nav_date = None
    if nav.update_time:
        try:
            nav_date = datetime.datetime.fromtimestamp(nav.update_time / 1000).strftime("%Y-%m-%d")
        except Exception:
            nav_date = str(nav.update_time)
    return {
        "code": code,
        "name": info.fs_name if info else code,
        "net_worth": nav.net_worth,
        "day_rate": nav.day_rate,
        "nav_date": nav_date,
        "fs_type": info.fs_type if info else None,
        "syl_1y": info.syl_1y if info else None,   # 近1月
        "syl_3y": info.syl_3y if info else None,   # 近3月
        "syl_6y": info.syl_6y if info else None,   # 近6月
        "syl_1n": info.syl_1n if info else None,   # 近1年
        "fund_minsg": info.fund_minsg if info else None,
    }


@router.get("/fund/{code}/history", summary="基金净值历史走势（旧→新）")
def fund_nav_history(
    code: str,
    days: int = Query(120, ge=1, le=730, description="返回交易日数"),
    db: Session = Depends(get_db),
):
    """查询基金单位净值历史（用于详情页 NAV 走势图），按日期升序返回。"""
    rows = crud_fund.get_fund_nav_history(db, code, limit=days)
    out = []
    for r in reversed(rows):  # 转旧→新
        d = None
        if r.update_time:
            try:
                d = datetime.datetime.fromtimestamp(r.update_time / 1000).strftime("%Y-%m-%d")
            except Exception:
                d = str(r.update_time)
        out.append({"date": d, "net_worth": r.net_worth, "day_rate": r.day_rate})
    return out


@router.get("/kline", summary="单标的K线（收盘价序列）")
def kline(
    symbol: str = Query(..., description="带前缀行情代码，如 sh600519"),
    count: int = Query(60, ge=1, le=365, description="返回根数"),
    db: Session = Depends(get_db),
):
    """查询单标的的历史 K 线（默认前复权），用于详情页迷你走势图。"""
    client = get_client()
    try:
        kl = client.get_kline(symbol, count=count)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"行情源不可用: {e}")
    return [
        {"date": k.date, "open": k.open, "close": k.close,
         "high": k.high, "low": k.low, "volume": k.volume}
        for k in (kl or [])
    ]


@router.get("/search", response_model=List[dict], summary="行情名称/代码搜索")
def search(
    q: str = Query(..., min_length=1, description="代码或名称关键词，如 600519 / 茅台"),
    db: Session = Depends(get_db),
):
    """按代码或名称搜索 A 股/基金标的（腾讯 smartbox，返回带前缀 symbol）。"""
    client = get_client()
    return client.search(q, limit=8)
