# api/fund_router.py
"""
基金用户管理 API 路由
=====================

适配自 founds/route_fund_screening.py：
- 认证方式与本项目一致：使用 core.auth_dependency.get_current_user（JWT），
  通过 current_user.user_id（Integer）做用户隔离（原 backend.users.user_auth 不可用）
- 移除依赖缺失模块的自动爬取 / Celery 触发逻辑（backend.founds.founds_format / tasks_data_crawl）
- 基金数据写入接口由 crud.fund 提供，便于后续接入数据源
"""
import re
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from core.database import get_db
from core.auth_dependency import get_current_user
from models.user import User
from models.fund import FundInfo, FundNetValue
import crud.fund as crud_fund
from schemas.fund import (
    FundWatchListAdd, FundWatchListWithData,
    FundHoldingCreate, FundHoldingUpdate, FundHoldingOut, FundHoldingsSummary,
)

router = APIRouter(prefix="/fund-screening", tags=["基金用户管理"])


# ============================================================
# 基金搜索
# ============================================================

@router.get("/search", summary="搜索基金")
async def search_funds(
    keyword: str = Query(..., min_length=1, description="搜索关键词（代码或名称）"),
    limit: int = Query(20, ge=1, le=100, description="最大返回数量"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    搜索基金（从 FundInfo 表）
    - 支持按基金代码或名称模糊搜索
    - 返回基金基础信息 + 最新净值
    """
    results = crud_fund.search_fund_info(db, keyword, limit)
    fund_list = []
    for fund in results:
        latest = crud_fund.get_fund_latest_nav(db, fund.fs_code)
        fund_list.append({
            "fs_code": fund.fs_code,
            "fs_name": fund.fs_name,
            "fs_type": fund.fs_type,
            "net_worth": latest.net_worth if latest else None,
            "day_rate": latest.day_rate if latest else None,
        })
    return {"status": "success", "data": fund_list, "total": len(fund_list)}


# ============================================================
# 基金关注管理
# ============================================================

@router.post("/watch/add", summary="添加关注基金")
def add_watch_fund(
    watch_data: FundWatchListAdd,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """批量添加关注基金（基金代码用逗号分隔，自动提取6位数字）"""
    codes = re.findall(r'\d{6}', watch_data.fund_codes)
    if not codes:
        raise HTTPException(status_code=400, detail="未找到有效的基金代码（需要6位数字）")

    result = crud_fund.add_multiple_to_fund_watchlist(db, current_user.user_id, codes)
    message = f"已为 {current_user.nickname or current_user.account} 添加 {result['success_count']} 只基金"
    return {"status": "success", "message": message, "data": result}


@router.delete("/watch/remove/{fund_code}", summary="移除关注基金")
def remove_watch_fund(
    fund_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """移除关注基金（严格隔离）"""
    result = crud_fund.remove_from_fund_watchlist(db, current_user.user_id, fund_code)
    if result:
        return {"status": "success", "message": f"已移除 {fund_code}"}
    raise HTTPException(status_code=404, detail="关注记录不存在")


@router.get("/watch/list", response_model=List[FundWatchListWithData], summary="获取关注列表")
def list_watch_funds(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的关注列表及最新净值"""
    return crud_fund.get_user_fund_watchlist_with_data(db, current_user.user_id)


# ============================================================
# 基金持仓管理
# ============================================================

@router.post("/holdings/add", summary="添加基金持仓")
def add_holding(
    holding_data: FundHoldingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """添加基金持仓记录（自动计算总成本 = 购买金额 + 手续费）"""
    data = holding_data.model_dump()
    holding = crud_fund.create_fund_holding(db, current_user.user_id, data)
    return {
        "status": "success",
        "message": f"已添加 {holding.fund_code} 持仓",
        "data": FundHoldingOut.model_validate(holding),
    }


@router.get("/holdings/my", response_model=List[FundHoldingOut], summary="获取我的持仓")
def get_my_holdings(
    active_only: bool = Query(True, description="是否只显示持有中的持仓"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的持仓列表"""
    holdings = crud_fund.get_user_fund_holdings(db, current_user.user_id, active_only)
    return holdings


@router.put("/holdings/{holding_id}", summary="修改持仓记录")
def update_holding(
    holding_id: int,
    update_data: FundHoldingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """修改持仓记录（严格隔离，只能修改自己的）"""
    data = update_data.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="没有要更新的数据")

    holding = crud_fund.update_fund_holding(db, current_user.user_id, holding_id, data)
    if not holding:
        raise HTTPException(status_code=404, detail="持仓记录不存在")

    return {
        "status": "success",
        "message": "持仓更新成功",
        "data": FundHoldingOut.model_validate(holding),
    }


@router.delete("/holdings/{holding_id}", summary="删除持仓记录")
def delete_holding(
    holding_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除持仓记录（严格隔离）"""
    result = crud_fund.delete_fund_holding(db, current_user.user_id, holding_id)
    if result:
        return {"status": "success", "message": "持仓已删除"}
    raise HTTPException(status_code=404, detail="持仓记录不存在")


@router.post("/holdings/{holding_id}/close", summary="平仓")
def close_holding(
    holding_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """平仓（标记为不再持有，严格隔离）"""
    holding = crud_fund.close_fund_holding(db, current_user.user_id, holding_id)
    if not holding:
        raise HTTPException(status_code=404, detail="持仓记录不存在")

    return {
        "status": "success",
        "message": f"已平仓 {holding.fund_code}",
        "data": FundHoldingOut.model_validate(holding),
    }


@router.get("/holdings/summary", response_model=FundHoldingsSummary, summary="持仓汇总")
def get_holdings_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的持仓汇总统计"""
    return crud_fund.get_user_fund_holdings_summary(db, current_user.user_id)
