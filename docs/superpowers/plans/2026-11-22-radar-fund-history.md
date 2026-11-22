# 雷达风格资金历史回填 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans with an independent final review.

**Goal:** 用已核验公开历史资金补齐六风格同版1/5日评分变化，不等待逐日积累，不删因子。
**Architecture:** 独立、可恢复的本地历史回填器。公开东方财富逐股日资金，已有同花顺本地日线提供同篮子成交额/广度；按当前完整成员逐日核对有效交易样本、日期和币种，聚合并合入原radar-inputs-v1，再用原安全发布器上线。原价格因子和v2评分权重不变，较早按当前成份重建明确标示非严格时点历史。
**Tech Stack:** Python, Hithink read-only CLI, public Eastmoney, existing D1 and Vue.
**Spec:** 用户明确要求各风格5日变化回填并自动完成、上线，沿用既有自动授权。

## Constraints and review focus
- 只补已完成交易日，目标至少最新日及前5个交易间隔；按完整成员集合核验，停牌/缺行情不填资金零。
- 严格同日、元单位、资金分类、完整成员；历史成交额不可从被舍入的资金占比反推。
- 真实无交易记录可按日排除，未知缺报仍缺失。支持限速、成功缓存、可续跑，不触碰MX额度。
- 保留最新已验收数据，历史包原子合并；不可让旧历史覆盖最新点。逐日historical membership approximation明确披露。
- 发布前后比对板块generation；保持原URL/日线服务/价格与评分公式不变。

## Tasks
- [x] 1. 少量公开历史接口探测，官方字段及已有同日样本核对。
- [x] 2. 回填器TDD：解析/本地日线导出/成员日核验/缓存/原子合并。
- [x] 3. 真实回填、数据与模型校验、独立复核、更新持久输入并安全发布。
- [x] 4. 页面保留历史重建说明；云端六组1/5期变化验证，提交主分支并上线。
