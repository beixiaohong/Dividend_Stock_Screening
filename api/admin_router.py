# api/admin_router.py
"""
后台管理 API 路由
=================
- 热门标的 hot_lists 的增删改查（主页展示内容，可由后台维护）
- 系统参数 system_settings（如默认初始资金）
- 默认数据重新播种

说明：当前实例为个人训练工具，后台接口仅做登录校验；如需更严格的管理员权限，
可在 User 模型增加角色字段后在此增加判断。
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.database import get_db
from core.auth_dependency import get_current_user
from models.user import User

import crud.simulation as crud_sim
from schemas.simulation import HotListIn, HotListUpdate, HotListItemOut, SettingIn

router = APIRouter(prefix="/admin", tags=["后台管理"])


@router.get("/hot-lists", response_model=List[HotListItemOut], summary="热门标的列表")
def list_hot(active_only: bool = False, db: Session = Depends(get_db),
             current_user: User = Depends(get_current_user)):
    """获取热门标的（默认含停用项，便于后台编辑）。"""
    return crud_sim.list_hot_lists(db, active_only=active_only)


@router.post("/hot-lists", response_model=HotListItemOut, summary="新增/更新热门标的")
def add_hot(payload: HotListIn, db: Session = Depends(get_db),
            current_user: User = Depends(get_current_user)):
    """新增热门标的；若 category+code 已存在则更新。"""
    obj = crud_sim.add_hot_list(db, payload.model_dump())
    return HotListItemOut.model_validate(obj)


@router.put("/hot-lists/{hot_id}", response_model=HotListItemOut, summary="修改热门标的")
def update_hot(hot_id: int, payload: HotListUpdate, db: Session = Depends(get_db),
               current_user: User = Depends(get_current_user)):
    obj = crud_sim.update_hot_list(db, hot_id, payload.model_dump(exclude_unset=True))
    if not obj:
        raise HTTPException(status_code=404, detail="热门标的不存在")
    return HotListItemOut.model_validate(obj)


@router.delete("/hot-lists/{hot_id}", summary="删除热门标的")
def delete_hot(hot_id: int, db: Session = Depends(get_db),
               current_user: User = Depends(get_current_user)):
    ok = crud_sim.delete_hot_list(db, hot_id)
    if not ok:
        raise HTTPException(status_code=404, detail="热门标的不存在")
    return {"status": "success", "message": "已删除"}


@router.get("/settings/{key}", summary="读取系统参数")
def get_setting(key: str, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    s = crud_sim.get_setting(db, key)
    if not s:
        raise HTTPException(status_code=404, detail="参数不存在")
    return {"key": s.key, "value": s.value, "description": s.description}


@router.put("/settings/{key}", summary="设置系统参数")
def set_setting(key: str, payload: SettingIn, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    s = crud_sim.set_setting(db, key, payload.value, payload.description)
    return {"key": s.key, "value": s.value, "description": s.description}


@router.post("/seed", summary="重新播种默认热门标的与参数")
def seed(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """仅当 hot_lists / initial_capital 为空时补充默认数据；已存在则不覆盖。
    播种后自动为默认场外基金补充最新净值。"""
    result = crud_sim.seed_default_data(db, crud_sim.get_initial_capital(db))
    # 同步默认场外基金净值（best-effort）
    try:
        from services.fund_nav import fetch_and_store, DEFAULT_OFF_FUND_CODES
        fund_nav = fetch_and_store(db, DEFAULT_OFF_FUND_CODES)
    except Exception as e:
        fund_nav = {"error": str(e)}
    return {"status": "success", "data": result, "fund_nav": fund_nav}


@router.post("/fund-nav/sync", summary="同步所有场外基金最新净值")
def sync_fund_nav(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """抓取所有场外热门标的 + 用户关注的场外基金的最新净值并入库。"""
    from services.fund_nav import sync_all_fund_navs
    res = sync_all_fund_navs(db)
    return {"status": "success", "data": res}
