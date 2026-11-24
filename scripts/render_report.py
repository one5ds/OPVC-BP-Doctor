#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BP 医生 · 渲染器
读取一个诊断结果 JSON，生成：
  1) 单文件 HTML 报告（内联 CSS/JS，含 PDF 下载 + 打印 fallback）
  2) 结构化 md 病历（含版本对照，自动匹配上一版）

用法：
  python render_report.py --data <diagnosis.json> --outdir <输出目录>

JSON 数据结构见 SKILL.md「数据结构」或 references/data_schema.md。
"""
import argparse, json, os, re, sys, html, glob, datetime, copy

# 对外展示版（脱敏）：把项目名/简称及 redactions 词表中的所有原文替换为代称。
# 词表由诊断 JSON 的 public_profile.redactions 提供；按原文长度降序替换，避免短词先命中切碎长词。
def redact_data(d, cfg=None):
    cfg = cfg or {}
    out = copy.deepcopy(d)
    short = d.get("project_short") or ""
    name = d.get("project_name") or ""
    pub_short = cfg.get("project_short") or "某项目"
    pub_name = cfg.get("project_name") or "某项目（脱敏）"
    mapping = dict(cfg.get("redactions") or {})
    if name and name != pub_name:
        mapping[name] = pub_name
    if short and short != pub_short:
        mapping[short] = pub_short
    ordered = sorted(mapping.items(), key=lambda kv: -len(str(kv[0]))) if mapping else []

    def walk(o):
        if isinstance(o, str):
            s = o
            for k, v in ordered:
                if k:
                    s = s.replace(str(k), str(v))
            return s
        if isinstance(o, list):
            return [walk(x) for x in o]
        if isinstance(o, dict):
            return {kk: (vv if kk == "public_profile" else walk(vv)) for kk, vv in o.items()}
        return o

    out = walk(out)
    out["project_short"] = pub_short
    out["project_name"] = pub_name
    out["_public_badge"] = cfg.get("badge", "对外展示版 · 已脱敏")
    return out

HERE = os.path.dirname(os.path.abspath(__file__))
TPL_HTML = os.path.join(HERE, "..", "assets", "bp-report-template.html")
TPL_MD = os.path.join(HERE, "..", "assets", "bp-record-template.md")

# 等级主色 / 总分卡片浅色底
# 全站统一「光谱过渡」：天蓝 → 绿 → 黄 → 橙 → 红 → 紫；等级 A–E 走该序列（E 取末端的紫）
GRADE_COLOR = {"A": "#1A93C9", "B": "#28A067", "C": "#C89112", "D": "#D96B25", "E": "#7A2C86"}
GRADE_TINT = {"A": "#eaf6fc", "B": "#eaf7ef", "C": "#fdf6e4", "D": "#fdf0e7", "E": "#f5ecf8"}

# 档位色：优 → 良 → 中 → 差 → 弱（光谱前五段：天蓝 / 绿 / 黄 / 橙 / 红）
TIER_RAMP = ["#1A93C9", "#28A067", "#C89112", "#D96B25", "#C13A2E"]

# B 部分满分（35 分制）：满分起扣，只记减分
B_MAX = 35.0

# 病情严重程度：等级 -> (标签, 段号1-5, 颜色, 描述)；危重取光谱末端紫
# 口径：70 分 = 合格（同行平均水平），因此「中度」对应的是「能看懂但需补证据」，不是「推倒重来」
SEVERITY = {
    "A": ("健康", 1, "#1A93C9", "逻辑、证据、表达均达专业沟通水准，无结构性病灶，可直接递交投资人。"),
    "B": ("轻度", 2, "#28A067", "核心成立，仅个别维度需补强或澄清，一两轮修改即可递出。"),
    "C": ("中度", 3, "#C89112", "骨架完整、结论基本成立，但有证据缺口或局部口径不闭合，补齐后可递；不必推倒重来。"),
    "D": ("较重", 4, "#D96B25", "存在结构性缺陷，多个核心逻辑站不住，需大修后再谈递交。"),
    "E": ("危重", 5, "#7A2C86", "无法完成让阅读者理解项目核心的基本任务，需从零重建 BP 的信息骨架。"),
}
SEV_LABELS = ["健康", "轻度", "中度", "较重", "危重"]
SEV_COLORS = ["#1A93C9", "#28A067", "#C89112", "#D96B25", "#7A2C86"]
# 五档对应的分数区间（与 scoring.md §1 等级映射严格一致），用于刻度标注与箭头定位
# 校准基线：常规 BP 落在 68–77（C 段中位数 70），故 C 段是五档里唯一为「补齐即可」的区间
SEV_BANDS = [(88, 100), (78, 88), (68, 78), (56, 68), (0, 56)]
SEV_RANGES = ["88–100", "78–87", "68–77", "56–67", "0–55"]

def severity_of(grade):
    return SEVERITY.get(grade_letter(grade), SEVERITY["B"])

def sev_position(total):
    """把总分换算成刻度条上的位置（百分比，左=健康/高分，右=危重/低分）。

    刻度条是按等级区间等宽划分的五档（各占 20%），因此不能用 (100-分数) 直接线性映射，
    否则 43 分会落到「中度」附近，与 D=较重 的判定自相矛盾。
    这里在每个等级区间内做线性插值，保证箭头一定落在该等级对应的那一段里。
    """
    try:
        t = float(total)
    except (TypeError, ValueError):
        t = 0.0
    t = max(0.0, min(100.0, t))
    for i, (lo, hi) in enumerate(SEV_BANDS):
        if t >= lo or i == len(SEV_BANDS) - 1:
            frac = (hi - t) / float(hi - lo)   # 0 = 段左端(高分)，1 = 段右端(低分)
            # 限幅：让箭头明显落在本段内部，不要贴在两段的分界线上
            frac = max(0.08, min(0.86, frac))
            return max(3.0, min(97.0, i * 20.0 + frac * 20.0))
    return 50.0

def sev_gauge_html(level, total=0, label=""):
    # 固定「天蓝→绿→黄→橙→红→紫」光谱刻度条 + 红色箭头标出按等级区间换算后的位置
    pos = sev_position(total)
    try:
        t = int(round(float(total or 0)))
    except (TypeError, ValueError):
        t = 0
    return ('<div class="sev-track"><div class="sev-bar">%s</div>'
            '<div class="sev-mark" style="left:%.1f%%">'
            '<div class="sev-pill">▼ 本项目 %d 分 · %s</div>'
            '<div class="sev-tip"></div></div></div>'
            % ("".join('<i style="left:%d%%"></i>' % (k * 20) for k in range(1, 5)), pos, t, e(label)))

def sev_scale_html(level):
    out = []
    for i in range(1, 6):
        on = i == level
        style = (' style="color:%s"' % SEV_COLORS[i - 1]) if on else ""
        out.append('<span%s%s>%s<em>%s 分</em></span>'
                   % (' class="on"' if on else "", style, SEV_LABELS[i - 1], SEV_RANGES[i - 1]))
    return "".join(out)

def e(s):
    """HTML 转义。"""
    return html.escape("" if s is None else str(s), quote=True)

def to_pct(score):
    """把 0–10 的维度分换算成百分制整数（7 → 70）。"""
    try:
        return int(round(float(score) * 10))
    except (TypeError, ValueError):
        return 0

def tier_of(score):
    """维度档位：阈值与总分等级区间同刻度（88/78/68/56 分），7.0 = 合格而非优秀。"""
    try:
        s = float(score)
    except (TypeError, ValueError):
        s = 0
    if s >= 8.8: return "优", TIER_RAMP[0]
    if s >= 7.8: return "良", TIER_RAMP[1]
    if s >= 6.8: return "合格", TIER_RAMP[2]
    if s >= 5.6: return "偏弱", TIER_RAMP[3]
    if s >= 1: return "差", TIER_RAMP[4]
    return "缺项", "#8a94a3"

def grade_of_total(total):
    """总分 -> 等级字母，区间与 scoring.md §1 / SEV_BANDS 严格一致（88/78/68/56 分界）。"""
    try:
        t = float(total)
    except (TypeError, ValueError):
        t = 0
    if t >= 88: return "A"
    if t >= 78: return "B"
    if t >= 68: return "C"
    if t >= 56: return "D"
    return "E"

def grade_letter(grade):
    m = re.match(r"\s*([A-E])", grade or "")
    return m.group(1) if m else "B"

def verification_tag(text):
    """返回 (显示文本, 是否警示)。"""
    t = (text or "").strip()
    if not t:
        return "未核验", False
    if "出入" in t:
        return "🔍 " + t, True
    if "无法验证" in t or "未验证" in t:
        return t, False
    return "🔍 " + t, False

# ---------- HTML 片段构建 ----------

def build_warning_strips(d):
    strips = []
    if d.get("meta_missing"):
        strips.append(
            '<div class="strip strip-info"><strong>元信息缺失，置信度受限</strong>'
            '行业 / 阶段 / 用途无法从文本判断，分数置信度下降；补全信息后分数可能变化。</div>'
        )
    redlines = d.get("redlines") or []
    if redlines:
        items = "".join("<li>%s</li>" % e(x) for x in redlines)
        strips.append(
            '<div class="strip strip-redline"><strong>红线命中 · A 部分额外 −10 / 条</strong>'
            '<ul>%s</ul></div>' % items
        )
    ai = d.get("ai") or {}
    level = int(ai.get("level", 0) or 0)
    if level > 0:
        signals = "".join("<li>%s</li>" % e(x) for x in (ai.get("signals") or []))
        strips.append(
            '<div class="strip strip-ai"><strong>AI 通道 · %s −%s</strong>%s</div>'
            % (e(ai.get("label", "")), e(ai.get("deduct", 0)),
               ("<ul>%s</ul>" % signals) if signals else "")
        )
    return ('<div class="warning-area">%s</div>' % "\n".join(strips)) if strips else ""

def build_ai_inline(d):
    ai = d.get("ai") or {}
    if int(ai.get("level", 0) or 0) >= 3:
        return '<div class="ai-flag-inline">⚠ AI 敷衍重扣</div>'
    return ""

def build_overview_rows(dims):
    """评分总览：每项固定三段（名称 + 档位 + 分数 / 评分条 / 一句话问题）。

    不再用固定像素列宽 + 左缩进的多列网格——那在手机上会把维度名挤成两行、
    把问题文字压进右侧窄栏，看起来「分太碎」。这里全部改为流式布局，窄屏自然堆叠。
    """
    rows = []
    for dm in dims:
        s = dm.get("score", 0)
        tier, color = tier_of(s)
        pct = to_pct(s)
        rows.append(
            '<div class="ov-row">'
            '<div class="ov-top">'
            '<span class="ov-name">%s</span>'
            '<span class="ov-tier" style="background:%s">%s</span>'
            '<span class="ov-score" style="color:%s"><b>%d</b><i>/100</i></span>'
            '</div>'
            '<div class="bar-track"><div class="bar-fill" style="width:%d%%;background:%s"></div></div>'
            '<div class="ov-problem">%s</div>'
            '</div>' % (e(dm.get("name", "")), color, e(tier), color, pct, pct, color,
                        e(dm.get("problem", "")))
        )
    return "\n".join(rows)

def build_dim_cards(dims):
    cards = []
    for dm in dims:
        s = dm.get("score", 0)
        tier, color = tier_of(s)
        # 子项分（宏观政策三子项）
        sub = ""
        if dm.get("subscores"):
            spans = "".join("<span>%s：<b>%s</b></span>" % (e(k), e("%d/100" % to_pct(v))) for k, v in dm["subscores"].items())
            sub = '<div class="subscore"><b>子项打分</b> &nbsp;%s</div>' % spans
        # 核验标记
        vtxt, vwarn = verification_tag(dm.get("verification", ""))
        vtag = '<span class="vtag%s">%s</span>' % (" warn" if vwarn else "", e(vtxt))
        # 诊断区：临床依据
        evidence = ('<div class="dim-block"><div class="blk-t"><span class="k">诊断</span>临床依据（BP 位置 / 原句）</div>'
                    '<div class="evidence">%s</div></div>' % e(dm.get("evidence", "信息缺失")))
        # 诊断区：待核实要点
        qlis = "".join("<li>%s</li>" % e(x) for x in (dm.get("questions") or []))
        qblock = ('<div class="dim-block"><div class="blk-t"><span class="k">问诊</span>待核实要点</div>'
                  '<ul class="q-list">%s</ul></div>' % qlis) if qlis else ""
        # 处方区：与诊断区明确区分
        rx = []
        for i, p in enumerate(dm.get("prescriptions") or [], 1):
            rx.append(
                '<div class="rx-item">'
                '<div class="rx-h"><span class="n">%d</span>%s</div>'
                '<div class="rx-line"><b>处方内容（改什么）：</b>%s</div>'
                '<div class="rx-line"><b>施治方法（怎么改）：</b>%s</div>'
                '<div class="rx-line pass"><b>疗效标准（什么算过关）：</b>%s</div>'
                '</div>' % (i, e(p.get("title", "")), e(p.get("what", "")),
                            e(p.get("how", "")), e(p.get("pass", "")))
            )
        rxblock = ""
        if rx:
            rxblock = ('<div class="rx-zone" style="--rx-color:%s">'
                       '<div class="rx-band"><span class="rt"><span class="rx-sym">℞</span>处方 · PRESCRIPTION</span></div>'
                       '%s</div>' % (color, "".join(rx)))
        cards.append(
            '<div class="dim-card" style="--tier-color:%s">'
            '<div class="dim-head"><div class="dim-title"><span class="dt-dot"></span>%s</div>'
            '<div class="dim-meta">%s<span class="dim-tier">%s</span><span class="dim-score">%d / 100</span></div></div>'
            '%s%s%s%s</div>' % (color, e(dm.get("name", "")), vtag, e(tier), to_pct(s),
                                evidence, sub, qblock, rxblock)
        )
    return "\n".join(cards)

def badge_html(d):
    """标题下方的徽章：对外展示版优先，其次是自定义 badge（如「报告范本」）。"""
    if d.get("_public_badge"):
        return '<div class="public-badge">%s</div>' % e(d["_public_badge"])
    if d.get("badge"):
        return '<div class="public-badge">%s</div>' % e(d["badge"])
    return ""

def build_followups(d):
    items = list(d.get("followups") or [])
    if d.get("meta_missing") and not any("行业" in x or "阶段" in x for x in items):
        items.insert(0, "补充行业、项目类型、阶段与 BP 用途（元信息缺失，直接影响权重与置信度）。")
    lis = "".join("<li>%s</li>" % e(x) for x in items)
    if not lis:
        lis = "<li>无（信息充分）。</li>"
    return '<ul class="plain-list">%s</ul>' % lis

PRIO_COLORS = ["#C13A2E", "#D96B25", "#C89112", "#28A067", "#1A93C9"]

def build_priorities(d):
    items = []
    for i, p in enumerate(d.get("priorities") or [], 1):
        pc = PRIO_COLORS[(i - 1) % len(PRIO_COLORS)]
        items.append(
            '<div class="prio-item" style="--pc:%s"><div class="prio-n">%d</div><div class="prio-body">'
            '<div class="prio-title">%s</div>'
            '<div class="prio-impact">预期疗效（分数影响）：%s（估计值，非承诺）</div>'
            '</div></div>' % (pc, i, e(p.get("title", "")), e(p.get("impact", "")))
        )
    return "\n".join(items) if items else '<ul class="plain-list"><li>无。</li></ul>'

def build_verification_list(d):
    items = "".join("<li>%s</li>" % e(x) for x in (d.get("verification_summary") or []))
    if not items:
        items = "<li>无可核验项或未能联网核验（均已在对应维度标注「无法验证」）。</li>"
    return '<ul class="plain-list">%s</ul>' % items

def fmt1(v):
    """一位小数，去掉无意义的 .0（5.7 / 20 / 0）。"""
    s = "%.1f" % float(v)
    return s[:-2] if s.endswith(".0") else s

def build_b_part(d):
    """B 部分（BP 作为沟通工具的质量）：**满分 35 起扣**，只列已触发的减分项。

    口径：`B = 35 − Σ减分`，不设基准分、不设加分项。
    - 未触发的检查项（points=0）不进入报告，避免读者在「0 分占位」上浪费时间；
      六类里没出现的类别，就是通过检查的类别。
    - 对外一律换算为百分制（原始 35 分制 × 100/35），并保留一行原始口径便于回溯。
    """
    b = d.get("b_part") or {}
    if not b:
        return '<div class="bcard" style="padding:16px 20px;color:#8a94a3">未提供 B 部分明细。</div>'
    K = 100.0 / B_MAX
    deducts = [x for x in (b.get("deducts") or []) if abs(float(x.get("points", 0) or 0)) > 0]
    dsum = sum(abs(float(x.get("points", 0) or 0)) for x in deducts)
    raw = max(0.0, min(B_MAX, B_MAX - dsum))
    pct = raw * K

    rows = []
    for x in deducts:
        t = (x.get("type") or "其他").strip()
        pt = abs(float(x.get("points", 0) or 0))
        rows.append(
            '<li class="brow"><span class="btag">%s</span>'
            '<span class="btext">%s</span>'
            '<span class="bps">−%s</span></li>' % (e(t), e(x.get("note") or ""), fmt1(pt * K))
        )
    body = "".join(rows) if rows else (
        '<li class="brow empty">品牌 / 排版 / 缺项 / AI 味 / 表达 / 逻辑 六类均未触发减分，本项满分。</li>')

    formula = '满分 %s － 减分 <em>%s</em> ＝ %s / 100' % (fmt1(100.0), fmt1(dsum * K), fmt1(pct))
    rail = '原始 35 分制：35 － %g ＝ %g / 35' % (dsum, raw)
    cnt = ('共 <b>%d</b> 项 · 合计 <b>−%s</b> / 100' % (len(deducts), fmt1(dsum * K))) if rows \
        else '无减分项'

    ap = d.get("a_part") or {}
    comp = ""
    if ap:
        try:
            asc = float(ap.get("score", 0) or 0)
            comp = ('<div class="bcomp">总分 ＝ A 部分 <b>%s</b> / 100 × 65%% ＋ B 部分 <b>%s</b> / 100 × 35%%'
                    ' ＝ <b class="bcomp-t">%d / 100</b></div>'
                    % (fmt1(asc / 65.0 * 100.0), fmt1(pct), int(round(asc + raw))))
        except (TypeError, ValueError):
            comp = ""
    return (
        '<div class="bcard">'
        '<div class="bcard-top">'
        '<div class="bnum"><span>%d</span><i>/100</i></div>'
        '<div class="bmeta"><div class="bformula">%s</div>'
        '<div class="brail">%s</div>'
        '<div class="bhint">%s</div></div>'
        '</div>%s'
        '<div class="bminus-t">已触发减分项 · DEDUCTIONS<span class="cnt">%s</span></div>'
        '<ul class="bminus-list">%s</ul>'
        '</div>' % (
            int(round(pct)), formula, e(rail),
            e(b.get("note") or "B 部分只扣「这份文档本身」的问题（呈现、自洽、完整度），不重复扣项目质地。"),
            comp, cnt, body)
    )

def render_html(d):
    with open(TPL_HTML, "r", encoding="utf-8") as f:
        tpl = f.read()
    short = d.get("project_short") or d.get("project_name") or "项目"
    date = d.get("date") or datetime.date.today().isoformat()
    datec = date.replace("-", "")
    grade = d.get("grade") or "B · 小修可用"
    gl = grade_letter(grade)
    sev_label, sev_level, sev_color, sev_desc = severity_of(grade)
    mapping = {
        "{{PROJECT_NAME}}": e(d.get("project_name") or short),
        "{{PROJECT_SHORT}}": e(short),
        "{{DATE}}": e(date),
        "{{PDF_FILENAME}}": e("BP诊断报告_%s_%s%s.pdf" % (short, datec, "_对外展示版" if d.get("_public_badge") else "")),
        "{{GRADE_COLOR}}": GRADE_COLOR.get(gl, "#1A93C9"),
        "{{GRADE_TINT}}": GRADE_TINT.get(gl, "#eaf6fc"),
        "{{SEV_COLOR}}": sev_color,
        "{{SEV_LABEL}}": e(sev_label),
        "{{SEV_GAUGE}}": sev_gauge_html(sev_level, d.get("total", 0), sev_label),
        "{{SEV_SCALE}}": sev_scale_html(sev_level),
        "{{SEV_DESC}}": e(sev_desc),
        "{{TOTAL}}": e(int(round(float(d.get("total", 0))))),
        "{{GRADE}}": e(grade),
        "{{DIAGNOSIS}}": e(d.get("diagnosis", "")),
        "{{AI_INLINE}}": build_ai_inline(d),
        "{{PUBLIC_BADGE}}": badge_html(d),
        "{{WARNING_STRIPS}}": build_warning_strips(d),
        "{{OVERVIEW_ROWS}}": build_overview_rows(d.get("dimensions") or []),
        "{{B_PART_BODY}}": build_b_part(d),
        "{{DIMENSION_CARDS}}": build_dim_cards(d.get("dimensions") or []),
        "{{FOLLOWUP_LIST}}": build_followups(d),
        "{{PRIORITY_LIST}}": build_priorities(d),
        "{{VERIFICATION_LIST}}": build_verification_list(d),
    }
    for k, v in mapping.items():
        tpl = tpl.replace(k, v)
    return tpl

# ---------- MD 病历构建 ----------

def find_prev_record(outdir, short, suffix=""):
    pattern = os.path.join(outdir, "BP病历_%s_*_v*%s.md" % (short, suffix))
    files = glob.glob(pattern)
    def ver(p):
        m = re.search(r"_v(\d+)(?:_[^/]*)?\.md$", p)
        return int(m.group(1)) if m else 0
    return max(files, key=ver) if files else None

def scoring_version():
    """从本技能 SKILL.md 的 frontmatter 读取版本号，作为病历的「标尺版本」。

    评分口径一旦改动，新旧病历的分数就不在同一把尺子上；把版本号写进病历，
    复诊时才能判断「分数变化」是真进步还是换尺子造成的。
    """
    try:
        with open(os.path.join(HERE, "..", "SKILL.md"), "r", encoding="utf-8") as f:
            head = f.read(1200)
        m = re.search(r'^version:\s*"?([0-9]+\.[0-9]+\.[0-9]+)', head, re.M)
        return m.group(1) if m else ""
    except OSError:
        return ""

def parse_prev(path):
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as f:
        txt = f.read()
    m = re.search(r"^(\d+)\s*/\s*100", txt, re.M)
    total = int(m.group(1)) if m else None
    gm = re.search(r"等级\s+([A-E][^\n]*)", txt)
    grade = gm.group(1).strip() if gm else None
    scores = {}
    for line in txt.splitlines():
        # 兼容两种表体：百分制「| 团队 | 80/100 | …」与旧口径「| 团队 | 8.0 | …」
        mm = re.match(r"^\|\s*([^|]+?)\s*\|\s*(\d+(?:\.\d+)?)(?:\s*/\s*100)?\s*\|", line)
        if mm and mm.group(1).strip() not in ("维度", "---"):
            scores[mm.group(1).strip()] = float(mm.group(2))
    ver = 1
    vm = re.search(r"_v(\d+)(?:_[^/]*)?\.md$", os.path.basename(path))
    if vm:
        ver = int(vm.group(1))
    # 百分制标记：新病历表头含「百分制」，旧病历为 0–10 制，对照时需 ×10 归一
    is_pct = "百分制" in txt
    sm = re.search(r"标尺版本：v?([0-9]+\.[0-9]+\.[0-9]+)", txt)
    return {"total": total, "grade": grade, "scores": scores, "version": ver,
            "path": path, "pct": is_pct, "scale": (sm.group(1) if sm else None)}

def prev_score_pct(prev, name):
    """把上一版维度分统一成百分制；旧版为 0–10 制则 ×10。"""
    v = prev["scores"].get(name)
    if v is None:
        return None
    return int(round(v)) if prev.get("pct") else int(round(v * 10))

def render_md(d, prev):
    with open(TPL_MD, "r", encoding="utf-8") as f:
        tpl = f.read()
    short = d.get("project_short") or d.get("project_name") or "项目"
    date = d.get("date") or datetime.date.today().isoformat()
    newver = (prev["version"] + 1) if prev else 1
    total = int(round(float(d.get("total", 0))))
    grade = d.get("grade") or "B · 小修可用"

    # 红线 / AI 标注
    flags = []
    if d.get("redlines"):
        flags.append("红线：%s" % "；".join(d["redlines"]))
    ai = d.get("ai") or {}
    if int(ai.get("level", 0) or 0) > 0:
        flags.append("AI 通道：%s −%s（%s）" % (ai.get("label", ""), ai.get("deduct", 0), "；".join(ai.get("signals") or [])))
    flag_str = "有 · " + " | ".join(flags) if flags else "无"

    # 维度表（百分制）
    rows = []
    for dm in d.get("dimensions") or []:
        tier, _ = tier_of(dm.get("score", 0))
        rows.append("| %s | %d/100 | %s | %s |" % (dm.get("name", ""), to_pct(dm.get("score", 0)), tier, dm.get("problem", "")))
    dim_rows = "\n".join(rows)

    # 药方摘要
    rx = []
    for dm in d.get("dimensions") or []:
        for p in dm.get("prescriptions") or []:
            rx.append("1. **%s · %s**：改什么=%s；怎么改=%s；过关标准=%s" %
                      (dm.get("name", ""), p.get("title", ""), p.get("what", ""), p.get("how", ""), p.get("pass", "")))
    rx_str = "\n".join(rx) if rx else "无。"

    # 追问
    fus = list(d.get("followups") or [])
    if d.get("meta_missing") and not any("行业" in x or "阶段" in x for x in fus):
        fus.insert(0, "补充行业、项目类型、阶段与 BP 用途。")
    fu_str = "\n".join("- [ ] " + x for x in fus) if fus else "- [ ] 无"

    # B 部分（BP 本体质量）：满分 35 起扣，只列已触发的减分项（百分制展示）
    b = d.get("b_part") or {}
    if b:
        K = 100.0 / B_MAX
        deducts = [x for x in (b.get("deducts") or []) if abs(float(x.get("points", 0) or 0)) > 0]
        dsum = sum(abs(float(x.get("points", 0) or 0)) for x in deducts)
        braw = max(0.0, min(B_MAX, B_MAX - dsum))
        bpct = braw * K
        bl = ["## B 部分（BP 本体质量）· 满分起扣 · 百分制",
              "满分 %s － 减分 %s ＝ **%s / 100**（原始 35 分制：35 － %g ＝ %g / 35）"
              % (fmt1(100.0), fmt1(dsum * K), fmt1(bpct), dsum, braw),
              "", "| 减分项 | 说明 | 分（百分制） |", "|---|---|---|"]
        if deducts:
            for x in deducts:
                pv = abs(float(x.get("points", 0) or 0))
                bl.append("| %s | %s | －%s |" % (x.get("type", ""), x.get("note", ""), fmt1(pv * K)))
        else:
            bl.append("| — | 六类均未触发减分 | 0 |")
        if b.get("note"):
            bl += ["", "> " + b["note"]]
        b_str = "\n".join(bl)
    else:
        b_str = "未提供 B 部分明细。"

    # 外部核验
    ver_str = "\n".join("- " + x for x in (d.get("verification_summary") or [])) or "- 无可核验项"

    mapping = {
        "{{PROJECT_SHORT}}": short,
        "{{DATE}}": date,
        "{{VERSION}}": str(newver),
        "{{SCORING_VERSION}}": scoring_version() or "—",
        "{{PUBLIC_NOTE}}": (
            ("- 发布属性：**%s**，项目名 / 人名 / 机构名已按词表脱敏。\n" % d["_public_badge"])
            if d.get("_public_badge")
            else (("- 发布属性：**%s**\n" % d["badge"]) if d.get("badge") else "")),
        "{{META}}": d.get("meta", "缺失"),
        "{{TOTAL}}": str(total),
        "{{GRADE}}": grade,
        "{{FLAGS}}": flag_str,
        "{{DIMENSION_ROWS}}": dim_rows,
        "{{B_PART}}": b_str,
        "{{PRESCRIPTIONS}}": rx_str,
        "{{FOLLOWUPS}}": fu_str,
        "{{VERIFICATION}}": ver_str,
    }
    out = tpl
    for k, v in mapping.items():
        out = out.replace(k, v)

    # 版本对照章节（百分制）
    if prev:
        cur_scale = scoring_version()
        comparable = bool(cur_scale) and prev.get("scale") == cur_scale
        cmp_rows = []
        for dm in d.get("dimensions") or []:
            name = dm.get("name", "")
            new = to_pct(dm.get("score", 0))
            old = prev_score_pct(prev, name)
            if old is None:
                cmp_rows.append("| %s | — | %d/100 | 新增 | 新增 |" % (name, new))
            elif not comparable:
                # 跨标尺版本：分数不同源于尺子不同，不呈现涨跌，只留分数备查
                cmp_rows.append("| %s | %d/100 | %d/100 | 不可比 | — |" % (name, old, new))
            else:
                delta = new - old
                sign = ("+%d" % delta) if delta > 0 else ("%d" % delta)
                solved = "是" if delta >= 15 else ("部分" if delta > 0 else ("否" if delta == 0 else "倒退"))
                cmp_rows.append("| %s | %d/100 | %d/100 | %s | %s |" % (name, old, new, sign, solved))

        scale_note = ""
        if not comparable:
            scale_note = ("> ⚠ **标尺版本不同**（v%s → v%s）：两次诊断使用的评分口径不一致，"
                          "分数与维度变化**不可直接比较**（下表「变化」列已置为不可比），"
                          "只能核对「上一版的问题项是否已消除」。\n\n"
                          % (prev.get("scale") or "未标注 · v1.1.0 之前", cur_scale or "当前"))
        oldt = prev["total"] if prev["total"] is not None else "—"
        dtot = total - prev["total"] if prev["total"] is not None else None
        dtot_s = ("+%d" % dtot) if (dtot is not None and dtot > 0) else (str(dtot) if dtot is not None else "—")
        unresolved = d.get("unresolved_high_priority") or ["见上一版优先级清单，逐条核对是否达标。"]
        # 跨标尺时总分差同样不可比，改为并列展示
        tot_line = ("总分：%s → %d（变化 %s）" % (oldt, total, dtot_s)) if comparable \
            else ("总分：%s → %d（跨标尺版本，不计算变化）" % (oldt, total))
        block = (
            "\n## 版本对照（v%d → v%d）\n%s"
            "| 维度 | 旧分 | 新分 | 变化 | 上一版核心问题是否解决 |\n"
            "|---|---|---|---|---|\n%s\n\n"
            "%s\n"
            "等级：%s → %s\n"
            "**仍未解决的高优先级问题：**\n%s\n"
            % (prev["version"], newver, scale_note, "\n".join(cmp_rows), tot_line,
               prev["grade"] or "—", grade,
               "\n".join("%d. %s" % (i, x) for i, x in enumerate(unresolved, 1)))
        )
        out = out.replace("## 外部核验标记", block + "\n## 外部核验标记")
    return out, newver

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="诊断结果 JSON 文件路径")
    ap.add_argument("--outdir", required=True, help="输出目录")
    ap.add_argument("--public", action="store_true", help="生成脱敏的对外展示版（项目名/人名/机构等按 public_profile.redactions 替换）")
    args = ap.parse_args()

    with open(args.data, "r", encoding="utf-8") as f:
        d = json.load(f)

    # 标尺一致性守卫：总分与 grade 字段必须落在同一区间，否则提示（不阻断渲染）
    try:
        exp = grade_of_total(d.get("total"))
        if exp != grade_letter(d.get("grade")):
            sys.stderr.write(
                "⚠ 等级与总分不一致：总分 %s 应属 %s 级，JSON 写的是「%s」。请按 scoring.md §1 校正。\n"
                % (d.get("total"), exp, d.get("grade")))
    except Exception:
        pass

    os.makedirs(args.outdir, exist_ok=True)

    suffix = ""
    if args.public:
        d = redact_data(d, d.get("public_profile") or {})
        suffix = "_对外展示版"

    short = d.get("project_short") or d.get("project_name") or "项目"
    date = d.get("date") or datetime.date.today().isoformat()
    datec = date.replace("-", "")

    prev = parse_prev(find_prev_record(args.outdir, short, suffix))
    md, newver = render_md(d, prev)

    html_path = os.path.join(args.outdir, "BP诊断报告_%s_%s%s.html" % (short, datec, suffix))
    md_path = os.path.join(args.outdir, "BP病历_%s_%s_v%d%s.md" % (short, datec, newver, suffix))

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(render_html(d))
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    print(json.dumps({
        "html": html_path,
        "md": md_path,
        "version": newver,
        "prev_version": prev["version"] if prev else None,
        "total": d.get("total"),
        "grade": d.get("grade"),
    }, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
