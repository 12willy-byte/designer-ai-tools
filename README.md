# 设计师 AI 辅助自动化工具

> 一套覆盖室内设计师完整项目流程的 AI 辅助工具。

## 项目结构

```
├── modules/
│   ├── generate_template.py      # Excel 问卷模板生成器
│   └── parse_survey.py           # Excel → JSON 解析器
├── templates/
│   ├── 设计需求问卷模板.xlsx        # 空的问卷模板
│   └── 设计条件.json               # 解析后的结构化 JSON（示例）
├── docs/                         # 文档
├── .gitignore
└── README.md
```

## 7 大模块

| # | 阶段 | 状态 |
|:-:|------|:----:|
| 1 | **客户接洽与需求调研** → Excel 问卷 → JSON | ✅ 完成 |
| 2 | 概念方案设计 | ⏳ 待开发 |
| 3 | 深化方案设计 | ⏳ 待开发 |
| 4 | 施工图设计 | ⏳ 待开发 |
| 5 | 预算与报价 | ⏳ 待开发 |
| 6 | 施工跟进与项目管理 | ⏳ 待开发 |
| 7 | 软装摆场与交付 | ⏳ 待开发 |

## 使用方式

### 1. 生成问卷模板
```bash
python modules/generate_template.py
```

### 2. 客户填写后解析为 JSON（AI 输入条件）
```bash
python modules/parse_survey.py "填写后的问卷.xlsx" "输出.json"
```
