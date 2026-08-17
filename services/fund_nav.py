# services/fund_nav.py
"""
场外基金净值获取与入库（爬虫）
================================

为模拟盘提供场外开放式基金的「最新单位净值 + 日收益率」数据，写入：
- db_founds_data (FundNetValue)  净值历史（按 founds_id + update_time 去重）
- db_founds_info (FundInfo)      基金基础信息（名称 / 类型）

数据来源（仅用标准库 urllib，不依赖 akshare / efinance）：
- 主：天天基金估值接口  fundgz.1234567.com.cn/js/{code}.js
      返回最新单位净值(dwjz) 与 当日估算涨幅(gszzl)，稳定、无需 cookie。
- 备：东方财富历史净值接口 api.fund.eastmoney.com/f10/lsjz
      返回官方净值序列，可精确计算日收益率，并带基金类型。

说明：
- 场外基金盘中无实时价，主页与模拟盘均以「最新净值」计价；
  今日净值一般在收盘后由基金公司披露，盘中使用的是上一交易日的官方净值 + 当日估算涨幅。
- 所有抓取均为 best-effort：网络不可用 / 接口抖动时返回失败列表，不影响主流程。
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Dict, Any, List, Optional

from services.stock_data.providers import BaseProvider, _to_float
import crud.fund as crud_fund


# ============================================================
# 类型映射（东方财富 FundType -> 本项目 fs_type）
# 1=股票型 2=债券型 3=混合型
# ============================================================
# 东方财富 FundType 数字代码 -> 本项目 fs_type（1=股票 2=债券 3=混合）
_FUND_TYPE_CODE = {
    "001": 1, "005": 1, "007": 1,   # 股票型 / 指数型 / QDII(含股)
    "002": 3, "006": 3,             # 混合型 / 短期理财(归混合)
    "003": 2, "008": 2, "011": 2,   # 债券型
}

def _map_fs_type(fund_type: Optional[str]) -> Optional[int]:
    if not fund_type:
        return None
    s = str(fund_type).strip()
    if s in _FUND_TYPE_CODE:
        return _FUND_TYPE_CODE[s]
    # 兼容中文描述（历史/其他来源）
    if "股票" in s:
        return 1
    if "债券" in s:
        return 2
    if "混合" in s:
        return 3
    if "指数" in s:
        return 1
    return None


def _nav_date_to_ms(date_str: Optional[str]) -> int:
    """净值日期（YYYY-MM-DD）转为毫秒时间戳（按 15:00 收盘计）。"""
    if date_str:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=15, minute=0)
            return int(dt.timestamp() * 1000)
        except ValueError:
            pass
    return int(datetime.now().timestamp() * 1000)


class FundNavProvider(BaseProvider):
    """场外基金净值数据源（东方财富历史净值接口，权威、含官方日收益与类型）。

    注：天天基金估值接口(fundgz.1234567.com.cn)现已失效（返回 HTML 页面），
    故统一改用东财接口；基金名称由东财基金搜索接口补全。
    """

    name = "fund_eastmoney"

    def fetch_latest(self, code: str) -> Optional[Dict[str, Any]]:
        """获取单只基金最新净值信息，返回：
            {code, name, nav_date, net_worth, day_rate, cumulative, fs_type}
        或 None（抓取失败）。
        """
        info = self._fetch_lsjz(code)
        if not info or info.get("net_worth") is None:
            return None
        # 补全名称（ljsz 不含名称）
        if not info.get("name"):
            info["name"] = self._fetch_name(code)
        return info

    # -------------------- 净值（东财历史净值） --------------------
    def _fetch_lsjz(self, code: str) -> Optional[Dict[str, Any]]:
        url = (
            "https://api.fund.eastmoney.com/f10/lsjz"
            f"?fundCode={code}&pageIndex=1&pageSize=2"
        )
        try:
            text = self._http_get(url, referer="http://fundf10.eastmoney.com/")
        except Exception:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        ls = (data.get("Data") or {}).get("LSJZList") or []
        if not ls:
            return None

        def _d(x: Dict[str, Any]) -> str:
            return x.get("FSRQ") or ""

        ls_sorted = sorted(ls, key=_d, reverse=True)
        cur = ls_sorted[0]
        net = _to_float(cur.get("DWJZ"))
        if net is None:
            return None
        prev = ls_sorted[1] if len(ls_sorted) > 1 else None
        day_rate = None
        if prev:
            prev_net = _to_float(prev.get("DWJZ"))
            if prev_net:
                day_rate = round((net - prev_net) / prev_net * 100, 4)
        fund_type = (data.get("Data") or {}).get("FundType")
        return {
            "code": code,
            "name": None,  # 历史净值接口不含名称，由 _fetch_name 补全
            "nav_date": cur.get("FSRQ"),
            "net_worth": net,
            "day_rate": day_rate,
            "cumulative": _to_float(cur.get("LJJZ")),
            "fs_type": _map_fs_type(fund_type),
        }

    # -------------------- 名称（东财基金搜索） --------------------
    def _fetch_name(self, code: str) -> Optional[str]:
        url = (
            "https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx"
            f"?m=1&key={code}"
        )
        try:
            text = self._http_get(url, referer="https://fundf10.eastmoney.com/")
        except Exception:
            return None
        try:
            data = json.loads(text)
            datas = data.get("Datas") or []
            if datas:
                return datas[0].get("NAME")
        except json.JSONDecodeError:
            pass
        return None


# ============================================================
# 高层：抓取并入库
# ============================================================
def fetch_and_store(db, codes: List[str], provider: Optional[FundNavProvider] = None) -> Dict[str, Any]:
    """批量抓取基金净值并写入 FundNetValue / FundInfo。

    返回 {updated, failed, details}。网络异常 / 缺失数据计入 failed，不抛错。
    """
    provider = provider or FundNavProvider()
    nav_rows: List[Dict[str, Any]] = []
    updated = 0
    failed: List[str] = []
    details: List[Dict[str, Any]] = []

    for code in codes:
        code = (code or "").strip()
        if not code:
            continue
        try:
            info = provider.fetch_latest(code)
        except Exception as e:  # 单只失败不影响其他
            failed.append(code)
            details.append({"code": code, "error": str(e)})
            continue
        if not info or info.get("net_worth") is None:
            failed.append(code)
            details.append({"code": code, "error": "无净值数据"})
            continue

        # 更新基金基础信息（名称 / 类型），None 值不覆盖已有
        try:
            crud_fund.upsert_fund_info(db, {
                "fs_code": code,
                "fs_name": info.get("name"),
                "fs_type": info.get("fs_type"),
            })
        except Exception:
            pass

        nav_rows.append({
            "founds_id": code,
            "update_time": _nav_date_to_ms(info["nav_date"]),
            "net_worth": info["net_worth"],
            "day_rate": info.get("day_rate"),
        })
        updated += 1
        details.append({
            "code": code,
            "name": info.get("name"),
            "nav": info["net_worth"],
            "date": info["nav_date"],
            "day_rate": info.get("day_rate"),
        })
        time.sleep(0.15)  # 礼貌限速

    if nav_rows:
        try:
            crud_fund.save_fund_nav_batch(db, nav_rows)
        except Exception as e:
            details.append({"error": f"批量写入失败: {e}"})

    return {"updated": updated, "failed": failed, "details": details}


def sync_all_fund_navs(db) -> Dict[str, Any]:
    """汇总所有需要净值的基金（场外热门标的 + 用户关注的场外基金）并同步。

    返回 fetch_and_store 的结果；无待同步基金时返回空结果。
    """
    import crud.simulation as crud_sim

    codes: set = set()
    for r in crud_sim.list_hot_lists(db, active_only=True):
        if r.category == "fund" and r.market_type == "off":
            codes.add(r.code)
    for c in crud_fund.get_all_watched_fund_codes(db):
        codes.add(c)

    if not codes:
        return {"updated": 0, "failed": [], "details": [], "message": "无待同步基金"}

    return fetch_and_store(db, sorted(codes))


# 项目默认场外基金代码（与 crud.simulation._DEFAULT_HOT 中 off 类型一致）
DEFAULT_OFF_FUND_CODES = ["110011", "161725", "005827", "320007"]
