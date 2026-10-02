# -*- coding: utf-8 -*-
"""
每日热点选题工作流 —— 端到端编排脚本。

流程（与 SKILL.md 的 DAG 一致）：
  S1 local-hotspot-track        候选热点三因子加权评分，淘汰 C 级
  S2 shortvideo-script-generate  为入选选题生成拍摄要点卡（钩子类型/发布槽位/时长预算）
  人工确认                        Top3 选题经人工确认后进入拍摄排期

本脚本承担 S1 的全部计算与 S2 的确定性部分（槽位/钩子类型映射、时长预算）；
「钩子具体台词」属模型创作，由 S2 的 prompt.txt 完成，脚本只输出结构卡。

用法：
  python run_flow.py --input input.json --outdir out
  python run_flow.py --demo

产物：
  out/每日选题推送.docx   Top3 选题卡 + 评估依据 + 发布建议
  out/选题评分明细.xlsx    全部候选评分明细
  out/daily_topic_flow.json  机器可读结果
"""
from __future__ import annotations

import argparse
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WF_DIR = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(WF_DIR))
sys.path.insert(0, os.path.join(REPO, "lib"))

try:
    import assettools as at
except ImportError:  # pragma: no cover
    print("[错误] 未找到 lib/assettools.py。请确认工作流位于 <repo>/workflows/<slug>/scripts/ 下，"
          "且 <repo>/lib/assettools.py 存在。", file=sys.stderr)
    sys.exit(2)

GRADE_A, GRADE_B = 70, 55
NODE_KEYWORDS = ("情人节", "七夕", "五一", "暑期", "暑假", "国庆", "圣诞", "跨年", "中秋", "元旦", "春节")
PRICE_WORDS = ("人均", "元", "平价", "便宜")
SCHEDULE = {"A 追": "24h 内拍摄，明日午高峰 12:00 发布", "B 观察": "次日复查热度，涨则拍，槽位后日晚高峰 18:00"}

DEMO = {
    "city": "成都",
    "category": "火锅",
    "candidates": [
        {"title": "老板把毛肚免费续到凌晨2点的老店", "source": "小红书本地生活",
         "heat_48h": 88000, "same_city_videos": 8, "match": 0.9, "hours_since": 6},
        {"title": "国庆去哪吃？成都火锅节10月1日开幕", "source": "抖音同城热榜",
         "heat_48h": 88000, "same_city_videos": 60, "match": 0.85, "hours_since": 40},
        {"title": "七夕火锅店情侣套餐预订火了", "source": "小红书本地生活",
         "heat_48h": 41000, "same_city_videos": 25, "match": 0.8, "hours_since": 100},
        {"title": "玉林巷子里人均50的苍蝇馆子火锅", "source": "小红书本地生活",
         "heat_48h": 36000, "same_city_videos": 45, "match": 0.9, "hours_since": 30},
        {"title": "春熙路新开的市井火锅，排队2小时也要吃", "source": "抖音同城热榜",
         "heat_48h": 128000, "same_city_videos": 260, "match": 0.95, "hours_since": 20},
        {"title": "上个月爆火的旋转火锅现在凉凉了", "source": "大众点评热门",
         "heat_48h": 15000, "same_city_videos": 310, "match": 0.5, "hours_since": 240},
    ],
}


def _heat_score(vals):
    logs = [math.log10(max(v, 1)) for v in vals]
    lo, hi = min(logs), max(logs)
    if hi == lo:
        return [50.0] * len(vals)
    return [round((v - lo) / (hi - lo) * 100, 1) for v in logs]


def _competition(n):
    if n <= 20:
        return 100.0
    if n >= 200:
        return 0.0
    return round((200 - n) / 180 * 100, 1)


def _score(payload):
    cands = payload.get("candidates", [])
    if not cands:
        raise SystemExit("[错误] candidates 为空：请提供候选热点清单（S1 local-hotspot-track 输入不能为空）")
    heats = _heat_score([c.get("heat_48h", 0) for c in cands])
    rows = []
    for c, h in zip(cands, heats):
        age = c.get("hours_since", 0)
        comp = _competition(c.get("same_city_videos", 0))
        match = float(c.get("match", 0)) * 100
        is_node = any(k in c.get("title", "") for k in NODE_KEYWORDS)
        base = h * 0.4 + comp * 0.3 + match * 0.3
        decay = 1.0 if is_node else 0.6 + 0.4 * (0.5 ** (age / 48))
        final = round(base * decay, 1)
        if age > 168 and not is_node:
            level = "C 淘汰"
        elif final >= GRADE_A:
            level = "A 追"
        elif final >= GRADE_B:
            level = "B 观察"
        else:
            level = "C 放弃"
        rows.append({"选题": c.get("title", ""), "来源": c.get("source", ""),
                     "热度分": h, "竞争度分": comp, "匹配度分": round(match, 1),
                     "总分": final, "级别": level})
    rows.sort(key=lambda r: -r["总分"])
    return rows


def _hook_type(title):
    """S2 确定性映射：按选题文本特征给钩子类型建议（台词由模型写）。"""
    if any(k in title for k in NODE_KEYWORDS):
        return "稀缺/节点 + 过程展示（节点提前布局，画面用节点氛围）"
    if any(k in title for k in PRICE_WORDS):
        return "价格反差（第一句放人均价数字）"
    return "提问式或过程展示（用画面反差制造信息差）"


def _budget(level):
    return "60s（270-320 字）" if level == "A 追" else "45s（200-240 字）"


def _plan(rows, payload):
    picks = [r for r in rows if r["级别"] == "A 追"][:2] + [r for r in rows if r["级别"] == "B 观察"][:1]
    plan = []
    for r in picks:
        plan.append({
            "选题": r["选题"],
            "级别": r["级别"],
            "总分": r["总分"],
            "钩子类型建议": _hook_type(r["选题"]),
            "时长预算": _budget(r["级别"]),
            "发布建议": SCHEDULE[r["级别"]],
            "合规提醒": "涉及商家合作须标「探店合作」；节点类提前 7-14 天拍" if r["级别"] in ("A 追", "B 观察") and any(k in r["选题"] for k in NODE_KEYWORDS) else "涉及商家合作须标「探店合作」",
        })
    return plan, len(picks)


def build(payload, outdir):
    rows = _score(payload)
    plan, n_picks = _plan(rows, payload)
    at.ensure_outdir(outdir)
    xlsx = at.write_excel(
        os.path.join(outdir, "选题评分明细.xlsx"),
        {"评分明细": rows},
        highlights={"评分明细": {"级别": "contains:A 追"}},
        widths={"评分明细": {"选题": 40}})
    sections = [
        {"heading": "执行摘要",
         "paras": [f"{payload.get('city','')} {payload.get('category','')}：候选 {len(rows)} 条，"
                   f"入选 {n_picks} 条（A 级优先）。节点类话题不参与时效衰减。"]},
        {"heading": "今日选题卡（Top3）",
         "table": {"cols": ["选题", "级别/总分", "钩子类型建议", "时长预算", "发布建议", "合规提醒"],
                   "rows": [[p["选题"], f"{p['级别']}（{p['总分']} 分）", p["钩子类型建议"],
                             p["时长预算"], p["发布建议"], p["合规提醒"]] for p in plan]}},
        {"heading": "淘汰与观察名单",
         "bullets": [f"{r['级别']}｜{r['选题']}（{r['总分']} 分）" for r in rows if r["级别"].startswith("C")]},
        {"heading": "人工确认点",
         "bullets": ["1. 确认入选选题信息真实（排队/免费续等须店家确认）",
                     "2. 确认拍摄档期与店家配合项",
                     "3. 确认后再交 shortvideo-script-generate 出完整脚本"]},
    ]
    docx = at.write_docx(os.path.join(outdir, "每日选题推送.docx"),
                         "每日热点选题推送", sections)
    js = at.write_json({"summary": {"city": payload.get("city"), "category": payload.get("category"),
                                    "candidates": len(rows), "picked": n_picks},
                        "plan": plan, "rows": rows, "generated_at": at.stamp(),
                        "note": "S1 评分与 S2 结构卡为脚本输出；钩子台词与完整脚本由 S2 模型按 prompt.txt 生成"},
                       os.path.join(outdir, "daily_topic_flow.json"))
    return {"files": [xlsx, docx, js], "plan": plan, "picked": n_picks}


def main():
    ap = argparse.ArgumentParser(description="每日热点选题工作流 —— S1 评分 + S2 选题卡")
    ap.add_argument("--input", help="输入 JSON（city/category/candidates）")
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    payload = DEMO if a.demo else (at.read_json(a.input) if a.input else ap.error("需要 --input 或 --demo"))
    r = build(payload, a.outdir)
    print(f"入选 {r['picked']} 条选题 —— 端到端完成")
    for p in r["plan"]:
        print(f"  [{p['级别']}] {p['选题']} → {p['发布建议']}")
    for f in r["files"]:
        print(" 产物:", f)
    at.emit(r)


if __name__ == "__main__":
    main()
