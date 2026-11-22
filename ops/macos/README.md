# Market dashboard LaunchAgent

This directory prepares one user LaunchAgent. Preparation does not load or start
it. No credentials belong in these files or in a plist.

Use a stable checkout, rather than a temporary worktree, for a long-lived job.
The installer validates that this is the Git checkout root and that its CLI,
config, wrapper, plist template and the parent log rotation policy are readable,
before creating files or invoking launchctl. Linked worktrees and paths under
`.codex/worktrees/` are refused by default for every action. An explicit
`--allow-worktree` flag overrides this guard, for example `--prepare
--allow-worktree`; using it for a long-lived service is strongly discouraged
because removing the worktree breaks its executable paths. The same flag is
needed to disable or remove a job intentionally created from a worktree.
From that checkout, set the Financial Knowledge Repository root explicitly when
the checkout is not its direct `finance-monitor/` child:

```bash
export MARKET_DASHBOARD_PROJECT_ROOT="/Users/robot_ever/Codex/Financial Knowledge Repository"
# Optional: choose an absolute Python executable with the required local tools.
export MARKET_DASHBOARD_PYTHON="$(command -v python3)"
./ops/macos/install-market-dashboard-service.sh --prepare
```

Preparation validates the existing `scripts/rotate_service_logs.py` path, writes
`~/Library/LaunchAgents/com.robot-ever.finance-monitor.market-dashboard.plist` with
mode 0600, and creates `logs/market-dashboard/` with mode 0700 and private logs.
Both the wrapper and installer reject symlinks at `logs` and
`logs/market-dashboard` before creating/chmodding files; individual log files
also reject symlinks. It preserves the first differing pre-install plist as `.plist.bak`. Repeating
preparation with identical configuration leaves that backup intact.

Review the rendered plist before opting in:

```bash
./ops/macos/install-market-dashboard-service.sh --enable
```

The explicit enable action enables and bootstraps an unloaded job. It never
bootouts/restarts a loaded job or kickstarts a run. To apply changed paths to a
loaded job, use `--disable` followed by `--enable`. No RunAtLoad or KeepAlive is
configured. Launchd wakes every 300 seconds; the Python job owns Shanghai
session gating, one successful publication per 15-minute bucket, process locking
and one final close snapshot in its 15:00–15:30 catch-up window.

The wrapper parses the parent `.env` as single-line literal `KEY=VALUE`
assignments, optionally prefixed by `export`, without executing shell expressions
or printing values. Existing process variables take precedence. Single or
double outer quotes preserve every character inside; backslashes are literal,
with no escape decoding. In an unquoted value, `#` begins a comment only when
preceded by whitespace: `synthetic#suffix` stays intact, while `synthetic # note`
becomes `synthetic`. Internal spaces and unquoted quotes stay literal. A comment
after a closing outer quote must be separated by whitespace. Shell
variable/command expansion and multiline values are not supported. Wind keeps
its existing user configuration; the plist PATH
includes Homebrew locations. The wrapper exports `MARKET_DASHBOARD_STATE_ROOT`
as `<project root>/state`, then execs `python -m tools.market_dashboard.job`.
Logs use the existing project's 2 MB / three-backup copy-truncate policy at each
wake. Neither source nor installer writes tokens, a publication URL or MX keys.

Stop and remove the service with explicit actions:

```bash
./ops/macos/install-market-dashboard-service.sh --disable
./ops/macos/install-market-dashboard-service.sh --uninstall
# Restore the saved pre-install plist, while leaving the job disabled:
./ops/macos/install-market-dashboard-service.sh --restore
```

Uninstall retains the rendered plist as `.plist.disabled`, its original
`.plist.bak`, snapshots and logs. Restore does not load/start the restored job.
Re-enable is always explicit. These actions affect only this dashboard label.

The Financial project's health script treats an uninstalled/unloaded dashboard
as informational. For an enabled dashboard, intraday buckets receive a
ten-minute collection grace. A missing same-day published close remains an
error from 15:30 through that trading day's end. Lunch, pre-open, weekends and
explicit configured non-trading dates do not create intraday source-delay
errors. Weekdays are an approximation unless `schedule.tradingDates` is present
in the checkout's versioned config; supply the same calendar for job and health
before relying on holiday suppression.

## 完整本地备用首页

使用`python3 ops/macos/install-local-board-service.py --install`安装登录后自动运行的回环网页服务及桌面 **Finance Monitor 本地看板.app**。桌面入口可自行恢复服务，无需Codex在线。打开 `http://127.0.0.1:5184/`，包含全球联动、雷达、跨市场风险、新闻与板块研究。直接公开源及本机缓存支持无代理访问；断网保留原时间，失效风险不显示常态。仅本机可访问，不改采集器。打开方式与维护见[本地使用说明](../../docs/local-board-access.md)。

## ETF资金观察日频服务

`python3 ops/macos/install-etf-observation-service.py --enable` 安装独立的 `com.robot-ever.finance-monitor.etf-observation`。每30分钟唤醒，上海9–23点检查；完整同日数据复用，失败按小时重试，次日确认前一日份额。源与方法见 [ETF观察](../../docs/csi300-etf-observation.md)。不修改原板块及雷达评分服务。
