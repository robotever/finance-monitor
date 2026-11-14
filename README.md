# NewsMonitor

市场研究首页、全球债务风险和实时财经新闻聚合：[生产页面](https://newsmonitor.pages.dev/)。市场研究面板目前为 **v0.1 / 试运行**，三交易日灰度验收尚未完成。

## 首页功能

- 全局环境、A 股整体、六类风格、35 个 Wind 二级行业，以及“25 个核心概念 + 10 个动态热点”，统一展示强度、热度、风险、完整度、时间与贡献因素。
- 本地 Python 采集 Wind / FRED / 妙想并计算二级指标，经认证 Pages Function 发布到 D1；浏览器只读最新快照及短期历史。供应商原始响应与凭证不上传。
- 保留全球债务四条主线（美国利率、信用与久期、日本资金、欧洲主权），新闻每 5 分钟刷新，实时快讯聚合成功来源。
- 缺失不补零；证据不足、滞后、无可比历史和刷新失败均明确披露。风险红色仅表达风险分，缺失为灰色虚线，滞后为灰紫实线。

2026-11-13 的原始真实收盘基线含 43 个评分对象，整体完整度 **40%**；加入概念雷达后，v2 每次快照包含 78 个可见评分对象。完整度是有效输入权重的覆盖比例（含冷启动折扣），不是数据准确率或收益概率；缺少单位、过期数据与不可用跨资产指标会减少覆盖。低于 70% 提示证据不足，低于 50% 不给阶段结论。详见[运行手册](docs/market-dashboard-operations.md)。

## 开发与验证

技术栈：Vue 3、TypeScript、Vite、Pinia、Tailwind CSS、Cloudflare Pages Functions / D1。

```bash
npm ci
npm run dev
python3 -m unittest discover -s tools/market_dashboard/tests -v
python3 '/Users/robot_ever/Codex/Financial Knowledge Repository/scripts/regression_service_reliability.py'
PYTHONPYCACHEPREFIX=/private/tmp/newsmonitor-python-cache python3 '/Users/robot_ever/Codex/Financial Knowledge Repository/scripts/intake_health_check.py'
npm test
npm run build
```

开发地址为 [localhost:5173](http://localhost:5173)，构建输出 `dist/`。Vite 只提供现有新闻/FRED 代理；研究 API 需 Pages Functions 环境（如 `npx wrangler pages dev dist`）或本地测试中的受控 API 响应。

## 部署与运维

仓库：[robotever/newsmonitor](https://github.com/robotever/newsmonitor)。当前发布流程使用 Wrangler；GitHub 的 `main` 也连接 Pages，发布时只能选择一个触发路径，避免重复部署。必须一同保留 `functions/`、`migrations/` 与 `wrangler.toml` 中的 `MARKET_DB` 绑定。

[运行手册](docs/market-dashboard-operations.md)涵盖持久环境、证书、迁移、轮换、手工运行、诊断、回滚、停用及灰度清单。[macOS 调度说明](ops/macos/README.md)描述安装器的准备、启用和恢复行为。长期服务应指向稳定 checkout；本工作树的 Task 9 不部署、不安装或启用 LaunchAgent。

### 板块轮动影子验证（仅本地）

v3 影子任务保留全球环境、A 股整体、六类风格的强度／热度／风险；35 个行业及全部 75 个概念改为强度／机会／风险和热度状态。可见概念仍为 25 个核心与 10 个动态席位，完整的 110 个板块放在 `sectorRotation`。该区块保存归一化组件摘要、各轴完整度、排名和正式收盘上榜统计；组件权重与热度阈值统一放在 `auditDefinitions`，每行 `missing` 的整数索引对应区块的 `missingReasons`，保留全部缺失原因并控制 JSON 正文不超过 256 KiB。完整精度、嵌套组件及历史百分位保留在本地私有收盘状态中。

LaunchAgent 保持已加载及每 5 分钟检查，无需卸载、重装或改间隔。影子任务只在北京时间 09:45–09:55、11:30–11:40、14:00–14:10、15:00–15:30 运行，包含端点，不补跑错过的盘中窗口。每个行业及概念批次的所有行都必须有当日有效时间；正式收盘还要求每行来源时间不早于 15:00，15:30 后不补收盘。`--force` 不绕过这些要求。节假日需提供已确认的 `schedule.tradingDates`；默认仍按工作日近似。

```bash
# 单独运行本地影子任务；即使提供发布凭据，也不会调用生产发布接口。
python3 -m tools.market_dashboard.job --rotation-shadow --skip-rotation-publish
# 只读摘要：行数、版本、覆盖度、延迟和安全错误码；不采集、不输出明细。
python3 -m tools.market_dashboard.job --rotation-report
# 离线合成数据验证；固定关键窗口时间，不写状态、不发布。
python3 -m tools.market_dashboard.job --rotation-shadow --fixture --dry-run
```

命令使用与原任务相同的 `MARKET_DASHBOARD_STATE_ROOT`。影子快照、独立比较历史及健康摘要只写入父项目 `state/market-dashboard-shadow/`（目录 0700、文件 0600）；与 v2 共用采集锁，但不改 v2 的 `last-success.json` 或健康摘要。夹具模式必须加 `--dry-run`，避免污染真实验证状态。测试、夹具及回填的合成载荷一律禁止发布。

经本地验证后，操作者可在稳定 checkout 的父项目 `.env` 设置 `MARKET_DASHBOARD_ROTATION_SHADOW=1`。包装器在每次原 v2 调用后另跑一次本地影子任务；v2 生产更新继续运行。影子日志单独写入私有 `logs/market-dashboard-shadow/`，沿用 2 MB／三份备份的轮换策略。设置为 `0` 或移除该变量即可关闭影子运行，无需停止已加载的服务。显式传入影子命令只运行影子任务。本次代码变更不修改实际 `.env`、LaunchAgent 或生产服务。

真实 K 线响应、20／60／250 日历史、历史资金与广度以及调用额度仍未通过可行性核验；本地载荷始终标记 `releaseEligible=false`，不会解锁公开机会分或 v3 生产发布。缺少可靠同期成交额时，5／20 日资金比率保持缺失，不能用当日成交额替代；Wind 失败不会静默切换妙想。

## 数据限制

- v0.1 权重、分位和阶段阈值是研究假设，尚未历史回测，不构成投资建议。
- 默认 A 股交易日仅按工作日近似；假日与跨日比较需要经确认的交易日历。
- 本机离线、供应商额度、字段/单位变化会中断更新；保留最后成功快照，不以模拟值填补或自动混用供应商口径。
- 全球序列含日频、月频，不能视作全部盘中实时；`sourceMode` 记录选定来源，不保证该来源的每项数据均可用。
- 概念强度、热度、风险和动态席位均由 Wind 结构化行情计算；妙想仅用于发现候选线索，不参与概念评分，也不会在 Wind 失败时静默替代。
