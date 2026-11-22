# 本地板块看板：不依赖 Codex 的打开方式

平常双击桌面上的 **Finance Monitor 本地看板.app**。入口会检查并恢复后台网页服务，再打开默认浏览器；不需要先打开 Codex，不需要通过 Cloudflare。

备用地址：http://127.0.0.1:5184/__hithink-preview 。可加入浏览器书签，只适用于这台Mac。登录Mac后后台服务自动启动，关闭浏览器不会停止服务。

桌面另有 **Finance Monitor 本地说明.txt**，可在无法连接ChatGPT时直接查看。

## 可用范围

提供本地行业三榜、概念观察、历史轮动、板块评分与成分股详情，读取现有采集器的已提交快照。网络中断仍可查看已采集数据，以页面时间为准；新闻、全球图表和完整首页尚未本地化。本次只增加本地展示服务，不增加数据采集任务、不改变15分钟采集安排。

## 维护

- 服务标签：`com.robot-ever.finance-monitor.local-board`。
- 安装器：`ops/macos/install-local-board-service.py`；桌面应用为本地生成的小型启动器，不依赖Codex或大模型。
- 登录项：`~/Library/LaunchAgents/com.robot-ever.finance-monitor.local-board.plist`，RunAtLoad/KeepAlive开启，异常退出自动恢复。
- 监听：仅`127.0.0.1:5184`，不开放到局域网或互联网。
- 日志：`~/Library/Logs/Finance Monitor/local-board.log`及`local-board-error.log`。
- 安装命令：在有真实数据的运行目录执行`python3 ops/macos/install-local-board-service.py --install`；`--open`可检查/恢复服务并打开浏览器。安装器检查本地快照、保留先前配置备份。
- 当前实际运行目录：`/Users/robot_ever/.codex/worktrees/market-research-homepage/newsmonitor`；桌面启动器和登录服务都固定到该实际目录。源码主副本仍在Financial Knowledge Repository/finance-monitor，源数据不复制到桌面。

## 2026-11-22 验证

三项安装器单元测试通过。已实测首次加载、SIGTERM后PID变化自动恢复、完全卸载服务后通过桌面.app重新加载并打开浏览器、重复安装；本地数据API返回v0.4与11/20数据，潜在/主线/风险10/7/10。后台进程父PID为1，确认由macOS管理；只监听127.0.0.1。未实际重启或注销整机，登录自启结论来自已加载的RunAtLoad配置。
