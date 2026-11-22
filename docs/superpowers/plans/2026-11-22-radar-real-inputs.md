# 雷达资金和广度恢复 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans; independent data-source and collector tasks may run in parallel, followed by whole-change review.

**Goal:** 将已核验资金和广度上线，继续补齐六风格，保留缺口，验证通过后重算，不删减因子。

**Architecture:** 沿用Mac采集、D1保存、Pages展示结构。独立日线采集器用现有同花顺/MX凭据，发布规范化聚合历史；浏览器不持有密钥。云端保留价格因子，按同日真实资金及广度新增解释与评分输入；缺失不重新分配权重、不拼旧版本分数。

**Tech Stack:** Python, existing financial CLIs, Cloudflare D1/Pages, Vue, Node tests.

**Spec:** 用户2026-11-22明确批准自动实施、部署，跳过逐项审批；此前数据实测记录 docs/verification/2026-11-22-radar-funding-breadth-probe.json。

## Global Constraints
- 不删除既有因子以隐藏缺失，不填零，不把成交额当资金净流入。
- 未验证的风格资金不进入评分；严格身份、日期、单位、全量成员验证。
- 当前成份历史重建标注近似，不能宣称严格时点历史。
- 独立表/任务，不改板块D1批次与原服务；日线数据不能宣称盘中实时。
- 线上地址保留 newsmonitor.pages.dev；凭据只留现有用户级可信来源。

## Review Focus
- API返回200行但total更大；身份误识别和偷偷增加正资金筛选必须拒绝。
- 成份更新时间晚于行情日，历史重建必须披露。
- 资金缺失时分数不重分配，不将旧日期对齐到今日。
- 自动任务失败时旧数据仍带实际日期；失败不能覆盖新批次。
- 生产构建/发布不可影响原板块数据。

## Contract
输入聚合包 schemaVersion=radar-inputs-v1，observedAt=ISO，marketDate=YYYY-MM-DD，objects 包含 ashare/large/small/value/growth/dividend/tech，键不可扩展。
每个对象 {id,scope,sources:string[],membershipAsOf:date|null,history:Point[]}。
Point={date,up:int|null,down:int|null,flat:int|null,turnover:number|null,mainNetFlow:number|null,fundMatched:int|null,fundExpected:int|null,membershipMode:'provider-aggregate'|'current-members'}。
金额均元，按日期升序，最多320期；未知为null。sources可取MX/Hithink/CSI，source metadata不得含密钥/原始个股响应。

## Tasks
- [x] 1. 补测剩余成份和分批资金，独立测试身份/单位/完整度。
- [x] 2. Python采集器：规范化历史、准确篮子汇总、缓存与安全发布；验证后真实运行。
- [x] 3. 独立D1输入表、鉴权发布API、读取API和过期保护；测试失败关闭。
- [x] 4. 卡片展示原始广度和资金摘要，折叠详细来源；新增同日因子并版本化评分，缺失保留。
- [x] 5. 自启动日线任务、实际发布、回归与浏览器云端验收、独立审查、同步主分支、上线后核验。
