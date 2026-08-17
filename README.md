# 股票价值分析系统

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

一个基于 FastAPI 的智能股票价值分析系统,专注于筛选**低波动率、高股息率、有成长价值**的优质股票。

---

## 📑 目录

- [功能特性](#-功能特性)
- [系统架构](#-系统架构)
- [快速开始](#-快速开始)
- [安装部署](#-安装部署)
- [使用指南](#-使用指南)
- [API文档](#-api文档)
- [数据模型](#-数据模型)
- [评分系统](#-评分系统)
- [常见问题](#-常见问题)
- [开发指南](#-开发指南)
- [更新日志](#-更新日志)

---

## ✨ 功能特性

### 核心功能

- ✅ **多用户支持** - 每个用户独立的股票关注列表
- ✅ **三数据源独立存储** - 市场数据/历史数据/分红数据分离
- ✅ **自动定时任务** - 每日自动获取数据和分析
- ✅ **智能评分系统** - 综合波动率、股息率、成长性三维度评分
- ✅ **完整字段映射** - 20+字段完整保存
- ✅ **批量数据补充** - 专业的历史数据补充工具
- ✅ **灵活导出功能** - 全局/个人CSV导出

### 技术特性

- 🚀 **高性能** - 批量处理,异步IO
- 🔒 **数据安全** - SQLite持久化存储
- 📊 **实时统计** - 字段完整性实时监控
- 🔄 **双数据源** - 自动切换,提高成功率
- 🌐 **RESTful API** - 标准化接口设计
- 📱 **自动化** - 定时任务,无需人工干预

---

## 🏗️ 系统架构

### 技术栈

```
后端框架: FastAPI
数据库: SQLite
数据源: AkShare + efinance
调度器: APScheduler
ORM: SQLAlchemy
异步处理: asyncio
```

### 数据流程

```
1. 数据获取 (15:30)
   ├─ 调用东方财富API
   ├─ 获取全市场5000+股票数据
   ├─ 完整字段映射(20+字段)
   └─ 批量保存到数据库

2. 历史数据补充 (按需)
   ├─ 优先使用efinance
   ├─ 备用akshare
   ├─ 前复权数据
   └─ 保存11个字段

3. 数据分析 (16:00)
   ├─ 获取实时市场数据
   ├─ 计算技术指标(波动率)
   ├─ 计算财务指标(ROE/增长率)
   ├─ 计算股息率
   ├─ 综合评分
   └─ 生成投资建议

4. 结果导出
   ├─ 全局导出(所有股票)
   └─ 用户导出(关注股票)
```

---

## 🚀 快速开始

### 前置要求

- Python 3.8+
- pip 包管理器

### 5分钟快速体验

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动服务
python main.py

# 3. 访问API文档
浏览器打开: http://localhost:8000/docs

# 4. 创建用户
curl -X POST "http://localhost:8000/users/create?user_id=demo&username=演示用户"

# 5. 添加关注股票
curl -X POST "http://localhost:8000/watch/add?user_id=demo&stock_codes=600036,000001,600519"

# 6. 获取市场数据
curl -X POST "http://localhost:8000/data/market/fetch?force=true"

# 7. 补充历史数据
python supplement_history.py watch --mode full

# 8. 执行分析
curl -X POST "http://localhost:8000/analyze/manual"

# 9. 导出结果
curl "http://localhost:8000/export/user?user_id=demo" --output result.csv
```

---

## 📦 安装部署

### 本地部署

```bash
# 1. 克隆项目
git clone <repository-url>
cd stock-analysis-system

# 2. 创建虚拟环境(推荐)
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# 3. 安装依赖
pip install -r requirements.txt

# 4. 启动服务
python main_enhanced.py

# 5. 访问服务
浏览器打开: http://localhost:8000
```

---

## 📖 使用指南

### 基础使用流程

#### 1. 用户管理

```bash
# 创建用户
POST /users/create?user_id=user001&username=张三
```

#### 2. 股票关注管理

```bash
# 添加关注
POST /watch/add?user_id=user001&stock_codes=600036,000001,600519

# 查看关注列表
GET /watch/list?user_id=user001

# 移除关注
DELETE /watch/remove?user_id=user001&stock_code=600036
```

#### 3. 数据获取

```bash
# 获取全市场数据
POST /data/market/fetch?force=true

# 获取单只股票历史数据
POST /data/history/fetch?stock_code=600036

# 获取分红数据
POST /data/dividend/fetch?date_str=20241115
```

#### 4. 批量补充历史数据

```bash
# 查看数据状态
python supplement_history.py report

# 补充用户关注股票
python supplement_history.py watch --mode full

# 补充单只股票
python supplement_history.py single --code 600036
```

#### 5. 数据分析

```bash
# 分析单只股票
POST /analyze/stock?stock_code=600036

# 批量分析所有关注股票
POST /analyze/manual
```

#### 6. 导出结果

```bash
# 导出全局结果
GET /export/global

# 导出用户结果
GET /export/user?user_id=user001
```

### 高级功能

#### 自动化定时任务

系统启动后会自动配置定时任务:

- **每日 15:30** - 自动获取全市场数据
- **每日 16:00** - 自动分析所有关注股票

#### 数据诊断

```bash
# 运行诊断工具
python diagnose_data.py

# 查看字段完整性、数据量等统计信息
```

---

## 📡 API文档

### 完整API列表

| 类别 | 端点 | 方法 | 说明 |
|------|------|------|------|
| **用户** | `/users/create` | POST | 创建用户 |
| **关注** | `/watch/add` | POST | 添加关注 |
| | `/watch/remove` | DELETE | 移除关注 |
| | `/watch/list` | GET | 查看关注 |
| **数据** | `/data/market/fetch` | POST | 获取市场数据 |
| | `/data/history/fetch` | POST | 获取历史数据 |
| | `/data/dividend/fetch` | POST | 获取分红数据 |
| **分析** | `/analyze/stock` | POST | 分析单只 |
| | `/analyze/manual` | POST | 批量分析 |
| **导出** | `/export/global` | GET | 全局导出 |
| | `/export/user` | GET | 用户导出 |
| **系统** | `/status` | GET | 系统状态 |

访问交互式文档: `http://localhost:8000/docs`

---

## 🗄️ 数据模型

### 核心数据表

#### 1. daily_market_data - 市场数据

包含20+字段:
- 基础: code, name, date
- 价格: latest_price, high, low, open, close_prev
- 成交: volume, amount, turnover_rate
- 估值: pe_dynamic, pb
- 其他: amplitude, change_pct等

#### 2. historical_data - 历史数据

包含11个字段:
- OHLC: open, high, low, close
- 成交: volume, amount
- 指标: amplitude, turnover_rate, change_pct

#### 3. stock_analysis_results - 分析结果

包含评分详情:
- 价格估值: latest_price, pe_ratio, pb_ratio
- 波动率: volatility_30d, volatility_60d
- 财务: roe, profit_growth, dividend_yield
- 评分: volatility_score, dividend_score, growth_score
- 结果: total_score, suggestion

---

## 🎮 模拟盘系统（纸面交易 / 投资训练）

在原有「数据获取体系 + 记账体系」之上，新增的一套**虚拟资金模拟交易系统**，用于训练投资能力。

### 功能特性

- ✅ **虚拟资金账户** — 每个用户独立账户，默认初始资金 ¥1,000,000（后台可改）
- ✅ **支持个股 + 基金** — 基金区分**场内（ETF/LOF，按市价）**与**场外（开放式，按净值申购/赎回）**
- ✅ **真实成交逻辑** — 按实时价（个股/场内）/最新净值（场外）成交，自动清算现金、加权成本、记已实现盈亏
- ✅ **实时估值** — 聚合持仓实时市值与浮动/总盈亏
- ✅ **东财式主页** — `/home` 展示热门指数/股票/ETF/基金实时行情板，每 15 秒自动刷新
- ✅ **后台可维护** — `/admin` 增删改热门标的、调整初始资金、补充默认数据

### 页面入口

| 页面 | 地址 | 说明 |
|------|------|------|
| 行情主页 | `http://localhost:8000/home` | 实时行情板（公开访问） |
| 模拟交易终端 | `http://localhost:8000/sim` | 登录后买卖、查看持仓/流水 |
| 后台管理 | `http://localhost:8000/admin` | 维护热门标的与参数 |

### 核心 API

| 类别 | 端点 | 方法 | 说明 |
|------|------|------|------|
| 账户 | `/sim/account` | GET | 获取（自动开户）模拟账户 |
| | `/sim/reset` | POST | 重置账户（清空持仓/流水） |
| 个股 | `/sim/stock/buy` `/sim/stock/sell` | POST | 模拟买入/卖出个股 |
| 基金 | `/sim/fund/buy` `/sim/fund/sell` | POST | 模拟买入/卖出基金（场内/场外） |
| 持仓 | `/sim/positions` | GET | 我的持仓（含实时估值） |
| 流水 | `/sim/trades` | GET | 交易流水 |
| 汇总 | `/sim/summary` | GET | 账户总资产+收益+持仓 |
| 行情 | `/market/home` | GET | 主页热门标的事实时行情 |
| | `/market/quote?symbol=sh600519` | GET | 单标的实时行情 |
| 后台 | `/admin/hot-lists` | GET/POST/PUT/DELETE | 热门标的维护 |
| | `/admin/settings/{key}` | GET/PUT | 系统参数（如 initial_capital） |
| | `/admin/seed` | POST | 补充默认热门标的与参数（并同步默认场外基金净值） |
| | `/admin/fund-nav/sync` | POST | 同步所有场外基金（热门+关注）最新净值 |
| 净值 | `/market/fund/{code}` | GET | 场外基金最新净值（缺失时自动补抓） |

### 数据模型（新增）

- `sim_accounts` — 模拟账户（可用资金 / 初始资金 / 总资产 / 收益）
- `sim_stock_positions` — 个股持仓（加权成本 / 实时市值 / 浮动·已实现盈亏）
- `sim_fund_positions` — 基金持仓（含 `market_type` 场内 on / 场外 off）
- `sim_trades` — 成交流水（复盘用）
- `hot_lists` — 主页热门标的（后台可维护：股票/基金/指数/ETF）
- `system_settings` — 系统参数（默认初始资金等）

### 场内 / 场外说明

- **场内基金（ETF/LOF）**：像股票一样在交易时段按实时市价买卖，份额不变。
- **场外基金（开放式）**：T 日按最新净值申购（金额→份额）、赎回（份额→金额）；无盘中实时净值，主页显示「最新净值 + 日涨幅」。
- 指数/ETF 的代码前缀特殊（如 `000001` 上证指数应为 `sh`），热门表直接存带前缀的 `symbol` 规避歧义。

### 场外基金净值数据（自动获取）

场外基金无盘中实时价，主页与模拟盘均以「最新单位净值」计价。净值由内置爬虫 `services/fund_nav.py` 自动维护：

- **数据来源**：东方财富基金历史净值接口（官方净值 + 精确日收益率 + 基金类型），基金名称由东财搜索接口补全。
- **写入表**：`db_founds_data`（净值历史，按 基金代码+日期 去重）、`db_founds_info`（名称/类型）。
- **自动同步时机**：
  1. 服务启动播种默认数据时，best-effort 抓取 4 只默认场外基金净值；
  2. 调用 `/admin/seed` 或 `/admin/fund-nav/sync` 手动补充；
  3. 每日 21:00 定时任务同步所有场外热门标的 + 用户关注的场外基金；
  4. 主页 `/market/home` 与 `/market/fund/{code}` 在缺数据时**自愈式**自动补抓一次。
- 启动首屏若网络不可用，主页场外基金暂显示 `--`，待上述任一同步后即可显示真实净值。

### 启动

```bash
pip install -r requirements.txt
python main.py
# 浏览器打开 http://localhost:8000/home
```

> 启动时会自动播种默认热门标的和初始资金参数（已存在则跳过）；如需补充，登录后台点击「补充默认热门标的」。

---

## 🎯 评分系统

### 三维度评分体系(总分100)

#### 1. 波动率评分 (0-40分)

| 30日波动率 | 评分 | 评价 |
|-----------|------|------|
| < 20% | 40分 | 极低波动 |
| 20-30% | 30分 | 低波动 |
| 30-40% | 20分 | 中等波动 |
| 40-50% | 10分 | 较高波动 |
| > 50% | 0分 | 高波动 |

#### 2. 股息率评分 (0-30分)

| 股息率 | 评分 | 评价 |
|--------|------|------|
| ≥ 5% | 30分 | 高股息 |
| ≥ 4% | 25分 | 较高股息 |
| ≥ 3% | 20分 | 中等股息 |
| ≥ 2% | 15分 | 一般股息 |
| ≥ 1% | 10分 | 低股息 |

#### 3. 成长性评分 (0-30分)

| ROE | 评分 | 评价 |
|-----|------|------|
| > 15% | 30分 | 优秀 |
| > 12% | 25分 | 良好 |
| > 10% | 20分 | 中等 |
| > 8% | 15分 | 一般 |
| > 5% | 10分 | 较差 |

### 投资建议

| 总分 | 建议 |
|------|------|
| ≥ 70分 | 强烈推荐 ⭐⭐⭐⭐⭐ |
| 60-69分 | 推荐 ⭐⭐⭐⭐ |
| 50-59分 | 可以关注 ⭐⭐⭐ |
| 40-49分 | 观望 ⭐⭐ |
| < 40分 | 不推荐 ⭐ |

---

## ❓ 常见问题

### Q1: 如何开始使用?

按照[快速开始](#-快速开始)章节的步骤操作即可。

### Q2: 数据库字段为空怎么办?

使用增强版代码 `main_enhanced.py` 并重新获取数据,字段完整性会从70%提升到95%+。

详见: [FIELD_ENHANCEMENT.md](FIELD_ENHANCEMENT.md)

### Q3: 历史数据如何补充?

使用专用补充工具:
```bash
python supplement_history.py report  # 查看状态
python supplement_history.py watch   # 补充关注股票
```

详见: [HISTORY_SUPPLEMENT_GUIDE.md](HISTORY_SUPPLEMENT_GUIDE.md)

### Q4: 数据多久更新一次?

- 市场数据: 每日15:30自动更新
- 历史数据: 按需手动更新
- 分析结果: 每日16:00自动更新

### Q5: 遇到网络错误怎么办?

运行网络诊断工具:
```bash
python network_diagnostic.py
```

详见: [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

---

## 🔧 开发指南

### 项目结构

```
stock-analysis-system/
├── main_enhanced.py              # 主程序(推荐)
├── supplement_history.py         # 历史数据补充工具
├── diagnose_data.py              # 数据诊断工具
├── requirements.txt              # 依赖列表
├── README.md                     # 本文件
├── FIELD_ENHANCEMENT.md          # 字段优化说明
├── HISTORY_SUPPLEMENT_GUIDE.md   # 历史数据补充指南
├── BUG_FIXES.md                  # Bug修复记录
├── TROUBLESHOOTING.md            # 故障排查指南
├── outputs/                      # 导出文件目录
└── stock_advanced_system.db      # SQLite数据库
```

### 添加新功能

```python
@app.post("/your/endpoint")
async def your_function(param: str):
    """你的函数说明"""
    # 你的逻辑
    return {"status": "success"}
```

---

## 📝 更新日志

### v2.3 (2024-02-11) - 字段增强版

**新增**:
- ✅ 完整字段映射(20个字段)
- ✅ 实时字段完整性统计
- ✅ 历史数据完整保存(11个字段)
- ✅ 双重字段获取保障

### v2.2 (2024-02-11) - Bug修复版

**修复**:
- ✅ CSV导出重复定义
- ✅ 文件名格式化错误
- ✅ 分红数据获取函数缺失
- ✅ 股息率/波动率计算完善

### v2.1 (2024-02-10) - 网络优化版

**新增**:
- ✅ 智能重试机制
- ✅ 网络代理禁用
- ✅ 批量保存优化

---

## 🙏 致谢

- [FastAPI](https://fastapi.tiangolo.com/)
- [AkShare](https://akshare.akfamily.xyz/)
- [efinance](https://github.com/Micro-sheep/efinance)
- [SQLAlchemy](https://www.sqlalchemy.org/)
- [APScheduler](https://apscheduler.readthedocs.io/)

---

## 📞 相关文档

- [字段优化说明](FIELD_ENHANCEMENT.md)
- [历史数据补充指南](HISTORY_SUPPLEMENT_GUIDE.md)
- [Bug修复记录](BUG_FIXES.md)
- [故障排查指南](TROUBLESHOOTING.md)
- [版本对比](COMPARISON.md)

---

**免责声明**: 本系统仅供学习研究使用,不构成任何投资建议。股市有风险,投资需谨慎。

---

Made with ❤️ for Value Investors