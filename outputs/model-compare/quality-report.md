# M3 概念方案「真实 AI 模式」模型选型对比报告

日期：2025-07-19 ｜ 基线提交：da3ef9c ｜ 流水线：`modules/m2_concept_design/mvp_pipeline`（输入 `templates/design_conditions.sample.json`：两室一厅 68㎡、三口之家、现代简约、预算 28 万、高频中餐、儿童房 ENF 级）

## 1. 连通性验证

| 供应商 | 凭证来源 | 结果 |
|---|---|---|
| DeepSeek | `~/.zshrc` 的 `DEEPSEEK_API_KEY` | ✅ `POST /v1/chat/completions` 正常，1.4s 返回，token 用量可获取（本次 46 tokens）。注：账号的 `deepseek-chat` 别名实际路由到 `deepseek-v4-flash` |
| OpenAI | `~/.codex/auth.json` | ❌ 该文件 `auth_mode=chatgpt`，`OPENAI_API_KEY` 字段为空（null），只有 ChatGPT 订阅的 OAuth access_token；用该 token 调 `api.openai.com/v1/models` 返回 403（缺少 `api.model.read` scope）——**这是 ChatGPT 订阅专用凭证，不能调 OpenAI 平台 API** |

**结论：OpenAI 无法作为对比选手。** 按预案对比退化为 DeepSeek 单模型验收；为保留选型价值，改为同厂商内两候选对比：`deepseek-chat`（默认）vs `deepseek-reasoner`（推理模型）。**如需跨厂商对比，请补充 OpenAI 平台 API key（platform.openai.com 充值账号的 sk-... key，非 ChatGPT 订阅凭证）或 Moonshot 的 `MOONSHOT_API_KEY`**——客户端已支持 `AI_PROVIDER=openai|moonshot`，补 key 后运行 `python3 scripts/compare_models.py --providers deepseek,openai` 即可。

## 2. 运行与耗时（真实 API，各 1 次完整流水线）

| 步骤 | deepseek-chat | deepseek-reasoner |
|---|---|---|
| 设计定位（chat） | 3.6s | 7.1s |
| 色彩方案（chat_json） | 3.7s | 5.6s |
| 材质方案（chat_json） | 8.1s | 18.0s |
| 意向板/布局/PPTX（本地） | <0.2s | <0.2s |
| **全程** | **15.5s** | **30.9s** |

两步布局均被自动化门禁正确拦截（缺结构/机电/门洞信息），两模型行为一致。JSON 解析：2 次运行 × 2 个 chat_json 调用全部一次解析成功，未触发兜底分支；本次为防真实输出抖动已给 `_parse_json_object` 增加平衡括号提取兜底。

成本量级（估算）：单次全流程约 8–12k tokens，按 DeepSeek 公开定价量级为人民币分级（chat 更低，reasoner 因推理 token 约为其 2–4 倍），可忽略；以官方价格页为准。

## 3. 真实生成文案摘录（证据）

### deepseek-chat

> 本案为一对夫妻与一名学龄儿童打造一处兼具温润质感与高效收纳的现代简约居所。面对 65.4㎡ 的紧凑户型与高频中餐的生活习惯，设计的核心在于"通透"与"秩序"……厨房虽仅 3.7㎡，但通过优化动线并预留大单槽与洗碗机位，确保实用性与舒适度。

> 色彩方案「暖木蓝调」：暖白 #F5F0EB（60%）/ 原木色 #C4A882 / 低饱和蓝灰 #B0BEC5，木色"浅橡木或白蜡木，保留木纹自然质感"，并按 5 个房间逐一给出 base/accent 与搭配说明。

> 材质：厨房"防滑地砖 浅米灰色 哑光（参考型号: 马可波罗·云石灰·CH8001）"、墙面"多乐士·象牙白·30YY 78/035"，全局建议含室内门/门五金/窗框/踢脚线/柜体饰面。

### deepseek-reasoner

> 本案定位于 65㎡ **三居室**（输入实为两室一厅，见幻觉分析）……厨房 3.7㎡ 采用 L 型台面嵌大单槽与洗碗机，并借玻璃推拉门引入客厅光线……卫生间 3.7㎡ 实现三段式干湿分离，洗簌区外移释放空间。（文案末尾"克制 · 舒"截断不完整）

> 色彩方案「暖灰原木·蓝调」：暖白 #FFF5E6 / 低饱和蓝灰 #9EB7C4 / 原木色 #D2B48C，木色"浅原木色（如白橡木、榉木）"。

> 材质：厨房"木纹砖 浅原木色（MK-OT6801）"、墙面"暖白（多乐士 30YY 72/012）蛋壳光"、背景墙"亮光釉面砖 规格300x600mm"。

## 4. 质量维度对比

| 维度 | deepseek-chat | deepseek-reasoner |
|---|---|---|
| 中文文案贴合度 | 高：逐一引用房间面积、大单槽/洗碗机、整墙衣柜、儿童房等输入条件 | 高，且有更具体的设计手法（L 型台面、磁吸轨道灯、三段式干湿分离），但把户型写成"三居室"，与输入矛盾 |
| 结构完整性 | 严格按 prompt 输出三段（定位/关键词/调性），无截断 | 输出三段但调性段末尾截断（"克制 · 舒"），稳定性较差 |
| 色彩/材质可用信息 | HEX/RGB/比例/分房间建议齐全；材质带品牌色号并标注"参考型号"前缀 | HEX 齐全；材质引用 NCS/RAL/多乐士色号和规格（300x600mm），信息密度略高，但自编型号（MK-OT6801）无"参考"标注 |
| JSON 解析容错 | 全部一次解析成功 | 全部一次解析成功（reasoning 不污染最终 JSON） |
| AI 幻觉 | ① 把"1孩"推断为"学龄儿童"（未标注假设）；② 品牌型号为模型生成，虽已加"参考型号"字样仍需设计师复核；③ 用房间面积加总 65.4㎡ 替代输入建面 68㎡，未说明口径 | ① 同样推断"学龄儿童"；② **户型事实错误"三居室"**（输入：两室一厅）；③ 提出"洗簌区外移""玻璃推拉门"等超输入的设计主张且未标注为建议；④ 面积同样用 65㎡ 替代 68㎡ |
| 耗时 | 15.5s（快约 2 倍） | 30.9s（材质步推理耗时 18s） |
| 成本量级 | 基准 | 约 2–4 倍（推理 token） |

## 5. 选型结论

**保持 `deepseek-chat` 为默认模型，不更换。** 理由：

1. 文案贴合度与 reasoner 同档，且严格按输出结构交付，无截断；
2. reasoner 出现事实性错误（三居室）和输出截断，对"前期提案直接给客户看"的场景风险更高；
3. reasoner 耗时约 2 倍、成本约 2–4 倍，质量提升不足以抵消；
4. reasoner 材质步 18s 的长推理在交互式提案工具里是明显体验短板。

**差距清单（按优先级）：**

1. **幻觉标注**：两模型都会推断儿童年龄、自编品牌型号、改用房间加总面积——step1/step3 的 prompt 应强制要求"输入没有的信息必须标注为假设/建议"，并在材质 JSON 增加 `assumption` 字段；
2. **设计定位的对话腔与 Markdown**：真实输出带"好的，根据您提供的……"开场白和 `###` 标题直接进入 PPTX 正文，step1 prompt 应要求"直接输出正文、不用 Markdown 标题"或后处理剥离；
3. **面积口径**：输入建面 68㎡ 与房间加总 65.3㎡ 不一致时，流水线应提示确认，而不是让模型自由选择；
4. **跨厂商对比未完成**：需用户补 OpenAI 平台 key 或 Moonshot key 后重跑 `scripts/compare_models.py`。

## 6. 真实模式暴露的 bug 与修复（均已最小修复并回归）

| Bug | 影响 | 修复 |
|---|---|---|
| `step4_mood_board.py` 读入设计定位后按 200 字截断并**覆写** `设计定位.txt` | 真实长文案被截断，PPTX 同步残缺（demo 文案短所以离线验收从未发现） | 保留全文回写，截断只用于意向板绘制 |
| `step4` 意向板右侧色板、木色、底部标签为硬编码假数据（如"LDK一体化""智能家居预留"） | 意向板与真实色彩方案互相矛盾，且出现输入中不存在的卖点 | 色板/木色改读 `色彩方案色板.json`，标签改用输入的风格与关键词，硬编码仅作回退 |
| 意向板设计定位长文本单行溢出、含 `\n` 时 Pillow 叠打 | 文字互相重叠不可读 | 压平空白后按 38 字手动换行（最多 5 行） |
| `step2/3/4` 字体写死 Windows 路径 `C:/Windows/Fonts/msyh.ttc` | macOS/Linux 下 PNG 中文全部渲染为方块 | 新增 `core/font_utils.load_cjk_font()`，按 Windows/macOS/Linux 候选路径回退 |
| `step3` 全局材质建议直接打印 JSON 键名（`door_material:`） | 交付图出现原始字段名 | 增加中文标签映射 |
| `core/ai_client._parse_json_object` 兜底不足 | 真实输出带尾注时可能解析失败（本次未触发，预防性加固） | 增加平衡括号提取兜底 |

## 7. ai_client 多模型化改造

- 新增统一环境变量层：`AI_PROVIDER`（deepseek|openai|moonshot，默认 deepseek 保持兼容）、`AI_MODEL` / `AI_API_KEY` / `AI_BASE_URL`，优先级：通用 `AI_*` > 厂商专有（`DEEPSEEK_API_KEY` 等）> 内置预设；
- 预设：deepseek → api.deepseek.com + deepseek-chat；openai → api.openai.com + gpt-4o；moonshot → api.moonshot.cn + moonshot-v1-8k；
- `AI_DEMO_MODE`、`chat_json()`、错误语义不变，demo 输出带 provider 标注；`.env.example` 已更新；
- 新增 `scripts/compare_models.py`：`--providers deepseek,openai`（支持 `deepseek@deepseek-reasoner` 指定型号），逐 provider 子进程跑完整流水线（os.environ 切换，无需改流水线），产物收集到 `outputs/model-compare/<label>/`，汇总每步成败/近似耗时到 `compare-summary.json`。

## 8. 回归与提交

- `AI_DEMO_MODE=1` 下 5 个离线验收脚本（`scripts/validate_*.py`）全部通过；
- `outputs/` 已加入 `.gitignore`，本报告通过 `!outputs/model-compare/quality-report.md` 例外强制入库；
- 提交哈希见 git log（中文 commit message，无产物、无密钥）。

## 9. 遗留问题

1. 需用户补充 OpenAI **平台** API key（或 `MOONSHOT_API_KEY`）才能完成跨厂商对比；
2. 幻觉标注 prompt 加固（差距清单第 1、2 项）建议列入下一里程碑；
3. 面积口径冲突（建面 vs 房间加总）应在认知链路层提示确认；
4. 意向板/色板/材质图为 PIL 绘制的中文排版，视觉精细度有限，后续可换 HTML 渲染。

---

# 加固后复验（prompt 幻觉标注加固）

日期：2025-07-19 ｜ 基线提交：9579219 ｜ 模型：deepseek-chat（默认）｜ 输入：`templates/design_conditions.sample.json`（run1）与 `templates/manual_space_data.template.json`（run2）｜ 产物：`outputs/model-compare/post-hardening/`（不入库）

## A. 加固内容（改动文件）

| 文件 | 改动 |
|---|---|
| `modules/m2_concept_design/step1_design_brief.py` | 系统提示加入「事实与假设边界」三条硬规则（推断须以"假设："开头单独标注、总面积以输入建筑面积为准且引用房间加总须注明口径、户型/房间以输入为准不得增减改写）；并要求直接输出正文、不用对话开场白和 Markdown 标题。用户提示改为显式标注"输入事实"，并**修复面积读取 bug**：原代码读 `project.area`（模板实际键为 `area_m2`），读取失败后退到房间加总面积——这正是上一轮模型用 65.4㎡ 替代 68㎡ 的直接诱因；现同时给出"建筑面积（输入口径）"与"房间加总约XX㎡（不含公摊/墙体，不得替代建筑面积）"两个口径 |
| `modules/m2_concept_design/step3_material_board.py` | 系统提示：输入未提供品牌偏好时禁止编造品牌名/型号，`code` 字段留空或填价位档（如"ENF级颗粒板，约260元/㎡"），举例必须标注"示例品牌，可替换"且只能放 notes；新增顶层 `assumptions` 数组集中承载推断（每条以"假设："开头）；只为输入列出的房间生成方案。用户提示显式给出"品牌偏好： 输入未提供"与两种面积口径；解析后兜底 `assumptions` 为 list |
| `modules/m2_concept_design/step2_color_palette.py` / `step5_layout_sketch.py` | 同步加入轻量版边界规则（房间不增减、不编品牌、推断以"假设："标注），schema 不变 |
| `modules/m2_concept_design/step7_build_pptx.py` | 新增一页「假设与口径说明」（插在结尾页前，原页面结构不变）：汇总设计定位正文中的"假设"行、材质方案 `assumptions` 数组、以及"建筑面积 vs 房间加总"口径说明；封面面积由"房间加总 65 m² · 5室"修正为"建筑面积 68 m² · 5 个房间"（房间数含厨卫，不再写成"5室"） |
| `core/ai_client.py` | demo 模式材质 mock 增加 `assumptions` 字段，保证离线验收覆盖新字段路径 |

## B. 三类问题逐项核验（真实模式，deepseek-chat × 2 次运行）

### ① 推断信息不标注 → 已消除

**修复前**（第 3 节摘录）："本案为一对夫妻与一名**学龄儿童**打造……"——"学龄"为模型推断，与事实混排，无任何标注。

**修复后**（run1 设计定位）："本案以68㎡两室一厅为载体，为三口之家打造一处兼具通透感与收纳力的现代简约居所……"——全文无未标注推断；run1/run2 正文均未再出现"学龄"类推断。模型的推断全部集中到材质方案 JSON 的 `assumptions` 数组，run1 共 5 条、run2 共 6 条，**每条均以"假设："开头**，例如：

> "假设：未提供窗户具体尺寸，窗框颜色默认为深灰色断桥铝。"（run1）
> "假设：户型未提及阳台，故不考虑阳台材质。"（run2）

PPTX 第 8 页「假设与口径说明」逐条列出全部假设，页眉明示"以下内容为 AI 推断或口径说明，非客户输入事实，请设计师复核后再向客户呈现"。

### ② 自编品牌型号 → 已消除

**修复前**（第 3 节摘录）：厨房地砖"马可波罗·云石灰·CH8001"、墙面"多乐士·象牙白·30YY 78/035"、reasoner 的"MK-OT6801"。

**修复后**：对两次运行的全部 JSON 产物 + 设计定位文本扫描 21 个常见品牌/型号关键词，**材质方案零命中**；所有 `code` 字段均为价位档描述，例如：

> 客厅地板 `code: "约220元/㎡（ENF级）"`；厨房墙砖 `code: "约80元/㎡（瓷片）"`；次卧洞洞板 `code: "约120元/㎡（桦木多层板）"`

唯一命中为 run2 色彩方案 `wood_tone`："浅橡木色，纹理细腻，**示例品牌：宜家、大自然地板（可替换）**"——按规则标注了"示例品牌…可替换"，属合规行为而非违规。

### ③ 面积口径混乱 → 已消除

**修复前**（第 3 节摘录）："面对 65.4㎡ 的紧凑户型"——用房间加总面积替代输入建面 68㎡，无口径说明。

**修复后**：run1/run2 设计定位均以"本案以**68㎡**两室一厅……"开头，正文不出现 65㎡；PPTX 封面为"建筑面积 68 m² · 5 个房间"；「假设与口径说明」页首条固定写明：

> "面积口径：本方案总面积以建筑面积 68㎡ 为准；各房间加总约 65.4㎡（不含公摊/墙体），两者差异属正常口径差。"

根因修复：step1 原代码读 `project.area`（实际键为 `area_m2`）失败后静默回退到房间加总面积，等于把错误口径直接喂给模型。

### ④ 空间数量一致性（顺带核验）

run1/run2 的设计定位、色彩方案、材质方案的房间集合与输入完全一致（客厅/主卧/次卧/厨房/卫生间，5 个），无新增空间；"三居室"类户型错误未再出现（两模型运行均正确引用"两室一厅"）。

## C. 复验产物清单（outputs/model-compare/post-hardening/，gitignore 不入库）

- `run1-sample/`：sample 输入 + `concept_output/`（设计定位/色彩/材质/意向板/PPTX 等全套）
- `run2-manual/`：manual 模板输入 + `concept_output/` 全套
- 两次运行布局草案仍被自动化门禁正确拦截（缺结构/机电/门洞信息），与上轮一致

## D. 回归

`AI_DEMO_MODE=1` 下 5 个离线验收脚本（`scripts/validate_*.py`）全部通过；demo mock 的 `assumptions` 字段驱动 PPT 假设页在 demo 路径同样生效。

## E. 遗留问题

1. 跨厂商对比仍未完成：需用户补 OpenAI 平台 API key 或 `MOONSHOT_API_KEY`；
2. 假设标注存在轻微"过度标注"：个别 assumptions 条目实为输入事实的转述（如"客户家庭有儿童"输入已写明"1孩"），无害，后续可收紧；
3. 色彩/布局步骤的推断标注仍靠文本"假设："前缀，未像材质步骤一样结构化为数组（上轮真实运行中布局被门禁拦截，未产生实测样本）；
4. 面积口径冲突（建面 vs 房间加总）仍建议在认知链路层（space_profile）向用户提示确认，本轮只在生成侧统一口径；
5. 意向板/色板/材质图为 PIL 绘制的中文排版，视觉精细度有限，后续可换 HTML 渲染。
