# Finance Monitor 项目改名与兼容迁移

## 授权与命名

用户要求将NewsMonitor整体改为Finance Monitor（含首页和GitHub仓库）。随后明确选择“保留旧网址，只改现有项目名称”。不新建Pages项目，不向新项目配置发布密钥。

- 显示名：Finance Monitor；包/仓库/目录名：finance-monitor。
- GitHub：https://github.com/robotever/finance-monitor 。GitHub旧仓库地址保留平台跳转。
- Cloudflare Pages项目：finance-monitor；生产域名仍 https://newsmonitor.pages.dev/ 。Cloudflare原位改名不会改变已分配的pages.dev子域。
- 数据库保留原名称newsmonitor-market-dashboard与UUID dabc291a-86b3-46ea-89dd-1060120f5da1，MARKET_DB绑定及已有数据不重建、不迁移、不清空。
- 页面标题Finance Monitor · 全市场研究终端，页头FINANCE MONITOR、标志F、页脚同名，favicon更换为F。
- 自动任务标签改为com.robot-ever.finance-monitor.market-dashboard及原有后缀，保留间隔、参数、状态目录与启用状态。影子任务不因改名启动。
- 稳定目录和活动工作树改为finance-monitor，旧路径作为兼容符号链接保留，Git worktree元数据修复，不复制私有数据库。

## 迁移原则

保留历史验收中的旧URL、旧路径与已发布部署编号；它们是历史证据。文档中当前路径和项目名更新。技术兼容层仍可能出现newsmonitor，不据此声称零旧字符串。

Cloudflare Git关联按repo_id 1215707453识别同一仓库；其repo_name返回值可能仍为旧缓存。迁移期间暂时暂停自动Git构建，手动发布经验证版本；最后恢复原自动设置，避免中途自动构建覆盖正式站。

## 检查

- Vue/TypeScript正式构建通过。
- 改名涉及的默认HTML元信息、D1绑定不变、八项观察目录定向检查3/3通过。
- 预览d17bbdb6实际浏览器：标题、页头、aria标签均为Finance Monitor；390px无横向溢出。
- 初次Python组合检查发现父项目健康检查仍使用旧标签，已修改父项目两处引用并保留备份；对应健康测试重跑通过。
- 初次全量Node检查在无本轮修改的SQL用例长时间未返回，已停止并保留/tmp/finance-monitor-full-tests.log，不宣称全量通过；改名相关检查另外执行。
