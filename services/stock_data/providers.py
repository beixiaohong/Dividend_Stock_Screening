"""多数据源 Provider 实现。

设计原则：
1. 只用标准库 urllib 发请求，不依赖 akshare / efinance，避免其接口频繁失效。
2. 每家 Provider 负责把自己独有的原始返回解析、归一化为 StockQuote / Kline。
3. 网络/解析异常统一包装成 ProviderError，由上层 client 做重试与降级。
4. 字段映射均经过真实样本验证（见 docs/stock_data_acquisition.md）。

数据源说明：
- 腾讯 gtimg（TencentProvider）：最稳定，无需 Cookie，支持批量实时行情与 K 线。
- 东方财富 push2（EastMoneyProvider）：擅长"全市场快照"与历史 K 线，偶发断连。
- 新浪 hq（SinaProvider）：备用实时行情，需带 Referer，盘前可能返回 0。
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
import urllib.parse
from typing import Optional

from .models import (
    StockQuote,
    Kline,
    Market,
    market_of,
    normalize_code,
    ProviderError,
)


def _to_float(val, default: Optional[float] = None) -> Optional[float]:
    """把字符串/数字安全转 float；空、'-'、非数字返回 default。"""
    if val is None:
        return default
    if isinstance(val, str):
        s = val.strip().replace(",", "").replace("%", "")
        if s in ("", "-", "--", "None", "nan", "NaN"):
            return default
        try:
            return float(s)
        except ValueError:
            return default
    try:
        f = float(val)
        return f
    except (ValueError, TypeError):
        return default


class BaseProvider:
    """所有数据源的基类。"""

    name: str = "base"

    def __init__(
        self,
        timeout: float = 10.0,
        max_retries: int = 2,
        user_agent: str = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    ):
        self.timeout = timeout
        self.max_retries = max_retries
        self.user_agent = user_agent

    # ------------------------------------------------------------------
    # HTTP 基础
    # ------------------------------------------------------------------
    def _http_get(self, url: str, referer: str | None = None, encoding: str = "utf-8") -> str:
        """标准库发起 GET，返回解码后的文本。

        任何网络/HTTP 异常都包装成 ProviderError 抛出。
        """
        headers = {"User-Agent": self.user_agent, "Accept": "*/*", "Connection": "keep-alive"}
        if referer:
            headers["Referer"] = referer
        req = urllib.request.Request(url, headers=headers)
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                # 先按指定编码解，失败再退回 gbk（腾讯/新浪中文接口常见）
                try:
                    return raw.decode(encoding)
                except UnicodeDecodeError:
                    return raw.decode("gbk", errors="replace")
            except Exception as e:  # 网络错误 / HTTP 错误 / 超时
                last_err = e
                if attempt < self.max_retries - 1:
                    time.sleep(0.3 * (attempt + 1))
        raise ProviderError(self.name, f"http_get failed: {last_err}", cause=last_err)

    # ------------------------------------------------------------------
    # 接口（子类实现）
    # ------------------------------------------------------------------
    def get_realtime(self, codes: list[str]) -> list[StockQuote]:
        """批量获取实时行情。默认不支持返回空列表。"""
        raise NotImplementedError

    def get_market_snapshot(self) -> list[StockQuote]:
        """获取全市场快照。默认不支持返回空列表。"""
        raise NotImplementedError

    def get_kline(self, code: str, count: int = 120, adjust: str = "qfq") -> list[Kline]:
        """获取历史 K 线。默认不支持返回空列表。"""
        raise NotImplementedError

    def health_check(self) -> bool:
        """简单健康检查：能连通即 True。"""
        try:
            self._http_get("https://qt.gtimg.cn/q=sh000001", timeout=5)
            return True
        except Exception:
            return False


# ==========================================================================
# 腾讯财经 Provider（主数据源）
# ==========================================================================

class TencentProvider(BaseProvider):
    """腾讯财经 gtimg 接口。

    实时行情：https://qt.gtimg.cn/q=sh600036,sz000001
    K 线：    https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh600036,day,,,N,qfq
    """

    name = "tencent"

    # 腾讯实时行情字段索引（已用真实样本验证）
    _F_NAME = 1
    _F_CODE = 2
    _F_PRICE = 3
    _F_PREV_CLOSE = 4
    _F_OPEN = 5
    _F_VOLUME = 6
    _F_TIMESTAMP = 30
    _F_CHANGE_AMOUNT = 31
    _F_CHANGE_PCT = 32
    _F_HIGH = 33
    _F_LOW = 34
    _F_PRICE_VOL_AMOUNT = 35   # "price/volume/amount"
    _F_TURNOVER = 38
    _F_PE = 39
    _F_AMPLITUDE = 43
    _F_CIRC_MCAP = 44          # 流通市值（亿）
    _F_TOTAL_MCAP = 45         # 总市值（亿）
    _F_PB = 46

    def _code_with_market(self, code: str) -> str:
        """带前缀代码转行情查询代码。已带 sh/sz 前缀时原样保留（避免指数被误判为深市股票）。"""
        s = (code or "").strip().lower()
        if s.startswith(("sh", "sz")):
            return s
        c = normalize_code(s)
        return f"{market_of(c).value}{c}"

    def get_realtime(self, codes: list[str]) -> list[StockQuote]:
        if not codes:
            return []
        qt_codes = [self._code_with_market(c) for c in codes]
        url = "https://qt.gtimg.cn/q=" + ",".join(qt_codes)
        text = self._http_get(url, referer="https://gu.qq.com/")
        return self._parse_realtime(text)

    def get_market_snapshot(self, universe: Optional[list[str]] = None) -> list[StockQuote]:
        """腾讯批量实时行情（按代码全集分块查询）。

        参数 universe 为带市场前缀的代码列表（如 ["sh600036","sz000001"]）。
        不传或为空则返回空，由 client 改用东财快照或缓存。
        """
        if not universe:
            return []
        out: list[StockQuote] = []
        chunk_size = 200
        for i in range(0, len(universe), chunk_size):
            chunk = universe[i : i + chunk_size]
            url = "https://qt.gtimg.cn/q=" + ",".join(chunk)
            text = self._http_get(url, referer="https://gu.qq.com/")
            out.extend(self._parse_realtime(text))
        return out

    def get_kline(self, code: str, count: int = 120, adjust: str = "qfq") -> list[Kline]:
        market_code = self._code_with_market(code)
        # klt: day=day, week=week, month=month；adjust: qfq 前复权 / hfq 后复权
        url = (
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
            f"?param={market_code},day,,,{count},{adjust}"
        )
        text = self._http_get(url, referer="https://gu.qq.com/")
        return self._parse_kline(text, code)

    # -------------------- 解析 --------------------
    def _parse_realtime(self, text: str) -> list[StockQuote]:
        quotes: list[StockQuote] = []
        # 形如 v_sh600036="1~招商银行~...";
        pattern = re.compile(r'v_([a-z]{2}\d{6})="(.*?)";', re.DOTALL)
        for m in pattern.finditer(text):
            raw_code = m.group(1)            # sh600036
            market = raw_code[:2]
            code = raw_code[2:]
            fields = m.group(2).split("~")
            if len(fields) < 47:
                continue
            # 时间戳 yyyymmddHHMMSS
            ts = None
            ts_raw = fields[self._F_TIMESTAMP]
            if ts_raw and len(ts_raw) >= 14 and ts_raw.isdigit():
                try:
                    from datetime import datetime

                    ts = datetime.strptime(ts_raw, "%Y%m%d%H%M%S")
                except ValueError:
                    ts = None

            amount = None
            seg = fields[self._F_PRICE_VOL_AMOUNT]
            if seg and "/" in seg:
                parts = seg.split("/")
                if len(parts) >= 3:
                    amount = _to_float(parts[2])  # 元

            quote = StockQuote(
                code=code,
                name=fields[self._F_NAME],
                market=market,
                price=_to_float(fields[self._F_PRICE]),
                prev_close=_to_float(fields[self._F_PREV_CLOSE]),
                open=_to_float(fields[self._F_OPEN]),
                high=_to_float(fields[self._F_HIGH]),
                low=_to_float(fields[self._F_LOW]),
                change_amount=_to_float(fields[self._F_CHANGE_AMOUNT]),
                change_pct=_to_float(fields[self._F_CHANGE_PCT]),
                volume=_to_float(fields[self._F_VOLUME]),   # 手
                amount=amount,
                amplitude=_to_float(fields[self._F_AMPLITUDE]),
                turnover_rate=_to_float(fields[self._F_TURNOVER]),
                pe=_to_float(fields[self._F_PE]),
                pb=_to_float(fields[self._F_PB]),
                total_market_cap=_to_float(fields[self._F_TOTAL_MCAP], 0.0) * 1e8 if _to_float(fields[self._F_TOTAL_MCAP]) is not None else None,
                circ_market_cap=_to_float(fields[self._F_CIRC_MCAP], 0.0) * 1e8 if _to_float(fields[self._F_CIRC_MCAP]) is not None else None,
                timestamp=ts,
                source=self.name,
            )
            quotes.append(quote)
        return quotes

    def _parse_kline(self, text: str, code: str) -> list[Kline]:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ProviderError(self.name, f"kline json decode error: {e}")
        node = data.get("data", {}).get(self._code_with_market(code), {})
        # 优先 qfqday，其次 day / 其他周期
        rows = node.get("qfqday") or node.get("day") or []
        klines: list[Kline] = []
        for row in rows:
            # [date, open, close, high, low, volume]
            if len(row) < 6:
                continue
            klines.append(
                Kline(
                    code=normalize_code(code),
                    date=row[0],
                    open=_to_float(row[1], 0.0) or 0.0,
                    close=_to_float(row[2], 0.0) or 0.0,
                    high=_to_float(row[3], 0.0) or 0.0,
                    low=_to_float(row[4], 0.0) or 0.0,
                    volume=_to_float(row[5], 0.0) or 0.0,
                    source=self.name,
                )
            )
        return klines


# ==========================================================================
# 东方财富 Provider（全市场快照 / K 线）
# ==========================================================================

class EastMoneyProvider(BaseProvider):
    """东方财富 push2 接口。

    全市场快照：https://push2.eastmoney.com/api/qt/clist/get
    单股行情：  https://push2.eastmoney.com/api/qt/stock/get
    K 线：      https://push2his.eastmoney.com/api/qt/stock/kline/get
    """

    name = "eastmoney"

    # 公开通用 ut 参数（浏览器请求常用，非私密）
    UT = "bd1d9ddb04089700cf9c27f6f7426281"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._snapshot_fields = (
            "f12,f14,f2,f3,f9,f23,f5,f6,f10,f11"
        )
        # 沪深京 A 股筛选条件
        self._fs = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"

    def _secid(self, code: str) -> str:
        """转东财 secid（沪市 1.xxxx / 深市 0.xxxx）。

        已带 sh/sz 前缀时直接按前缀决定市场，避免指数（如 sh000001 上证指数）
        被数字前缀规则误判为深市（sz000001 平安银行）。
        """
        s = (code or "").strip().lower()
        if s.startswith("sh"):
            market = "1"
        elif s.startswith("sz"):
            market = "0"
        else:
            market = "1" if market_of(s) == Market.SH else "0"
        return f"{market}.{normalize_code(s)}"

    def get_stock_universe(self) -> list[str]:
        """获取全市场 A 股代码全集（带市场前缀，如 "sh600036"）。

        用于在东财不可用时，为腾讯批量快照提供代码列表。结果会被 client 缓存到本地。
        """
        url_tpl = (
            "https://push2.eastmoney.com/api/qt/clist/get"
            "?pn={pn}&pz={pz}&ut={ut}&fs={fs}&fields=f12,f13"
        )
        page_size = 1000
        codes: list[str] = []
        pn = 1
        total_pages = 1
        while pn <= total_pages:
            url = url_tpl.format(pn=pn, pz=page_size, ut=self.UT, fs=self._fs)
            text = self._http_get(url, referer="https://quote.eastmoney.com/")
            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                raise ProviderError(self.name, f"universe json decode: {e}")
            diff = data.get("data", {}).get("diff")
            if diff is None:
                raise ProviderError(self.name, "universe empty data")
            if pn == 1:
                total = data.get("data", {}).get("total", 0)
                total_pages = max(1, (total + page_size - 1) // page_size)
            items = diff.values() if isinstance(diff, dict) else diff
            for item in items:
                code = str(item.get("f12", ""))
                mkt = str(item.get("f13", ""))  # 1=上交所 0=深交所
                if not code:
                    continue
                prefix = "sh" if mkt == "1" else "sz"
                codes.append(f"{prefix}{code}")
            pn += 1
        return codes

    # -------------------- 快照 --------------------
    def get_market_snapshot(self) -> list[StockQuote]:
        url_tpl = (
            "https://push2.eastmoney.com/api/qt/clist/get"
            "?pn={pn}&pz={pz}&ut={ut}&fs={fs}&fields={fields}&fltt=2"
        )
        page_size = 1000
        all_quotes: list[StockQuote] = []
        pn = 1
        total_pages = 1
        while pn <= total_pages:
            url = url_tpl.format(
                pn=pn, pz=page_size, ut=self.UT, fs=self._fs, fields=self._snapshot_fields
            )
            text = self._http_get(url, referer="https://quote.eastmoney.com/")
            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                raise ProviderError(self.name, f"snapshot json decode: {e}")
            diff = data.get("data", {}).get("diff")
            if diff is None:
                # 东财偶发返回空 data（接口抖动），直接抛出让上层降级
                raise ProviderError(self.name, "snapshot empty data")
            if pn == 1:
                total = data.get("data", {}).get("total", 0)
                total_pages = max(1, (total + page_size - 1) // page_size)
            for item in diff.values() if isinstance(diff, dict) else diff:
                q = self._parse_one_snapshot(item)
                if q:
                    all_quotes.append(q)
            pn += 1
        return all_quotes

    def _parse_one_snapshot(self, item: dict) -> Optional[StockQuote]:
        code = normalize_code(str(item.get("f12", "")))
        if not code:
            return None
        # 东财部分字段在无行情时为 0，保留 None 语义（PE/PB 为 0 不代表亏损）
        pe = _to_float(item.get("f9"))
        pb = _to_float(item.get("f23"))
        return StockQuote(
            code=code,
            name=str(item.get("f14", "")),
            market=market_of(code).value,
            price=_to_float(item.get("f2")),
            change_pct=_to_float(item.get("f3")),
            volume=_to_float(item.get("f5")),     # 手
            amount=_to_float(item.get("f6")),     # 元
            pe=pe if (pe not in (0, None)) else None,
            pb=pb if (pb not in (0, None)) else None,
            source=self.name,
        )

    # -------------------- 单股 --------------------
    def get_realtime(self, codes: list[str]) -> list[StockQuote]:
        quotes: list[StockQuote] = []
        for code in codes:
            q = self._get_single(code)
            if q:
                quotes.append(q)
        return quotes

    def _get_single(self, code: str) -> Optional[StockQuote]:
        secid = self._secid(code)
        fields = "f43,f44,f45,f46,f47,f48,f57,f58,f60,f116,f117,f162,f167,f171"
        url = (
            f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}"
            f"&fields={fields}&ut={self.UT}&fltt=2"
        )
        text = self._http_get(url, referer="https://quote.eastmoney.com/")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ProviderError(self.name, f"single json decode: {e}")
        d = data.get("data")
        if not d:
            return None
        return StockQuote(
            code=normalize_code(str(d.get("f57", code))),
            name=str(d.get("f58", "")),
            market=market_of(code).value,
            price=_to_float(d.get("f43")),
            prev_close=_to_float(d.get("f60")),
            open=_to_float(d.get("f46")),
            high=_to_float(d.get("f44")),
            low=_to_float(d.get("f45")),
            volume=_to_float(d.get("f47")),
            amount=_to_float(d.get("f48")),
            pe=_to_float(d.get("f162")),
            pb=_to_float(d.get("f167")),
            total_market_cap=_to_float(d.get("f116")),
            circ_market_cap=_to_float(d.get("f117")),
            change_pct=_to_float(d.get("f171")),
            source=self.name,
        )

    # -------------------- K 线 --------------------
    def get_kline(self, code: str, count: int = 120, adjust: str = "qfq") -> list[Kline]:
        secid = self._secid(code)
        fqt = "1" if adjust == "qfq" else ("2" if adjust == "hfq" else "0")
        url = (
            "https://push2his.eastmoney.com/api/qt/stock/kline/get"
            f"?secid={secid}&ut={self.UT}&klt=101&fqt={fqt}"
            f"&lmt={count}&fields1=f1,f2,f3,f4,f5,f6"
            "&fields2=f51,f52,f53,f54,f55,f56"
        )
        text = self._http_get(url, referer="https://quote.eastmoney.com/")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ProviderError(self.name, f"kline json decode: {e}")
        klines_raw = data.get("data", {}).get("klines", [])
        out: list[Kline] = []
        for line in klines_raw:
            parts = line.split(",")
            if len(parts) < 6:
                continue
            out.append(
                Kline(
                    code=normalize_code(code),
                    date=parts[0],
                    open=_to_float(parts[1], 0.0) or 0.0,
                    close=_to_float(parts[2], 0.0) or 0.0,
                    high=_to_float(parts[3], 0.0) or 0.0,
                    low=_to_float(parts[4], 0.0) or 0.0,
                    volume=_to_float(parts[5], 0.0) or 0.0,
                    source=self.name,
                )
            )
        return out


# ==========================================================================
# 新浪财经 Provider（备用实时行情）
# ==========================================================================

class SinaProvider(BaseProvider):
    """新浪财经 hq 接口。

    实时行情：https://hq.sinajs.cn/list=sh600036,sz000001
    注意：需要带 Referer，盘前可能返回 0 值。
    """

    name = "sina"

    # 新浪字段索引（逗号分隔）
    _F_NAME = 0
    _F_OPEN = 1
    _F_PREV_CLOSE = 2
    _F_PRICE = 3
    _F_HIGH = 4
    _F_LOW = 5
    _F_VOLUME = 8          # 股（需 /100 转为手）
    _F_AMOUNT = 9          # 元
    _F_CHANGE_AMOUNT = 29  # 涨跌额（部分时段可能缺失）
    _F_CHANGE_PCT = 30     # 涨跌幅（%）
    _F_DATE = 31
    _F_TIME = 32

    def _code_with_market(self, code: str) -> str:
        """带前缀代码转新浪查询代码。已带 sh/sz 前缀时原样保留。"""
        s = (code or "").strip().lower()
        if s.startswith(("sh", "sz")):
            return s
        c = normalize_code(s)
        return f"{market_of(c).value}{c}"

    def get_realtime(self, codes: list[str]) -> list[StockQuote]:
        if not codes:
            return []
        sina_codes = [self._code_with_market(c) for c in codes]
        url = "https://hq.sinajs.cn/list=" + ",".join(sina_codes)
        text = self._http_get(
            url, referer="https://finance.sina.com.cn/", encoding="gbk"
        )
        return self._parse_realtime(text)

    def _parse_realtime(self, text: str) -> list[StockQuote]:
        quotes: list[StockQuote] = []
        pattern = re.compile(r'var hq_str_([a-z]{2}\d{6})="(.*?)";', re.DOTALL)
        for m in pattern.finditer(text):
            raw_code = m.group(1)
            market = raw_code[:2]
            code = raw_code[2:]
            fields = m.group(2).split(",")
            if len(fields) < 10:
                continue
            name = fields[self._F_NAME]
            if not name:
                continue
            vol_shares = _to_float(fields[self._F_VOLUME])  # 股
            volume = (vol_shares / 100.0) if vol_shares is not None else None  # 手
            ts = None
            date_raw = fields[self._F_DATE]
            time_raw = fields[self._F_TIME]
            if date_raw and time_raw:
                try:
                    from datetime import datetime

                    ts = datetime.strptime(f"{date_raw} {time_raw}", "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    ts = None
            quotes.append(
                StockQuote(
                    code=code,
                    name=name,
                    market=market,
                    price=_to_float(fields[self._F_PRICE]),
                    prev_close=_to_float(fields[self._F_PREV_CLOSE]),
                    open=_to_float(fields[self._F_OPEN]),
                    high=_to_float(fields[self._F_HIGH]),
                    low=_to_float(fields[self._F_LOW]),
                    change_amount=_to_float(fields[self._F_CHANGE_AMOUNT]),
                    change_pct=_to_float(fields[self._F_CHANGE_PCT]),
                    volume=volume,
                    amount=_to_float(fields[self._F_AMOUNT]),
                    timestamp=ts,
                    source=self.name,
                )
            )
        return quotes
