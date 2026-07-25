import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Textarea } from '@/components/ui/textarea'
import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  Download,
  FileText,
  Loader2,
  RotateCcw,
  Upload,
  X,
} from 'lucide-react'
import type { HealthPayload, JobStatusPayload } from '@/types/job'

type Step = 1 | 2 | 3 | 4

const PIPELINE_STEPS = [
  '解析图纸', '空间建档', '需求画像', '闸门检查',
  '概念方案', '布局草案', '预算清单', '打包交付',
]

const FAMILY_OPTIONS = [
  { value: 'single', label: '单身' },
  { value: 'couple', label: '夫妻' },
  { value: 'family3', label: '三口之家' },
  { value: 'three_gen', label: '三代同堂' },
  { value: 'rental', label: '出租房' },
]

const STYLE_OPTIONS = ['现代简约', '原木', '奶油', '中古', '其他']

function ModeBadge({ mode }: { mode: 'real' | 'demo' | null }) {
  if (mode === 'real') {
    return <Badge className="bg-emerald-600 hover:bg-emerald-600">真实 AI 模式</Badge>
  }
  if (mode === 'demo') {
    return <Badge variant="secondary" className="text-amber-700 bg-amber-100">演示模式（离线占位输出）</Badge>
  }
  return <Badge variant="outline">模式检测中…</Badge>
}

interface PdfSlotProps {
  title: string
  required?: boolean
  hint: string
  file: File | null
  onFile: (f: File | null) => void
}

function PdfDropzone({ title, required, hint, file, onFile }: PdfSlotProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)

  const pick = (f: File | undefined | null) => {
    if (!f) return
    if (!f.name.toLowerCase().endsWith('.pdf')) return
    onFile(f)
  }
  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    pick(e.dataTransfer.files?.[0])
  }
  const onChange = (e: ChangeEvent<HTMLInputElement>) => {
    pick(e.target.files?.[0])
    e.target.value = ''
  }

  return (
    <div
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
      onDragLeave={() => setDragOver(false)}
      onDrop={onDrop}
      className={`cursor-pointer rounded-lg border-2 border-dashed p-6 transition-colors ${
        dragOver ? 'border-slate-500 bg-slate-100' : 'border-slate-300 bg-white hover:border-slate-400'
      }`}
    >
      <input ref={inputRef} type="file" accept=".pdf,application/pdf" className="hidden" onChange={onChange} />
      {file ? (
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <FileText className="h-8 w-8 shrink-0 text-slate-600" />
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-slate-900">{file.name}</p>
              <p className="text-xs text-slate-500">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
            </div>
          </div>
          <Button
            type="button" variant="ghost" size="icon"
            onClick={(e) => { e.stopPropagation(); onFile(null) }}
            aria-label="移除文件"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-2 text-center">
          <Upload className="h-8 w-8 text-slate-400" />
          <p className="text-sm font-medium text-slate-800">
            {title}
            {required && <span className="ml-1 text-red-500">*</span>}
          </p>
          <p className="text-xs text-slate-500">{hint}</p>
          <p className="text-xs text-slate-400">拖拽 PDF 到这里，或点击选择</p>
        </div>
      )}
    </div>
  )
}

export default function Home() {
  const [step, setStep] = useState<Step>(1)
  const [health, setHealth] = useState<HealthPayload | null>(null)

  const [structurePdf, setStructurePdf] = useState<File | null>(null)
  const [furnishedPdf, setFurnishedPdf] = useState<File | null>(null)

  const [projectName, setProjectName] = useState('')
  const [family, setFamily] = useState('')
  const [style, setStyle] = useState('')
  const [colorTone, setColorTone] = useState('')
  const [budgetWan, setBudgetWan] = useState('')
  const [areaM2, setAreaM2] = useState('')
  const [specialReq, setSpecialReq] = useState('')
  const [ceilingMm, setCeilingMm] = useState('')

  const [job, setJob] = useState<JobStatusPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const pollRef = useRef<number | null>(null)

  useEffect(() => {
    fetch('/api/health')
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setHealth(null))
  }, [])

  // 生成中：计时 + 轮询任务状态
  useEffect(() => {
    if (step !== 3 || !job) return
    const startedAt = Date.now()
    const tick = window.setInterval(() => setElapsed(Math.floor((Date.now() - startedAt) / 1000)), 1000)
    const poll = window.setInterval(async () => {
      try {
        const r = await fetch(`/api/jobs/${job.job_id}`)
        const payload: JobStatusPayload = await r.json()
        setJob(payload)
        if (payload.status === 'done') setStep(4)
        if (payload.status === 'failed') setError(payload.error || '任务失败')
      } catch {
        /* 轮询失败静默重试 */
      }
    }, 2000)
    pollRef.current = poll
    return () => { window.clearInterval(tick); window.clearInterval(poll) }
  }, [step, job?.job_id]) // eslint-disable-line react-hooks/exhaustive-deps

  const stageIndex = Math.min(
    Math.floor(elapsed / 6),
    PIPELINE_STEPS.length - 1,
  )

  const submit = async () => {
    if (!structurePdf) return
    setError(null)
    const fd = new FormData()
    fd.append('structure_pdf', structurePdf)
    if (furnishedPdf) fd.append('furnished_pdf', furnishedPdf)
    fd.append('project_name', projectName)
    fd.append('family', family)
    fd.append('style', style)
    fd.append('color_tone', colorTone)
    fd.append('budget_wan', budgetWan)
    fd.append('area_m2', areaM2)
    fd.append('special_requirements', specialReq)
    fd.append('ceiling_height_mm', ceilingMm)
    try {
      const r = await fetch('/api/projects', { method: 'POST', body: fd })
      const payload = await r.json()
      if (!r.ok) {
        setError(payload.error || '提交失败')
        return
      }
      setJob({ ...payload, summary: undefined })
      setElapsed(0)
      setStep(3)
    } catch {
      setError('无法连接后端服务，请确认 Flask 已启动')
    }
  }

  const reset = () => {
    setStep(1)
    setJob(null)
    setError(null)
    setStructurePdf(null)
    setFurnishedPdf(null)
    setElapsed(0)
  }

  const summary = job?.summary
  const userBudgetYuan = summary?.user_budget_wan ? summary.user_budget_wan * 10000 : null
  const budgetVerdict = (() => {
    if (!summary || userBudgetYuan == null || summary.budget_low == null || summary.budget_high == null) return null
    if (userBudgetYuan < summary.budget_low) return { text: '低于估算区间下限，预算偏紧', tone: 'text-red-600' }
    if (userBudgetYuan > summary.budget_high) return { text: '高于估算区间上限，预算充裕', tone: 'text-emerald-600' }
    return { text: '落在估算区间内，预算基本匹配', tone: 'text-slate-700' }
  })()

  const stepTitles = ['上传图纸', '填写需求', '生成中', '交付结果']

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-4">
          <div>
            <h1 className="text-lg font-semibold">设计师 AI 工具箱</h1>
            <p className="text-xs text-slate-500">上传图纸 + 填需求 → 下载概念提案交付包</p>
          </div>
          <ModeBadge mode={health?.ai_mode ?? null} />
        </div>
      </header>

      {/* 步骤条 */}
      <div className="mx-auto max-w-3xl px-4 pt-6">
        <ol className="flex items-center gap-2">
          {stepTitles.map((title, i) => {
            const n = (i + 1) as Step
            const active = n === step
            const done = n < step
            return (
              <li key={title} className="flex flex-1 items-center gap-2">
                <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-medium ${
                  done ? 'bg-emerald-600 text-white' : active ? 'bg-slate-900 text-white' : 'bg-slate-200 text-slate-500'
                }`}>{done ? <CheckCircle2 className="h-4 w-4" /> : n}</span>
                <span className={`text-xs ${active ? 'font-medium text-slate-900' : 'text-slate-500'}`}>{title}</span>
                {i < stepTitles.length - 1 && <Separator className="flex-1" />}
              </li>
            )
          })}
        </ol>
      </div>

      <main className="mx-auto max-w-3xl px-4 py-6">
        {error && (
          <div className="mb-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p className="font-medium">出错了</p>
              <p>{error}</p>
            </div>
          </div>
        )}

        {/* 第 1 步：上传图纸 */}
        {step === 1 && (
          <Card>
            <CardHeader>
              <CardTitle>上传图纸</CardTitle>
              <CardDescription>
                只支持 CAD 导出的<strong>矢量 PDF</strong>（线条可缩放清晰），不支持拍照或扫描件。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <PdfDropzone
                title="结构图（毛坯原始图）"
                required
                hint="必传：用于识别墙体、门洞与空间边界"
                file={structurePdf}
                onFile={setStructurePdf}
              />
              <PdfDropzone
                title="平面布置图（可选）"
                hint="有就传：双图交叉验证，房间识别更准"
                file={furnishedPdf}
                onFile={setFurnishedPdf}
              />
              <div className="flex justify-end">
                <Button disabled={!structurePdf} onClick={() => setStep(2)}>
                  下一步：填写需求
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* 第 2 步：填写需求 */}
        {step === 2 && (
          <Card>
            <CardHeader>
              <CardTitle>填写需求</CardTitle>
              <CardDescription>这些信息会进入需求画像与预算估算，尽量如实填写。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="project-name">项目名</Label>
                  <Input id="project-name" placeholder="例：深圳罗菁住宅毛坯改造"
                    value={projectName} onChange={(e) => setProjectName(e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label>家庭情况</Label>
                  <Select value={family} onValueChange={setFamily}>
                    <SelectTrigger><SelectValue placeholder="选择家庭结构" /></SelectTrigger>
                    <SelectContent>
                      {FAMILY_OPTIONS.map((o) => (
                        <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label>风格</Label>
                  <Select value={style} onValueChange={setStyle}>
                    <SelectTrigger><SelectValue placeholder="选择主风格" /></SelectTrigger>
                    <SelectContent>
                      {STYLE_OPTIONS.map((s) => (
                        <SelectItem key={s} value={s}>{s}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="color-tone">色调</Label>
                  <Input id="color-tone" placeholder="例：暖白、浅木色、低饱和灰"
                    value={colorTone} onChange={(e) => setColorTone(e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="budget">总预算（万元）</Label>
                  <Input id="budget" type="number" min="0" step="1" placeholder="例：35"
                    value={budgetWan} onChange={(e) => setBudgetWan(e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="area">建筑面积（㎡）</Label>
                  <Input id="area" type="number" min="0" step="1" placeholder="例：110；影响预算档位判定"
                    value={areaM2} onChange={(e) => setAreaM2(e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="ceiling">层高（毫米，可选）</Label>
                  <Input id="ceiling" type="number" min="0" step="50" placeholder="例：2800；不填按 2700 估算并标注假设"
                    value={ceilingMm} onChange={(e) => setCeilingMm(e.target.value)} />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="special">特殊要求</Label>
                <Textarea id="special" rows={4}
                  placeholder="例：承重墙不可拆改；厨房与卫生间湿区位置不动；儿童房需预留学习区。涉及承重、水电的改动请务必在此注明，系统会把它们列为待确认项。"
                  value={specialReq} onChange={(e) => setSpecialReq(e.target.value)} />
              </div>
              <div className="flex justify-between">
                <Button variant="outline" onClick={() => setStep(1)}>上一步</Button>
                <Button onClick={submit}>开始生成</Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* 第 3 步：生成中 */}
        {step === 3 && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Loader2 className="h-5 w-5 animate-spin text-slate-600" />
                正在生成概念提案
              </CardTitle>
              <CardDescription className="flex items-center gap-2">
                已用时 {elapsed} 秒，通常需要 1–3 分钟 <ModeBadge mode={job?.mode ?? null} />
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <Progress value={((stageIndex + 1) / PIPELINE_STEPS.length) * 100} />
              <ol className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {PIPELINE_STEPS.map((s, i) => {
                  const done = i < stageIndex
                  const active = i === stageIndex
                  return (
                    <li key={s} className={`flex items-center gap-2 rounded-md border px-3 py-2 text-xs ${
                      done ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                        : active ? 'border-slate-400 bg-white font-medium text-slate-900'
                          : 'border-slate-200 text-slate-400'
                    }`}>
                      {done ? <CheckCircle2 className="h-3.5 w-3.5" />
                        : active ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          : <CircleDashed className="h-3.5 w-3.5" />}
                      {s}
                    </li>
                  )
                })}
              </ol>
              <p className="text-xs text-slate-400">阶段进度为按时间的示意展示，实际以后台任务状态为准。</p>
              {job?.status === 'failed' && (
                <Button variant="outline" onClick={reset}>返回重新开始</Button>
              )}
            </CardContent>
          </Card>
        )}

        {/* 第 4 步：结果页 */}
        {step === 4 && summary && job && (
          <div className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>{summary.project_name || '概念提案'} 已生成</CardTitle>
                <CardDescription className="flex items-center gap-2">
                  共 {summary.delivery_file_count ?? '—'} 个交付文件 <ModeBadge mode={summary.mode} />
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <a href={`/api/jobs/${job.job_id}/download`} className="block">
                  <Button size="lg" className="w-full">
                    <Download className="mr-2 h-5 w-5" /> 下载交付包（zip）
                  </Button>
                </a>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <div className="rounded-lg border border-slate-200 bg-white p-3 text-center">
                    <p className="text-2xl font-semibold">{summary.room_count}</p>
                    <p className="text-xs text-slate-500">识别房间数</p>
                  </div>
                  <div className="rounded-lg border border-slate-200 bg-white p-3 text-center">
                    <p className="text-2xl font-semibold">
                      {summary.budget_low != null && summary.budget_high != null
                        ? `${(summary.budget_low / 10000).toFixed(1)}–${(summary.budget_high / 10000).toFixed(1)}万`
                        : '未生成'}
                    </p>
                    <p className="text-xs text-slate-500">预算估算区间</p>
                  </div>
                  <div className="rounded-lg border border-slate-200 bg-white p-3 text-center">
                    <p className="text-2xl font-semibold">{summary.question_count}</p>
                    <p className="text-xs text-slate-500">待确认问题</p>
                  </div>
                  <div className="rounded-lg border border-slate-200 bg-white p-3 text-center">
                    <p className="text-2xl font-semibold">{summary.assumption_count}</p>
                    <p className="text-xs text-slate-500">假设条目</p>
                  </div>
                </div>
                {summary.user_budget_wan != null && budgetVerdict && (
                  <p className={`text-sm ${budgetVerdict.tone}`}>
                    业主预算 {summary.user_budget_wan} 万元：{budgetVerdict.text}
                  </p>
                )}
                {summary.room_names.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {summary.room_names.map((n) => (
                      <Badge key={n} variant="secondary">{n}</Badge>
                    ))}
                  </div>
                )}
                <div className="rounded-lg border border-slate-200 bg-white p-3 text-sm">
                  <p className="mb-1 font-medium">自动化闸门</p>
                  <p className="text-xs text-slate-500">
                    放行 {summary.allowed_modules.length} 个模块
                    {summary.blocked_modules.length > 0 && `，拦截 ${summary.blocked_modules.length} 个`}
                  </p>
                  {summary.blocked_modules.map((b) => (
                    <div key={b.module} className="mt-2 rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
                      <p className="font-medium">已拦截：{b.module}</p>
                      {b.reasons.map((r) => <p key={r}>· {r}</p>)}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>

            {/* 待确认问题：系统核心资产，完整露出 */}
            <Card>
              <CardHeader>
                <CardTitle>待确认问题（{summary.question_count}）</CardTitle>
                <CardDescription>生成过程中无法从图纸或需求确认的信息，请逐条与业主核实。</CardDescription>
              </CardHeader>
              <CardContent>
                {summary.questions.length === 0 ? (
                  <p className="text-sm text-slate-500">本次输入信息完整，无待确认问题。</p>
                ) : (
                  <ul className="space-y-2">
                    {summary.questions.map((q, i) => (
                      <li key={i} className="rounded-lg border border-slate-200 bg-white p-3">
                        <div className="flex items-start justify-between gap-2">
                          <p className="text-sm text-slate-900">{q.question}</p>
                          <div className="flex shrink-0 gap-1">
                            {q.required && <Badge variant="destructive" className="text-[10px]">必须确认</Badge>}
                            <Badge variant="outline" className="text-[10px]">{q.source}</Badge>
                          </div>
                        </div>
                        {q.reason && <p className="mt-1 text-xs text-slate-500">{q.reason}</p>}
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>

            {/* 假设清单：系统核心资产，完整露出 */}
            <Card>
              <CardHeader>
                <CardTitle>假设清单（{summary.assumption_count}）</CardTitle>
                <CardDescription>AI 在信息不足时做出的推断，全部以「假设：」开头标注，设计师复核时可逐条推翻。</CardDescription>
              </CardHeader>
              <CardContent>
                {summary.assumptions.length === 0 ? (
                  <p className="text-sm text-slate-500">无假设条目。</p>
                ) : (
                  <ul className="space-y-2">
                    {summary.assumptions.map((a, i) => (
                      <li key={i} className="rounded-lg border border-slate-200 bg-white p-3">
                        <p className="text-sm text-slate-900">{a.text}</p>
                        <p className="mt-1 text-xs text-slate-400">来源：{a.sources.join('、')}</p>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>

            <div className="rounded-lg border border-slate-300 bg-slate-100 p-4 text-sm text-slate-600">
              <p className="font-medium text-slate-800">诚实提示</p>
              <p className="mt-1">
                本交付包为<strong>提案初稿</strong>：预算为区间参考价（非报价单），布局为概念草案，
                承重、水电、结构安全均未核实。所有内容需设计师复核后才能对客户使用。
              </p>
            </div>

            <div className="flex justify-center pb-6">
              <Button variant="outline" onClick={reset}>
                <RotateCcw className="mr-2 h-4 w-4" /> 开始新项目
              </Button>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
