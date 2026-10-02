---
name: publish-calendar-review-flow
description: 发布日历与复审工作流。DAG：local-hotspot-track 节点日历对齐 → multi-platform-spec-adapt 槽位分配（工作日12:00/18:00、周末11:00/19:00、每平台每天≤1条、节点内容优先落正日子）→ aigc-label-compliance 复审闸门（pending/failed 一律不入历）→ 人工逐条放行。产出周日历 Excel（日历/复审清单/未入历三 sheet）。当用户需要排发布计划、一周日历、发布前复审、节点营销排期时使用。
---

# 发布日历与复审

把定稿内容排成一周日历：对的平台、对的槽位、对的节点窗口，复审不过不入历。

## 元信息

| 字段 | 值 |
|------|-----|
| ID | `de_local_01_wf05` |
| 类型 | **`composite`（复合技能）** |
| 所属员工 | 探店编导 |
| 阶段 | `P0` |
| 复杂度 | `M` |
| 触发方式 | 定时（每周日 20:00 排下周）/ 手动 |
| ROI | 排期 + 复审一体：避免违规发布与同质撞车，月省约 5 小时 |
| 资产形态 | 提示词编排 + 可选 Python 编排脚本 |

## 能力描述

1. **节点对齐（S1）**：festival_days 映射到本周窗口（前 2 天后 1 天），节点内容优先排；
   标签区分「（国庆）」正日子与「（国庆窗口）」
2. **槽位分配（S2）**：工作日 12:00 午高峰 / 18:00 晚高峰，周末 11:00 / 19:00；
   每平台每天 ≤1 条（防同质撞车）；高优先占晚高峰；槽位满如实标「未排入」
3. **复审闸门（S3）**：review_status = passed 才入历，pending/failed 拦下并给原因；
   全部被拦则输出空日历 + 复审任务清单
4. **人工放行**：逐条放行，不做一键全发；week_start 非周一硬校验拒绝

## 编排的原子技能

| # | 原子技能 | 能力 |
|---|---------|------|
| 1 | [本地热点追踪](../../skills/local-hotspot-track/) | 节点日历与热点对齐 |
| 2 | [多平台规格适配](../../skills/multi-platform-spec-adapt/) | 平台槽位与规格 |
| 3 | [AIGC 标识合规](../../skills/aigc-label-compliance/) | 发布前复审 |

## 步骤链路（DAG）

```mermaid
flowchart LR
    IN["输入：周内容清单 + 节点日历"] --> S1["S1 local-hotspot-track"]
    S1 --> S2["S2 multi-platform-spec-adapt"]
    S2 --> S3["S3 aigc-label-compliance"]
    S3 --> G{"复审 passed？"}
    G -- 否 --> BLOCK["不入历"]
    G -- 是 --> CAL["槽位分配（脚本承担）"]
    BLOCK --> FIX["复审后补排"]
    CAL --> OUT["输出：周日历"]
    OUT --> HUMAN["人工逐条放行"]
```

## 步骤明细

| # | 步骤 | 技能资产 | 输入 | 输出 | 失败处理 |
|---|------|---------|------|------|---------|
| 1 | 节点对齐 | `local-hotspot-track` | week_start + festival_days | 窗口标记 + 优先序 | week_start 非周一报错；日期解析失败中止 |
| 2 | 槽位分配 | `multi-platform-spec-adapt` | 通过闸门的内容 | 7 天 × 槽位日历 | 槽位满标「未排入」给补排建议，不挤占已排 |
| 3 | 复审闸门 | `aigc-label-compliance` | review_status | 入历/拦下 | 全拦则空日历 + 任务清单 |
| 4 | 人工放行 | （人工） | 日历 | 逐条发布 | 发布前核对 AI 标识与「探店合作」 |

## 输入规格

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `week_start` | string | ✅ | 周一日期 YYYY-MM-DD（非周一拒绝） |
| `contents` | array | ✅ | id / title / platform / review_status / node_hint / priority |
| `festival_days` | array | ⬜ | date / name / window（相对天数） |

## 输出规格

| 字段 | 类型 | 说明 |
|------|------|------|
| `calendar` | array | 7 天 × 槽位（日期/槽位/平台/内容/ID） |
| `blocked` | array | 复审拦下清单与原因 |
| `unfilled` | array | 槽位未排清单与补排建议 |
| 产物 | file | `out/发布日历.xlsx`（三 sheet）、`out/publish_calendar_flow.json` |

## 错误处理

| 情况 | 处理方式 |
|------|---------|
| week_start 非周一 | 报错拒绝（防日历错位一周） |
| contents 为空 | 中止索要内容清单 |
| 复审全为 pending | 空日历 + 复审任务清单，不伪造排期 |
| 节点内容槽位满 | 如实标「未排入」，建议下周补排 |

## 使用步骤

### 方式一：纯提示词编排（跨平台）

1. 把 `prompt.txt` 全文粘贴为系统提示词
2. 提供周一日期、节点日历与内容清单
3. 得到周日历 + 复审清单 + 未入历说明
4. 逐条人工放行发布

### 方式二：带脚本（端到端产物）

```bash
python3 <WF_DIR>/scripts/run_flow.py --input input.json --outdir out
python3 <WF_DIR>/scripts/run_flow.py --demo
```

| 平台 | 编排方式 |
|------|---------|
| **Coze / 扣子** | 新建工作流 → 三技能节点 + 条件分支（复审闸门）+ 代码节点排槽 |
| **Dify** | 新建 Workflow → LLM 节点链 + 代码节点 |
| **WorkBuddy** | 新建 Skill 按 prompt.txt 步骤串联 |

## 边界（不做的事）

- ❌ 不排入复审未通过的内容，没有例外
- ❌ 不伪造排期；内容全拦就出空日历 + 任务清单
- ❌ 不接受非周一 week_start
- ❌ 不做一键全发，放行逐条
- ❌ 不对「周末主题排到周二」这类语义错配自动调换，提示人工处理

## 调用示例

**输入**（`examples/input.json`）：2026-09-28 周 / 国庆节点 / 6 条内容。

**输出**（脚本实跑）：4 条入历——「国庆火锅节逛吃攻略」落 10-01（国庆）晚高峰，
「毛肚免费续的老店」落周一晚高峰；2 条被复审闸门拦下（pending/failed）。

## 所属工作流

本资产为复合技能（工作流），是独立的端到端流程，不隶属于其他工作流。

## 合规声明

- 输出标注「AI 生成内容」；每条内容发布前核对 AI 标识与「探店合作」标注
- 节点营销遵守《互联网广告管理办法》合作标注义务
- 对外发布保留人工确认环节，逐条放行

---

*本复合技能遵循 [bangwozuo 数字员工资产规范](https://github.com/bangwozuo/digital-employee-spec) v3.0*
