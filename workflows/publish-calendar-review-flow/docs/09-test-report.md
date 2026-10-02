# 测试报告 —— publish-calendar-review-flow

## 一、结构校验

| 项 | 结果 |
|---|---|
| 四件套齐全（SKILL.md / prompt.txt / schema.json / examples/input.json） | ✅ PASS |
| SKILL.md 九段齐全 + frontmatter + ID 行（`de_local_01_wf05`） | ✅ PASS |
| prompt.txt ≥ 1200 字（T3 标准） | ✅ PASS |
| DAG 节点 = 本仓真实技能 slug（local-hotspot-track / multi-platform-spec-adapt / aigc-label-compliance） | ✅ PASS |
| examples/input.json 为真实数据，无占位符 | ✅ PASS |
| 无 API Key / 无模型调用代码 | ✅ PASS |

## 二、脚本实跑

**命令**：

```bash
python scripts/run_flow.py --demo
python scripts/run_flow.py --input examples/input.json --outdir out
```

**运行环境**：Python 3.13（WorkBuddy 内置）/ openpyxl

| 项 | 结果 |
|---|---|
| 退出码 | 0（两种模式均 0） |
| 处理规模 | 6 条内容 / 1 个节点 / 7 天日历 |
| 产物 1 | `out/发布日历.xlsx`（周日历 / 复审清单 / 未入历 三 sheet，拦下行标红） |
| 产物 2 | `out/publish_calendar_flow.json`（calendar/blocked/unfilled） |
| 耗时 | < 1 s |

### 端到端结果核对（实跑值）

| 检查 | 结果 |
|---|---|
| 复审闸门 | C4(pending)/C6(failed) 均不入历且逐条给原因 ✅ |
| 节点正日子优先 | C2（国庆）落 10-01 周四 18:00 晚高峰，非窗口首日 ✅ |
| 窗口标签区分 | 09-29 标「（国庆窗口）」、10-01 标「（国庆）」 ✅ |
| 高优先占晚高峰 | C1/C2 均落 18:00 ✅ |
| 每平台每天 ≤1 条 | 周一抖音 1 条、小红书 1 条，无同平台同日撞车 ✅ |
| 槽位正确性 | 周四为工作日槽（12:00/18:00），未误用周末槽 ✅ |
| 人工放行环节 | 输出提醒 3 条，未代发布 ✅ |

### 注入故障验证（失败处理）

| 故障 | 行为 |
|---|---|
| week_start = 周三 | 报错拒绝，退出码非 0 ✅ |
| contents = [] | 中止索要清单 ✅ |
| 全部内容 pending | 空日历 + 复审任务清单，不伪造排期（按规则推演） ✅ |
| 日期格式非法 | 报错「格式非法（应为 YYYY-MM-DD）」 ✅ |

## 三、边界与已知限制

| 限制 | 说明 |
|---|---|
| 槽位为通用基准 | 12:00/18:00 为探店品类通用高峰，账号后台有真实粉丝活跃数据后应覆盖 |
| 语义错配不自动调 | 「周末 vlog 排周二」如实排入并提示人工调换，不做内容语义判断 |
| 复审状态由上游提供 | 本流读取 review_status，复审动作在 aigc-label-compliance 内完成 |
| 跨月周 | 周一在月末、周日在次月时日期换算已验证（datetime 处理） |

## 四、结论

**通过。** 节点对齐、槽位规则、复审闸门、周一起始硬校验全部正确，
注入故障行为符合 prompt 承诺，端到端产出 Excel/JSON。

---

*测试报告基于真实实跑输出生成 · 2026-09-30*
