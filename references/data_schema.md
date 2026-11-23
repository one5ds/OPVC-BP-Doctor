# 诊断结果 JSON 数据结构（供 render_report.py 消费）

完成诊断后，先把结论整理成一个 JSON 文件（任意路径，如 `bp_data.json`），再运行渲染脚本：
```
python scripts/render_report.py --data <json路径> --outdir <输出目录>
```
渲染器负责所有 HTML/MD 拼装、版本对照与文件命名。正文内容一律由诊断阶段填入 JSON；**不要手写 HTML 片段**。

## 顶层字段

| 字段 | 类型 | 说明 |
|---|---|---|
| project_name | string | 项目全称（用于标题） |
| project_short | string | 项目简称（用于文件名，避免空格与特殊符号） |
| date | string | 诊断日期 `YYYY-MM-DD` |
| badge | string | 可选。标题下方的自定义徽章，如「报告范本 · 虚构示例」；`--public` 时被脱敏徽章覆盖 |
| meta | string | 「行业 / 项目类型 / 阶段 / BP 用途」一行文本 |
| meta_missing | bool | 行业/阶段/用途无法判断时为 true，触发警示条与追问 |
| total | number | 总分 0–100（A 折算 + B） |
| grade | string | 如 `C · 需大修`（等级字母决定主色） |
| diagnosis | string | 诊断结论，2–3 句、约 60–140 字的医疗口吻（先定性病象、再说后果与建议） |
| redlines | string[] | 命中的红线描述，每条自动 −10 已在总分内体现；留空数组表示无 |
| a_part | object | A 部分合成，见下（用于报告中「A ＋ B ＝ 总分」的核对行） |
| b_part | object | B 部分减分明细，见下（**必填**，报告单独成节展示） |
| ai | object | AI 敷衍通道，见下 |
| dimensions | object[] | 各维度诊断，见下（建议含 A 部 9 项 + 宏观政策三子项见某维度 subscores） |
| followups | string[] | 追问清单，按影响分数排序 |
| priorities | object[] | 修改优先级 3–5 条，见下 |
| verification_summary | string[] | 外部核验标记汇总 |
| unresolved_high_priority | string[] | 仅再诊断时需要：仍未解决的高优先级问题 |
| public_profile | object | 可选。仅 `--public` 脱敏模式读取，见下 |

## a_part / b_part 对象（分数合成与 B 部分明细）

`a_part`：

| 字段 | 类型 | 说明 |
|---|---|---|
| score | number | A 部分折算后得分（0–65，已含红线扣分） |
| note | string | 可选，如「含红线 −10；权重已按有收入 + To VC 调整」 |

`b_part`（**满分 35 起扣，只记减分**）：

| 字段 | 类型 | 说明 |
|---|---|---|
| deducts | object[] | 减分项：`{"type":"逻辑","points":11,"note":"证据（页号/原句）"}`，`points` 填正数（渲染时显示为 −N），**只填真正触发扣分的项**，未触发的类别直接不写 |
| base | number | 可选，仅为兼容旧数据保留；渲染时忽略，恒按满分 35 起扣 |
| note | string | 可选，说明扣分边界 |

- **不再有加分项**（`bonus` 字段已废弃，传了也会被忽略）；`total` 由渲染器按 `35 − Σpoints` 推出，不要手填。
- 减分项 `type` 必须落在六类内：`品牌` / `排版` / `缺项` / `AI 味` / `表达` / `逻辑`。六类都要在心里逐类检查，但**只写扣分的那些**；未触发的类别不出现在报告里，不要写 `"points": 0` 的占位项。
- 分值与量程见 `scoring.md` §5.1（35 分制）；渲染器自动折算百分制展示。

```json
"a_part": {"score": 28.4, "note": "含红线 −10"},
"b_part": {
  "deducts": [
    {"type": "逻辑", "points": 11, "note": "营收口径三版互斥（正文 3000 万 / 图表 5.28 亿 / 公开报道约 5 亿），未解释"},
    {"type": "排版", "points": 5, "note": "多页整页图片化，文字不可检索复制"},
    {"type": "表达", "points": 4, "note": "财务预测只给结果不给假设，无敏感性分析"},
    {"type": "品牌", "points": 2, "note": "首屏无一句话定位，品牌资产分散"},
    {"type": "缺项", "points": 1, "note": "无独立风险与应对页、无关键假设清单"}
  ],
  "note": "B 部分满分起扣：只扣这份文档本身的问题，不重复扣项目质地。"
}
```

## public_profile 对象（对外展示版脱敏）

| 字段 | 类型 | 说明 |
|---|---|---|
| project_short | string | 对外显示简称，如 `某硅光芯片企业`（必填） |
| project_name | string | 对外显示全称（必填） |
| redactions | object | **原文→代称**词表：项目名、创始人姓名、机构、地名、客户、竞品、投资方等。按原文长度降序替换 |
| badge | string | 可选，报告顶部标识，默认「对外展示版 · 已脱敏」 |

示例：
```json
"public_profile": {
  "project_short": "某硅光芯片企业",
  "project_name": "某硅光芯片企业 · 面向智算中心的硅光技术产业化项目",
  "redactions": {
    "示例光子科技（某地）有限公司": "某硅光芯片企业",
    "示例光子科技": "某企业", "示例光子": "该企业",
    "张三": "创始人 W", "某大学微电子所": "某国家级院所", "某地": "该地"
  },
  "badge": "对外展示版 · 已脱敏"
}
```
词表要覆盖所有可识别信息（含竞品名、投资方、地名、具体人名）；生成后须全文搜索确认无残留。脱敏只替换名称，不改分数与诊断逻辑。

## ai 对象

| 字段 | 类型 | 说明 |
|---|---|---|
| level | int | 0=无；1=局部(−3)；2=高度疑似(−8)；3=AI敷衍(−15) |
| label | string | 如 `AI 敷衍：不具备与投资人真实对话的功能` |
| deduct | int | 3 / 8 / 15 / 0 |
| signals | string[] | 命中的具体文本信号（落在文本特征，不指控作者） |

level=3 时渲染器自动在总分块加「⚠ AI 敷衍重扣」，诊断文案须含「实质内容不足以支撑一次真实融资对话，建议人工重写核心逻辑后再提交」，且 priorities 第一条必须是「人工重写核心段落」。

## dimensions 数组元素

| 字段 | 类型 | 说明 |
|---|---|---|
| name | string | 维度名（团队 / 市场与需求 / 宏观政策契合度 / …） |
| score | number | 该维度 0–10 分（渲染器自动 ×10 换算为百分制显示，档位与颜色自动判定） |
| problem | string | 一句话问题，用于总览表 |
| evidence | string | 诊断依据，引用 BP 页码/章节/原句；信息缺失则写「信息缺失」 |
| subscores | object | 可选。宏观政策契合度必填三子项：`{"方向匹配":8,"政策论证质量":4,"顺风/逆风判断":5}`（渲染器同样 ×10 显示为 80/100 等） |
| verification | string | `可追溯` / `无法验证` / `与公开信息存在出入`（渲染器自动加 🔍 与警示样式） |
| questions | string[] | 该维度下的问题（编号列表） |
| prescriptions | object[] | 药方，见下 |

## prescriptions 数组元素（每条药方）

| 字段 | 类型 | 说明 |
|---|---|---|
| title | string | 药方短标题 |
| what | string | 改什么（报告显示为「处方内容」） |
| how | string | 怎么改（报告显示为「施治方法」） |
| pass | string | 过关标准（报告显示为「疗效标准」） |

禁止「加强/完善/优化/提升」单独作动词；三项都必须写具体。

## priorities 数组元素

| 字段 | 类型 | 说明 |
|---|---|---|
| title | string | 优先级事项（含改什么） |
| impact | string | 如 `+3~5`（渲染器自动加「分（估计值，非承诺）」） |

## 打分与文案约束（仍须遵守 scoring.md）

- 总分 = A 部分九维度按调整后权重折算（满 65） + B 部分（满 35，最低 0），取整。
- A 部分宏观政策契合度取三子项算术平均参与折算，subscores 必须给出。
- 命中红线已在总分内扣分；redlines 数组仅用于展示。
- AI 通道扣分已计入 B；ai.deduct 仅用于展示。
- 每个 evidence 必须可追溯到 BP 具体位置或标记「信息缺失」。
