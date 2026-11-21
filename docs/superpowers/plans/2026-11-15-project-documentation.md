# Finance Monitor Project Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可持续维护的 Finance Monitor 项目文档体系，并校正当前状态说明。

**Architecture:** README 只负责导航和快速开始；按职责拆分架构、目录、数据源、开发和状态文档；运行细节继续由现有运维手册负责，历史设计与验证记录继续作为证据。所有状态陈述使用日期快照，并区分生产、验收、影子和规划。

**Tech Stack:** Markdown、Vue 3、TypeScript、Python、Cloudflare Pages Functions / D1

**Spec:** `docs/superpowers/specs/2026-11-15-project-documentation-design.md`

## Global Constraints

- 不修改运行时代码、数据源配置、Cloudflare 配置或数据库。
- 不记录凭据、原始供应商载荷、本机私有状态或临时文件。
- 不把 sector rotation v3、妙想切换或 15 分钟新策略描述为已经生产上线。
- 保留并链接已有运维、设计、计划和验证文档。

## Review Focus

- README 与 `docs/STATUS.md` 对生产/验收状态的表述必须一致。
- 数据源文档必须区分“实测可用”与“待盘中验证”。
- 命令、文件路径和目录职责必须能在仓库中找到对应实体。
- 相对链接不得失效。
- CHANGELOG 只归纳重要变化，不推断未发布版本。

---

### Task 1: 核心导航与状态

**Files:**
- Modify: `README.md`
- Create: `docs/STATUS.md`
- Create: `CHANGELOG.md`

- [x] **Step 1:** 按设计重写 README，并加入完整文档导航。
- [x] **Step 2:** 记录截至 2026-11-15 的生产、验收、影子和数据验证状态。
- [x] **Step 3:** 从 Git 历史归纳阶段性变更。
- [x] **Step 4:** 检查 README 与状态文档之间的状态表述一致。

### Task 2: 架构、目录和数据源

**Files:**
- Create: `docs/ARCHITECTURE.md`
- Create: `docs/PROJECT_STRUCTURE.md`
- Create: `docs/DATA_SOURCES.md`

- [x] **Step 1:** 记录浏览器、Functions/D1、本地采集器和外部来源的数据流。
- [x] **Step 2:** 记录目录职责和常见修改入口。
- [x] **Step 3:** 记录 Wind、妙想、FRED 和新闻来源的职责、切换边界及成本策略。
- [x] **Step 4:** 对照源码、配置和迁移文件复核事实。

### Task 3: 开发流程与总体验证

**Files:**
- Create: `docs/DEVELOPMENT.md`
- Create: `CONTRIBUTING.md`

- [x] **Step 1:** 记录环境、测试、分支、提交、变更和发布前检查流程。
- [x] **Step 2:** 建立简短贡献入口。
- [x] **Step 3:** 运行 Markdown 链接检查、`git diff --check`、前后端测试和生产构建。
- [x] **Step 4:** 审查文档事实、重复内容和敏感信息。
