# Finance Monitor

Finance Monitor 是一个面向个人研究流程的金融市场首页，整合实时财经新闻、全球债务风险、A 股市场状态、行业／概念雷达和板块轮动研究。

- 生产页面：[Finance Monitor](https://newsmonitor.pages.dev/)
- 代码仓库：[robotever/finance-monitor](https://github.com/robotever/finance-monitor)
- 首页：全球联动图表、财经快讯与市场研究雷达
- 板块研究：同花顺行业/概念评分、历史轮动与成分股；Mac采集计算，Cloudflare D1发布派生结果

> 本项目提供研究辅助信息，不构成投资建议。评分、阈值和权重仍是待回测的研究假设。

## 主要能力

- 聚合 11 个中外财经新闻源，每个来源最多展示 10 条，前端每 5 分钟刷新。
- 展示全球环境、A 股整体、六类市场风格和 35 个 Wind 二级行业的二级评分。
- 展示 25 个核心概念和 10 个动态热点概念。
- 提供全球债务风险监测，包括美国利率、信用与久期、日本资金和欧洲主权风险。
- 板块轮动 v3 为 35 个行业和 75 个概念计算强度、机会、风险、热度状态、排名与历史上榜信息。
- 缺失数据不补零；滞后、证据不足、无比较历史和数据源异常均显式披露。

## 当前状态

以下为2026-11-15的早期记录；当前上线信息以[改名迁移记录](docs/verification/2026-11-21-finance-monitor-rename.md)和[首页运维](docs/home-terminal-operations.md)为准：

- 生产页面继续使用 v2；概念雷达已进入生产。
- v3 界面已在独立验收页面通过桌面端和移动端技术检查，但页面使用合成测试数据。
- Wind 全量只读验证已覆盖 35 个行业和 75 个概念；上一交易日截面完整，110 个板块全部具备至少 20 个收盘历史，108 个具备至少 60 个，107 个具备至少 250 个。
- 妙想已实测返回代表性板块的涨跌、成交、换手、资金和涨跌家数；全量映射、批量能力和盘中时效仍待交易时间验证。
- 计划采用 15 分钟盘中刷新，并为 Wind／妙想切换保留明确的数据源边界；该策略尚未部署。

完整状态和未决事项见 [项目状态](docs/STATUS.md)。

## 技术架构

```text
Wind / 妙想 / FRED / 新闻源
             │
             ▼
macOS 本地采集与评分（Python）
             │ 只发布派生结果
             ▼
Cloudflare Pages Functions ── D1
             │
             ▼
Vue 3 / TypeScript 前端
```

浏览器不会持有供应商密钥；供应商原始响应不发布到 Cloudflare。详细说明见 [系统架构](docs/ARCHITECTURE.md) 和 [数据源策略](docs/DATA_SOURCES.md)。

## 快速开始

要求：Node.js、npm、Python 3。访问真实市场数据还需要本机已配置相应供应商凭据。

```bash
npm ci
npm run dev
```

开发地址默认为 [localhost:5173](http://localhost:5173)。Vite 只代理现有新闻／FRED 请求；研究 API 需要 Pages Functions 环境或测试中的受控响应。

完整验证：

```bash
python3 -m unittest discover -s tools/market_dashboard/tests -v
npm test
npm run build
```

验收模式使用隔离的合成数据：

```bash
npm run build:acceptance
npm run preview
```

## 文档导航

| 文档 | 用途 |
|---|---|
| [项目状态](docs/STATUS.md) | 生产、验收、影子、数据验证和下一步 |
| [系统架构](docs/ARCHITECTURE.md) | 组件边界、数据流、存储、契约与安全 |
| [项目结构](docs/PROJECT_STRUCTURE.md) | 目录职责和常见修改入口 |
| [数据源策略](docs/DATA_SOURCES.md) | Wind、妙想、同花顺离线库、FRED、新闻来源及切换原则 |
| [开发规范](docs/DEVELOPMENT.md) | 本地开发、测试、分支、提交和发布流程 |
| [运行手册](docs/market-dashboard-operations.md) | 调度、诊断、密钥、回滚和服务管理 |
| [板块评分评价](docs/sector-score-evaluation.md) | 强度／机会／风险的PIT检验、基准和解释规则 |
| [macOS 服务](ops/macos/README.md) | LaunchAgent 安装、启用、停用和恢复 |
| [变更记录](CHANGELOG.md) | 重要功能与工程变化 |
| [贡献说明](CONTRIBUTING.md) | 修改项目时的最短入口 |

设计与实施过程保存在 `docs/superpowers/`；实测证据和验收记录保存在 `docs/verification/`。它们是历史证据，不代替上述当前文档。

## 部署边界

生产使用 Cloudflare Pages、Pages Functions 和 D1。发布必须保留 `functions/`、`migrations/` 以及 `wrangler.toml` 中的 `MARKET_DB` 绑定。GitHub 自动构建与 Wrangler 手工部署不能同时触发同一次发布。

长期本地任务必须指向稳定 checkout，不应指向临时 Codex worktree。任何 D1 迁移、生产发布、功能开关切换或 LaunchAgent 变更都需要单独验证和明确批准。

## 数据与安全原则

- 不提交或输出 API Key、发布令牌和供应商授权信息。
- 不把测试数据、回放数据或回填结果标记为实时市场观测。
- 不在没有显式来源状态的情况下静默混合 Wind 与妙想口径。
- 评分版本、数据契约和板块宇宙均需版本化；不兼容变更必须同步迁移、测试和文档。
- 数据源失败时保留最后一次成功快照并显示滞后，不生成看似正常的替代值。
