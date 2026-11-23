# 贡献指南

谢谢愿意花时间。这个项目的价值全在「尺子准不准」，所以最欢迎的不是功能，是**误判**。

## 最有用的三种反馈

1. **这条尺子不对**：拿一份真实 BP 跑，指出某个维度分数明显偏高或偏低，并说明为什么。
2. **漏了一种病**：某种常见的 BP 问题（或红线）没被现有规则覆盖。
3. **报告读不下去**：排版、层级、信息密度上的具体问题。

提 Issue 时如果能附上脱敏后的诊断 JSON（`--public` 生成的版本），处理速度会快很多。**不要上传他人的 BP 原文。**

## 本地开发

环境：Python 3.8+，无第三方依赖。

```bash
# 渲染示例，检查改动有没有破坏版式
python scripts/render_report.py --data assets/sample-diagnosis.json --outdir /tmp/out

# 脱敏模式
python scripts/render_report.py --data assets/sample-diagnosis.json --outdir /tmp/out --public

# 语法检查
python -m py_compile scripts/render_report.py
```

改模板或渲染器之后，**至少看一眼渲染结果**：手机宽度（375–430px）下有没有横向溢出、卡片内的处方区有没有退化成多层嵌套、病情刻度条的箭头有没有落回对应等级区间。这三处是历史上反复出错的地方。

## 改评分口径的流程

评分口径（`references/scoring.md`）改动会导致**历史病历不可比**，所以：

1. 先开 Issue，说明改哪一条、为什么现在的口径不对、改动后同一份 BP 的分数会怎么变；
2. 维护者确认后再提 PR；
3. PR 里必须同步更新：`references/scoring.md`、受影响的 `SKILL.md` 段落、`CHANGELOG.md`。

只改渲染、排版、文案的 PR 不需要走这个流程，直接提。

## 提交规范

```
feat: 新增对赌条款类红线
fix: 修复窄屏下处方区溢出
docs: 补充 data_schema 的 priorities 字段说明
refactor: 抽离刻度定位函数
```

一次提交只做一件事。涉及版式的改动请附改动前后的截图。

## 不要做的事

- 不要在示例数据里填真实公司名、人名、机构名，全部用「某外资机器人企业」这类指代；
- 不要在 SKILL.md、README 或脚本里写死绝对路径（`C:/Users/xxx/...`、`/home/xxx/...`）——别人克隆后必然失效，脚本内一律用 `os.path.dirname(__file__)` 定位资源，文档里用 `$SKILL` 或相对路径；
- 不要让报告输出投资建议——这是这个项目的边界，不是待办事项；
- 不要引入第三方 Python 依赖，零依赖是刻意保持的。

## License

提交即表示同意以 [MIT](LICENSE) 协议发布你的贡献。
