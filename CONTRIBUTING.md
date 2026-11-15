# 贡献说明

NewsMonitor 是金融研究工具。修改前请先阅读：

1. [项目状态](docs/STATUS.md)
2. [系统架构](docs/ARCHITECTURE.md)
3. [开发规范](docs/DEVELOPMENT.md)
4. 涉及数据时阅读 [数据源策略](docs/DATA_SOURCES.md)

最小交付要求：

- 变更范围清晰，不覆盖已有未提交工作；
- 功能或修复有自动测试；
- Python 测试、`npm test`、`npm run build` 和 `git diff --check` 通过；
- 数据、契约、状态或用户可见行为变化同步更新文档和 `CHANGELOG.md`；
- 不提交密钥、供应商原始响应、私有状态、日志或临时验收产物；
- 不把合成、回放、回填或影子数据描述为生产实时数据。

提交信息使用 `feat:`、`fix:`、`test:`、`docs:` 或 `ops:` 等现有前缀。通过 Pull Request 合并；数据库迁移、生产部署和长期服务变更需要单独批准。
