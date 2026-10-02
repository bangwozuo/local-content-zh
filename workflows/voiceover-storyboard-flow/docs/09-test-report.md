# 测试报告 —— voiceover-storyboard-flow

## 一、结构校验

| 项 | 结果 |
|---|---|
| 四件套齐全（SKILL.md / prompt.txt / schema.json / examples/input.json） | ✅ PASS |
| SKILL.md 九段齐全 + frontmatter + ID 行（`de_local_01_wf03`） | ✅ PASS |
| prompt.txt ≥ 1200 字（T3 标准） | ✅ PASS |
| DAG 节点 = 本仓真实技能 slug（shortvideo-script-generate / multi-platform-spec-adapt） | ✅ PASS |
| examples/input.json 为真实逐字稿，无占位符 | ✅ PASS |
| 无 API Key / 无模型调用代码 | ✅ PASS |

## 二、脚本实跑

**命令**：

```bash
python scripts/run_flow.py --demo
python scripts/run_flow.py --input examples/input.json --outdir out
```

**运行环境**：Python 3.13（WorkBuddy 内置）/ openpyxl / matplotlib

| 项 | 结果 |
|---|---|
| 退出码 | 0（两种模式均 0） |
| 处理规模 | 5 段逐字稿（45s），台词 119 字 |
| 产物 1 | `out/分镜口播校验表.xlsx`（逐镜校验/五段占比/平台核对 三 sheet） |
| 产物 2 | `out/分镜时长分布.png`（五段柱状图） |
| 产物 3 | `out/voiceover_flow.json`（verdict/rows/share/issues） |
| 耗时 | < 1 s |

### 端到端结果核对（实跑值）

| 检查 | 结果 |
|---|---|
| 台词字数实数 | 手数「14点准时出炉的碱水包，去晚只能闻香味」= 18 字（标点不计）✅ |
| 钩子双红线（>3s / >15 字） | 3s 合规但 18 字 → 🔴 ✅ |
| 语速上限 6.0 字/秒 | 钩子恰 6.0 未触发上限、由字数规则拦截 ✅ |
| B-roll 留白不误报 | 场景 2.87 / 亮点 1.92 字/秒均 ✅ |
| 口播必需段下限 2.5 | 引导段 2.22 → 🟡 ✅；互动段 2.6 ✅ |
| 时间轴连续 | 0-3-18-31-40-45s 无重叠无空洞，合计 = 45s ✅ |
| 占比等比缩放 | 预算 ×45/60（2.2/16.5/15/7.5/3.8），偏差全部 ≤3s ✅ |
| 平台核对 | 抖音 60s / 小红书 240s 均 ✅ |
| verdict | 需微调（🔴1 + 🟡1，无时间轴问题）✅ |

### 注入故障验证

| 故障 | 行为 |
|---|---|
| segments=[] | 报错退出，无半成品文件 ✅ |
| 段名「开场白」不在五段内 | 标注「不在五段结构内」并计入时间轴 ✅ |
| 时间轴 3/20/18/10/5（合计 56s） | 报「≠ 目标 60s（±2s）」✅ |
| 结尾互动 3s | 报「< 4s，提问式结尾没给观众反应时间」✅ |

## 三、边界与已知限制

| 限制 | 说明 |
|---|---|
| 数字念法偏差 | 「176」按 3 字符计但实念 5 音节，人工对稿对大数字段加 1-2s |
| 语气词即兴 | 实拍即兴增词约 5%，校验按干净稿计 |
| 语速基准为经验值 | 上限 6.0/下限 2.5 为探店口播经验参数，可按账号风格调整 |
| 平台时长上限常量 | 随平台改版需更新 PLATFORM_MAX |

## 四、结论

**通过。** 四道量化检查与手数/手算一致，B-roll 留白假阳性已拦截，
注入故障行为全部正确，端到端产出 Excel/PNG/JSON 三类文件。

---

*测试报告基于真实实跑输出生成 · 2026-09-30*
