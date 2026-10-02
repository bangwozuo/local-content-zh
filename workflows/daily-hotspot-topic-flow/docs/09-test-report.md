# 测试报告 —— daily-hotspot-topic-flow

## 一、结构校验

| 项 | 结果 |
|---|---|
| 四件套齐全（SKILL.md / prompt.txt / schema.json / examples/input.json） | ✅ PASS |
| SKILL.md 九段齐全 + frontmatter + ID 行（`de_local_01_wf01`） | ✅ PASS |
| prompt.txt ≥ 1200 字（T3 标准） | ✅ PASS |
| DAG 节点 = 本仓真实技能 slug（local-hotspot-track / shortvideo-script-generate） | ✅ PASS |
| examples/input.json 为真实数据，无占位符 | ✅ PASS |
| 无 API Key / 无模型调用代码 | ✅ PASS |

## 二、脚本实跑

**命令**：

```bash
python scripts/run_flow.py --demo
python scripts/run_flow.py --input examples/input.json --outdir out
```

**运行环境**：Python 3.13（WorkBuddy 内置）/ openpyxl / python-docx

| 项 | 结果 |
|---|---|
| 退出码 | 0（两种模式均 0） |
| 处理规模 | 6 条候选 → 3 张选题卡 |
| 产物 1 | `out/每日选题推送.docx`（37.7 KB，摘要/选题卡表/淘汰名单/确认点 四节） |
| 产物 2 | `out/选题评分明细.xlsx`（5.8 KB，A 级行标红） |
| 产物 3 | `out/daily_topic_flow.json`（3.2 KB） |
| 耗时 | < 1 s |

### 端到端结果核对（实跑值）

| # | 选题 | 总分 | 级别 | 槽位 |
|---|---|---|---|---|
| 1 | 毛肚免费续到凌晨2点 | 87.0 | A 追 | 次日午高峰 12:00 |
| 2 | 火锅节10月1日开幕 | 81.8 | A 追 | 节点类提前 7-14 天 |
| 3 | 春熙路市井火锅 | 61.6 | B 观察 | 次日复查后晚高峰 18:00 |

### 质量核对

| 检查 | 结果 |
|---|---|
| 评分公式与 local-hotspot-track 一致（0.4/0.3/0.3 + 48h 半衰 + 节点豁免） | ✅ 毛肚店 87.0 两处一致 |
| 节点类不衰减 | 七夕 hours_since=100 仍得 71.9（时效系数 1.0）✅ |
| Top3 取卡规则（A 前 2 + B 第 1） | 七夕 71.9（A 第 3）落选进入轮换候选，取舍如实展示 ✅ |
| 超期淘汰 | 旋转火锅 240h → C 淘汰 9.2 ✅ |
| 空输入行为 | candidates=[] → 报错退出，无半成品文件 ✅ |
| 依赖缺失行为 | 缺 python-docx 时打印修复命令退出码 2 ✅ |

## 三、边界与已知限制

| 限制 | 说明 |
|---|---|
| 数据采集不在脚本内 | 候选热点需手动粘贴（不做爬虫） |
| 钩子台词不在脚本内 | 脚本只出钩子类型建议，台词由 S2 模型按 prompt.txt 生成 |
| 槽位为通用基准 | 午高峰 12:00/晚高峰 18:00 为探店品类通用槽位，账号有自己的粉丝活跃时段后应覆盖 |
| B 级复查为人工动作 | 次日互动量复查需人工执行，脚本不做跨日追踪 |

## 四、结论

**通过。** DAG 双技能编排真实可跑，评分与上游技能口径一致，端到端产出三类文件，
失败分支（空输入/数据不全/超期淘汰/取舍展示）行为正确。

---

*测试报告基于真实实跑输出生成 · 2026-09-30*
