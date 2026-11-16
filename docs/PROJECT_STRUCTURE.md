# 项目结构

## 顶层目录

```text
newsmonitor/
├── src/                       # Vue 前端
├── functions/                 # Cloudflare Pages Functions
├── tools/market_dashboard/    # Python 采集、评分、影子运行与诊断
├── config/                    # 版本化市场配置和概念宇宙
├── migrations/                # Cloudflare D1 数据库迁移
├── ops/macos/                 # LaunchAgent 与运行包装器
├── tests/                     # Node 前端／Functions／模型测试
├── docs/                      # 当前文档、历史设计、计划和验证记录
├── public/                    # 静态资源与 Pages redirects
├── package.json               # 前端命令与依赖
├── wrangler.toml              # Cloudflare Pages / D1 绑定
└── README.md                  # 项目入口
```

运行产生的 `state/`、`logs/`、供应商原始响应和密钥不属于仓库内容。

## `src/`：浏览器应用

| 路径 | 职责 |
|---|---|
| `views/HomeView.vue` | 首页布局和主要模块组合 |
| `components/MarketResearchDashboard.vue` | 市场研究首页容器、刷新和 v2/v3 边界 |
| `components/SectorRotationBoard.vue` | 板块轮动列表、矩阵和视图切换 |
| `components/SectorRotationDetail.vue` | 板块详情与指标解释 |
| `components/ConceptRadar.vue` | 核心概念与动态热点 |
| `components/DebtRiskDashboard.vue` | 全球债务风险模块 |
| `components/News*.vue` | 新闻卡片、快讯和滚动展示 |
| `features/market-dashboard/` | 市场 API、类型、模型和验收适配器 |
| `features/debt-monitor/` | 债务监测 API、类型和模型 |
| `api/` | 新闻源清单、策略和抓取器 |
| `stores/news.ts` | 新闻状态、刷新和主题状态 |

## `functions/`：Cloudflare 边缘层

```text
functions/
├── api/market-dashboard/      # v2/v3 主快照发布、最新值、历史
├── api/sector-rotation/       # v3 板块列表、历史和详情
├── _lib/market-dashboard.js   # 服务端 schema、校验和公共投影
└── [[catchall]].js            # 其他 Pages 请求处理
```

修改生产 payload 时，必须同时检查 `_lib/market-dashboard.js`、Python 生产者、前端模型和 Functions 测试。

## `tools/market_dashboard/`：本地生产者

| 文件 | 职责 |
|---|---|
| `job.py` | 任务入口、调度、锁、采集编排、发布与状态提交 |
| `sources.py` | Wind、妙想、FRED 调用与源数据验证 |
| `scoring.py` | v2 通用评分原语和加权模型 |
| `concepts.py` | 概念宇宙、派生指标和动态席位选择 |
| `rotation.py` | v3 板块强度／机会／风险模型 |
| `rotation_store.py` | 派生价格和正式收盘历史 |
| `rotation_operations.py` | 影子运行健康、账本和发布门禁 |
| `rotation_probe.py` | 只读 Wind 能力、覆盖和成本探针 |
| `rotation_diagnostics.py` | 离线历史诊断 |
| `rotation_evaluation.py` | 强度／机会／风险的只读PIT评价、基准比较和Markdown报告 |
| `hithink_history.py` | 同花顺本地日线的分页只读适配、严格校验和覆盖审计 |
| `sector_mapping.py` | Wind／同花顺当前成份解析、重合度门禁和聚合证据采集 |
| `fixtures/` | 只用于测试的受控合成／截断样本 |
| `tests/` | Python 单元、集成和运维测试 |

## `config/`：版本化配置

- `market-dashboard.json`：评分权重、阈值、刷新窗口、来源与发布策略。
- `market-concepts.json`：75 个概念的固定宇宙、25 个核心概念和相关版本。
- `sector-overlap-candidates.json`：32 个机械同名 Wind／同花顺概念代码对。
- `sector-price-history-candidates.json`：同日成份重合度聚合证据和价格历史候选状态；不进入生产评分。
- `sector-price-history-qualifications.json`：当前成份候选的日线一致性二次门禁；当前最终通过数为 0。

配置不是普通参数文件：修改权重、阈值、身份集合或调度会改变研究含义，必须带测试、变更记录和必要的版本升级。

## `docs/`：文档层次

| 路径 | 定位 |
|---|---|
| `ARCHITECTURE.md` | 当前架构的权威说明 |
| `PROJECT_STRUCTURE.md` | 当前目录和入口说明 |
| `DATA_SOURCES.md` | 当前来源策略和切换边界 |
| `DEVELOPMENT.md` | 当前开发流程 |
| `STATUS.md` | 带日期的当前状态 |
| `market-dashboard-operations.md` | 运行和故障处理手册 |
| `verification/` | 某次验证的证据记录 |
| `superpowers/specs/` | 历史功能设计 |
| `superpowers/plans/` | 历史实施计划 |

“当前文档”应随实现更新；设计、计划和验证记录应保留历史语境，不回写成当前说明。

## 常见修改入口

| 需求 | 首先检查 | 同步检查 |
|---|---|---|
| 增删新闻源 | `src/api/news-policy.mjs`、`src/api/sources.ts` | 新闻测试、README |
| 修改市场评分 | `config/market-dashboard.json`、`tools/market_dashboard/scoring.py` | Python 测试、契约版本、CHANGELOG |
| 修改板块评分 | `tools/market_dashboard/rotation.py`、`config/market-dashboard.json` | store、Functions、前端模型、完整测试 |
| 调整行业／概念集合 | `tools/market_dashboard/sources.py`、`config/market-concepts.json` | 宇宙版本、Functions 常量、迁移与测试 |
| 增加 API 字段 | Python payload、Functions `_lib` | D1、前端类型／模型、API 测试 |
| 修改调度 | `config/market-dashboard.json`、`tools/market_dashboard/job.py`、`ops/macos/` | 运维测试、运行手册、成本估算 |
| 修改生产部署 | `wrangler.toml`、Functions、migrations | Cloudflare 绑定、回滚和验收记录 |
| 修改验收页面 | `acceptance*.mjs`、Dashboard | acceptance 测试、`noindex` 和隔离检查 |
| 修改离线历史数据 | `tools/market_dashboard/hithink_history.py`、`docs/DATA_SOURCES.md` | 复权口径、身份映射、适配器测试和授权边界 |
| 修改跨源板块映射 | `config/sector-overlap-candidates.json`、`tools/market_dashboard/sector_mapping.py` | 同日成份证据、门槛版本、差异样本和生产隔离 |
