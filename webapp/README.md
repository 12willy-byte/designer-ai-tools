# 设计师 AI 工具箱 · Web 界面

上传矢量 PDF 图纸 + 填写需求 → 异步跑 M0–M6 流水线 → 下载概念提案交付包（zip）。

## 一键启动（前后端一起）

```bash
cd webapp
npm install        # 首次
npm run dev        # Flask(127.0.0.1:8791) + Vite(默认 5273)
npm run dev -- --port 7100   # 指定前端端口；--host 等参数同样透传给 vite
```

浏览器打开 Vite 提示的地址即可。`/api` 由 vite proxy 转发到 Flask。

## AI 模式

- 环境变量存在 `DEEPSEEK_API_KEY`（或 `AI_API_KEY`）→ 真实模式（DeepSeek）。
- 否则自动进入演示模式（`AI_DEMO_MODE=1`，离线占位输出），界面右上角会如实标注。
- 新版 DeepSeek 端点的 key 只接受 `deepseek-v4-pro` / `deepseek-v4-flash`
  （默认 preset 的 `deepseek-chat` 会被 400 拒绝），此时需
  `export DEEPSEEK_MODEL=deepseek-v4-pro` 再启动。

## 后端 API（Flask，server/app.py）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 + 当前 AI 模式 |
| POST | `/api/projects` | multipart：`structure_pdf`（必传）、`furnished_pdf`（可选）+ 需求字段（project_name / family / style / color_tone / budget_wan / area_m2 / ceiling_height_mm / special_requirements）→ `{job_id}` |
| GET | `/api/jobs/<id>` | 状态轮询（queued/running/done/failed）；done 时带摘要（房间数、预算区间、闸门放行/拦截、待确认问题、假设清单、交付文件数） |
| GET | `/api/jobs/<id>/download` | 交付包 zip 下载 |

安全：单请求 50MB 上限、仅 .pdf、文件名净化（CJK 名落回固定名防互相覆盖）、
运行目录隔离在 `server/runs/<job_id>/`（已 gitignore）、任务状态仅存内存
（进程重启即清空，无需数据库）。

## 目录

```
webapp/
  dev.mjs            # node 启动器：spawn Flask + vite，透传 CLI 参数
  server/app.py      # Flask 后端（单文件）
  server/runs/       # 任务运行目录（gitignore）
  src/pages/Home.tsx # 前端单页四步流程（上传 → 需求 → 生成中 → 结果）
  src/types/job.ts   # API 类型定义
```
