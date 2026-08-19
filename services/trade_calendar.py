# services/trade_calendar.py
"""
A股交易日历与交易时间工具
========================
- 交易时段：工作日 9:30-11:30、13:00-15:00（股票）
- 场外基金：任意时间可申赎；工作日 15:00 前下单按当日净值确认（T 日），
  15:00 后（含周末任意时间）按下一工作日净值确认（T+1）。

注意：当前仅按周末判断休市，法定节假日可在此扩展（维护节假日集合即可）。
"""
from datetime import date, datetime, time, timedelta

# 法定节假日（示例，可扩展；格式 YYYY-MM-DD）
# HOLIDAYS = {"2026-10-01", ...}
HOLIDAYS: set[str] = set()


def is_workday(d: date) -> bool:
    """是否为工作日（周一至周五且非法定节假日）。"""
    if d.weekday() >= 5:
        return False
    if d.isoformat() in HOLIDAYS:
        return False
    return True


def next_workday(d: date) -> date:
    """下一个工作日。"""
    d = d + timedelta(days=1)
    while not is_workday(d):
        d = d + timedelta(days=1)
    return d


def is_stock_trading_time(now: datetime | None = None) -> bool:
    """是否处于 A 股股票交易时段（工作日 9:30-11:30 / 13:00-15:00）。"""
    now = now or datetime.now()
    if not is_workday(now.date()):
        return False
    t = now.time()
    return (time(9, 30) <= t <= time(11, 30)) or (time(13, 0) <= t <= time(15, 0))


def fund_settle_date(now: datetime | None = None) -> date:
    """场外基金申赎的净值确认日（T 日 / T+1）。

    - 工作日 15:00 前 -> 当日（T 日）
    - 工作日 15:00 后 / 非工作日任意时间 -> 下一工作日（T+1）
    """
    now = now or datetime.now()
    if not is_workday(now.date()):
        return next_workday(now.date())
    if now.time() > time(15, 0):
        return next_workday(now.date())
    return now.date()


def next_trade_confirm(now: datetime | None = None) -> tuple[date, bool]:
    """股票下一可交易时段说明（供前端提示）。返回 (最近工作日, 是否今日盘中)。"""
    now = now or datetime.now()
    if is_stock_trading_time(now):
        return now.date(), True
    if is_workday(now.date()):
        return now.date(), False
    return next_workday(now.date()), False
