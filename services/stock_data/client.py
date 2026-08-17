"""股票数据获取编排层（客户端）。

职责：
1. 多源有序降级：主源（腾讯）→ 备源（东财/新浪），任一可用即返回。
2. 指数退避重试：对瞬断/超时的 Provider 做有限次重试，避免偶发失败。
3. 熔断保护：每个 Provider 独立熔断器，连续失败自动熔断，冷却后试探恢复。
4. 结果缓存 + 兜底：
   - 实时行情短期缓存；当所有源都挂时，回退到"最近一次成功的缓存"。
   - 全市场快照：东财为主；东财不可用时，用"本地缓存的 A 股代码全集 + 腾讯批量"
     重建快照；若连代码全集都无法获取，则回退到最近一次成功快照文件。
5. 统一归一化：所有源输出 StockQuote，下游无需关心来源差异。
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
import urllib.parse
from typing import Optional

from .models import (
    StockQuote,
    Kline,
    normalize_code,
    ProviderError,
    AllProvidersFailed,
)
from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from .providers import (
    BaseProvider,
    TencentProvider,
    EastMoneyProvider,
    SinaProvider,
)

# 缓存目录（与代码同级的 cache/，已在 .gitignore 忽略）
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
_UNIVERSE_FILE = os.path.join(_CACHE_DIR, "astock_universe.json")
_SNAPSHOT_FILE = os.path.join(_CACHE_DIR, "snapshot_cache.json")


class StockDataClient:
    def __init__(
        self,
        providers: Optional[list[BaseProvider]] = None,
        *,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        backoff_max: float = 8.0,
        cache_ttl: float = 5.0,            # 实时行情缓存有效期（秒）
        cache_max_stale: float = 86400.0,  # 兜底缓存最大可用陈旧度（秒，默认 1 天）
        enable_cache: bool = True,
        breaker_config: Optional[CircuitBreakerConfig] = None,
        universe_file: str = _UNIVERSE_FILE,
        snapshot_file: str = _SNAPSHOT_FILE,
    ):
        # 默认顺序：腾讯（最稳）→ 东财（全市场/K线）→ 新浪（备用实时）
        self.providers = providers or [
            TencentProvider(),
            EastMoneyProvider(),
            SinaProvider(),
        ]
        self.breakers = {
            p.name: CircuitBreaker(p.name, breaker_config or CircuitBreakerConfig())
            for p in self.providers
        }
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.enable_cache = enable_cache
        self.cache_ttl = cache_ttl
        self.cache_max_stale = cache_max_stale
        self.universe_file = universe_file
        self.snapshot_file = snapshot_file
        self._cache: dict[str, tuple[float, object]] = {}

    # ------------------------------------------------------------------
    # 能力过滤
    # ------------------------------------------------------------------
    @staticmethod
    def _supports(provider: BaseProvider, method: str) -> bool:
        """判断 provider 是否真正实现了某方法（而非沿用基类抛 NotImplementedError）。

        同时兼容两种覆盖方式：类级别覆盖（真实 Provider）与实例级别绑定（测试替身）。
        """
        inst = getattr(provider, method, None)
        base = getattr(BaseProvider, method, None)
        if inst is None or base is None:
            return False
        inst_fn = getattr(inst, "__func__", inst)
        return inst_fn is not base

    # ------------------------------------------------------------------
    # 重试 + 熔断
    # ------------------------------------------------------------------
    def _call(self, provider: BaseProvider, method: str, *args, **kwargs):
        breaker = self.breakers[provider.name]
        if not breaker.allow():
            raise ProviderError(provider.name, "circuit_open")
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                result = getattr(provider, method)(*args, **kwargs)
                breaker.record_success()
                return result
            except Exception as e:  # 任何异常（含 NotImplementedError）统一包装，保证降级链不中断
                last_err = ProviderError(
                    provider.name, f"{type(e).__name__}: {e}", cause=e
                )
                breaker.record_failure()
                if attempt < self.max_retries - 1 and breaker.allow():
                    wait = min(self.backoff_max, self.backoff_base * (2 ** attempt))
                    time.sleep(wait)
                else:
                    break
        raise last_err or ProviderError(provider.name, "retry_exhausted")

    # ------------------------------------------------------------------
    # 缓存
    # ------------------------------------------------------------------
    def _cache_get(self, key: str):
        if not self.enable_cache:
            return None
        item = self._cache.get(key)
        if item is None:
            return None
        ts, value = item
        if time.time() - ts > self.cache_max_stale:
            self._cache.pop(key, None)
            return None
        return value

    def _cache_set(self, key: str, value) -> None:
        if not self.enable_cache:
            return
        self._cache[key] = (time.time(), value)

    # 代码全集 / 快照的磁盘缓存
    def _load_universe(self) -> Optional[list[str]]:
        try:
            if os.path.exists(self.universe_file):
                with open(self.universe_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            return None
        return None

    def _save_universe(self, codes: list[str]) -> None:
        try:
            os.makedirs(os.path.dirname(self.universe_file), exist_ok=True)
            with open(self.universe_file, "w", encoding="utf-8") as f:
                json.dump(codes, f)
        except Exception:
            pass

    def _load_snapshot_cache(self) -> Optional[list[StockQuote]]:
        try:
            if os.path.exists(self.snapshot_file):
                with open(self.snapshot_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                return [StockQuote(**d) for d in raw]
        except Exception:
            return None
        return None

    def _save_snapshot_cache(self, quotes: list[StockQuote]) -> None:
        try:
            os.makedirs(os.path.dirname(self.snapshot_file), exist_ok=True)
            with open(self.snapshot_file, "w", encoding="utf-8") as f:
                json.dump([q.to_dict() for q in quotes], f, ensure_ascii=False)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def get_realtime(self, codes: list[str]) -> dict[str, StockQuote]:
        """批量获取实时行情，返回 {code: StockQuote}。"""
        wanted = [normalize_code(c) for c in codes if normalize_code(c)]
        result: dict[str, StockQuote] = {}
        remaining = list(wanted)
        last_err: Exception | None = None

        for p in self.providers:
            if not remaining:
                break
            if not self.breakers[p.name].allow():
                continue
            if not self._supports(p, "get_realtime"):
                continue
            try:
                quotes = self._call(p, "get_realtime", remaining)
            except ProviderError as e:
                last_err = e
                continue
            for q in quotes:
                if q.code in remaining and q.code not in result and q.price is not None:
                    result[q.code] = q
                    remaining.remove(q.code)

        # 兜底：用缓存填补仍然缺失的代码
        for c in list(remaining):
            cached = self._cache_get(f"realtime:{c}")
            if isinstance(cached, StockQuote):
                result[c] = cached
                remaining.remove(c)

        for q in result.values():
            self._cache_set(f"realtime:{q.code}", q)

        if not result and last_err:
            raise AllProvidersFailed(f"实时行情获取失败（末源错误：{last_err}）")
        return result

    def get_realtime_one(self, code: str) -> Optional[StockQuote]:
        """获取单只股票实时行情。"""
        res = self.get_realtime([code])
        return res.get(normalize_code(code))

    def get_market_snapshot(self) -> list[StockQuote]:
        """获取全市场行情快照，多层降级：

        1) 东财 clist 全量（含代码全集，顺便更新本地缓存）；
        2) 腾讯按"本地缓存代码全集"批量查询；
        3) 回退到最近一次成功快照文件（在 cache_max_stale 内）。
        """
        last_err: Exception | None = None

        # 1) 东财全量
        for p in self.providers:
            if not self._supports(p, "get_market_snapshot"):
                continue
            if not self.breakers[p.name].allow():
                continue
            try:
                quotes = self._call(p, "get_market_snapshot")
            except ProviderError as e:
                last_err = e
                continue
            if quotes:
                universe = [f"{q.market}{q.code}" for q in quotes if q.market and q.code]
                if universe:
                    self._save_universe(universe)
                self._save_snapshot_cache(quotes)
                return quotes

        # 2) 腾讯按缓存代码全集批量
        try:
            quotes = self._snapshot_via_tencent()
            if quotes:
                self._save_snapshot_cache(quotes)
                return quotes
        except Exception as e:  # noqa: BLE001
            last_err = e

        # 3) 回退到最近一次成功快照
        stale = self._load_snapshot_cache()
        if stale:
            return stale

        raise AllProvidersFailed(f"全市场快照获取失败（末源错误：{last_err}）")

    def _snapshot_via_tencent(self) -> list[StockQuote]:
        universe = self._load_universe()
        if not universe:
            # 尝试从东财补一份代码全集
            em = next((p for p in self.providers if isinstance(p, EastMoneyProvider)), None)
            if em and self.breakers[em.name].allow():
                universe = self._call(em, "get_stock_universe")
                if universe:
                    self._save_universe(universe)
        if not universe:
            return []
        tencent = next((p for p in self.providers if isinstance(p, TencentProvider)), None)
        if tencent is None:
            return []
        return tencent.get_market_snapshot(universe)

    def get_kline(self, code: str, count: int = 120, adjust: str = "qfq") -> list[Kline]:
        """获取历史 K 线，按 providers 顺序降级。"""
        code = normalize_code(code)
        last_err: Exception | None = None
        for p in self.providers:
            if not self._supports(p, "get_kline"):
                continue
            if not self.breakers[p.name].allow():
                continue
            try:
                klines = self._call(p, "get_kline", code, count, adjust)
            except ProviderError as e:
                last_err = e
                continue
            if klines:
                return klines
        if last_err:
            raise AllProvidersFailed(f"K线获取失败（末源错误：{last_err}）")
        raise AllProvidersFailed("所有数据源均未返回K线")

    # ------------------------------------------------------------------
    # 行情搜索（腾讯 smartbox，直接返回带前缀的 symbol，便于 /market/quote）
    # ------------------------------------------------------------------
    def search(self, query: str, limit: int = 8) -> list[dict]:
        """按代码或名称搜索标的，返回 [{symbol, code, name}, ...]。

        symbol 已带市场前缀（如 sh600519 / sz000858 / sh000001），
        可直接传入 /market/quote 或主页详情。腾讯不可用时返回空列表。
        """
        q = query.strip()
        if not q:
            return []
        url = "https://smartbox.gtimg.cn/s3/?v=2&t=all&q=" + urllib.parse.quote(q)
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://stockapp.finance.qq.com/",
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except Exception:
            return []
        m = re.search(r"\((.*)\)\s*;?\s*$", raw, re.DOTALL)
        if not m:
            return []
        try:
            data = json.loads(m.group(1).strip())
        except Exception:
            return []
        # 兼容个别版本外层多包了一层数组的情况
        if (isinstance(data, list) and len(data) == 1
                and isinstance(data[0], list) and data[0]
                and isinstance(data[0][0], list)):
            data = data[0]
        out = []
        for item in data:
            if not isinstance(item, list) or len(item) < 2:
                continue
            symbol = str(item[0])
            name = str(item[1])
            out.append({
                "symbol": symbol,
                "code": normalize_code(symbol),
                "name": name,
            })
            if len(out) >= limit:
                break
        return out

    # ------------------------------------------------------------------
    # 运维 / 观测
    # ------------------------------------------------------------------
    def health(self) -> dict:
        """返回各数据源健康度（熔断器状态）。"""
        out = {}
        for p in self.providers:
            breaker = self.breakers[p.name]
            out[p.name] = {
                "circuit_state": breaker.state.value,
                "consecutive_failures": breaker._consecutive_failures,
                "reachable": breaker.allow(),
            }
        return out

    def reset_breakers(self) -> None:
        for b in self.breakers.values():
            b.force_close()

    # ------------------------------------------------------------------
    # 落库映射（惰性，不强制依赖数据库）
    # ------------------------------------------------------------------
    @staticmethod
    def to_daily_market_dict(q: StockQuote) -> dict:
        """把 StockQuote 映射为 DailyMarketData 表的字段字典，便于 upsert。"""
        return {
            "code": q.code,
            "name": q.name,
            "latest_price": q.price if q.price is not None else 0.0,
            "change_pct": q.change_pct if q.change_pct is not None else 0.0,
            "change_amount": q.change_amount if q.change_amount is not None else 0.0,
            "high": q.high,
            "low": q.low,
            "open": q.open,
            "close_prev": q.prev_close,
            "volume": q.volume if q.volume is not None else 0.0,
            "amount": q.amount if q.amount is not None else 0.0,
            "pe_dynamic": q.pe,
            "pb": q.pb,
            "total_market_cap": q.total_market_cap,
            "circulating_market_cap": q.circ_market_cap,
        }


_client: Optional[StockDataClient] = None


def get_client() -> StockDataClient:
    """进程级单例客户端。"""
    global _client
    if _client is None:
        _client = StockDataClient()
    return _client
