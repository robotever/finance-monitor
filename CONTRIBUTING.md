# 贡献说明

Finance Monitor 是金融研究工具。修改前请先阅读：

1. [项目状态](docs/STATUS.md)
2. [系统架构](docs/ARCHITECTURE.md)
3. [开发规范](docs/DEVELOPMENT.md)
4. 涉及数据时阅读 [数据源策略](docs/DATA_SOURCES.md)

**长期交付约定：每次功能修改必须同时更新本地版与线上版，并在两个实际运行入口分别验证；只完成一端不得声明整体完成。** 具体步骤与记录要求见 [双端同步交付](docs/DEVELOPMENT.md#本地版与线上版同步交付长期要求)。

最小交付要求：

- 变更范围清晰，不覆盖已有未提交工作；
- 功能或修复有自动测试；
- Python 测试、`npm test`、`npm run build` 和 `git diff --check` 通过；
- 数据、契约、状态或用户可见行为变化同步更新文档和 `CHANGELOG.md`；
- 不提交密钥、供应商原始响应、私有状态、日志或临时验收产物；
- 不把合成、回放、回填或影子数据描述为生产实时数据。

提交信息使用 `feat:`、`fix:`、`test:`、`docs:` 或 `ops:` 等现有前缀。通过 Pull Request 合并；数据库迁移、生产部署和长期服务变更需要单独批准。
