# 系统架构

## 2026-11-26 独立市场观测

首页新增独立市场观测链路：Mac使用同花顺REST全A快照及官方CLI只读历史，计算19项原值统计；严格契约通过后写本地原子快照并发布独立D1表。本地/线上共享组件，原板块与雷达评分不改动。详见[方法和运行边界](market-observation.md)。

## 2026-11-22 板块机会版本切换

板块本地评分版本为sector-score-v0.4：位置60%、四项改善40%，强度风险计算不变。已存分位/原子经离线迁移生成同版历史，完整full基座与daily-v1增量按historyBaseGeneration隔离读取和保留。相同观测时点的评分修订通过显式当前代比较切换，不改写来源时间，不允许较旧行情回退。

## 2026-11-22 首页雷达输入链路

市场研究雷达与板块是独立链路：Mac日线任务采集同花顺/中证成份及妙想资金广度，校验后向独立D1表radar_input_batches发布聚合包；Pages在读取同日价格历史后计算radar-score-v2，浏览器展示分数、涨跌家数和净流入原值。云端公开行情/宏观源与D1真实输入并行读取，源失败不复制旧日期、不重分配权重。板块Mac评分及原D1批次不受影响。

独立源代码、契约与更新边界见[雷达方法](market-radar-methodology.md)；日线采集器radar_inputs.py，发布器radar_input_service.py，安装器ops/macos/install-radar-input-service.py。


## 1. 系统边界

Finance Monitor 由四个运行边界组成：浏览器前端、Cloudflare 边缘接口与存储、本地采集评分任务、外部数据源。

```text
┌──────────────────────────────────────────────────────────────┐
│ External sources                                             │
│ Wind · Hithink · 东方财富妙想 · FRED · RSS/JSON 新闻源       │
└───────────────────────────┬──────────────────────────────────┘
                            │ credentials stay local
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ Local producer (macOS / Python)                              │
│ collect → validate → normalize → score → build payload       │
│ private state · lock · health · logs                         │
└───────────────────────────┬──────────────────────────────────┘
                            │ authenticated derived payload
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ Cloudflare Pages Functions + D1                              │
│ validate contract → store snapshot → serve latest/history    │
└───────────────────────────┬──────────────────────────────────┘
                            │ public derived JSON
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ Vue browser application                                     │
│ news · debt monitor · market dashboard · sector rotation     │
└──────────────────────────────────────────────────────────────┘
```

新闻聚合是例外：浏览器通过项目 API 适配器读取代理或公开源，不进入本地市场评分发布链路。

## 2. 前端

前端使用 Vue 3、TypeScript、Pinia、Vue Router、Vite 和 Tailwind CSS。

- `HomeView.vue` 负责首页组合。
- `MarketResearchDashboard.vue` 加载 v2 市场首页，可加载 Wind v3 真实数据观察版；Hithink v4 通过独立默认关闭开关选择。
- `SectorRotationBoard.vue` 与 `SectorRotationDetail.vue` 展示板块轮动视图。
- `DebtRiskDashboard.vue` 独立处理全球债务风险。
- `stores/news.ts` 管理新闻抓取、5 分钟刷新和深色模式。
- `features/*/model.mjs` 是浏览器侧纯模型层；`api.mjs` 负责远端契约读取和错误归类。

生产构建默认不启用验收数据。`build:acceptance` 通过独立 Vite mode 注入合成数据适配器，禁止回退到生产 API，并设置 `noindex,nofollow`。

## 3. 本地采集与评分

`tools/market_dashboard/` 是市场研究数据生产者。

1. `sources.py` 调用 Wind、FRED 和妙想适配器，保留字段、单位、身份和时间元数据。
2. `job.py` 负责调度门禁、并发锁、派生输入、评分、状态提交和发布。
3. `scoring.py` 计算 v2 的全球、A 股、风格、行业和概念分数。
4. `rotation.py` 计算 v3 的强度、机会、风险和热度状态。
5. `rotation_store.py` 保存私有派生历史，不保存供应商原始载荷。
6. `rotation_operations.py` 维护影子运行账本和发布资格证据。
7. `rotation_probe.py` 只输出白名单元数据，用于 Wind 能力、历史覆盖和调用成本验证。

生产任务由 macOS LaunchAgent 每 300 秒唤醒，实际是否采集由北京时间交易时段门禁决定。v2 当前按 15 分钟 bucket 运行；v3 仍保留四个关键窗口；Hithink v4 使用独立的 15 分钟上海交易时段门禁；私有影子服务现已启用，公开开关仍关闭。旧 Wind 分频策略不因此视为已部署，见 [数据源策略](DATA_SOURCES.md)。

## 4. Cloudflare 接口与存储

Cloudflare Pages Functions 位于 `functions/`：

| 路由 | 作用 |
|---|---|
| `POST /api/market-dashboard/publish` | 验证发布令牌和数据契约，写入 D1 |
| `GET /api/market-dashboard/latest` | 读取最新 v2 或 v3 快照 |
| `GET /api/market-dashboard/history` | 读取指定窗口的市场历史 |
| `GET /api/sector-rotation/latest` | 按行业／概念及视图读取最新板块列表 |
| `GET /api/sector-rotation/history` | 读取板块排名与评分历史 |
| `GET /api/sector-rotation/detail` | 读取单个板块的审计详情 |

`functions/_lib/market-dashboard.js` 是服务端契约和校验的权威实现。发布接口先验证完整 payload，再写主快照；v3 使用 D1 batch 同时写板块明细，避免只写入一半。

D1 迁移：

- `0001_market_dashboard.sql`：市场首页快照。
- `0002_sector_rotation.sql`：板块轮动明细、排名和查询索引。

## 5. 数据契约与版本

| 契约 | 当前值 | 状态 |
|---|---|---|
| 市场首页 schema | `market-dashboard-v2` | 生产 |
| 市场评分 | `market-score-v0.1` | 生产 |
| 概念选择 | `concept-selection-v0.1` | 生产 |
| 概念评分 | `concept-score-v0.1` | 生产 |
| 板块轮动 schema | `market-dashboard-v3` | 已有生产观察版记录 |
| 板块评分 | `sector-score-v0.2` | 观察期，未验证预测有效性 |
| 板块宇宙 | `sector-universe-v0.1` | Wind v3 保留 |
| Hithink schema / 评分 | `market-dashboard-v4` / `sector-score-v0.3` | 私有实现，未部署 |
| Hithink 宇宙 | `sector-universe-ths-v1` | 90 行业 / 390 概念 |
| Hithink 特征 / 成份 | `sector-features-ths-v1` / `sector-membership-ths-v1` | 独立版本门禁 |

任何改变对象身份、字段含义、评分算法或板块集合的不兼容修改，都必须产生新版本，并同步修改 Python 生产者、Functions 校验、D1 查询、前端模型、测试和文档。

## 6. 状态与一致性

- v2 本地成功状态位于项目根目录之外的私有 `state/market-dashboard/`。
- v3 影子状态位于 `state/market-dashboard-shadow/`，与 v2 隔离。
- 文件使用同目录临时文件、`fsync` 和原子替换；目录与文件权限分别为 0700 和 0600。
- 采集使用共享文件锁，防止 v2 和影子任务并发调用供应商。
- D1 以 `observed_at + scoring_version` 或相应板块唯一键去重。
- 失败不会覆盖最后成功快照；重复 bucket 不重新采集。

## 7. 失败与降级

- 数据缺失保持 `null`／缺失原因，不转为零。
- 身份、单位、时间或 schema 不匹配时整组失败关闭。
- 数据源失败时不自动换成另一供应商的同名字段。
- 页面可继续展示最后成功快照，但必须显示滞后。
- 测试、验收、回放和历史回填不得伪装成实时观测。

## 8. 安全边界

- Wind、妙想和发布令牌只存在于受信任的本机环境或 Cloudflare Secret。
- 浏览器只接收派生评分和必要的来源时间，不接收供应商原始响应。
- 日志和健康摘要只输出白名单字段与安全错误码。
- 发布 payload 有大小、时间、身份、单位、取值范围和版本校验。
- 生产部署、D1 迁移、功能开关和长期服务变更是独立受控操作。

## 9. 关键设计决策

- **本地生产、云端分发：** 金融供应商工具在本机运行，Cloudflare 只保存派生结果。
- **失败关闭：** 宁可显示证据不足，也不以错误数据形成完整分数。
- **版本化契约：** 生产 v2 与验收 v3 可并存，避免前后端同时切换造成中断。
- **来源不静默混用：** Wind 与妙想的板块口径不同，切换必须显式且可追踪。
- **验收隔离：** 合成界面验收与真实数据验证分开，防止测试数据进入生产。

运行操作详见 [运行手册](market-dashboard-operations.md)，当前真实状态见 [项目状态](STATUS.md)。

## 10. Hithink v4 隔离链路

`hithink_cli.py` 严格接收官方 CLI 标准化数据并按上海时区处理时间；`hithink_store.py` 保存私有 SQLite 标量，`hithink_backfill.py` / `hithink_breadth.py` 提供指数与广度历史；`rotation_v4.py` 负责独立特征和评分；`hithink_job.py` 调度实时优先、批量复用股票快照、持久化私有 payload 及健康状态。供应商股票 DuckDB 仅经官方 CLI 只读使用。当前成份回填明确标记 `current_members_backfill`；严格成份快照标记 `point_in_time_snapshot`，另保留真实可得时间，后者也不能自动证明历史预测及时性。

新增迁移 `0003_hithink_sector_rotation_v4.sql` 仅附加 manifest、chunk、sector 三张表。`POST /api/sector-rotation/v4/manifest|chunk|activate` 使用认证和独立公开授权门禁，校验每块最多 50 行、完整请求最多 131072 字节及 SHA-256 摘要；激活前校验整批数量、身份和摘要，原子激活后才可读。`GET /api/sector-rotation/v4/latest|catalog|history|detail` 只读取 active manifest 和完整五版本组合，无数据返回 `NO_SNAPSHOT`，不从 v3 拼接。公开投影排除成份列表、原始响应、私有分数容器和本地路径。

`src/features/sector-rotation-v4/` 拥有独立契约；首页开关 `VITE_HITHINK_SECTOR_V4` 默认关闭，`HithinkSectorBoard.vue` 展示三组行业榜和核心／动态概念，`/sectors/hithink` 提供搜索分页。无有效 v4 快照时保留原有 v3／v2 视图。配置 `publishEnabled=false`；公开接口的实现存在不代表已部署。私有影子服务已启用并由每 300 秒唤醒的独立 LaunchAgent 调用当前工作树，机器须保持唤醒；公开 v4 远端迁移、发布与切换仍待独立授权和自然交易日验收，见 [验证记录](verification/2026-11-17-hithink-sector-v4.md)。
