"""把多源股票数据客户端（stock_data.client）产出的 StockQuote / Kline，
upsert 到本项目的 db_stock_daily_market / historical_data 表。

对 ORM 模型与会话的导入是"惰性"的：本模块被 import 时不会触发数据库
相关依赖，方便在无 DB 环境（如单元测试）下直接引用 client。
"""

from __future__ import annotations

import datetime
from typing import Iterable

from .client import StockDataClient, get_client
from .models import StockQuote, Kline, normalize_code


def _get_models():
    """惰性加载 ORM 模型与会话（指向本项目真实模块）。"""
    from core.database import SessionLocal
    from models.stock import (
        DailyMarketData,
        HistoricalData,
    )

    return SessionLocal, DailyMarketData, HistoricalData


def upsert_realtime(quotes: Iterable[StockQuote], db=None) -> int:
    """把实时行情写入 db_stock_daily_market（按 date+code 更新或插入）。

    返回写入条数。db 为可选；不传则内部新建并关闭会话。
    """
    SessionLocal, DailyMarketData, _ = _get_models()
    own = db is None
    if own:
        db = SessionLocal()
    try:
        today = datetime.date.today()
        count = 0
        for q in quotes:
            if q.price is None:
                continue
            row = (
                db.query(DailyMarketData)
                .filter(DailyMarketData.code == q.code, DailyMarketData.date == today)
                .first()
            )
            d = StockDataClient.to_daily_market_dict(q)
            if row is None:
                row = DailyMarketData(date=today, code=q.code)
                db.add(row)
            for key, val in d.items():
                setattr(row, key, val)
            row.updated_at = datetime.datetime.now()
            count += 1
        db.commit()
        return count
    finally:
        if own:
            db.close()


def upsert_kline(code: str, klines: Iterable[Kline], db=None) -> int:
    """把 K 线写入 db_stock_historical（先删后插，保证幂等）。"""
    SessionLocal, _, HistoricalData = _get_models()
    own = db is None
    if own:
        db = SessionLocal()
    try:
        code = normalize_code(code)
        db.query(HistoricalData).filter(HistoricalData.stock_code == code).delete()
        for k in klines:
            db.add(
                HistoricalData(
                    stock_code=k.code,
                    date=datetime.datetime.strptime(k.date, "%Y-%m-%d").date(),
                    open=k.open,
                    close=k.close,
                    high=k.high,
                    low=k.low,
                    volume=k.volume,
                )
            )
        db.commit()
        return len(list(klines))
    finally:
        if own:
            db.close()


def fetch_and_store_realtime(codes: list[str], client: StockDataClient | None = None) -> dict:
    """抓取并落库：实时行情。返回 {code: quote} 与写入条数。"""
    client = client or get_client()
    quotes = client.get_realtime(codes)
    written = upsert_realtime(quotes.values())
    return {"quotes": quotes, "written": written}


def fetch_and_store_snapshot(client: StockDataClient | None = None) -> dict:
    """抓取并落库：全市场快照。"""
    client = client or get_client()
    quotes = client.get_market_snapshot()
    written = upsert_realtime(quotes)
    return {"total": len(quotes), "written": written}
