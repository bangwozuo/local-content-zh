# -*- coding: utf-8 -*-
"""
探店脚本生成工作流 —— 端到端编排脚本。

流程（与 SKILL.md 的 DAG 一致）：
  S1 shortvideo-script-generate   分镜时长预算与口播字数校验（60s 五段结构）
  S2 multi-platform-spec-adapt    多平台规格检查（画幅/时长/标题字数）
  S3 aigc-label-compliance        极限词/导流词/标注词表扫描
  人工确认                         终审 AI 标识与探店合作标注

本脚本承担三步的确定性部分：时长配平、语速匹配、标题字数、词表扫描；
「钩子台词怎么写」属模型创作，由各步 prompt.txt 完成。

用法：
  python run_flow.py --input input.json --outdir out
  python run_flow.py --demo

产物：
  out/拍摄脚本包.docx        校验报告（时长配平/语速/规格/合规 四节）
  out/分镜校验表.xlsx         逐镜头校验明细（问题行标红）
  out/storevisit_flow.json   机器可读结果
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

SPEED = 5.0          # 中文口播基准 5 字/秒
TOLERANCE = 0.2      # 语速容差 ±20%
PLATFORM_LIMITS = {"抖音": 30, "小红书": 20, "视频号": 16, "B站": 40}
FORBIDDEN = [
    (r"最好|最佳|最优|最强|最低价|最便宜|第一|TOP\s*1|冠军|唯一|独家|首创|顶级|极品|100\s*%|百分百",
     "🔴 红线", "极限词（《广告法》第九条）"),
    (r"加微信|微信号|VX|vx|扫码进群|私信领",
     "🔴 红线", "站外导流（平台社区规范）"),
    (r"降尿酸|养胃|降血压|抗癌|排毒",
     "🔴 红线", "食品功效宣称"),
    (r"手慢无|错过等一年|仅此一天",
     "🟡 警告", "虚假紧迫"),
]
REQUIRED_MARK = "探店合作"

DEMO = {
    "store_name": "玉林陈记老火锅",
    "target_duration_s": 60,
    "platforms": ["抖音", "小红书", "视频号"],
    "titles": {"抖音": "人均65的现撕毛肚老火锅我找到了", "小红书": "成都玉林火锅推荐｜人均65 现撕毛肚",
               "视频号": "带爸妈吃玉林巷子里的20年老火锅"},
    "shots": [
        {"no": 1, "dur_s": 3, "words": 14, "desc": "毛肚特写推向镜头"},
        {"no": 2, "dur_s": 4, "words": 22, "desc": "巷子口跟拍至店门"},
        {"no": 3, "dur_s": 5, "words": 26, "desc": "牛油下锅沸腾"},
        {"no": 4, "dur_s": 5, "words": 24, "desc": "毛肚夹起慢动作"},
        {"no": 5, "dur_s": 5, "words": 25, "desc": "入口反应"},
        {"no": 6, "dur_s": 3, "words": 0, "desc": "鸭血颤动特写（无口播）"},
        {"no": 7, "dur_s": 13, "words": 64, "desc": "满桌环绕报菜价"},
        {"no": 8, "dur_s": 17, "words": 82, "desc": "团购引导+探店合作标注"},
        {"no": 9, "dur_s": 5, "words": 22, "desc": "结尾提问"},
    ],
    "copy_text": ("人均65，毛肚管够的老火锅我找到了。玉林巷子口进去五十米，锅底每天现炒的牛油。"
                  "毛肚每日现撕，入口先脆后麻。人均65就能吃撑。抖音团购88元双人餐，菜单价176，"
                  "探店合作。你们那儿人均60能吃到这种毛肚吗？"),
    "ai_involved": ["AI写稿"],
    "business_type": "付费挂车",
}


def _s1_check(shots, target):
    """分镜时长配平 + 语速匹配 + 首镜钩子检查。"""
    total = sum(s.get("dur_s", 0) for s in shots)
    rows, issues = [], []
    for s in shots:
        dur, words = s.get("dur_s", 0), s.get("words", 0)
        if words == 0:
            speed, verdict, note = "-", "✅", "纯画面镜头（B-roll）"
        else:
            speed = round(words / dur, 2)
            if abs(speed - SPEED) / SPEED <= TOLERANCE:
                verdict, note = "✅", f"{speed} 字/秒，在 4.0-6.0 容差内"
            elif speed > SPEED:
                verdict, note = "🔴", f"{speed} 字/秒超上限，减 {int(words - dur * SPEED * (1 + TOLERANCE))} 字或延时长"
            else:
                verdict, note = "🟡", f"{speed} 字/秒偏慢，删画面留白或补台词"
        rows.append({"镜头": s.get("no"), "时长s": dur, "口播字数": words,
                     "语速(字/秒)": speed, "画面": s.get("desc", ""), "判定": verdict, "说明": note})
        if verdict in ("🔴", "🟡"):
            issues.append(f"镜头{s.get('no')}：{note}")
    if total != target:
        issues.append(f"分镜总时长 {total}s ≠ 目标 {target}s（允许 ±2s），需配平")
    if shots and shots[0].get("dur_s", 99) > 3:
        issues.append(f"首镜头 {shots[0]['dur_s']}s > 3s：黄金3秒必须给钩子，压缩首镜或换钩子画面")
    first = shots[0] if shots else {}
    if first and first.get("words", 0) > 15:
        issues.append(f"钩子台词 {first['words']} 字 > 15 字上限，3 秒内念不完")
    return total, rows, issues


def _s2_check(titles, platforms):
    """标题字数与平台规格检查。"""
    rows, issues = [], []
    for p in platforms:
        t = titles.get(p, "")
        limit = PLATFORM_LIMITS.get(p, 30)
        n = len(t)
        ok = 0 < n <= limit
        rows.append({"平台": p, "标题": t, "字数": n, "上限": limit, "判定": "✅" if ok else "🔴",
                     "说明": "合规" if ok else (f"超 {n - limit} 字，需压缩" if n else "缺标题")})
        if not ok:
            issues.append(f"{p} 标题 {n} 字超上限 {limit}")
    return rows, issues


def _s3_scan(text, business_type, ai_involved):
    """极限词/导流/功效词表扫描 + 标注义务检查。"""
    rows, issues = [], []
    for pat, level, rule in FORBIDDEN:
        for m in re.finditer(pat, text):
            rows.append({"级别": level, "原文片段": m.group(0), "命中规则": rule})
            issues.append(f"{level}｜{rule}｜「{m.group(0)}」")
    if business_type in ("付费挂车", "置换", "付费不挂车") and REQUIRED_MARK not in text:
        rows.append({"级别": "🔴 红线", "原文片段": "（全文未出现标注）",
                     "命中规则": "探店合作标注缺失（《互联网广告管理办法》第9条）"})
        issues.append("🔴｜全文未标「探店合作」，付费/置换探店必须标注")
    if ai_involved and ai_involved != ["无"]:
        rows.append({"级别": "🔵 提示", "原文片段": f"AI 成分：{'、'.join(ai_involved)}",
                     "命中规则": "AI 显式标识（《人工智能生成合成内容标识办法》2025-09-01）",
                     })
        issues.append("🔵｜含 AI 成分：发布时开启平台 AI 声明，AI 封面须画面内标识")
    return rows, issues


def build(payload, outdir):
    if not payload.get("shots"):
        raise SystemExit("[错误] shots 为空：S1 需要 is分镜草案（no/dur_s/words/desc），不能为空")
    total, s1_rows, issues = _s1_check(payload["shots"], payload.get("target_duration_s", 60))
    s2_rows, s2_issues = _s2_check(payload.get("titles", {}), payload.get("platforms", ["抖音"]))
    s3_rows, s3_issues = _s3_scan(payload.get("copy_text", ""), payload.get("business_type", "自费"),
                                  payload.get("ai_involved", ["无"]))
    issues += s2_issues + s3_issues
    red = sum(1 for i in issues if i.startswith("🔴"))
    at.ensure_outdir(outdir)
    xlsx = at.write_excel(
        os.path.join(outdir, "分镜校验表.xlsx"),
        {"分镜校验": s1_rows, "标题规格": s2_rows, "合规扫描": s3_rows or [{"级别": "（无命中）"}]},
        highlights={"分镜校验": {"判定": "contains:🔴"},
                    "标题规格": {"判定": "contains:🔴"},
                    "合规扫描": {"级别": "contains:红线"}},
        widths={"分镜校验": {"画面": 30, "说明": 36}, "合规扫描": {"命中规则": 40}})
    verdict = "打回重改" if red else ("可进人工终审" if issues else "通过")
    sections = [
        {"heading": "执行摘要",
         "paras": [f"《{payload.get('store_name','')}》探店脚本包校验完成：分镜 {len(payload['shots'])} 镜"
                   f"合计 {total}s，标题 {len(s2_rows)} 个，合规命中 {len(s3_rows)} 项。",
                   f"结论：{verdict}（红线 {red} 项，问题共 {len(issues)} 项）。"]},
        {"heading": "S1 时长配平与语速校验",
         "table": {"cols": ["镜头", "时长s", "口播字数", "语速", "判定", "说明"],
                   "rows": [[r["镜头"], r["时长s"], r["口播字数"], r["语速(字/秒)"], r["判定"], r["说明"]] for r in s1_rows]}},
        {"heading": "S2 多平台标题规格",
         "table": {"cols": ["平台", "标题", "字数/上限", "判定"],
                   "rows": [[r["平台"], r["标题"], f"{r['字数']}/{r['上限']}", r["判定"]] for r in s2_rows]}},
        {"heading": "S3 合规扫描",
         "table": {"cols": ["级别", "原文片段", "命中规则"],
                   "rows": [[r["级别"], r["原文片段"], r["命中规则"]] for r in s3_rows] or [["（无命中）", "", ""]]}},
        {"heading": "问题清单与整改", "bullets": issues or ["无问题，可进入人工终审"]},
        {"heading": "人工确认点",
         "bullets": ["1. 终审 AI 声明开关与画面内标识",
                     "2. 终审「探店合作」贴纸在前 3s 可见",
                     "3. 价格与划线价依据截图留存"]},
    ]
    docx = at.write_docx(os.path.join(outdir, "拍摄脚本包.docx"), "探店拍摄脚本包校验报告", sections)
    js = at.write_json({"verdict": verdict, "red": red, "issues": issues,
                        "total_duration": total, "generated_at": at.stamp(),
                        "note": "S1-S3 确定性校验为脚本输出；台词创作由各步模型按 prompt.txt 完成"},
                       os.path.join(outdir, "storevisit_flow.json"))
    return {"files": [xlsx, docx, js], "verdict": verdict, "red": red, "issues": issues}


def main():
    ap = argparse.ArgumentParser(description="探店脚本生成工作流 —— 时长/规格/合规三步校验")
    ap.add_argument("--input", help="输入 JSON（shots/titles/copy_text…）")
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    payload = DEMO if a.demo else (at.read_json(a.input) if a.input else ap.error("需要 --input 或 --demo"))
    r = build(payload, a.outdir)
    print(f"校验完成 —— {r['verdict']}（红线 {r['red']} 项，问题 {len(r['issues'])} 项）")
    for f in r["files"]:
        print(" 产物:", f)
    at.emit(r)


if __name__ == "__main__":
    main()
