# GitHub 发布清单

仓库要填的每一项文案都在这里，复制粘贴即可。

---

## 仓库名

`opvc-bp-doctor`

与 WorkBuddy 技能 ID 保持一致，避免两处名字对不上。

## About（仓库简介，右上角）

**英文**（推荐，GitHub 全球可见）：

```
Score a business plan, locate what's broken, prescribe fixes. 100-point rubric, single-file HTML report + versioned record. Zero dependencies.
```

**中文**（如果你的受众主要是国内）：

```
给商业计划书打分、找病灶、开处方的开源工具。100 分制，输出 HTML 诊断报告与可版本对照的病历。
```

## Website

填公众号文章链接，或 AIOpenVC 站点。没有就留空。

## Topics（标签，12 个以内）

```
business-plan  pitch-deck  startup  venture-capital  ai-agent  llm
rubric  diagnostic  workbuddy-skill  python  html-report  due-diligence
```

## Release · v1.0.0

**Tag**：`v1.0.0`
**Title**：`v1.0.0 — 把看 BP 的判断做成可执行的尺子`

**描述**：

```markdown
首个开源版本。

**评分体系**：总分 100 = A 部分 65（项目与逻辑，9 维度）+ B 部分 35（文档质量，满分起扣）。A 部分权重按阶段与用途调整，总和恒为 100%。

**两条独立通道**：红线（每条 −10，不占维度分）与 AI 敷衍（−3 / −8 / −15，独立标注并列出文本信号）。

**交付物**：单文件 HTML 诊断报告（带 PDF 导出）+ 结构化 md 病历。复诊自动递增版本并生成逐维度对照。

**脱敏**：`--public` 按词表替换项目名、人名、机构、客户、竞品，输出可公开版本。

**零依赖**：渲染器仅用 Python 标准库。

新增示例数据（虚构工业机器人项目，61 分 · C 级）与完整渲染样例。

它不判断投不投，只判断这份 BP 作为信息传递工具做到什么程度。

**Full Changelog**: https://github.com/<your-name>/opvc-bp-doctor/blob/main/CHANGELOG.md
```

## 社交预览图

`docs/social-preview.png`（1280×640）已生成，在仓库 **Settings → General → Social preview** 上传。

---

## 首次推送

仓库目录已经 `git init` 并完成首次 commit，只需要接上远端：

```bash
cd opvc-bp-doctor    # 进入仓库根目录（本机路径按你自己的实际位置填）

# 先在 GitHub 网页上建一个空仓库（不要勾选 README / .gitignore / LICENSE）
git remote add origin https://github.com/<your-name>/opvc-bp-doctor.git
git branch -M main
git push -u origin main
```

用 SSH 的话把地址换成 `git@github.com:<your-name>/opvc-bp-doctor.git`。

## 推送后建议做的三件事

1. **开 Issue 模板**：Settings → Features → Issues → Set up templates。至少一个「尺子不准」模板，引导用户贴脱敏后的 JSON 而不是 BP 原文。
2. **打开 Discussions**（可选）：用来接「这个项目该怎么写」这类开放讨论，避免 Issue 区被提问淹没。
3. **在公众号文章里放仓库链接**，并在 README 顶部回链文章——两边互相导流。

## 注意

- 示例数据里**不能**出现真实公司名、人名、机构名。当前 `assets/sample-diagnosis.json` 与 `examples/` 下的产物均为虚构指代，可以直接公开。
- 如果后续要放真实案例，一律走 `--public` 脱敏，并人工全文搜一遍原名称再提交。
