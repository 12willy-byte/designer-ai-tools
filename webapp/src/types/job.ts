export interface QuestionItem {
  question: string
  source: string
  category: string
  reason: string
  required: boolean
}

export interface AssumptionItem {
  text: string
  sources: string[]
}

export interface BlockedModule {
  module: string
  reasons: string[]
}

export interface JobSummary {
  mode: 'real' | 'demo'
  demo_mode: boolean
  room_count: number
  room_names: string[]
  total_area_m2: number | null
  budget_low: number | null
  budget_high: number | null
  user_budget_wan: number | null
  layout_mode: string | null
  degraded_reasons: string[]
  allowed_modules: string[]
  blocked_modules: BlockedModule[]
  questions: QuestionItem[]
  question_count: number
  assumptions: AssumptionItem[]
  assumption_count: number
  delivery_file_count: number | null
  delivery_package_dir: string | null
  ai_repair_count: number
  ai_repairs: { context: string; path: string; action: string; detail: string }[]
  project_name: string | null
}

export interface JobStatusPayload {
  job_id: string
  status: 'queued' | 'running' | 'done' | 'failed'
  mode: 'real' | 'demo'
  error?: string
  summary?: JobSummary
}

export interface HealthPayload {
  ok: boolean
  ai_mode: 'real' | 'demo'
  ai_mode_label: string
  max_upload_mb: number
}
