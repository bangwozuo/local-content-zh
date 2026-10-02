# -*- coding: utf-8 -*-
"""
口播文案 + 分镜工作流 —— 端到端编排脚本。

流程（与 SKILL.md 的 DAG 一致）：
  S1 shortvideo-script-generate   口播逐字稿 + 分镜表生成
  S2 voiceover-storyboard-flow 本步  台词字数/语速/时间轴/五段占比确定性校验
  S3 multi-platform-spec-adapt    平台版本时长与调性核对
  人工确认                          逐镜对稿

本脚本承担 S2/S3 的确定性部分：**从台词原文直接数汉字**（标点不计），
校验语速 4.0-6.0 字/秒、时间轴连续无重叠、五段时长占比对照推荐区间（±3s）。

五段结构推荐（60s 基准）：钩子 3s / 场景 22s / 亮点 20s / 引导 10s / 互动 5s。

用法：
  python run_flow.py --input input.json --outdir out
  python run_flow.py --demo

产物：
  out/分镜口播校验表.xlsx   逐镜校验 + 五段占比 两 sheet
  out/分镜时长分布.png      各段时长 vs 推荐区间柱状图
  out/voiceover_flow.json  机器可读结果
"""
from __future__ import annotations

import argparse
import os
import re
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

SPEED, TOL = 5.0, 0.2
SEG_BUDGET = {"钩子": 3, "场景与菜品": 22, "亮点与价格": 20, "团购引导": 10, "结尾互动": 5}
SEG_ORDER = list(SEG_BUDGET)
PLATFORM_MAX = {"抖音": 60, "小红书": 240, "视频号": 60, "B站": 300}

DEMO = {
    "store_name": "巷口面包研究所",
    "target_duration_s": 45,
    "platforms": ["抖音", "小红书"],
    "segments": [
        {"seg": "钩子", "dur_s": 3, "line": "14点准时出炉的碱水包，去晚只能闻香味。"},
        {"seg": "场景与菜品", "dur_s": 15, "line": "巷口这家面包研究所，黄油是发酵黄油，面团每天凌晨四点起缸。碱水包表皮咬下去是脆的，里面还是软的。"},
        {"seg": "亮点与价格", "dur_s": 13, "line": "招牌碱水结6块一个，海盐卷8块，人均22就能带走一袋子。"},
        {"seg": "团购引导", "dur_s": 9, "line": "位置在巷口第一间，团购3件套29块，探店合作。"},
        {"seg": "结尾互动", "dur_s": 5, "line": "你们那儿碱水包卖多少钱一个？"},
    ],
}


def _hanzi(s):
    """台词字数：只数汉字与数字串（口播要念出来的都算），标点与空格不计。"""
    s = re.sub(r"\s", "", s or "")
    s = re.sub(r"[，。！？、：；「」…—,.!?~～]", "", s)
    return len(s)


def _s2_check(segments, target):
    rows, issues = [], []
    cursor = 0
    for seg in segments:
        name = seg.get("seg", "")
        dur = seg.get("dur_s", 0)
        line = seg.get("line", "")
        n = _hanzi(line)
        start, end = cursor, cursor + dur
        cursor = end
        if name not in SEG_BUDGET:
            issues.append(f"段落「{name}」不在五段结构内（{ '/'.join(SEG_ORDER) }）")
        if n == 0:
            speed, verdict, note = "-", "✅", "纯画面（B-roll），无口播"
        else:
            speed = round(n / dur, 2) if dur else 999
            if speed > 6.0:
                verdict = "🔴"
                over = int(n - dur * 6.0)
                note = f"{speed} 字/秒念不完，{dur}s 最多念 {int(dur*6)} 字，需删约 {over} 字"
            elif speed < 2.5 and name in ("钩子", "团购引导", "结尾互动"):
                verdict = "🟡"
                note = f"{speed} 字/秒台词过稀：该段必须持续口播，画面会掉信息"
            elif speed < 4.0:
                verdict, note = "✅", f"{speed} 字/秒，B-roll 留白正常（场景/亮点段允许）"
            else:
                verdict, note = "✅", f"{speed} 字/秒"
        if name == "钩子" and dur > 3:
            verdict, note = "🔴", f"钩子 {dur}s > 3s，完播率红线"
        if name == "钩子" and n > 15:
            verdict, note = "🔴", f"钩子 {n} 字 > 15 字，3 秒念不完"
        rows.append({"段落": name, "时间轴": f"{start}-{end}s", "时长s": dur,
                     "台词字数": n, "语速": speed, "判定": verdict, "台词": line[:24],
                     "说明": note})
        if verdict in ("🔴", "🟡"):
            issues.append(f"{name}（{start}-{end}s）：{note}")
    total = cursor
    if abs(total - target) > 2:
        issues.append(f"时间轴合计 {total}s ≠ 目标 {target}s（允许 ±2s）")
    tail = [r for r in rows if r["段落"] == "结尾互动"]
    if tail and tail[0]["时长s"] < 4:
        issues.append(f"结尾互动仅 {tail[0]['时长s']}s < 4s，提问式结尾没给观众反应时间")
    return total, rows, issues


def _segment_share(rows, target):
    """推荐区间按目标时长等比缩放（预算表为 60s 基准）。"""
    scale = target / 60.0
    agg = {}
    for r in rows:
        agg.setdefault(r["段落"], {"dur": 0, "words": 0})
        agg[r["段落"]]["dur"] += r["时长s"]
        agg[r["段落"]]["words"] += r["台词字数"] or 0
    out = []
    for seg in SEG_ORDER:
        d = agg.get(seg, {"dur": 0, "words": 0})
        budget = round(SEG_BUDGET[seg] * scale, 1)
        dev = round(d["dur"] - budget, 1)
        ok = abs(dev) <= 3
        out.append({"段落": seg, "实际时长s": d["dur"], "推荐s(按目标缩放)": budget,
                    "偏差": f"{dev:+g}s", "判定": "✅" if ok else "🔴",
                    "字数": d["words"],
                    "说明": "在 ±3s 容差内" if ok else f"偏 {dev:+g}s，超容差"})
    return out


def _s3_check(platforms, target):
    rows = []
    for p in platforms:
        mx = PLATFORM_MAX.get(p)
        if mx is None:
            rows.append({"平台": p, "时长上限": "待核对官方", "判定": "🔵", "说明": "不在常量表，发布前查官方"})
            continue
        ok = target <= mx
        rows.append({"平台": p, "时长上限": f"{mx}s", "判定": "✅" if ok else "🔴",
                     "说明": f"{target}s 成片" + ("" if ok else f" 超 {target-mx}s，需剪短或转长视频位")})
    return rows


def build(payload, outdir):
    if not payload.get("segments"):
        raise SystemExit("[错误] segments 为空：需要逐段口播稿（seg/dur_s/line），不能为空")
    total, rows, issues = _s2_check(payload["segments"], payload.get("target_duration_s", 60))
    share = _segment_share(rows, payload.get("target_duration_s", 60))
    plat = _s3_check(payload.get("platforms", ["抖音"]), payload.get("target_duration_s", 60))
    for r in plat:
        if r["判定"] == "🔴":
            issues.append(f"{r['平台']}：{r['说明']}")
    at.ensure_outdir(outdir)
    xlsx = at.write_excel(
        os.path.join(outdir, "分镜口播校验表.xlsx"),
        {"逐镜校验": rows, "五段占比": share, "平台核对": plat},
        highlights={"逐镜校验": {"判定": "contains:🔴"}, "五段占比": {"判定": "contains:🔴"}},
        widths={"逐镜校验": {"台词": 30, "说明": 40}})
    png = at.bar_chart(
        os.path.join(outdir, "分镜时长分布.png"),
        [s["段落"] for s in share],
        [s["实际时长s"] for s in share],
        title="五段时长 vs 推荐区间（±3s）", ylabel="秒")
    verdict = "打回重改" if any(i.startswith(("🔴",)) or "🔴" in i for i in issues) else \
              ("需微调" if issues else "通过")
    js = at.write_json({"verdict": verdict, "total": total, "issues": issues,
                        "rows": rows, "share": share, "generated_at": at.stamp(),
                        "note": "台词字数由脚本按汉字实数（标点不计），与人工数法可能有 ±1 字出入"},
                       os.path.join(outdir, "voiceover_flow.json"))
    print(f"校验完成 —— {verdict}（合计 {total}s，问题 {len(issues)} 项）")
    return {"files": [xlsx, png, js], "verdict": verdict, "total": total, "issues": issues}


def main():
    ap = argparse.ArgumentParser(description="口播文案+分镜工作流 —— 字数/语速/时间轴/占比校验")
    ap.add_argument("--input", help="输入 JSON（segments/target_duration_s/platforms）")
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
