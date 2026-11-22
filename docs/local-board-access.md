# 完整本地首页：不依赖 Codex 的打开方式

平常双击桌面上的 **Finance Monitor 本地看板.app**，或打开 http://127.0.0.1:5184/ 并加入书签。入口会检查并恢复后台服务，再打开默认浏览器；不需要先打开 Codex，也不需要访问 Cloudflare。

登录这台 Mac 后服务自动启动，关闭浏览器不会停止服务。桌面另有 **Finance Monitor 本地说明.txt**，无法联系 ChatGPT 时也能查看。旧书签 `/__hithink-preview` 自动转到板块研究。

## 功能和数据

完整首页复用线上界面，市场研究雷达内另有[沪深300 ETF资金观察及历史比例图](csi300-etf-observation.md)，包含全球联动八项报价与走势图、市场研究雷达、跨市场风险监控、财经快讯、固定新闻卡片及板块研究入口。板块详情、历史轮动、成分股读取本机已提交快照和历史库，保留原来的15分钟采集安排与评分方法。

本地首页直接读取公开数据接口及本机真实资金／广度输入，不通过 Cloudflare/D1 中转。全球联动改用本地绘制的图表，避免依赖 TradingView 外部窗口；不提供 TradingView 全部工具。腾讯／新浪提供行情，黄金为伦敦金CFD，原油为纽约原油CFD参考报价；来源、实际时间、币种及缓存状态在图表中标明。

有网络时会请求最新可用数据；没有网络时可打开页面、查看已保存行情、板块、新闻和研究数据。缓存保持原时间，不伪装为实时数据。雷达保留明确标识的最近可用结果；风险关键输入请求失败时不沿用旧“常态”结论。超过两小时的快讯退出实时区，可在历史快讯中查看。首次使用且从未成功保存的数据无法凭空补齐。

本机不必开启代理，但公开数据网站自身的可达性仍可能影响更新。Mac关机或睡眠期间不会采集；其他设备不能通过127.0.0.1访问本机。

## 维护

- 服务标签：`com.robot-ever.finance-monitor.local-board`，RunAtLoad/KeepAlive开启，异常退出自动恢复。
- 安装器：`ops/macos/install-local-board-service.py`；执行 `python3 ops/macos/install-local-board-service.py --install` 更新，`--open` 可检查／恢复服务并打开浏览器。
- 登录项：`~/Library/LaunchAgents/com.robot-ever.finance-monitor.local-board.plist`。
- 监听：仅 `127.0.0.1:5184`；接口只读，不向浏览器提供凭据。
- 日志：`~/Library/Logs/Finance Monitor/local-board.log` 及 `local-board-error.log`。
- 缓存：运行目录 `data/local-home/`，已排除版本控制。删除缓存不会删除正式板块历史，但会失去断网备用数据。
- 实际运行目录：`/Users/robot_ever/.codex/worktrees/market-research-homepage/newsmonitor`；桌面启动器固定到此处。源码主副本为 `/Users/robot_ever/Codex/Financial Knowledge Repository/finance-monitor`，源数据不复制到桌面。

验证结果见 [完整本地首页验收](verification/2026-11-22-local-full-home.md)。尚未实际重启或注销整机，登录自启依据已加载配置和托管进程验证。
