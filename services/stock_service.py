import os
import re
import time
import json
import random
import asyncio
import datetime
import pandas as pd
import numpy as np
import requests
import efinance as ef
import akshare as ak
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from core.database import SessionLocal
from core.config import settings  # 确保这行存在
from models.stock import DailyMarketData, HistoricalData, DividendData, StockAnalysisResult, UserStockWatch
from models.holdings import UserStockHolding  # 添加这行导入
from crud.stock import save_market_data_batch, save_analysis_result

class StockDataService:
    def __init__(self):
        import os
        for key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY']:
            os.environ.pop(key, None)
        os.environ['NO_PROXY'] = '*'
        
        self.settings = settings
        self.debug_mode = os.getenv('DEBUG_MODE', 'false').lower() == 'true'
        
        # 添加缓存层
        self.financial_cache = {}  # 财务数据缓存
        self.cache_expiry = {}     # 缓存过期时间
        self.CACHE_TTL = 3600      # 缓存有效期1小时

        self.em_fields_map = {
        'f12': 'code',          # 股票代码
        'f14': 'name',          # 股票名称
        'f2': 'latest_price',   # 最新价
        'f3': 'change_pct',     # 涨跌幅
        'f9': 'pe_dynamic',     # 动态市盈率
        'f23': 'pb',            # 市净率
        'f5': 'volume',         # 成交量
        'f6': 'amount',         # 成交额
        # 可以根据需要添加更多字段映射
    }

        # 优化请求会话配置
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.proxies = {"http": None, "https": None}
        
        # 增强连接池配置
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        
        # 配置重试策略
        retry_strategy = Retry(
            total=3,  # 总重试次数
            backoff_factor=1,  # 退避因子
            status_forcelist=[429, 500, 502, 503, 504],  # 需要重试的状态码
            allowed_methods=["HEAD", "GET", "OPTIONS"]  # 允许重试的方法
        )
        
        adapter = HTTPAdapter(
            pool_connections=10,  # 连接池大小
            pool_maxsize=20,      # 最大连接数
            max_retries=retry_strategy
        )
        
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # 设置请求头
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Cache-Control": "max-age=0"
        }
        self.session.headers.update(self.headers)
        
        # 目标参数 (东方财富)
        self.target_ut = "bd1d9ddb04089700cf9c27f6f7426281"
        # ✅ 完整 Cookie，对齐浏览器实际请求（缺少这些东财会断开连接）
        # 注意：qgqp_b_id / nid18 等有效期较长，但建议每隔几周从浏览器重新复制一次
        self.target_cookies = {
            "ut": self.target_ut,
            "qgqp_b_id": "9fb8c26c0a40e0e20ffd551bb6a52cdf",
            "st_nvi": "4U97b8QAwVvKIFT5nsAGl367a",
            "nid18": "03c4e656b6d9f1dfd8b102df6f142ef1",
            "nid18_create_time": "1770771500629",
            "gviem": "4GJIS9Ainpfv_DL4nyasN4263",
            "gviem_create_time": "1770771500629",
            "quote_lt": "1",
            "st_pvi": "35819178068592",
            "st_sp": "2025-09-17 09:51:41",
            "st_inirUrl": "https://www.google.com/",
        }

        self._check_akshare_interfaces()

    def _check_akshare_interfaces(self):
        """检查akshare可用接口"""
        if self.debug_mode:
            print("🔍 检查akshare接口可用性...")
        
        # 测试常用接口
        interfaces_to_check = [
            'stock_financial_abstract_ths',
            'stock_financial_report_sina', 
            'stock_a_indicator_lg',
            'stock_a_lg_indicator',
            'stock_individual_info'
        ]
        
        available_interfaces = []
        for interface in interfaces_to_check:
            if hasattr(ak, interface):
                available_interfaces.append(interface)
                if self.debug_mode:
                    print(f"   ✓ {interface}")
            else:
                if self.debug_mode:
                    print(f"   ✗ {interface}")
        
        self.available_akshare_interfaces = available_interfaces
        if self.debug_mode:
            print(f"✅ 可用接口: {len(available_interfaces)}个")

    # =========================================================================
    # 数据类型安全转换
    # =========================================================================

    def _safe_float(self, val):
        """
        安全转换为浮点数 - 通用版
        仅做类型转换和空值/异常值处理，不含任何业务逻辑
        需要业务校验的字段（PE/PB）请使用专用方法 _safe_pe / _safe_pb
        """
        try:
            if val is None or val == '' or val == '-':
                return None
            if isinstance(val, float) and (pd.isna(val) or np.isinf(val)):
                return None
            if isinstance(val, str):
                # 处理百分比
                if '%' in val:
                    return float(val.replace('%', '').strip())
                val = val.strip().replace(',', '')
                if val.lower() in ['--', 'null', 'nan', 'none', '-']:
                    return None
            result = float(val)
            if np.isinf(result) or np.isnan(result):
                return None
            return result
        except (ValueError, TypeError) as e:
            if hasattr(self, 'debug_mode') and self.debug_mode:
                print(f"      ⚠️ 数值转换警告: '{val}' -> None ({str(e)})")
            return None

    def _safe_float_default(self, val, default: float = 0.0):
        """带默认值的安全浮点转换，None 时返回 default（用于不允许空的数值字段）"""
        result = self._safe_float(val)
        return result if result is not None else default

    def _safe_pe(self, val):
        """
        PE 专用安全转换
        - 保留负 PE 语义（亏损股）
        - 无效值（'-', null）或极端值（绝对值超过 10000）返回 None
        - None 存入数据库，区别于 0（0 会产生误判）
        """
        result = self._safe_float(val)
        if result is None:
            return None
        # 东方财富对亏损股有时返回 -999.xx 这样的标记值，过滤掉
        if result <= -10000 or result >= 10000:
            if self.debug_mode:
                print(f"      ⚠️ 检测到异常PE值: {result}，已置为 None")
            return None
        return result

    def _safe_pb(self, val):
        """
        PB 专用安全转换
        - PB < 0 通常是数据异常，返回 None
        - 超过 10000 返回 None
        """
        result = self._safe_float(val)
        if result is None:
            return None
        if result < 0 or result >= 10000:
            if self.debug_mode:
                print(f"      ⚠️ 检测到异常PB值: {result}，已置为 None")
            return None
        return result

    def _safe_int(self, val):
        """安全转换为整数 - 增强版"""
        try:
            if pd.isna(val) or val == '-' or val is None or val == '':
                return 0
            if isinstance(val, str):
                val = val.strip().replace(',', '')
                if val.lower() in ['--', 'null', 'nan', 'none']:
                    return 0
            return int(float(val))  # 先转float再转int避免精度问题
        except (ValueError, TypeError):
            return 0

    def refresh_ut(self):
        """自动刷新 ut 参数"""
        print("🔄 正在刷新 ut 参数...")
        try:
            url = "https://quote.eastmoney.com/center/gridlist.html"
            response = self.session.get(url, timeout=10, verify=False)
            if response.status_code == 200:
                print("✅ ut 参数刷新成功")
                return True
            return False
        except Exception as e:
            print("❌ 刷新 ut 失败:", e)
            return False

    # =========================================================================
    # 核心抓取逻辑
    # =========================================================================

    async def fetch_em_data_via_web_api(self, page_size: int = 100) -> pd.DataFrame:
        """增强版数据抓取 - 增加网络容错"""
        all_dfs = []
        current_page = 1
        total_pages = 999
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        
        # clist/get 是 JSONP 接口，浏览器以脚本方式加载（script标签），对应头部如下
        headers = {
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Connection": "keep-alive",
            "Referer": "https://quote.eastmoney.com/center/gridlist.html",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
            "Sec-Fetch-Dest": "script",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "same-site",
            "sec-ch-ua": '"Not(A:Brand";v="8", "Chromium";v="144", "Google Chrome";v="144"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }
        
        print(f"\n🌐 启动增强版数据抓取 (每页 {page_size} 条)")

        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        def _make_session():
            """每次创建全新 session，避免同一 TCP 连接被限速"""
            s = requests.Session()
            s.trust_env = False
            s.proxies = {"http": None, "https": None}
            s.cookies.update(self.target_cookies)
            # 注意：这里不配置自动重试，断连由外层逻辑手动处理并重建session
            adapter = HTTPAdapter(pool_connections=2, pool_maxsize=5, max_retries=0)
            s.mount("http://", adapter)
            s.mount("https://", adapter)
            return s

        session = _make_session()
        consecutive_failures = 0
        max_consecutive_failures = 5  # 提高容忍度
        # 每隔几页主动重建 session，模拟浏览器重新打开
        pages_per_session = random.randint(4, 7)
        pages_in_current_session = 0

        while current_page <= total_pages and consecutive_failures < max_consecutive_failures:
            try:
                # 主动轮换 session（模拟用户间隔操作）
                if pages_in_current_session >= pages_per_session:
                    session.close()
                    cooldown = random.uniform(30, 60)
                    print(f"   🔄 主动轮换连接，冷却 {cooldown:.0f} 秒...")
                    await asyncio.sleep(cooldown)
                    session = _make_session()
                    pages_in_current_session = 0
                    pages_per_session = random.randint(4, 7)

                print(f"   ➤ 抓取第 {current_page}/{total_pages if total_pages != 999 else '?'} 页...")
                
                # ✅ cb 和 _ 每次请求动态生成，避免被识别为爬虫
                _ts = int(time.time() * 1000)
                params = {
                    "cb": f"jQuery341015241163678647807_{_ts}",
                    "pn": str(current_page),
                    "np": "1",
                    "ut": self.target_ut,
                    "fltt": "2",
                    "invt": "2",
                    "fs": "m:0+t:6+f:!2,m:0+t:13+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:81+s:2048",
                    "fields": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f19,f20,f21,f23,f24,f25,f22,f11,f62,f111,f128,f136,f115,f148,f152",
                    "wbp2u": "|0|0|0|web",
                    "fid": "f3",
                    "po": "1",
                    "pz": str(page_size),
                    "_": str(_ts)
                }
                
                # 发送请求
                response = await asyncio.to_thread(
                    session.get, 
                    url, 
                    params=params, 
                    headers=headers, 
                    timeout=30,
                    verify=False
                )
                
                if response.status_code != 200:
                    print(f"   ⚠️ HTTP状态码: {response.status_code}")
                    consecutive_failures += 1
                    await asyncio.sleep(5)
                    continue
                
                # 解压响应：requests 自动处理 gzip/deflate/br
                # 若服务器仍强制返回 zstd，用 zstandard 库手动解压
                content_encoding = response.headers.get("Content-Encoding", "").lower()
                if "zstd" in content_encoding:
                    try:
                        import zstandard as zstd_lib
                        raw_text = zstd_lib.ZstdDecompressor().decompress(response.content).decode("utf-8")
                    except ImportError:
                        print("   ❌ 服务器返回了 zstd 压缩，请执行: pip install zstandard")
                        consecutive_failures += 1
                        await asyncio.sleep(5)
                        continue
                    except Exception as e:
                        print(f"   ⚠️ zstd 解压失败: {e}")
                        consecutive_failures += 1
                        await asyncio.sleep(5)
                        continue
                else:
                    raw_text = response.text
                json_match = re.search(r'jQuery.*?\((.*)\)', raw_text)
                if not json_match:
                    print(f"   ⚠️ 无法解析JSON响应，原始内容(前500字符): {raw_text[:500]!r}")
                    consecutive_failures += 1
                    await asyncio.sleep(5)
                    continue
                
                res_json = json.loads(json_match.group(1))
                if not res_json or not res_json.get("data"):
                    if self.refresh_ut():
                        params["ut"] = self.target_ut
                        consecutive_failures = 0  # 重置失败计数
                        continue
                    else:
                        print("   ⚠️ 无法刷新ut参数")
                        consecutive_failures += 1
                        await asyncio.sleep(10)
                        continue
                
                # 首次获取总记录数
                if current_page == 1:
                    total_records = res_json["data"]["total"]
                    total_pages = (total_records + page_size - 1) // page_size
                    print(f"   📊 全市场共 {total_records} 只股票，预计 {total_pages} 页")
                
                # 处理数据
                batch_df = pd.DataFrame(res_json["data"]["diff"])
                if not batch_df.empty:
                    all_dfs.append(batch_df)
                    consecutive_failures = 0  # 重置失败计数
                    pages_in_current_session += 1
                    print(f"   ✅ 第 {current_page} 页抓取成功 ({len(batch_df)} 条记录)")
                else:
                    print(f"   ⚠️ 第 {current_page} 页无数据")
                
                # 检查是否完成
                if current_page >= total_pages:
                    break
                    
                # 页间等待：模拟正常翻页节奏（3~8秒），session轮换时会有更长冷却
                wait_time = random.uniform(3, 8)
                print(f"   💤 等待 {wait_time:.1f} 秒...")
                await asyncio.sleep(wait_time)
                current_page += 1
                
            except requests.exceptions.ConnectionError as e:
                print(f"   ❌ 连接错误: {str(e)[:100]}")
                consecutive_failures += 1
                if consecutive_failures < max_consecutive_failures:
                    # 断连时重建 session + 较长冷却，避免继续用同一连接被拒
                    session.close()
                    wait_time = consecutive_failures * 20 + random.uniform(10, 30)
                    print(f"   🔄 重建连接，冷却 {wait_time:.0f} 秒后重试...")
                    await asyncio.sleep(wait_time)
                    session = _make_session()
                    pages_in_current_session = 0
                continue
                
            except requests.exceptions.Timeout as e:
                print(f"   ❌ 请求超时: {str(e)[:100]}")
                consecutive_failures += 1
                if consecutive_failures < max_consecutive_failures:
                    print("   💤 超时重试中...")
                    await asyncio.sleep(10)
                continue
                
            except Exception as e:
                print(f"   ❌ 第 {current_page} 页处理异常: {str(e)[:100]}")
                consecutive_failures += 1
                if consecutive_failures < max_consecutive_failures:
                    print("   💤 异常重试中...")
                    await asyncio.sleep(15)
                continue
        
        # 清理资源
        try:
            session.close()
        except Exception:
            pass
        
        # 返回结果
        if not all_dfs:
            print("❌ 所有页面抓取失败")
            return pd.DataFrame()
        
        final_df = pd.concat(all_dfs, ignore_index=True)
        
        # 应用字段映射
        if hasattr(self, 'em_fields_map'):
            final_df = final_df.rename(columns=self.em_fields_map)
        
        # 显示字段完整性统计
        print(f"\n✅ 总计获取 {len(final_df)} 条数据")
        print(f"\n📊 字段完整性统计:")
        for col in ['code', 'name', 'latest_price', 'pe_dynamic', 'pb']:
            if col in final_df.columns:
                non_null = final_df[col].notna().sum()
                pct = (non_null / len(final_df)) * 100
                print(f"   [{'✅' if pct > 90 else '⚠️'}] {col:20s}: {non_null:5d}/{len(final_df)} ({pct:5.1f}%)")
        
        return final_df


    def fetch_qq_rank_full(self) -> pd.DataFrame:
        """腾讯行情排行接口分页拉取全市场 A 股（东财/akshare 不可达时的降级源）。

        返回列与 fetch_em_data_via_web_api 对齐（code/name/latest_price/change_pct/volume/amount）。
        """
        print("\n📡 通过腾讯行情排行接口获取全量行情数据...")
        rows: list[dict] = []
        offset = 0
        count = 200
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://gu.qq.com/",
        }
        while offset < 8000:
            url = (
                "https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList"
                f"?board_code=aStock&sort_type=price&direct=down&offset={offset}&count={count}&_appver=11.16.0"
            )
            try:
                r = self.session.get(url, timeout=10, headers=headers, verify=False)
                body = r.json()
            except Exception:
                print(f"   ⚠️ 排行接口第 {offset // count + 1} 页失败，终止")
                break
            data = body.get("data") or {}
            lst = data.get("rank_list") or []
            if not lst:
                break
            for it in lst:
                code = str(it.get("code", ""))
                if len(code) == 8:  # 去掉 sh/sz 前缀
                    code = code[2:]
                rows.append({
                    "code": code,
                    "name": str(it.get("name", "")),
                    "latest_price": self._safe_float_default(it.get("zxj")),
                    "change_pct": self._safe_float_default(it.get("zdf")),
                    "volume": self._safe_float_default(it.get("volume")),
                    "amount": self._safe_float_default(it.get("turnover")),
                })
            got = data.get("total") or 0
            if offset + len(lst) >= got:
                break
            offset += len(lst)
        print(f"   ✅ 腾讯排行获取成功，共 {len(rows)} 条记录")
        return pd.DataFrame(rows)


    async def fetch_em_data_via_akshare(self) -> pd.DataFrame:
        """
        通过 akshare 获取全量A股行情（备用方案）
        akshare 底层同样是东财数据，但封装了请求细节，不需要手动维护 Cookie/Header
        字段映射到与 fetch_em_data_via_web_api 相同的列名
        """
        print("\n📡 通过 akshare 获取全量行情数据...")
        try:
            df = await asyncio.to_thread(ak.stock_zh_a_spot_em)
            if df is None or df.empty:
                print("   ❌ akshare 返回空数据")
                return pd.DataFrame()

            print(f"   ✅ akshare 获取成功，共 {len(df)} 条记录")

            # akshare 字段名 -> 内部字段名
            col_map = {
                "代码":     "code",
                "名称":     "name",
                "最新价":   "latest_price",
                "涨跌幅":   "change_pct",
                "市盈率-动态": "pe_dynamic",
                "市净率":   "pb",
                "成交量":   "volume",
                "成交额":   "amount",
            }
            df = df.rename(columns=col_map)

            # 只保留需要的列（忽略多余列）
            keep = [c for c in col_map.values() if c in df.columns]
            df = df[keep].copy()

            # 字段完整性统计
            print(f"\n📊 字段完整性统计:")
            for col in ["code", "name", "latest_price", "pe_dynamic", "pb"]:
                if col in df.columns:
                    non_null = df[col].notna().sum()
                    pct = non_null / len(df) * 100
                    print(f"   [{'✅' if pct > 90 else '⚠️'}] {col:20s}: {non_null:5d}/{len(df)} ({pct:5.1f}%)")

            return df

        except Exception as e:
            print(f"   ❌ akshare 获取失败: {e}")
            return pd.DataFrame()

    async def fetch_daily_market_data(self, force: bool = False):
        """入库逻辑整合"""
        db = SessionLocal()
        today = datetime.date.today()
        
        if not force and db.query(DailyMarketData).filter(DailyMarketData.date == today).first():
            db.close()
            return {"status": "skip", "message": "今日数据已存在"}

        # 优先使用 akshare（更稳定），失败后降级到直接请求东财接口
        df = await self.fetch_em_data_via_akshare()
        if df.empty:
            print("   ⚠️ akshare 失败，降级到直接请求东财接口...")
            df = await self.fetch_em_data_via_web_api()
        if df.empty:
            print("   ⚠️ 东财接口失败，降级到腾讯行情排行全量...")
            df = await asyncio.to_thread(self.fetch_qq_rank_full)
        if df.empty:
            db.close()
            return {"status": "error", "message": "抓取数据为空"}

        # 删除旧数据并入库
        db.query(DailyMarketData).filter(DailyMarketData.date == today).delete()
        
        batch = []
        for _, row in df.iterrows():
            m = DailyMarketData(
                date=today,
                code=str(row.get('code', '')),
                name=str(row.get('name', '')),
                latest_price=self._safe_float_default(row.get('latest_price')),
                change_pct=self._safe_float_default(row.get('change_pct')),
                # ✅ 使用专用方法：保留负PE语义，None 存库而非 0
                pe_dynamic=self._safe_pe(row.get('pe_dynamic')),
                pb=self._safe_pb(row.get('pb')),
                volume=self._safe_float_default(row.get('volume')),
                amount=self._safe_float_default(row.get('amount')),
                updated_at=datetime.datetime.now()
            )
            batch.append(m)
        
        db.bulk_save_objects(batch)
        db.commit()
        db.close()
        return {"status": "success", "count": len(batch)}
   
    async def fetch_dividend_data(self, stock_code: str = None):
        """同步分红数据 (基于Akshare)"""
        db = SessionLocal()
        try:
            # 此处示例为获取最新分红公告，实际生产环境建议定时同步全量
            df = ak.news_trade_notify_dividend_baidu(date=datetime.date.today().strftime('%Y%m%d'))
            if df.empty: return
            
            for _, row in df.iterrows():
                div = DividendData(
                    stock_code=row['股票代码'],
                    stock_name=row['股票简称'],
                    ex_dividend_date=pd.to_datetime(row['除权日']).date(),
                    dividend=row['分红'],
                    report_period=row['报告期']
                )
                db.merge(div)
            db.commit()
        except: pass
        finally: db.close()

    async def _request_with_retry(self, url, params, max_retries=3):
        """增强版重试请求包装器"""
        for i in range(max_retries):
            try:
                # 在线程中执行同步请求
                response = await asyncio.to_thread(
                    self.session.get, url, params=params, timeout=15, verify=False
                )
                if response.status_code == 200:
                    return response.json()
            except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError, requests.exceptions.RemoteDisconnected) as e:
                wait_time = (i + 1) * 3  # 增加等待时间
                if i < max_retries - 1:
                    print(f"      ⚠️ 网络连接失败，{wait_time}秒后重试... ({i+1}/{max_retries})")
                    await asyncio.sleep(wait_time)
                    continue
                raise e
            except requests.exceptions.Timeout as e:
                if i < max_retries - 1:
                    print(f"      ⚠️ 请求超时，重试中... ({i+1}/{max_retries})")
                    continue
                raise e
        return None
    
    async def fetch_historical_data(self, stock_code: str):
        """同步历史K线"""
        db = SessionLocal()
        try:
            existing_count = db.query(HistoricalData).filter(
                HistoricalData.stock_code == stock_code
            ).count()
            if existing_count >= 100:
                return True
        finally:
            db.close()

        try:
            # 随机延迟，避免并发请求被识别
            await asyncio.sleep(random.uniform(2, 6))

            market = "1" if stock_code.startswith(('6', '9', '11')) else "0"
            url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
            params = {
                "cb": f"jQuery_{int(time.time()*1000)}",
                "secid": f"{market}.{stock_code}",
                "ut": self.target_ut,
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56",
                "klt": "101", "fqt": "1", "beg": "0", "end": "20500101",
                "lmt": "120", "_": str(int(time.time() * 1000))
            }

            # 用一次性 session，不带自动重试
            def _do_request():
                s = requests.Session()
                s.trust_env = False
                s.proxies = {"http": None, "https": None}
                s.cookies.update(self.target_cookies)
                from requests.adapters import HTTPAdapter
                s.mount("http://", HTTPAdapter(max_retries=0))
                s.mount("https://", HTTPAdapter(max_retries=0))
                try:
                    headers = {
                        "Referer": "https://quote.eastmoney.com/",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                    }
                    return s.get(url, params=params, headers=headers, timeout=20, verify=False)
                finally:
                    s.close()

            response = await asyncio.to_thread(_do_request)

            if response and response.status_code == 200:
                match = re.search(r'\(({.*})\)', response.text)
                if match:
                    res = json.loads(match.group(1))
                    klines = res.get("data", {}).get("klines", [])
                    if klines:
                        db = SessionLocal()
                        try:
                            db.query(HistoricalData).filter(
                                HistoricalData.stock_code == stock_code
                            ).delete()
                            for line in klines:
                                cols = line.split(',')
                                if len(cols) >= 5:
                                    h = HistoricalData(
                                        stock_code=stock_code,
                                        date=datetime.datetime.strptime(cols[0], "%Y-%m-%d").date(),
                                        open=self._safe_float_default(cols[1]),
                                        close=self._safe_float_default(cols[2]),
                                        high=self._safe_float_default(cols[3]),
                                        low=self._safe_float_default(cols[4])
                                    )
                                    db.add(h)
                            db.commit()
                            return True
                        except Exception as e:
                            db.rollback()
                            if self.debug_mode:
                                print(f"      ⚠️ K线保存失败: {e}")
                        finally:
                            db.close()

            return True  # K线失败不阻断后续分析

        except Exception as e:
            if self.debug_mode:
                print(f"      ⚠️ K线获取异常: {str(e)[:80]}")
            return True

    def _robust_request(self, url, params, timeout=20):
        """增强版HTTP请求 - 带重试和错误处理"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.session.get(url, params=params, timeout=timeout, verify=False)
                
                # 检查响应状态
                if response.status_code == 200:
                    return response
                elif response.status_code in [429, 500, 502, 503, 504]:
                    # 服务器错误，需要重试
                    wait_time = (attempt + 1) * 2
                    if self.debug_mode:
                        print(f"      ⚠️ 服务器错误 {response.status_code}，{wait_time}秒后重试... ({attempt+1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    # 其他错误
                    if self.debug_mode:
                        print(f"      ⚠️ HTTP错误 {response.status_code}")
                    return None
                    
            except requests.exceptions.ConnectionError as e:
                wait_time = (attempt + 1) * 3
                if attempt < max_retries - 1:
                    if self.debug_mode:
                        print(f"      ⚠️ 连接错误，{wait_time}秒后重试... ({attempt+1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    if self.debug_mode:
                        print(f"      ⚠️ 连接失败: {str(e)[:50]}")
                    return None
                    
            except requests.exceptions.Timeout as e:
                if attempt < max_retries - 1:
                    if self.debug_mode:
                        print(f"      ⚠️ 请求超时，重试中... ({attempt+1}/{max_retries})")
                    continue
                else:
                    if self.debug_mode:
                        print(f"      ⚠️ 请求超时: {str(e)[:50]}")
                    return None
                    
            except Exception as e:
                if self.debug_mode:
                    print(f"      ⚠️ 请求异常: {str(e)[:50]}")
                return None
        
        return None
        
    async def _fetch_kline_local(self, stock_code: str):
        """本地数据补充方案"""
        db = SessionLocal()
        try:
            # 检查是否已有部分数据
            existing_count = db.query(HistoricalData).filter(
                HistoricalData.stock_code == stock_code
            ).count()
            
            if existing_count > 0:
                print(f"      ℹ️ 使用现有{existing_count}条K线数据")
                return True
            
            # 如果完全没有数据，生成基础数据用于分析
            market_data = db.query(DailyMarketData).filter(
                DailyMarketData.code == stock_code
            ).first()
            
            if market_data and market_data.latest_price:
                # 生成一条基础K线数据
                fake_kline = HistoricalData(
                    stock_code=stock_code,
                    date=datetime.date.today(),
                    open=market_data.latest_price,
                    close=market_data.latest_price,
                    high=market_data.latest_price * 1.02,
                    low=market_data.latest_price * 0.98
                )
                db.add(fake_kline)
                db.commit()
                print(f"      ℹ️ 生成基础K线数据用于分析")
                return True
                
        except Exception as e:
            print(f"      ⚠️ 本地数据补充失败: {str(e)[:50]}")
        finally:
            db.close()
        
        return False
    
    async def _save_kline_data(self, stock_code: str, df):
        """保存K线数据的通用方法"""
        db = SessionLocal()
        try:
            # 清理旧数据
            db.query(HistoricalData).filter(HistoricalData.stock_code == stock_code).delete()
            
            # 保存新数据
            for _, row in df.iterrows():
                h = HistoricalData(
                    stock_code=stock_code,
                    date=pd.to_datetime(row['date'] if 'date' in row else row.index).date(),
                    open=self._safe_float_default(row.get('open', 0)),
                    close=self._safe_float_default(row.get('close', 0)),
                    high=self._safe_float_default(row.get('high', 0)),
                    low=self._safe_float_default(row.get('low', 0))
                )
                db.add(h)
            
            db.commit()
        finally:
            db.close()

    async def fetch_stock_dividend_history(self, stock_code: str):
        """同步历史分红记录"""
        db = SessionLocal()
        try:
            df = await asyncio.to_thread(ak.stock_history_dividend_detail, symbol=stock_code, indicator="分红")
            if df is None or df.empty: return
            
            for _, row in df.iterrows():
                ex_date_raw = row.get('除权除息日')
                if pd.isna(ex_date_raw) or str(ex_date_raw) in ['NaT', 'nan', '']: continue
                
                ex_date = pd.to_datetime(ex_date_raw).date()
                div_val = row.get('派息(每10股派,税前)', 0)
                if not div_val: continue
                
                div = DividendData(
                    stock_code=stock_code,
                    stock_name=row.get('名称', '未知'),
                    ex_dividend_date=ex_date,
                    dividend=f"10派{div_val}",
                    report_period=str(row.get('分红年度', ''))
                )
                db.merge(div)
            db.commit()
        except Exception as e:
            print(f"   ⚠️ {stock_code} 分红抓取失败: {e}")
        finally:
            db.close()

    # =========================================================================
    # 财务指标获取
    # =========================================================================

    async def fetch_financial_metrics(self, stock_code: str):
        """获取财务指标 - 修复版"""
        # 缓存检查
        cache_key = f"financial_{stock_code}"
        if cache_key in self.financial_cache:
            if time.time() < self.cache_expiry[cache_key]:
                cached_data = self.financial_cache[cache_key]
                if self.debug_mode:
                    print(f"      ℹ️ 使用缓存财务数据: ROE={cached_data[0]:.2f}%, Growth={cached_data[1]:.2f}%")
                return cached_data
        
        roe, growth = 0.0, 0.0
        attempts = []
        success_source = "none"
        
        try:
            # 1. 首选：efinance 财务数据
            attempts.append("efinance")
            df = await asyncio.to_thread(ef.stock.get_base_info, stock_code)
            
            if df is not None and not df.empty:
                # 统一数据格式处理
                if isinstance(df, pd.DataFrame):
                    if len(df) > 0:
                        data = df.iloc[0].to_dict()
                    else:
                        data = {}
                elif isinstance(df, pd.Series):
                    data = df.to_dict()
                else:
                    data = {}
                
                # 多种字段名匹配
                roe_fields = ['净资产收益率(%)', 'ROE(%)', '净资产收益率', 'roe', 'ROE']
                growth_fields = ['净利润同比(%)', '净利润增长率(%)', '净利润同比增长', 'net_profit_growth', 'profit_growth']
                
                # 提取 ROE
                for field in roe_fields:
                    if field in data and data[field] is not None:
                        roe_val = self._safe_float_default(data[field])
                        if roe_val != 0:
                            roe = roe_val
                            break
                
                # 提取利润增长率
                for field in growth_fields:
                    if field in data and data[field] is not None:
                        growth_val = self._safe_float_default(data[field])
                        if growth_val != 0:
                            growth = growth_val
                            break
                
                if roe != 0 or growth != 0:
                    if self.debug_mode:
                        print(f"      ✓ 通过 efinance 获取财务数据: ROE={roe:.2f}%, Growth={growth:.2f}%")
                    success_source = "efinance"
                    self.financial_cache[cache_key] = (float(roe), float(growth))
                    self.cache_expiry[cache_key] = time.time() + self.CACHE_TTL
                    return float(roe), float(growth)
                    
        except Exception as e:
            if self.debug_mode:
                print(f"      ⚠️ efinance 失败: {str(e)[:50]}")
        
        try:
            # 2. 备选：akshare 财务报表
            attempts.append("akshare_financial")
            formatted_code = self._format_stock_code_for_akshare(stock_code)
            
            try:
                df_fin = await asyncio.to_thread(ak.stock_financial_abstract_ths, symbol=stock_code)
            except AttributeError:
                try:
                    df_fin = await asyncio.to_thread(ak.stock_financial_report_sina, symbol=formatted_code)
                except:
                    df_fin = None
            
            if df_fin is not None and not df_fin.empty and len(df_fin) > 0:
                data_fin = df_fin.iloc[0].to_dict()
                
                roe = self._safe_float_default(data_fin.get('净资产收益率') or 
                                    data_fin.get('ROE') or 
                                    data_fin.get('净资产收益率(%)') or 0)
                growth = self._safe_float_default(data_fin.get('净利润同比增长') or 
                                        data_fin.get('净利润增长率') or 
                                        data_fin.get('净利润同比(%)') or 0)
                
                if roe != 0 or growth != 0:
                    if self.debug_mode:
                        print(f"      ✓ 通过 akshare 获取财务数据: ROE={roe:.2f}%, Growth={growth:.2f}%")
                    success_source = "akshare_financial"
                    self.financial_cache[cache_key] = (float(roe), float(growth))
                    self.cache_expiry[cache_key] = time.time() + self.CACHE_TTL
                    return float(roe), float(growth)
                    
        except Exception as e:
            if self.debug_mode:
                print(f"      ⚠️ akshare financial 失败: {str(e)[:50]}")
        
        try:
            # 3. 再备选：akshare 主要指标
            attempts.append("akshare_indicator")
            formatted_code = self._format_stock_code_for_akshare(stock_code)
            
            df_ind = None
            indicator_functions = [
                'stock_a_indicator_lg',
                'stock_a_lg_indicator',
                'stock_individual_info',
            ]
            
            for func_name in indicator_functions:
                try:
                    if hasattr(ak, func_name):
                        df_ind = await asyncio.to_thread(getattr(ak, func_name), symbol=stock_code)
                        if df_ind is not None and not df_ind.empty:
                            break
                except:
                    continue
            
            if df_ind is not None and not df_ind.empty and len(df_ind) > 0:
                data_ind = df_ind.iloc[0].to_dict()
                
                roe_fields = ['净资产收益率(%)', 'ROE', 'roe', '净资产收益率']
                growth_fields = ['净利润同比(%)', '净利润增长率(%)', '净利润同比增长']
                
                for field in roe_fields:
                    if field in data_ind and data_ind[field] is not None:
                        roe_val = self._safe_float_default(data_ind[field])
                        if roe_val != 0:
                            roe = roe_val
                            break
                
                for field in growth_fields:
                    if field in data_ind and data_ind[field] is not None:
                        growth_val = self._safe_float_default(data_ind[field])
                        if growth_val != 0:
                            growth = growth_val
                            break
                
                if roe != 0 or growth != 0:
                    if self.debug_mode:
                        print(f"      ✓ 通过 akshare 指标获取: ROE={roe:.2f}%, Growth={growth:.2f}%")
                    success_source = "akshare_indicator"
                    self.financial_cache[cache_key] = (float(roe), float(growth))
                    self.cache_expiry[cache_key] = time.time() + self.CACHE_TTL
                    return float(roe), float(growth)
                    
        except Exception as e:
            if self.debug_mode:
                print(f"      ⚠️ akshare indicator 失败: {str(e)[:50]}")
        
        # 4. 最后备选：从市场价格数据推算
        try:
            attempts.append("market_derived")
            derived_roe, derived_growth = await self._derive_financial_from_market(stock_code)
            if derived_roe != 0 or derived_growth != 0:
                if self.debug_mode:
                    print(f"      ✓ 通过市场数据推算: ROE={derived_roe:.2f}%, Growth={derived_growth:.2f}%")
                success_source = "market_derived"
                self.financial_cache[cache_key] = (float(derived_roe), float(derived_growth))
                self.cache_expiry[cache_key] = time.time() + self.CACHE_TTL
                return float(derived_roe), float(derived_growth)
        except Exception as e:
            if self.debug_mode:
                print(f"      ⚠️ 市场数据推算失败: {str(e)[:50]}")
        
        if roe == 0 and growth == 0:
            if self.debug_mode:
                print(f"      ❌ {stock_code} 财务指标获取完全失败 (尝试了: {', '.join(attempts)})")
        
        return float(roe), float(growth)
    
    def _format_stock_code_for_akshare(self, stock_code: str) -> str:
        """格式化股票代码以适配 akshare 接口"""
        if stock_code.startswith(('6', '9')):
            return f"sh{stock_code}"
        elif stock_code.startswith(('0', '3')):
            return f"sz{stock_code}"
        return stock_code
    
    async def _derive_financial_from_market(self, stock_code: str):
        """从市场价格数据推算基础财务指标 - 增强版"""
        db = SessionLocal()
        try:
            hist_data = db.query(HistoricalData).filter(
                HistoricalData.stock_code == stock_code
            ).order_by(HistoricalData.date.desc()).limit(252).all()
            
            if len(hist_data) < 30:
                return 0.0, 0.0
            
            prices = [float(h.close) for h in reversed(hist_data)]
            if len(prices) >= 2:
                annual_growth = ((prices[-1] / prices[0]) ** (252/len(prices)) - 1) * 100
                derived_growth = max(-50, min(50, annual_growth))
            else:
                derived_growth = 0.0
            
            if stock_code.startswith('688'):
                derived_roe = max(0, min(30, abs(derived_growth) * 0.6))
            else:
                derived_roe = max(0, min(30, abs(derived_growth) * 0.8))
            
            if self.debug_mode:
                print(f"      ℹ️ 市场数据推算: ROE≈{derived_roe:.2f}%, Growth≈{derived_growth:.2f}% (基于{len(prices)}天数据)")
            
            return float(derived_roe), float(derived_growth)
            
        except Exception as e:
            if self.debug_mode:
                print(f"      ⚠️ 市场数据推算异常: {str(e)[:50]}")
            return 0.0, 0.0
        finally:
            db.close()

    def _assess_data_quality(self, roe: float, growth: float, source: str) -> float:
        """评估数据质量 (0-1)"""
        quality = 0.0
        source_weights = {
            "efinance": 1.0,
            "akshare_financial": 0.8,
            "akshare_indicator": 0.6,
            "market_derived": 0.3
        }
        quality += source_weights.get(source, 0.1)
        if -50 <= roe <= 50:
            quality += 0.3
        if -100 <= growth <= 200:
            quality += 0.3
        if roe != 0:
            quality += 0.2
        if growth != 0:
            quality += 0.2
        return min(1.0, quality)

    # =========================================================================
    # 评分体系（满分 100 分）
    #
    #  维度           分值    说明
    #  ──────────────────────────────────────────────────────────
    #  波动率          0~30   低波动优先，v30 年化波动率
    #  股息率          0~25   年化股息率
    #  成长性          0~25   ROE(0~15) + 利润增速(0~10)
    #  估值            0~20   PE(0~12) + PB(0~8)，负PE不加分
    #
    #  建议档位：≥75 强烈推荐 / ≥55 推荐 / ≥40 关注 / <40 观望
    # =========================================================================

    def _calc_volatility_score(self, v30: float) -> int:
        """波动率评分 (0-30 分)，v30 为 30 日年化波动率(%)"""
        if v30 <= 0:
            return 0
        if v30 < 20:
            return 30
        elif v30 < 30:
            return 22
        elif v30 < 40:
            return 14
        elif v30 < 55:
            return 8
        else:
            return 3

    def _calc_dividend_score(self, div_yield: float) -> int:
        """股息率评分 (0-25 分)，div_yield 为年化股息率(%)"""
        if div_yield >= 6:
            return 25
        elif div_yield >= 4:
            return 20
        elif div_yield >= 2.5:
            return 14
        elif div_yield >= 1.2:
            return 8
        else:
            return 0

    def _calc_growth_score(self, roe: float, profit_growth: float) -> int:
        """
        成长性评分 (0-25 分)
        ROE 子分 (0-15) + 利润增速子分 (0-10)
        """
        # ROE 子分
        if roe >= 20:
            roe_score = 15
        elif roe >= 15:
            roe_score = 12
        elif roe >= 10:
            roe_score = 9
        elif roe >= 6:
            roe_score = 5
        elif roe > 0:
            roe_score = 2
        else:
            roe_score = 0  # 亏损不给分

        # 利润增速子分
        if profit_growth >= 30:
            growth_sub = 10
        elif profit_growth >= 15:
            growth_sub = 8
        elif profit_growth >= 5:
            growth_sub = 5
        elif profit_growth >= 0:
            growth_sub = 2
        else:
            growth_sub = 0  # 利润下滑不给分

        return roe_score + growth_sub

    def _calc_valuation_score(self, pe: float | None, pb: float | None) -> int:
        """
        估值评分 (0-20 分)
        PE 子分 (0-12)：负PE=亏损不加分，None=无数据不加分
        PB 子分 (0-8)
        """
        pe_score = 0
        pb_score = 0

        # PE 子分
        if pe is not None and pe > 0:
            if pe < 10:
                pe_score = 12
            elif pe < 18:
                pe_score = 10
            elif pe < 28:
                pe_score = 7
            elif pe < 40:
                pe_score = 4
            elif pe < 60:
                pe_score = 2
            else:
                pe_score = 0

        # PB 子分
        if pb is not None and pb > 0:
            if pb < 1.0:
                pb_score = 8
            elif pb < 2.0:
                pb_score = 6
            elif pb < 3.5:
                pb_score = 4
            elif pb < 6.0:
                pb_score = 2
            else:
                pb_score = 0

        return pe_score + pb_score

    # =========================================================================
    # 综合分析
    # =========================================================================

    async def analyze_stock(self, stock_code: str, db: Session):
        """
        综合分析评分（满分 100 分）
        维度：波动率(30) + 股息率(25) + 成长性(25) + 估值(20)
        """
        today = datetime.date.today()
        
        # 1. 基础行情校验
        market = db.query(DailyMarketData).filter(
            DailyMarketData.code == stock_code
        ).order_by(desc(DailyMarketData.date)).first()
        
        if not market or not market.latest_price:
            print(f"   ⚠️ {stock_code} 缺失实时行情，无法分析")
            return None

        # ---------------------------------------------------------
        # 2. 波动率计算
        # ---------------------------------------------------------
        v30, v60, vol_score = 0.0, 0.0, 0
        
        hist = db.query(HistoricalData).filter(
            HistoricalData.stock_code == stock_code
        ).order_by(desc(HistoricalData.date)).limit(120).all()

        if len(hist) >= 20:
            prices = [h.close for h in reversed(hist)]
            price_series = pd.Series(prices)
            log_returns = np.log(price_series / price_series.shift(1)).dropna()
            
            if len(log_returns) >= 30:
                v30 = float(log_returns.tail(30).std() * np.sqrt(252) * 100)
                
            if len(log_returns) >= 60:
                v60 = float(log_returns.tail(60).std() * np.sqrt(252) * 100)
            
            vol_score = self._calc_volatility_score(v30)

        # ---------------------------------------------------------
        # 3. 股息率计算
        # ---------------------------------------------------------
        div_yield, div_score = 0.0, 0
        one_year_ago = today - datetime.timedelta(days=365)
        
        dividends = db.query(DividendData).filter(
            DividendData.stock_code == stock_code,
            DividendData.ex_dividend_date >= one_year_ago
        ).all()
        
        total_cash_div = 0.0
        if dividends:
            for d in dividends:
                match = re.search(r'派(\d+\.?\d*)', str(d.dividend))
                if match:
                    total_cash_div += float(match.group(1)) / 10
            
            if total_cash_div > 0 and market.latest_price:
                div_yield = (total_cash_div / market.latest_price) * 100
                if self.debug_mode:
                    print(f"      ✓ 股息率: {div_yield:.2f}% (年度分红: {total_cash_div:.2f}元/股)")
            
            div_score = self._calc_dividend_score(div_yield)

        # ---------------------------------------------------------
        # 4. 财务数据 (ROE & Growth)
        # ---------------------------------------------------------
        roe, profit_growth = await self.fetch_financial_metrics(stock_code)
        growth_score = self._calc_growth_score(roe, profit_growth)

        # ---------------------------------------------------------
        # 5. 估值评分（直接使用修复后的 None 语义）
        # ---------------------------------------------------------
        pe_val = market.pe_dynamic   # None=亏损/无数据，负数=亏损，均不加分
        pb_val = market.pb
        valuation_score = self._calc_valuation_score(pe_val, pb_val)

        # ---------------------------------------------------------
        # 6. 汇总
        # ---------------------------------------------------------
        total = int(vol_score + div_score + growth_score + valuation_score)

        if total >= 75:
            suggestion = "强烈推荐"
        elif total >= 55:
            suggestion = "推荐"
        elif total >= 40:
            suggestion = "关注"
        else:
            suggestion = "观望"

        if self.debug_mode:
            print(
                f"      📊 {stock_code} 评分: "
                f"波动率{vol_score} + 股息{div_score} + 成长{growth_score} + 估值{valuation_score} "
                f"= {total} [{suggestion}]  PE={pe_val}  PB={pb_val}"
            )

        # ---------------------------------------------------------
        # 7. 持久化
        # ---------------------------------------------------------
        analysis_res = StockAnalysisResult(
            stock_code=stock_code,
            stock_name=market.name,
            analysis_date=today,
            
            # 基础数据
            latest_price=market.latest_price,
            pe_ratio=pe_val,      # ✅ 保留 None / 负数语义
            pb_ratio=pb_val,
            
            # 波动率指标
            volatility_30d=round(v30, 2),
            volatility_60d=round(v60, 2),
            
            # 财务指标
            dividend_yield=round(div_yield, 2),
            roe=round(roe, 2),
            profit_growth=round(profit_growth, 2),
            
            # 评分
            volatility_score=int(vol_score),
            dividend_score=int(div_score),
            growth_score=int(growth_score),
            valuation_score=int(valuation_score),   # ✅ 新增估值得分字段
            total_score=total,
            
            suggestion=suggestion,
            data_source="automated_v4"
        )

        try:
            db.merge(analysis_res)
            db.commit()
            return analysis_res.total_score
        except Exception as e:
            db.rollback()
            print(f"   ❌ {stock_code} 结果入库失败: {e}")
            return None

    # =========================================================================
    # 批量分析任务
    # =========================================================================

    async def analyze_all_watched_stocks(self):
        """主分析任务循环 - 修复版"""
        db = SessionLocal()
        stats = {
            "success": 0, 
            "failed": 0, 
            "financial_failed": 0,
            "network_errors": 0,
            "data_errors": 0,
            "timeout_errors": 0,
            "total_processed": 0
        }
        semaphore = asyncio.Semaphore(self.settings.CONCURRENT_LIMIT)
        
        try:
            # 获取关注股票列表
            watched_raw = db.query(UserStockWatch.stock_code).distinct().all()
            watched_codes = list(set([w[0] for w in watched_raw if w[0] and len(w[0]) == 6 and w[0].isdigit()]))
            total = len(watched_codes)
            
            print(f"🚀 启动深度分析 (共 {total} 只)...")
            print(f"📊 配置: 并发数{self.settings.CONCURRENT_LIMIT}, 超时{self.settings.FINANCIAL_FETCH_TIMEOUT}s")
            
            # 获取高优先级股票
            priority_stocks = await self._get_priority_stocks(db, [(code,) for code in watched_codes])
            print(f"🎯 优先处理 {len(priority_stocks)} 只重要股票...")
            
            # 记录已处理的股票
            processed_stocks = set()
            tasks = []
            
            async def process_stock(stock_index, stock_code):
                if stock_code in processed_stocks:
                    return
                processed_stocks.add(stock_code)
                
                async with semaphore:
                    try:
                        stats["total_processed"] += 1
                        current_index = stats["total_processed"]
                        
                        kline_success = await self.fetch_historical_data(stock_code)
                        if not kline_success and self.debug_mode:
                            print(f"      ⚠️ K线获取失败，但仍继续分析...")
                        
                        await self.fetch_stock_dividend_history(stock_code)
                        score = await self.analyze_stock(stock_code, db)
                        
                        if score is not None:
                            stats["success"] += 1
                            success_rate = (stats["success"] / current_index) * 100 if current_index > 0 else 0
                            print(f"   ✓ {current_index}/{total} {stock_code} 分析完成 (评分: {score}, 成功率: {success_rate:.1f}%)")
                        else:
                            stats["failed"] += 1
                            success_rate = (stats["success"] / current_index) * 100 if current_index > 0 else 0
                            print(f"   ❌ {current_index}/{total} {stock_code} 分析失败 (成功率: {success_rate:.1f}%)")
                        
                    except Exception as e:
                        stats["failed"] += 1
                        stats["total_processed"] += 1
                        current_index = stats["total_processed"]
                        success_rate = (stats["success"] / current_index) * 100 if current_index > 0 else 0
                        error_msg = str(e).lower()
                        
                        if "connection" in error_msg or "disconnected" in error_msg:
                            stats["network_errors"] += 1
                        elif "timeout" in error_msg:
                            stats["timeout_errors"] += 1
                        elif "data" in error_msg or "format" in error_msg:
                            stats["data_errors"] += 1
                        else:
                            stats["financial_failed"] += 1
                        
                        print(f"   ❌ {current_index}/{total} {stock_code} 处理异常: {str(e)[:50]} (成功率: {success_rate:.1f}%)")
                    
                    # 延迟策略
                    delay = random.uniform(
                        self.settings.FETCH_DELAY_MIN, 
                        self.settings.FETCH_DELAY_MAX
                    )
                    remaining = total - current_index
                    eta_minutes = (remaining * delay) / 60 if remaining > 0 else 0
                    print(f"   💤 等待 {delay:.1f} 秒... (预计剩余: {eta_minutes:.1f}分钟)")
                    await asyncio.sleep(delay)
            
            # 处理所有股票
            all_stocks = priority_stocks + [code for code in watched_codes if code not in priority_stocks]
            for i, code in enumerate(all_stocks, 1):
                tasks.append(process_stock(i, code))
                
            await asyncio.gather(*tasks, return_exceptions=True)
            
            # 最终统计
            final_success_rate = (stats["success"] / total) * 100 if total > 0 else 0
            print(f"\n🏁 分析完成!")
            print(f"📊 总体统计:")
            print(f"   总数: {total}")
            print(f"   成功: {stats['success']} ({final_success_rate:.1f}%)")
            print(f"   失败: {stats['failed']}")
            if stats["network_errors"] > 0:
                print(f"   网络错误: {stats['network_errors']}")
            if stats["timeout_errors"] > 0:
                print(f"   超时错误: {stats['timeout_errors']}")
            if stats["data_errors"] > 0:
                print(f"   数据错误: {stats['data_errors']}")
            if stats["financial_failed"] > 0:
                print(f"   财务数据失败: {stats['financial_failed']}")
                
        except Exception as e:
            print(f"🚨 分析过程中发生严重错误: {e}")
            import traceback
            traceback.print_exc()
        finally:
            db.close()
    
    async def _check_update_needed(self, db: Session, watched_stocks):
        """检查是否需要更新"""
        latest_analysis = db.query(StockAnalysisResult).order_by(
            desc(StockAnalysisResult.analysis_date)
        ).first()
        
        if not latest_analysis:
            return True
        
        watched_codes = set([row[0] for row in watched_stocks])
        today_analyzed_codes = set([
            result.stock_code for result in 
            db.query(StockAnalysisResult.stock_code).filter(
                StockAnalysisResult.analysis_date == datetime.date.today()
            ).all()
        ])
        
        return not watched_codes.issubset(today_analyzed_codes)
    
    async def _get_priority_stocks(self, db: Session, all_stocks):
        """获取高优先级股票（持仓或高评分）"""
        holdings = db.query(UserStockHolding.stock_code).filter(
            UserStockHolding.is_active == True
        ).distinct().all()
        
        high_score = db.query(StockAnalysisResult.stock_code).filter(
            StockAnalysisResult.total_score > 80
        ).distinct().all()
        
        priority_set = set([h[0] for h in holdings] + [s[0] for s in high_score])
        all_codes = set([row[0] for row in all_stocks])
        
        return list(priority_set.intersection(all_codes))
    
    async def _check_network_health(self):
        """检查网络连接健康度"""
        try:
            response = await asyncio.to_thread(
                self.session.get, "https://httpbin.org/get", timeout=5
            )
            return response.status_code == 200
        except:
            return False
    
    async def _adaptive_delay(self, network_healthy: bool):
        """自适应延迟调整"""
        if network_healthy:
            return random.uniform(
                self.settings.FETCH_DELAY_MIN,
                self.settings.FETCH_DELAY_MAX
            )
        else:
            return random.uniform(
                self.settings.FETCH_DELAY_MAX,
                self.settings.FETCH_DELAY_MAX * 2
            )

    # =========================================================================
    # 数据维护工具
    # =========================================================================

    async def clean_abnormal_pe_data(self):
        """清理历史异常PE数据（将旧逻辑错误归零的记录修正为 None）"""
        db = SessionLocal()
        try:
            # pe_ratio=0 且股价正常 → 大概率是被旧 _safe_float 误归零的
            abnormal_records = db.query(StockAnalysisResult).filter(
                StockAnalysisResult.pe_ratio == 0.0,
                StockAnalysisResult.latest_price > 0
            ).all()
            
            if abnormal_records:
                print(f"🔍 发现 {len(abnormal_records)} 条疑似被错误归零的PE记录，已修正为 None")
                for record in abnormal_records:
                    record.pe_ratio = None
                db.commit()
                print("✅ 历史异常PE数据已清理")
            else:
                print("✅ 未发现异常PE数据")
                
        except Exception as e:
            print(f"❌ 清理异常数据失败: {e}")
        finally:
            db.close()

    async def validate_analysis_data(self):
        """验证分析数据的合理性"""
        db = SessionLocal()
        try:
            one_week_ago = datetime.date.today() - datetime.timedelta(days=7)
            
            suspicious_records = db.query(StockAnalysisResult).filter(
                StockAnalysisResult.analysis_date >= one_week_ago,
                (StockAnalysisResult.total_score > 100) |
                (StockAnalysisResult.total_score < 0)
            ).all()
            
            if suspicious_records:
                print(f"⚠️ 发现 {len(suspicious_records)} 条可疑数据:")
                for record in suspicious_records:
                    issues = []
                    if record.total_score > 100 or record.total_score < 0:
                        issues.append(f"评分异常({record.total_score})")
                    print(f"   {record.stock_code} {record.analysis_date}: {', '.join(issues)}")
            else:
                print("✅ 数据验证通过")
                
        except Exception as e:
            print(f"❌ 数据验证失败: {e}")
        finally:
            db.close()

stock_service = StockDataService()