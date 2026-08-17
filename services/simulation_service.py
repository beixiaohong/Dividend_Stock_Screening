# services/simulation_service.py
"""
模拟盘交易服务（核心业务逻辑）
==============================

职责：
1. 个股 / 基金（场内·场外）的下单成交，自动完成现金清算、加权成本、已实现盈亏。
2. 实时估值：拉取持仓实时价（股票/场内基金）与最新净值（场外基金），刷新市值与浮动盈亏，
   重算账户总资产与总收益。
3. 主页行情聚合：读 hot_lists，对股票/指数/ETF/场内基金取实时行情，场外基金取最新净值。

复用现有数据获取体系（services.stock_data 多源实时行情）与记账范式。
"""
from typing import Optional, Dict, Any, List
from datetime import datetime

from sqlalchemy.orm import Session

import crud.simulation as crud_sim
import crud.fund as crud_fund
from models.simulation import SimStockPosition, SimFundPosition, SimAccount

from services.stock_data import get_client
from services.stock_data.models import normalize_code

from schemas.simulation import HomeData, HomeQuote


# ============================================================
# 行情代码前缀推断（股票/ETF/指数）
# 注意：指数与 ETF 不能套用普通股票规则（如 000001 应为 sh，510300 应为 sh）。
# 主页 hot_lists 已存 symbol，本函数仅作兜底（用户手动买入时使用）。
# ============================================================
_SH_3 = {
    "000", "880", "899", "930",          # 指数（上证系列 / 中证）
    "510", "511", "512", "513", "515", "516", "517", "518", "519",  # 上交所ETF
    "588",                                # 科创板ETF
    "500", "501", "502", "503", "504", "505", "506", "507", "508",  # 上交所基金/LOF
}
_SZ_3 = {
    "399",                                # 深证/国证指数
    "159", "150", "160", "161", "162", "163", "164", "165", "166", "167", "168",  # 深交所ETF/LOF
}
_SH_2 = {"60", "68", "69", "90", "51", "58", "56", "55", "50", "52", "11"}
_SZ_2 = {"00", "30", "20", "15", "16", "18", "12", "13", "39"}


def market_prefix(code: str) -> str:
    """推断带前缀的行情代码前缀（sh / sz）。"""
    code = (code or "").strip()
    if not (len(code) == 6 and code.isdigit()):
        return "sh"
    head3 = code[:3]
    head2 = code[:2]
    if head3 in _SH_3:
        return "sh"
    if head3 in _SZ_3:
        return "sz"
    if head2 in _SH_2:
        return "sh"
    if head2 in _SZ_2:
        return "sz"
    return "sh"


def _quote_symbol(code: str, symbol: Optional[str] = None) -> str:
    """返回用于实时行情查询的带前缀代码。"""
    if symbol:
        return symbol
    return market_prefix(code) + code


# ============================================================
# 账户总额重算
# ============================================================
def _recompute_totals(db: Session, acc: SimAccount) -> None:
    sp = crud_sim.get_stock_positions(db, acc.user_id, active_only=True)
    fp = crud_sim.get_fund_positions(db, acc.user_id, active_only=True)
    mv = sum(p.market_value or 0 for p in sp) + sum(p.market_value or 0 for p in fp)
    acc.total_asset = round(acc.cash_balance + mv, 2)
    acc.total_pnl = round(acc.total_asset - acc.initial_capital, 2)
    acc.total_pnl_pct = round(acc.total_pnl / acc.initial_capital * 100, 2) if acc.initial_capital else 0.0
    acc.position_count = len(sp) + len(fp)
    db.commit()
    db.refresh(acc)


# ============================================================
# 个股交易
# ============================================================
def buy_stock(
    db: Session, user_id: int, stock_code: str, stock_name: Optional[str] = None,
    shares: Optional[int] = None, price: Optional[float] = None, fee_rate: float = 0.0003,
) -> SimStockPosition:
    if not shares or shares <= 0:
        raise ValueError("买入股数必须大于 0")

    acc = crud_sim.ensure_account(db, user_id, crud_sim.get_initial_capital(db))
    client = get_client()

    if price is None:
        q = client.get_realtime_one(stock_code)
        if not q or q.price is None:
            raise ValueError("无法获取该股票实时价格，请稍后重试或手动指定价格")
        price = q.price

    fee = max(price * shares * fee_rate, 5.0)  # 股票最低 5 元
    cost = price * shares + fee
    if cost > acc.cash_balance + 1e-9:
        raise ValueError(f"可用资金不足：需要 {cost:.2f} 元，当前可用 {acc.cash_balance:.2f} 元")

    pos = crud_sim.get_stock_position(db, user_id, stock_code)
    if pos and pos.is_active:
        old_shares = pos.shares
        old_cost = old_shares * pos.avg_cost
        new_shares = old_shares + shares
        pos.avg_cost = round((old_cost + cost) / new_shares, 4)
        pos.shares = new_shares
        pos.stock_name = stock_name or pos.stock_name
        pos.is_active = True
    else:
        if pos is None:
            pos = SimStockPosition(user_id=user_id, stock_code=stock_code)
        pos.shares = shares
        pos.avg_cost = round(cost / shares, 4)
        pos.stock_name = stock_name
        pos.is_active = True
        db.add(pos)

    pos.current_price = price
    pos.market_value = round(pos.shares * price, 2)
    cost_basis = pos.shares * pos.avg_cost
    pos.floating_pnl = round(pos.market_value - cost_basis, 2)
    pos.floating_pnl_pct = round(pos.floating_pnl / cost_basis * 100, 2) if cost_basis else 0.0
    db.commit()
    db.refresh(pos)

    acc.cash_balance = round(acc.cash_balance - cost, 2)
    crud_sim.add_trade(db, user_id, {
        "asset_type": "stock", "side": "buy", "code": stock_code, "name": pos.stock_name,
        "price": price, "shares": shares, "amount": round(cost, 2), "fee": round(fee, 2),
        "cash_after": acc.cash_balance,
    })
    _recompute_totals(db, acc)
    return pos


def sell_stock(
    db: Session, user_id: int, stock_code: str, shares: Optional[int] = None,
    price: Optional[float] = None, fee_rate: float = 0.0003,
) -> SimStockPosition:
    if not shares or shares <= 0:
        raise ValueError("卖出股数必须大于 0")

    pos = crud_sim.get_stock_position(db, user_id, stock_code)
    if not pos or not pos.is_active or pos.shares < shares:
        raise ValueError("持仓不足或不存在该股票持仓")

    acc = crud_sim.get_account(db, user_id)
    client = get_client()
    if price is None:
        q = client.get_realtime_one(stock_code)
        if not q or q.price is None:
            raise ValueError("无法获取该股票实时价格，请稍后重试或手动指定价格")
        price = q.price

    fee = max(price * shares * fee_rate, 5.0)
    proceeds = price * shares - fee
    realized = (price - pos.avg_cost) * shares - fee
    pos.shares -= shares
    pos.realized_pnl = round((pos.realized_pnl or 0) + realized, 2)
    pos.current_price = price
    pos.market_value = round(pos.shares * price, 2)
    cost_basis = pos.shares * pos.avg_cost
    pos.floating_pnl = round(pos.market_value - cost_basis, 2)
    pos.floating_pnl_pct = round(pos.floating_pnl / cost_basis * 100, 2) if cost_basis else 0.0
    if pos.shares <= 0:
        pos.is_active = False
        pos.shares = 0
        pos.market_value = 0.0
    db.commit()
    db.refresh(pos)

    acc.cash_balance = round(acc.cash_balance + proceeds, 2)
    crud_sim.add_trade(db, user_id, {
        "asset_type": "stock", "side": "sell", "code": stock_code, "name": pos.stock_name,
        "price": price, "shares": shares, "amount": round(proceeds, 2), "fee": round(fee, 2),
        "cash_after": acc.cash_balance,
    })
    _recompute_totals(db, acc)
    return pos


# ============================================================
# 基金交易（场内 on / 场外 off）
# ============================================================
def buy_fund(
    db: Session, user_id: int, fund_code: str, market_type: str,
    fund_name: Optional[str] = None, shares: Optional[float] = None, amount: Optional[float] = None,
    price: Optional[float] = None, fee_rate: float = 0.0015,
) -> SimFundPosition:
    if market_type not in ("on", "off"):
        raise ValueError("market_type 必须为 on(场内) 或 off(场外)")

    acc = crud_sim.ensure_account(db, user_id, crud_sim.get_initial_capital(db))

    if market_type == "on":
        # 场内：按份额、市价买入
        if not shares or shares <= 0:
            raise ValueError("场内基金买入需提供份额")
        client = get_client()
        if price is None:
            q = client.get_realtime_one(fund_code)
            if not q or q.price is None:
                raise ValueError("无法获取该场内基金实时价格")
            price = q.price
        fee = price * shares * fee_rate
        cost = price * shares + fee
        if cost > acc.cash_balance + 1e-9:
            raise ValueError(f"可用资金不足：需要 {cost:.2f} 元，当前可用 {acc.cash_balance:.2f} 元")
        pos = crud_sim.get_fund_position(db, user_id, fund_code)
        if pos and pos.is_active:
            old = pos.shares * pos.avg_cost
            ns = pos.shares + shares
            pos.avg_cost = round((old + cost) / ns, 4)
            pos.shares = ns
        else:
            if pos is None:
                pos = SimFundPosition(user_id=user_id, fund_code=fund_code, market_type="on")
            pos.shares = shares
            pos.avg_cost = round(cost / shares, 4)
            pos.market_type = "on"
            db.add(pos)
        pos.fund_name = fund_name or pos.fund_name
        pos.is_active = True
        pos.current_price = price
    else:
        # 场外：按金额申购，T+1 确认份额（此处直接确认，用于训练）
        if not amount or amount <= 0:
            raise ValueError("场外基金申购需提供金额")
        if price is None:
            nav = crud_fund.get_fund_latest_nav(db, fund_code)
            if not nav or not nav.net_worth:
                raise ValueError("无该基金最新净值，无法申购（请先补充净值数据）")
            price = nav.net_worth
        fee = amount * fee_rate
        invest = amount - fee
        shares = invest / price
        cost = amount  # 投入总额（含费）
        pos = crud_sim.get_fund_position(db, user_id, fund_code)
        if pos and pos.is_active:
            old = pos.shares * pos.avg_cost
            ns = pos.shares + shares
            pos.avg_cost = round((old + cost) / ns, 4)
            pos.shares = round(ns, 4)
        else:
            if pos is None:
                pos = SimFundPosition(user_id=user_id, fund_code=fund_code, market_type="off")
            pos.shares = round(shares, 4)
            pos.avg_cost = round(cost / shares, 4)
            pos.market_type = "off"
            db.add(pos)
        pos.fund_name = fund_name or pos.fund_name
        pos.is_active = True
        pos.current_price = price
        cost_for_cash = amount
        acc.cash_balance = round(acc.cash_balance - cost_for_cash, 2)
        # 记录交易（金额模式）
        crud_sim.add_trade(db, user_id, {
            "asset_type": "fund", "side": "buy", "code": fund_code, "name": pos.fund_name,
            "market_type": "off", "price": price, "shares": round(shares, 4),
            "amount": round(amount, 2), "fee": round(fee, 2), "cash_after": acc.cash_balance,
        })
        # 更新市值后重算
        pos.market_value = round(pos.shares * price, 2)
        cost_basis = pos.shares * pos.avg_cost
        pos.floating_pnl = round(pos.market_value - cost_basis, 2)
        pos.floating_pnl_pct = round(pos.floating_pnl / cost_basis * 100, 2) if cost_basis else 0.0
        db.commit()
        db.refresh(pos)
        _recompute_totals(db, acc)
        return pos

    # 场内基金：更新市值并写交易、重算
    pos.market_value = round(pos.shares * price, 2)
    cost_basis = pos.shares * pos.avg_cost
    pos.floating_pnl = round(pos.market_value - cost_basis, 2)
    pos.floating_pnl_pct = round(pos.floating_pnl / cost_basis * 100, 2) if cost_basis else 0.0
    db.commit()
    db.refresh(pos)
    acc.cash_balance = round(acc.cash_balance - cost, 2)
    crud_sim.add_trade(db, user_id, {
        "asset_type": "fund", "side": "buy", "code": fund_code, "name": pos.fund_name,
        "market_type": "on", "price": price, "shares": shares,
        "amount": round(cost, 2), "fee": round(fee, 2), "cash_after": acc.cash_balance,
    })
    _recompute_totals(db, acc)
    return pos


def sell_fund(
    db: Session, user_id: int, fund_code: str,
    shares: Optional[float] = None, amount: Optional[float] = None,
    price: Optional[float] = None, fee_rate: float = 0.0015,
) -> SimFundPosition:
    pos = crud_sim.get_fund_position(db, user_id, fund_code)
    if not pos or not pos.is_active:
        raise ValueError("不存在该基金持仓")

    acc = crud_sim.get_account(db, user_id)
    market_type = pos.market_type

    if market_type == "on":
        if not shares or shares <= 0:
            raise ValueError("场内基金卖出需提供份额")
        if shares > pos.shares + 1e-9:
            raise ValueError("持仓份额不足")
        client = get_client()
        if price is None:
            q = client.get_realtime_one(fund_code)
            if not q or q.price is None:
                raise ValueError("无法获取该场内基金实时价格")
            price = q.price
        fee = price * shares * fee_rate
        proceeds = price * shares - fee
        realized = (price - pos.avg_cost) * shares - fee
        pos.shares = round(pos.shares - shares, 4)
    else:
        if not shares or shares <= 0:
            raise ValueError("场外基金赎回需提供份额")
        if shares > pos.shares + 1e-9:
            raise ValueError("持仓份额不足")
        if price is None:
            nav = crud_fund.get_fund_latest_nav(db, fund_code)
            if not nav or not nav.net_worth:
                raise ValueError("无该基金最新净值，无法赎回")
            price = nav.net_worth
        fee = price * shares * fee_rate
        proceeds = price * shares - fee
        realized = (price - pos.avg_cost) * shares - fee
        pos.shares = round(pos.shares - shares, 4)

    pos.realized_pnl = round((pos.realized_pnl or 0) + realized, 2)
    pos.current_price = price
    if pos.shares <= 1e-9:
        pos.is_active = False
        pos.shares = 0.0
        pos.market_value = 0.0
    else:
        pos.market_value = round(pos.shares * price, 2)
        cost_basis = pos.shares * pos.avg_cost
        pos.floating_pnl = round(pos.market_value - cost_basis, 2)
        pos.floating_pnl_pct = round(pos.floating_pnl / cost_basis * 100, 2) if cost_basis else 0.0
    db.commit()
    db.refresh(pos)

    acc.cash_balance = round(acc.cash_balance + proceeds, 2)
    crud_sim.add_trade(db, user_id, {
        "asset_type": "fund", "side": "sell", "code": fund_code, "name": pos.fund_name,
        "market_type": market_type, "price": price, "shares": shares,
        "amount": round(proceeds, 2), "fee": round(fee, 2), "cash_after": acc.cash_balance,
    })
    _recompute_totals(db, acc)
    return pos


# ============================================================
# 实时估值
# ============================================================
def revalue(db: Session, user_id: int) -> bool:
    """刷新用户所有持仓的实时市值与账户总额。返回实时行情是否可用。"""
    acc = crud_sim.ensure_account(db, user_id, crud_sim.get_initial_capital(db))
    client = get_client()
    realtime_available = True

    sp = crud_sim.get_stock_positions(db, user_id, active_only=True)
    fp_on = [p for p in crud_sim.get_fund_positions(db, user_id, active_only=True) if p.market_type == "on"]

    realtime_syms: List[str] = []
    sym_map: Dict[str, Any] = {}
    for p in sp:
        sym = _quote_symbol(p.stock_code)
        realtime_syms.append(sym)
        sym_map[normalize_code(sym)] = ("stock", p)
    for p in fp_on:
        sym = market_prefix(p.fund_code) + p.fund_code
        realtime_syms.append(sym)
        sym_map[normalize_code(sym)] = ("fund", p)

    quotes = {}
    if realtime_syms:
        try:
            quotes = client.get_realtime(realtime_syms)
        except Exception:
            realtime_available = False

    for norm_code, (kind, p) in sym_map.items():
        q = quotes.get(norm_code)
        if q and q.price is not None:
            p.current_price = q.price
            p.market_value = round(p.shares * q.price, 2)
            cost_basis = p.shares * p.avg_cost
            p.floating_pnl = round(p.market_value - cost_basis, 2)
            p.floating_pnl_pct = round(p.floating_pnl / cost_basis * 100, 2) if cost_basis else 0.0

    # 场外基金：取最新净值
    for p in crud_sim.get_fund_positions(db, user_id, active_only=True):
        if p.market_type == "off":
            nav = crud_fund.get_fund_latest_nav(db, p.fund_code)
            if nav and nav.net_worth:
                p.current_price = nav.net_worth
                p.market_value = round(p.shares * nav.net_worth, 2)
                cost_basis = p.shares * p.avg_cost
                p.floating_pnl = round(p.market_value - cost_basis, 2)
                p.floating_pnl_pct = round(p.floating_pnl / cost_basis * 100, 2) if cost_basis else 0.0

    db.commit()
    _recompute_totals(db, acc)
    return realtime_available


# ============================================================
# 汇总 & 主页
# ============================================================
def get_summary(db: Session, user_id: int):
    """账户 + 持仓汇总（先估值再返回）。"""
    from schemas.simulation import PortfolioSummary, AccountOut
    realtime_available = revalue(db, user_id)
    acc = crud_sim.get_account(db, user_id)
    sp = crud_sim.get_stock_positions(db, user_id, active_only=True)
    fp = crud_sim.get_fund_positions(db, user_id, active_only=True)
    return PortfolioSummary(
        account=AccountOut.model_validate(acc),
        stock_positions=sp,
        fund_positions=fp,
        realtime_available=realtime_available,
    )


def get_home_data(db: Session) -> HomeData:
    """主页热门标的事实时行情聚合。"""
    rows = crud_sim.list_hot_lists(db, active_only=True)
    groups: Dict[str, List[HomeQuote]] = {"index": [], "stock": [], "etf": [], "fund": []}
    realtime_syms: List[str] = []
    sym_map: Dict[str, HomeQuote] = {}

    for r in rows:
        item = HomeQuote(
            category=r.category, code=r.code, name=r.name or r.code,
            symbol=r.symbol, market_type=r.market_type, is_active=r.is_active,
        )
        groups.setdefault(r.category, []).append(item)
        if r.category in ("index", "stock", "etf"):
            sym = _quote_symbol(r.code, r.symbol)
            realtime_syms.append(sym)
            sym_map[normalize_code(sym)] = item
        elif r.category == "fund" and r.market_type == "on" and r.symbol:
            realtime_syms.append(r.symbol)
            sym_map[normalize_code(r.symbol)] = item

    client = get_client()
    realtime_available = True
    quotes = {}
    if realtime_syms:
        try:
            quotes = client.get_realtime(realtime_syms)
        except Exception:
            realtime_available = False

    for norm_code, item in sym_map.items():
        q = quotes.get(norm_code)
        if q:
            item.price = q.price
            item.prev_close = q.prev_close
            item.change_amount = q.change_amount
            item.change_pct = q.change_pct

    # 场外基金净值
    missing_off: List[str] = []
    for item in groups.get("fund", []):
        if item.market_type == "off":
            nav = crud_fund.get_fund_latest_nav(db, item.code)
            if nav and nav.net_worth:
                item.price = nav.net_worth
                item.change_pct = nav.day_rate
            else:
                missing_off.append(item.code)

    # 自愈：缺净值的场外基金自动补抓一次（best-effort，成功写入后首页即显示）
    if missing_off:
        try:
            from services.fund_nav import fetch_and_store
            fetch_and_store(db, missing_off)
            for item in groups.get("fund", []):
                if item.market_type == "off" and item.price is None:
                    nav = crud_fund.get_fund_latest_nav(db, item.code)
                    if nav and nav.net_worth:
                        item.price = nav.net_worth
                        item.change_pct = nav.day_rate
        except Exception:
            pass

    return HomeData(
        realtime_available=realtime_available,
        updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        indices=groups["index"],
        stocks=groups["stock"],
        etfs=groups["etf"],
        funds=groups["fund"],
    )
