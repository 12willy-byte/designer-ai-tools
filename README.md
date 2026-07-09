# 设计师 AI 辅助自动化工具

> AI 辅助室内设计师提效 —— 专注于问卷解析、素材整理、文档生成

## 核心理念

AI **辅助**设计师，而非替代设计师。
工具负责数据处理和文档生成，设计师专注于创意和判断。

## 项目结构

`
├── core/                          # 核心引擎
│   ├── data_model.py              # 统一数据模型
│   ├── ai_client.py               # 统一 LLM 客户端
│   ├── cad_reader.py              # DXF 图纸读取
│   ├── survey_parser.py           # Excel 问卷 -> 设计条件
│   └── template_generator.py      # 生成问卷 Excel 模板
│
├── modules/
│   ├── config.py                  # API 配置（环境变量）
│   ├── generate_template.py       # [旧] 问卷模板生成
│   ├── parse_survey.py            # [旧] 问卷解析
│   └── m2_concept_design/         # 概念方案（色板/材质/PPT）
│
├── templates/                     # 模板与样本数据
│   ├── 设计需求问卷模板.xlsx
│   └── *.json
│
├── docs/                          # 文档（待补充）
├── .env.example                   # 环境变量模板
├── .gitignore
└── README.md
`

## 快速开始

### 1. 配置 API 密钥

`ash
cp .env.example .env
# 编辑 .env 填入你的 DeepSeek API Key
`

### 2. 生成需求问卷

`python
from core.template_generator import generate_template
generate_template("问卷.xlsx")
`

### 3. 解析客户问卷

`python
from core.survey_parser import parse_survey, save_conditions
conditions = parse_survey("客户填写的问卷.xlsx")
save_conditions(conditions, "设计条件.json")
`

### 4. 读取 CAD 图纸

`python
from core.cad_reader import read_dxf_floor_plan
plan = read_dxf_floor_plan("原始结构图.dxf")
print(f"发现 {plan['total_lines']} 条可识别线段")
`

## AI 功能

| 功能 | 模块 | 状态 |
|------|------|:----:|
| Excel 问卷生成 | core/template_generator.py | ✅ |
| 问卷解析 → JSON | core/survey_parser.py | ✅ |
| CAD 图纸读取 | core/cad_reader.py | ✅ |
| 设计定位文案 | modules/m2_concept_design/step1 | ✅ |
| 色彩方案建议 | modules/m2_concept_design/step2 | ✅ |
| 材质方案 | modules/m2_concept_design/step3 | ✅ |
| 风格意向板 | modules/m2_concept_design/step4 | ✅ |
| 布局建议 | modules/m2_concept_design/step5 | ✅ |
| 概念PPT打包 | modules/m2_concept_design/step7 | ✅ |

## 环境变量

| 变量名 | 说明 |
|--------|------|
| DEEPSEEK_API_KEY | DeepSeek API 密钥 |
| DEEPSEEK_BASE_URL | API 地址（默认官方） |
| DASHSCOPE_API_KEY | 阿里云 DashScope 密钥（可选） |
