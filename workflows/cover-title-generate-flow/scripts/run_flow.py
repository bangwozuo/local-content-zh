# -*- coding: utf-8 -*-
"""
封面标题生成工作流 —— 端到端编排脚本。

流程（与 SKILL.md 的 DAG 一致）：
  S1 shortvideo-script-generate   从脚本钩子段提取标题候选素材
  S2 multi-platform-spec-adapt    按平台规格生成/核对标题与封面要求
  S3 aigc-label-compliance        标题极限词扫描
  人工确认                          封面成图与标题终选

本脚本承担 S2/S3 的确定性部分：标题多候选**打分排序**——
  得分 = 2×搜索词命中 + 数字锚点(1) + 字数达标(1) - 5×极限词命中
并输出每平台 Top2 推荐与封面规格核对。

用法：
  python run_flow.py --input input.json --outdir out
  python run_flow.py --demo

产物：
  out/封面标题矩阵.xlsx    全候选打分明细 + 平台推荐 两 sheet
  out/cover_title_flow.json  机器可读结果
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

TITLE_LIMIT = {"抖音": 30, "小红书": 20, "视频号": 16, "B站": 40}
COVER_SPEC = {"抖音": "9:16 或 3:4 竖版，大字报式，标题字占画面 ≥1/3",
              "小红书": "3:4 封面（点击率命门），首图含标题字",
              "视频号": "竖版大字，去价格字（熟人场忌报价）",
              "B站": "16:9 横版，含 3 个信息点"}
HOOK_TYPES = [("价格反差", r"人均|\d+\s*元|低价|平价|便宜"),
              ("稀缺/排队", r"排队|限量|限时|最后|出炉|开业"),
              ("提问式", r"为什么|凭什么|哪一家|多少|？|\?"),
              ("过程展示", r"拉丝|爆汁|现撕|现做|浇|出炉瞬间")]
FORBIDDEN = r"最好|最佳|第一|唯一|独家|顶级|极品|100\s*%|最低价"

DEMO = {
    "store_name": "玉林陈记老火锅",
    "search_words": ["成都", "玉林", "火锅", "人均"],
    "platforms": {
        "抖音": {"candidates": ["人均65的现撕毛肚老火锅我找到了", "玉林最好吃的火锅！", "成都玉林火锅探店：现撕毛肚管够"]},
        "小红书": {"candidates": ["成都玉林火锅推荐｜人均65 现撕毛肚", "玉林巷子里的宝藏火锅店", "人均65在玉林吃到现撕毛肚火锅"]},
        "视频号": {"candidates": ["带爸妈吃玉林20年老火锅", "这家玉林火锅店排队王终于吃到了", "玉林巷子里20年的牛油老火锅"]},
    },
}


def _classify(title):
    for name, pat in HOOK_TYPES:
        if re.search(pat, title):
            return name
    return "未识别（无强钩子，建议重写）"


def _score(title, words, limit):
    hits = sum(1 for w in words if w in title)
    has_num = bool(re.search(r"\d", title))
    ok_len = 0 < len(title) <= limit
    banned = re.findall(FORBIDDEN, title)
    score = hits * 2 + (1 if has_num else 0) + (1 if ok_len else 0) - len(banned) * 5
    return hits, has_num, ok_len, banned, round(score, 1)


def build(payload, outdir):
    platforms = payload.get("platforms", {})
    if not platforms:
        raise SystemExit("[错误] platforms 为空：需要各平台标题候选清单，不能为空")
    rows, recommends, issues = [], [], []
    for plat, cfg in platforms.items():
        limit = TITLE_LIMIT.get(plat)
        words = payload.get("search_words", [])
        cands = cfg.get("candidates", [])
        if not cands:
            issues.append(f"{plat}：候选标题为空，S1/S2 未产出")
            continue
        scored = []
        for t in cands:
            hits, has_num, ok_len, banned, score = _score(t, words, limit if limit else 30)
            verdict = "🔴" if banned else ("✅" if ok_len else "🔴")
            note = []
            if limit and len(t) > limit:
                note.append(f"超 {len(t)-limit} 字")
            if banned:
                note.append(f"极限词：{'、'.join(banned)}")
            if not has_num:
                note.append("无数字锚点，信息密度低")
            if hits == 0:
                note.append("未命中搜索词")
            rows.append({"平台": plat, "标题": t, "字数": len(t),
                         "上限": limit or "待核对官方", "搜索词命中": hits,
                         "数字锚点": "有" if has_num else "无",
                         "钩子类型": _classify(t),
                         "得分": score, "判定": verdict,
                         "说明": "；".join(note) or "合规"})
            if verdict == "🔴":
                issues.append(f"{plat}「{t}」：" + "；".join(note))
            scored.append((score, t, verdict))
        scored.sort(key=lambda x: (-x[0], x[1]))
        top = [s for s in scored if s[2] == "✅"][:2] or scored[:2]
        for score, t, _ in top:
            recommends.append({"平台": plat, "推荐标题": t, "得分": score,
                               "封面规格": COVER_SPEC.get(plat, "待核对官方")})
    at.ensure_outdir(outdir)
    xlsx = at.write_excel(
        os.path.join(outdir, "封面标题矩阵.xlsx"),
        {"候选打分": rows, "平台推荐": recommends},
        highlights={"候选打分": {"判定": "contains:🔴"}},
        widths={"候选打分": {"标题": 40, "说明": 34}, "平台推荐": {"推荐标题": 40, "封面规格": 36}})
    js = at.write_json({"issues": issues, "rows": rows, "recommends": recommends,
                        "formula": "得分 = 2×搜索词命中 + 数字锚点 + 字数达标 - 5×极限词命中",
                        "generated_at": at.stamp(),
                        "note": "打分为确定性规则分；标题创意由 S1/S2 模型按 prompt.txt 生成，人工终选封面"},
                       os.path.join(outdir, "cover_title_flow.json"))
    print(f"标题 {len(rows)} 条打分完成，推荐 {len(recommends)} 条，红线问题 {sum(1 for i in issues if '极限词' in i)} 项")
    return {"files": [xlsx, js], "rows": rows, "recommends": recommends, "issues": issues}


def main():
    ap = argparse.ArgumentParser(description="封面标题生成工作流 —— 多候选打分排序")
    ap.add_argument("--input", help="输入 JSON（search_words/platforms.candidates）")
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    payload = DEMO if a.demo else (at.read_json(a.input) if a.input else ap.error("需要 --input 或 --demo"))
    r = build(payload, a.outdir)
    for x in r["recommends"]:
        print(f"  [{x['平台']}] {x['推荐标题']}（{x['得分']} 分）")
    for f in r["files"]:
        print(" 产物:", f)
    at.emit(r)


if __name__ == "__main__":
    main()
