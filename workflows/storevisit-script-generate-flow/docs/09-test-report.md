# 测试报告 —— storevisit-script-generate-flow

## 一、结构校验

| 项 | 结果 |
|---|---|
| 四件套齐全（SKILL.md / prompt.txt / schema.json / examples/input.json） | ✅ PASS |
| SKILL.md 九段齐全 + frontmatter + ID 行（`de_local_01_wf02`） | ✅ PASS |
| prompt.txt ≥ 1200 字（T3 标准） | ✅ PASS |
| DAG 节点 = 本仓真实技能 slug（shortvideo-script-generate / multi-platform-spec-adapt / aigc-label-compliance） | ✅ PASS |
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
| 处理规模 | 9 镜分镜 + 3 平台标题 + 129 字文案 |
| 产物 1 | `out/拍摄脚本包.docx`（五节校验报告） |
| 产物 2 | `out/分镜校验表.xlsx`（三 sheet，问题行标红） |
| 产物 3 | `out/storevisit_flow.json`（verdict/red/issues） |
| 耗时 | < 1 s |

### 端到端结果核对（实跑值）

| 检查 | 结果 |
|---|---|
| 分镜合计 9 镜 = 60s（3+4+5+5+5+3+13+17+5） | ✅ 手算一致 |
| 语速逐镜 4.4-5.5 字/秒，全部落在 4.0-6.0 容差 | ✅ words/dur 逐镜复算一致 |
| B-roll 镜头（words=0）不判语速违规 | ✅ 镜头 6 |
| 首镜 3s ≤ 3s、钩子 14 字 ≤ 15 字 | ✅ 黄金 3 秒双检查通过 |
| 标题字数 15/30、18/20、15/16 | ✅ 逐平台核对一致 |
| 词表扫描 | 极限词/导流/功效 0 命中；「探店合作」在场 ✅ |
| AI 成分 → 🔵 提示（非红线） | ✅ verdict=可进人工终审 |
| 放行标准（红线 0 且问题 ≤1） | ✅ 与输出一致 |

### 注入故障验证（失败处理）

| 故障 | 行为 |
|---|---|
| shots=[] | 报错退出，无半成品文件 ✅ |
| 文案含「最好吃」+「加微信」+ 缺「探店合作」 | 红线 3 项，verdict=打回重改 ✅ |
| 首镜 6s / 钩子 22 字 / 语速 8.0 | 三条返工项各带具体数字 ✅ |
| 标题 25 字投小红书 | 「超 5 字，需压缩」🔴 ✅ |

## 三、边界与已知限制

| 限制 | 说明 |
|---|---|
| 「探店合作」只查出现不查位置 | 贴纸前 3s 可见性属画面检查，留给人工终审（prompt 已明确分工） |
| 词表扫描不识变体 | 谐音/拆字不在词表内，由 S3 模型按 prompt 复核 |
| 语速基准 5 字/秒 | 为探店口播经验值；极速节奏账号可整体上调基准并同步容差 |
| 标题上限随平台改版 | PLATFORM_LIMITS 常量需随平台公告更新 |

## 四、结论

**通过。** 三步 DAG 真实编排，量化校验与手算一致，注入故障的失败处理行为全部正确，
端到端产出 Word/Excel/JSON 三类文件。

---

*测试报告基于真实实跑输出生成 · 2026-09-30*
