# Opportunity v0.4 Implementation Plan

> Execute inline with superpowers:executing-plans. User approved the proposed scoring definition and automatic completion.

**Goal:** 机会表达低位吸引力，改善加分；强度风险继续独立。
**Architecture:** 同花顺v4独立评分版本升级v0.4，位置=100-价格历史分位，权重60/15/10/10/5。移除改善不足69封顶，保留样本/覆盖闸门与独立证据计数；用已存真实原子与分位离线重算15日全部480板块，强度风险逐值保持。完整新历史作为新日增量基座，拒绝跨版本拼接。
**Tech Stack:** Python pure scorer/migration, JS contracts, D1 full+daily publication, Vue detail.

- [x] 添加位置单调、缺失不补零、无改善低位可得高分、强度风险不变与迁移幂等测试；先确认失败。
- [x] 修改评分、版本契约、详情解释；实现可审计离线候选与锁保护原子切换、备份。
- [x] 重算真实15日480板块，比对新旧分布、低位/高风险样本、完整历史及强度风险恒等。
- [x] 新历史完整发布与增量基座切换；验证生产详情/历史/采集续接，记录结果，恢复自动部署。

说明：价格低位并非估值便宜；权重是可解释研究假设，本轮做行为一致性与数据验证，不声称收益预测已有效。
