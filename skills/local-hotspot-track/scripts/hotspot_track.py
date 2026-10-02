# -*- coding: utf-8 -*-
"""
本地热点追踪 —— 选题三因子加权评分器。

职责边界：本脚本只做**确定性计算与产物生成**（归一化、加权、时效衰减、排序、出表出图）。
信息源是否可信、匹配度怎么标定、假阳性怎么排除，由模型按 prompt.txt 完成（模型的强项）。

评分公式：
  热度分   = min-max 归一化(近48h互动量)                    权重 0.4
  竞争度分 = 反向线性插值(同城同类视频条数, <20 满分, >200 零分) 权重 0.3
  匹配度分 = 人工标定 0-1                                   权重 0.3
  时效衰减 = 得分 × (0.6 + 0.4 × 0.5^(小时/48))，超 168h 直接淘汰

用法：
  python hotspot_track.py --input input.json --outdir out
  python hotspot_track.py --demo

产物：
  out/选题评估榜.xlsx   候选明细 / 汇总 两 sheet（A级行标红）
  out/选题得分.png      Top10 得分柱状图
  out/hotspot_track.json  机器可读结果
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(SKILL_DIR))
sys.path.insert(0, os.path.join(REPO, "lib"))

try:
    import assettools as at
except ImportError:  # pragma: no cover
    print("[错误] 未找到 lib/assettools.py。请确认技能位于 <repo>/skills/<slug>/scripts/ 下，"
          "且 <repo>/lib/assettools.py 存在。", file=sys.stderr)
    sys.exit(2)

W_HEAT, W_COMP, W_MATCH = 0.4, 0.3, 0.3
HALF_LIFE_H = 48          # 热点半衰期 48h
MAX_AGE_H = 168           # 超 7 天淘汰
GRADE_A, GRADE_B = 70, 55

# 节点类关键词：命中后不按衰减淘汰，标注「节点类，提前布局」
NODE_KEYWORDS = ("情人节", "七夕", "五一", "暑期", "暑假", "国庆", "圣诞", "跨年", "中秋", "元旦", "春节")

DEMO = {
    "city": "成都",
    "category": "火锅",
    "window_days": 3,
    "candidates": [
        {"title": "春熙路新开的市井火锅，排队2小时也要吃", "source": "抖音同城热榜",
         "heat_48h": 128000, "same_city_videos": 260, "match": 0.95, "hours_since": 20},
        {"title": "玉林巷子里人均50的苍蝇馆子火锅", "source": "小红书本地生活",
         "heat_48h": 36000, "same_city_videos": 45, "match": 0.9, "hours_since": 30},
        {"title": "国庆去哪吃？成都火锅节10月1日开幕", "source": "抖音同城热榜",
         "heat_48h": 88000, "same_city_videos": 60, "match": 0.85, "hours_since": 40},
        {"title": "成都首家悬崖观景火锅开业", "source": "大众点评热门",
         "heat_48h": 52000, "same_city_videos": 18, "match": 0.7, "hours_since": 90},
        {"title": "暴雨天躲进火锅店的人都在拍这一幕", "source": "抖音同城热榜",
         "heat_48h": 210000, "same_city_videos": 900, "match": 0.4, "hours_since": 12},
        {"title": "老板把毛肚免费续到凌晨2点的老店", "source": "小红书本地生活",
         "heat_48h": 88000, "same_city_videos": 8, "match": 0.9, "hours_since": 6},
        {"title": "上个月爆火的旋转火锅现在凉凉了", "source": "大众点评热门",
         "heat_48h": 15000, "same_city_videos": 310, "match": 0.5, "hours_since": 240},
        {"title": "七夕火锅店情侣套餐预订火了", "source": "小红书本地生活",
         "heat_48h": 41000, "same_city_videos": 25, "match": 0.8, "hours_since": 100},
    ],
}


def _minmax(vals):
    """互动量跨数量级（万到百万），用 log10 归一化避免被极值压扁。"""
    import math
    logs = [math.log10(max(v, 1)) for v in vals]
    lo, hi = min(logs), max(logs)
    if hi == lo:
        return [50.0] * len(vals)
    return [round((v - lo) / (hi - lo) * 100, 1) for v in logs]


def _competition(n):
    # <20 条满分，>200 条零分，中间线性插值
    if n <= 20:
        return 100.0
    if n >= 200:
        return 0.0
    return round((200 - n) / 180 * 100, 1)


def evaluate(payload):
    cands = payload.get("candidates", [])
    if not cands:
        raise SystemExit("[错误] candidates 为空：请提供候选热点清单（title/heat_48h/same_city_videos/match/hours_since）")
    heats = _minmax([c.get("heat_48h", 0) for c in cands])
    rows = []
    for c, h in zip(cands, heats):
        age = c.get("hours_since", 0)
        comp = _competition(c.get("same_city_videos", 0))
        match = float(c.get("match", 0)) * 100
        base = h * W_HEAT + comp * W_COMP + match * W_MATCH
        is_node = any(k in c.get("title", "") for k in NODE_KEYWORDS)
        note = ""
        if age > MAX_AGE_H and not is_node:
            note = "超7天淘汰"
        elif is_node:
            note = "节点类，提前布局"
        elif age >= 15 * 24:
            note = ""
        if c.get("same_city_videos", 0) > 500:
            note = (note + "；" if note else "") + "疑似投放/红海，竞争度已计0分"
        if is_node:
            decay = 1.0                      # 节点类不衰减
        else:
            decay = 0.6 + 0.4 * (0.5 ** (age / HALF_LIFE_H))
        final = round(base * decay, 1)
        if age > MAX_AGE_H and not is_node:
            level = "C 淘汰"
        elif final >= GRADE_A:
            level = "A 追"
        elif final >= GRADE_B:
            level = "B 观察"
        else:
            level = "C 放弃"
        rows.append({
            "选题": c.get("title", ""),
            "来源": c.get("source", ""),
            "热度分(48h)": h,
            "竞争度分": comp,
            "匹配度分": round(match, 1),
            "时效系数": round(decay, 3),
            "总分": final,
            "级别": level,
            "备注": note,
        })
    rows.sort(key=lambda r: -r["总分"])
    for i, r in enumerate(rows, 1):
        r["#"] = i
    top3 = [r for r in rows if r["级别"] == "A 追"][:3] or rows[:3]
    summary = {
        "城市": payload.get("city", ""),
        "品类": payload.get("category", ""),
        "候选条数": len(rows),
        "A级(追)": sum(1 for r in rows if r["级别"] == "A 追"),
        "B级(观察)": sum(1 for r in rows if r["级别"] == "B 观察"),
        "C级(放弃)": sum(1 for r in rows if r["级别"].startswith("C")),
        "本周建议拍摄": "；".join(r["选题"] for r in top3),
    }
    return rows, summary


def build(payload, outdir):
    rows, summary = evaluate(payload)
    at.ensure_outdir(outdir)
    xlsx = at.write_excel(
        os.path.join(outdir, "选题评估榜.xlsx"),
        {
            "选题榜": rows,
            "汇总": [{"项": k, "内容": str(v)} for k, v in summary.items()],
        },
        highlights={"选题榜": {"级别": "contains:A 追"}},
        widths={"选题榜": {"选题": 40, "来源": 16, "备注": 26}},
    )
    top10 = rows[:10]
    png = at.bar_chart(
        os.path.join(outdir, "选题得分.png"),
        [r["选题"][:12] for r in top10],
        [r["总分"] for r in top10],
        title="同城选题得分 Top10（0-100）", ylabel="选题得分", horizontal=True)
    js = at.write_json({"summary": summary, "rows": rows,
                        "formula": "0.4*热度归一 + 0.3*竞争度反向 + 0.3*匹配度, 时效半衰48h",
                        "generated_at": at.stamp(),
                        "note": "机器加权结果；匹配度标定与假阳性排除须由模型按 prompt.txt 复核"},
                       os.path.join(outdir, "hotspot_track.json"))
    return {"files": [xlsx, png, js], "summary": summary,
            "a_count": summary["A级(追)"], "rows": rows}


def main():
    ap = argparse.ArgumentParser(description="本地热点追踪 —— 选题三因子加权评分")
    ap.add_argument("--input", help="输入 JSON（city/category/candidates）")
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--demo", action="store_true", help="用内置样例跑一遍")
    a = ap.parse_args()

    payload = DEMO if a.demo else (at.read_json(a.input) if a.input else ap.error("需要 --input 或 --demo"))
    r = build(payload, a.outdir)
    print(f"候选 {r['summary']['候选条数']} 条，A 级 {r['a_count']} 条 —— 本周建议拍摄：{r['summary']['本周建议拍摄']}")
    for f in r["files"]:
        print(" 产物:", f)
    at.emit(r)


if __name__ == "__main__":
    main()
