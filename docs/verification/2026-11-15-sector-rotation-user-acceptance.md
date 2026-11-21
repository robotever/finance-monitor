# 板块轮动临时验收记录

日期：2026-11-15。结论：本地与已获明确授权的 Cloudflare preview 桌面/手机响应式 QA 通过，可进入用户界面评审；用户本人尚未验收。正式域名仍为普通 v2 页面。

范围：acceptance 前端测试构建的本地检查及线上 preview 验证。全部评分、排名、覆盖率、来源时间和历史均为确定性合成测试数据，不代表真实市场信号。35 个测试行业、75 个测试概念与 2026-10-26 至 2026-11-13 的15个交易日仅用于检查信息结构和交互。详情注明“实际可得15个正式收盘日 · 最多60日”，并未补造60日历史；涨跌缺失显示为 —。详情中的 `Wind` 是现有来源契约枚举，不代表这些测试数值来自 Wind。

## 浏览器执行前检查单

以下检查单在浏览器执行前以“待执行”记录，执行后更新结果。浏览器为本机 Chrome，经 Playwright CLI 操作；手机项使用响应式视口模拟，不代表实机 Safari/Android 已验收。

| 检查 | 桌面 1440×900 | 手机 390×844 |
| --- | --- | --- |
| 页面与详情持续显示测试环境横幅 | 通过 | 通过 |
| 页面无横向溢出 | 1440 / 1440 px | 390 / 390 px |
| 行业/概念 × 潜在轮动/主线确认/风险升温 × 强度/机会，共12组合 | 12/12 通过 | 12/12 通过 |
| 历史矩阵仅内部横向滚动 | 通过；2390 / 1082 px | 通过；2390 / 360 px |
| 当前榜单与历史单元格详情打开、关闭与对应日期 | 3/3 通过 | 3/3 通过 |
| Tab/方向键/Home/End、详情焦点约束与 Esc 返回 | 通过 | 通过 |
| 刷新研究数据、整页刷新与直接链接 | 通过，见下文边界 | 通过，见下文边界 |
| 仅放行 loopback 静态资源；市场两类 API 请求为0 | 通过 | 通过 |
| 故意破坏本地 fixture：可见错误、保留横幅、无网络回退 | 通过 | 通过 |

两种视口均实际点击了12种组合。行业的潜在轮动、主线确认、风险升温分别显示12、13、10项；概念分别显示24、26、25项。每次切换断言选择状态、矩阵轴名称、15个日期列和10个名次行，并检查页面没有横向溢出。

矩阵以方向键触发横向滚动，再滚动至最右侧，桌面最终 `scrollLeft=1308`、手机 `2030`；页面宽度保持不变。两种视口均打开行业、概念当前榜单以及历史单元格详情。历史详情对应2026-10-26机会榜第1名；15日轨迹、关闭按钮、焦点约束、Escape 返回触发元素均通过。详情滚动至顶部和底部时，横幅均完整位于弹窗内且未被遮挡；页面滚动到矩阵时，横幅固定于视口顶部且未被遮挡。

页面内“刷新研究数据”和改变视口保留“行业 / 主线确认 / 机会”选择。整页刷新恢复默认“概念 / 潜在轮动 / 强度”；直接打开 `/?acceptance-review=1#rotation-title` 后保留测试标签且所有控件可操作。本轮范围不要求整页刷新保留筛选选择，也未实现筛选状态 URL 持久化；直接链接指现有首页与锚点，不包含不存在的子路由。

## 隔离与失败证据

只启动 `vite preview --host 127.0.0.1 --port 4174 --strictPort` 静态服务器，未启动 Functions、D1、provider collector 或 shadow 服务。浏览器在导航前设置拦截：仅放行同源首页、`/assets/` 与 favicon，其他请求在浏览器发送前中止。主检查记录240次请求尝试：48次为本地静态资源，192次被拦截；补充截图检查记录60次：12次本地静态资源，48次被拦截。两轮 `/api/market-dashboard` 和 `/api/sector-rotation` 请求尝试均为 **0**，放行的非静态请求为 **0**，未捕获的页面 JavaScript 异常为 **0**。

同页新闻、债务模块和外部字体仍会尝试加载，被本轮拦截器全部阻断；它们显示的 `Failed to fetch` 或离线错误是预期隔离结果，不作为这些模块已验收的证据。字体使用本机回退字体。本节证明本地受控浏览器的隔离；后续线上验证及其请求拦截边界单独记录如下。

故障检查在浏览器路由中将本地 fixture JS 响应替换为返回 `{schemaVersion: 'deliberately-malformed'}` 的模块，不修改源文件或构建文件。两种视口均显示“研究数据暂不可用 / 快照格式无效”、隐藏无效榜单并保留测试横幅；点击“重新读取”仍在本地失败，没有回退真实接口。

## 已授权的 Cloudflare preview 与线上验证

用户在本地 QA 后明确批准一次 preview 分支部署；部署由控制端完成，本轮仅验证和记录，没有重复部署。用户验收入口：[临时验收页面](https://sector-acceptance-20261115.newsmonitor.pages.dev/)；固定 deployment 地址：[e420761d preview](https://e420761d.newsmonitor.pages.dev/)。两个地址均为测试环境，不代表测试版已正式上线。

| 项目 | 已记录事实 |
| --- | --- |
| Cloudflare deployment ID | `e420761d-8a73-4824-a125-8393501789b1` |
| Environment / branch | `Preview` / `sector-acceptance-20261115` |
| Source commit | `1211b32`，验收实现基线仍为 `17944a5` |
| 部署时间精度 | 控制端只读 deployment list 查询时显示 `1 minute ago`；CLI 未提供精确创建时间，故不推造 UTC 创建时间 |
| 浏览器验证时间 | 2026-11-15 05:19:16.691–05:19:33.940 UTC；`verifiedAt=2026-11-15T05:19:33.940Z` |
| 部署终端事实（控制端记录） | Wrangler `4.162.0`：`Uploaded 5 files (2 already uploaded)`，随后 `Uploading _redirects`、`Uploading Functions bundle`、部署完成；原始终端输出未保存为日志 |
| 发布边界（控制端记录） | 未运行 D1 migration、未设置 feature flag、未改变 production alias；本次验证未调用 publish/provider，也未修改线上状态 |

**部署包含既有 Cloudflare Pages Functions bundle，不能描述为“只上传纯静态 bundle”或“没有部署 Functions”。** 浏览器证据验证的是验收前端使用静态 fixture transport，没有请求市场/轮动 API；不以此推断 Cloudflare 服务端没有运行任何 Functions。仓库保留 catchall Functions 与新闻/债务代理，普通用户浏览完整首页时其他模块仍可能调用这些代理。

线上验证使用本机 Chrome/Playwright，桌面 `1440×900`、手机模拟 `390×844`。在每次导航前安装请求记录和拦截：preview 只放行该域名 `/`、`/assets/`、favicon 的真实静态响应，新闻、债务、proxy 和外部字体请求在浏览器发送前中止；没有替换或伪造验收 HTML、JS、fixture、API 响应。故下列结果是**受控线上浏览器**证据，不是整站所有模块的无拦截验收或 Cloudflare 服务端调用日志。

- 固定 deployment 桌面与手机各实际操作行业/概念 × 三种观察视图 × 强度/机会 `12/12`，总计 `24/24`；卡片数量与本地记录一致，矩阵为15日期×10名次，页面无横向溢出。矩阵独立滚动至桌面 `1308`、手机 `2030` px。
- 每种视口打开行业、概念当前榜单和历史单元格详情，各 `3/3`；历史选择为2026-10-26机会榜第1名，均显示15日轨迹。按钮关闭、Enter打开、Tab/Shift+Tab焦点约束、Escape及焦点返回通过；详情横幅在滚动首尾保持可见。刷新研究数据、视口切换、整页刷新和锚点直链也通过，状态语义与本地记录一致。
- 两种视口的标题均为“板块轮动临时验收 · 测试数据”，robots meta 为 `noindex,nofollow`，页面及详情保留测试横幅，实际下载 `acceptance-fixtures-*` chunk，卡片名称为“测试行业/测试概念”。branch alias 另行导航也确认同样标题、robots、横幅与 fixture chunk。
- 固定 deployment 主检查记录 **180次请求尝试：36次真实静态资源，144次无关请求被发送前阻断；`/api/market-dashboard` 为0，`/api/sector-rotation` 为0；未捕获 JS 异常为0**。这些零值包括切换、刷新和详情全过程，证明本次验收操作未触发上述市场/轮动 Functions 的 D1 读取路径；没有直接探测 preview API 或数据库。此结论不覆盖普通用户页面中的其他模块、catchall 的静态转交或独立服务端活动。
- 独立打开 [production](https://newsmonitor.pages.dev/)：首页和主 JS/CSS 返回200，标题为“Finance Monitor · 实时热榜聚合”，没有 robots meta、测试横幅、板块轮动验收区或 fixture chunk。检查实际收到的 HTML/JS/CSS，未出现验收 adapter origin/error code、fixture chunk 名或测试横幅文字。仅放行页面自然发出的 `GET /api/market-dashboard/latest` 及 `history?window=5d`；二者返回200，latest 的实际 JSON 为 `schemaVersion=market-dashboard-v2`，可见页面也标明 v2。没有主动构造额外市场请求，没有 `/api/sector-rotation` 或 v3 请求。其他 proxy/font 请求继续阻断，避免访问 provider。

线上原始脚本、JSON、日志与12张截图保留在已忽略目录，不提交二进制：

```text
.superpowers/sdd/2026-11-15-sector-rotation-accelerated-acceptance/task-3-browser-artifacts/
  qa.js / qa-result.json / qa-result.log
  focused-tests.log / npm-build.log
  output/playwright/
    desktop-{initial,board,concept-opportunity,matrix,detail}.png
    mobile-{initial,board,concept-opportunity,matrix,detail}.png
    alias-mobile.png / production-desktop.png
```

已目视检查桌面榜单、手机榜单/详情和 production 截图；其余截图与自动断言一并保留。线上验证未重复注入损坏 fixture，本地故障隔离证据仍见上文。普通构建与必要组件/adapter 回归重新执行：19/19通过；`npm run build` 通过，最终 `dist` 为普通生产构建，未包含验收 metadata/fixture/adapter 标记。135项全套结果属于前一轮本地 QA，本轮文档改动没有重复全套测试。

## 临时页面的失效与移除边界

本次没有设置自动到期日期，也没有执行删除。固定 deployment URL 与 branch alias 当前均可访问；后续替换同分支部署可能改变 alias 指向，固定 deployment 地址应作为本次证据基准。`noindex,nofollow` 是索引提示，不是访问认证；链接可供持有者访问。

验收结束或要求撤回时，应另行授权删除上述 **preview deployment ID**，并复查固定 URL 和 alias 均不能继续提供本次验收页面；只移除或改指 alias 不能证明固定 deployment URL 已撤回。删除范围不得包含 production deployment、D1、生产 feature flag 或正式 alias。撤回不能清除用户已保存的截图或浏览器副本。没有将未设置的自动过期、未执行的删除或将来的测试版发布写成已完成。

## 本地证据与复现

验收的源代码基线为 `17944a5`，本轮未修改实现。先运行 `npm run build:acceptance`，保存静态产物，再用 loopback preview 执行检查。之后运行普通 `npm run build`，最终 `dist` 为普通生产构建。独立 QA 浏览器和临时服务器均已关闭，本地地址不是在线分享链接。

代表性截图和原始浏览器断言存放在已忽略的目录，不提交二进制：

```text
.superpowers/sdd/2026-11-15-sector-rotation-accelerated-acceptance/task-2-browser-artifacts/
  acceptance-dist/                 本次验收静态产物副本
  qa.js / qa-result.json           主检查脚本与完整断言结果
  screenshots.js / screenshots-result.log
  output/playwright/
    desktop-initial.png / mobile-initial.png
    desktop-board.png / mobile-board.png
    desktop-concept-opportunity.png / mobile-concept-opportunity.png
    desktop-matrix.png / mobile-matrix.png
    desktop-detail.png / mobile-detail.png
    desktop-malformed.png / mobile-malformed.png
```

本地重新查看已保存产物可用以下命令；浏览器复验须同时保留上述请求拦截，避免加载首页其他模块的实时请求：

```bash
npm run preview -- --outDir .superpowers/sdd/2026-11-15-sector-rotation-accelerated-acceptance/task-2-browser-artifacts/acceptance-dist --host 127.0.0.1 --port 4174 --strictPort
```

回归检查：`npm test` 135/135通过、0失败；`npm run build` 通过（包含 TypeScript 检查）；`git diff --check` 通过。普通构建保留原首页元信息，无 noindex、无 fixture chunk、无 acceptance adapter origin/error code；现有测试继续验证普通界面使用 v2。现有 Browserslist 数据过期提示不影响构建，未更新依赖。

## 结果与反馈

技术 QA 未发现 acceptance 专属阻塞缺陷，没有修改 Task 1 文件。用户评审仍待进行，优先请检查：

1. “潜在轮动 / 主线确认 / 风险升温”是否能直观区分，强度、机会和风险的解释是否足够清楚？
2. 行业与概念的切换位置、当前榜单的卡片密度是否顺手？手机是否容易找到历史矩阵？
3. 历史矩阵的横向滚动、日期、排名和强度/机会切换是否容易理解？
4. 详情是否优先展示了需要的信息，贡献因素和来源内容是否过多或缺项？
5. 测试数据横幅是否始终足够明显，有无某处让人误以为真实市场信号？

反馈每条单独记录，注明设备/浏览器、行业或概念、观察视图、矩阵维度、操作步骤、预期、实际结果和截图。建议格式：`UA-001｜手机390px / 概念 / 潜在轮动 / 机会｜操作…｜预期…｜实际…｜截图…`。先记录问题，再确认修改范围并复验；本记录不把用户未反馈视为通过。

| 编号 | 来源 | 问题或决定 | 状态 |
| --- | --- | --- | --- |
| UA-000 | 技术 QA | 本地及线上受控 preview 响应式、交互与市场 API 隔离检查通过；production仍为v2 | 已完成 |
| UA-001起 | 用户评审 | 等待用户实际操作后的反馈，暂无用户提交的问题 | 待验收 |

## 仍阻塞的动作

- 一次 Cloudflare preview 发布已获明确授权并完成；本轮只验证/记录，未再次部署或 push。用户本人验收及真实手机浏览器检查仍待进行。
- 测试版还须完成用户界面验收及至少一个真实完整交易日的安全影子记录：行业35/35、概念至少72/75，且不得有身份、单位、未来时间或误发布错误。此轮未检查或操作现有 shadow 服务。
- D1 迁移、v3 数据发布、正式 UI 开关及生产部署均未获本轮授权，保持阻塞；线上检查确认 production仍为v2。Functions bundle随preview上传不等于这些动作已获授权或执行。
- 合成数据不能验证行情正确性、评分效果或预测能力。一个真实交易日也不能证明预测有效；十交易日观察仍需独立执行，不能表述为成熟回测或收益承诺。
