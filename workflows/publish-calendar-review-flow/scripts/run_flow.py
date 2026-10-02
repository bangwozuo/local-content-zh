# -*- coding: utf-8 -*-
"""
发布日历与复审工作流 —— 端到端编排脚本。

流程（与 SKILL.md 的 DAG 一致）：
  S1 local-hotspot-track          节点日历与热点对齐
  S2 multi-platform-spec-adapt    各平台槽位与规格核对
  S3 aigc-label-compliance        发布前复审（红线未清不入历）
  人工确认                          放行逐条发布

本脚本承担 S2/S3 的确定性部分：
  槽位分配：工作日午高峰 12:00 / 晚高峰 18:00，周末 11:00 / 19:00；
  每平台每天 ≤1 条（同质内容互抢流量）；节点日优先排节点内容（提前 ≤2 天）；
  复审闸门：review_status != "passed" 的内容不入历，标「待复审」。

用法：
  python run_flow.py --input input.json --outdir out
  python run_flow.py --demo

产物：
  out/发布日历.xlsx      周日历 + 复审清单 + 未入历 三 sheet
  out/publish_calendar_flow.json  机器可读结果
"""
from __future__ import annotations

import argparse
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

WEEKDAY_SLOTS = ["12:00 午高峰", "18:00 晚高峰"]
WEEKEND_SLOTS = ["11:00 午前", "19:00 晚高峰"]
DOW = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

DEMO = {
    "week_start": "2026-09-28",   # 周一
    "festival_days": [{"date": "2026-10-01", "name": "国庆", "window": [-2, 1]}],
    "contents": [
        {"id": "C1", "title": "毛肚免费续的老店", "platform": "抖音", "review_status": "passed",
         "node_hint": "", "priority": "高"},
        {"id": "C2", "title": "国庆火锅节逛吃攻略", "platform": "抖音", "review_status": "passed",
         "node_hint": "国庆", "priority": "高"},
        {"id": "C3", "title": "玉林苍蝇馆子合集", "platform": "小红书", "review_status": "passed",
         "node_hint": "", "priority": "中"},
        {"id": "C4", "title": "带爸妈吃老火锅", "platform": "视频号", "review_status": "pending",
         "node_hint": "", "priority": "中"},
        {"id": "C5", "title": "周末探店 vlog", "platform": "小红书", "review_status": "passed",
         "node_hint": "", "priority": "低"},
        {"id": "C6", "title": "旋转火锅避雷", "platform": "B站", "review_status": "failed",
         "node_hint": "", "priority": "低"},
    ],
}


def _slots_for(dow):
    return WEEKEND_SLOTS if dow >= 5 else WEEKDAY_SLOTS


def build(payload, outdir):
    week_start = payload.get("week_start", "")
    if not week_start:
        raise SystemExit("[错误] week_start 缺失：需提供周一日期（YYYY-MM-DD）")
    import datetime as dt
    try:
        d0 = dt.date.fromisoformat(week_start)
    except ValueError:
        raise SystemExit(f"[错误] week_start 格式非法：{week_start}（应为 YYYY-MM-DD 且是周一）")
    if d0.weekday() != 0:
        raise SystemExit(f"[错误] {week_start} 是{DOW[d0.weekday()]}，week_start 必须是周一")

    contents = payload.get("contents", [])
    if not contents:
        raise SystemExit("[错误] contents 为空：需要待排期内容清单（id/title/platform/review_status）")

    # S3 复审闸门
    review_rows, blocked = [], []
    for c in contents:
        status = c.get("review_status", "pending")
        review_rows.append({"内容": f"{c.get('id')} {c.get('title')}", "平台": c.get("platform"),
                            "复审状态": status,
                            "处理": "可入历" if status == "passed" else "不入历"})
        if status != "passed":
            blocked.append(f"{c.get('id')}「{c.get('title')}」复审状态 {status}，不入历（先完成合规复审）")

    # S2 槽位分配（每平台每天 ≤1 条；高优先先占晚高峰）
    eligible = [c for c in contents if c.get("review_status") == "passed"]
    prio = {"高": 0, "中": 1, "低": 2}
    eligible.sort(key=lambda c: (prio.get(c.get("priority", "中"), 1), c.get("id", "")))
    calendar = [[{"平台": "", "内容": "", "id": ""} for _ in _slots_for(d)] for d in range(7)]
    used_platform_day = set()
    unfilled = []

    fest = {f["date"]: f for f in payload.get("festival_days", [])}
    node_days, node_base = {}, {}   # off → name：窗口日 / 节点当天
    for date_s, f in fest.items():
        base = dt.date.fromisoformat(date_s)
        w0, w1 = f.get("window", [-2, 1])
        for off in range(w0, w1 + 1):
            d = base + dt.timedelta(days=off)
            if d0 <= d <= d0 + dt.timedelta(days=6):
                node_days[(d - d0).days] = f["name"]
        if d0 <= base <= d0 + dt.timedelta(days=6):
            node_base[(base - d0).days] = f["name"]

    def place(c, prefer_offsets):
        for off in prefer_offsets:
            slots = _slots_for(off)
            order = [1, 0] if c.get("priority") == "高" else [0, 1]
            for si in order:
                if si >= len(slots):
                    continue
                key = (off, c.get("platform"))
                if key in used_platform_day or calendar[off][si]["id"]:
                    continue
                calendar[off][si] = {"平台": c.get("platform"), "内容": c.get("title"),
                                     "id": c.get("id")}
                used_platform_day.add(key)
                return True
        return False

    # 节点内容先排：优先节点当天，其次前一天/后一天，再扩到窗口与全周
    node_contents = [c for c in eligible if c.get("node_hint")]
    plain = [c for c in eligible if not c.get("node_hint")]
    for c in node_contents:
        base_offs = sorted(node_base) or []
        prefer = []
        for b in base_offs:
            prefer += [b, b - 1, b + 1]
        prefer += sorted(node_days) + [o for o in range(7)]
        seen = set()
        prefer = [o for o in prefer if 0 <= o < 7 and not (o in seen or seen.add(o))]
        if not place(c, prefer):
            unfilled.append(f"{c['id']}「{c['title']}」本周槽位已满，未排入")
    for c in plain:
        if not place(c, range(7)):
            unfilled.append(f"{c['id']}「{c['title']}」本周槽位已满，未排入")

    # 出表
    cal_rows = []
    for d in range(7):
        date = (d0 + dt.timedelta(days=d)).isoformat()[5:]
        slots = _slots_for(d)
        if d in node_base:
            tag = f"（{node_base[d]}）"
        elif d in node_days:
            tag = f"（{node_days[d]}窗口）"
        else:
            tag = ""
        for si, slot in enumerate(slots):
            cell = calendar[d][si]
            cal_rows.append({"日期": f"{DOW[d]} {date}{tag}", "槽位": slot,
                             "平台": cell["平台"], "内容": cell["内容"],
                             "ID": cell["id"]})
    at.ensure_outdir(outdir)
    xlsx = at.write_excel(
        os.path.join(outdir, "发布日历.xlsx"),
        {"周日历": cal_rows, "复审清单": review_rows,
         "未入历": [{"说明": s} for s in (blocked + unfilled)] or [{"说明": "（无）"}]},
        highlights={"复审清单": {"处理": "contains:不入历"}},
        widths={"周日历": {"内容": 32}, "未入历": {"说明": 50}})
    js = at.write_json({"week_start": week_start, "calendar": cal_rows,
                        "blocked": blocked, "unfilled": unfilled,
                        "generated_at": at.stamp(),
                        "note": "槽位与闸门为确定性规则；逐条发布仍需人工放行"},
                       os.path.join(outdir, "publish_calendar_flow.json"))
    n_placed = sum(1 for r in cal_rows if r["内容"])
    print(f"排期完成：{n_placed} 条入历，{len(blocked)} 条被复审闸门拦下，{len(unfilled)} 条槽位未排")
    return {"files": [xlsx, js], "placed": n_placed, "blocked": blocked, "unfilled": unfilled}


def main():
    ap = argparse.ArgumentParser(description="发布日历与复审工作流 —— 槽位分配 + 复审闸门")
    ap.add_argument("--input", help="输入 JSON（week_start/contents/festival_days）")
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    payload = DEMO if a.demo else (at.read_json(a.input) if a.input else ap.error("需要 --input 或 --demo"))
    r = build(payload, a.outdir)
    for f in r["files"]:
        print(" 产物:", f)
    at.emit(r)


if __name__ == "__main__":
    main()
