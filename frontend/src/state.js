import { reactive } from 'vue'

export const state = reactive({
  user: null, status: null, ready: false, summary: null, datasets: [], models: [], jobs: [],
  forecasts: [], settings: null, notifications: [], refreshing: false, lastUpdated: null,
})

const tracked = new Map()
let notificationId = 0

export function notify(message, kind = 'success') {
  const id = ++notificationId
  state.notifications.push({ id, message, kind })
  setTimeout(() => { state.notifications = state.notifications.filter(item => item.id !== id) }, 6000)
}

export async function api(path, options = {}) {
  const headers = { ...options.headers }
  let body = options.body
  if (body && !(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(body)
  }
  const response = await fetch('/api' + path, { ...options, headers, body, credentials: 'same-origin' })
  const result = await response.json().catch(() => ({}))
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith('/auth/')) state.user = null
    const detail = Array.isArray(result.detail) ? result.detail.map(item => item.msg).join('；') : result.detail
    throw new Error(detail || `请求失败 (${response.status})`)
  }
  return result
}

export function trackJob(jobId, message = '计算任务', callback) {
  if (jobId) tracked.set(jobId, { message, callback })
}

export async function refresh() {
  if (state.refreshing || !state.user) return
  state.refreshing = true
  try {
    const [summary, datasets, models, jobs, forecasts, settings] = await Promise.all([
      api('/dashboard'), api('/datasets'), api('/models'), api('/jobs'), api('/predictions'), api('/settings'),
    ])
    Object.assign(state, { summary, datasets, models, jobs, forecasts, settings, lastUpdated: new Date() })
    for (const job of jobs) {
      if (tracked.has(job.id) && ['success', 'failed', 'cancelled'].includes(job.status)) {
        const trackedJob = tracked.get(job.id)
        tracked.delete(job.id)
        if (job.status === 'success') {
          notify(trackedJob.message + '已完成')
          if (trackedJob.callback) await trackedJob.callback(job.result)
        } else notify(job.result?.error || trackedJob.message + '未完成', 'error')
      }
    }
  } finally {
    state.refreshing = false
  }
}

export async function act(callback) {
  try { return await callback() } catch (error) { notify(error.message || '操作失败', 'error'); return null }
}

export const number = (value, digits = 1) => value === null || value === undefined || !Number.isFinite(Number(value))
  ? '—' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits })
const businessDate = value => new Date(typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(value) && !/(Z|[+-]\d{2}:?\d{2})$/.test(value) ? value + '+08:00' : value)
export const dateTime = value => value ? businessDate(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Shanghai' }) : '—'
export const shortTime = value => value ? businessDate(value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Shanghai' }) : '—'
export const kinds = { ensemble: '集成树 + 残差校准', hybrid: 'SSM + 稀疏注意力', seasonal: '季节朴素基线' }
export const statuses = { training: '训练中', ready: '待上线', active: '已上线', archived: '已归档', failed: '失败', pending: '排队中', running: '运行中', success: '已完成', cancelled: '已取消' }
export const roles = { admin: '系统管理员', engineer: '算法工程师', operator: '业务运营' }
export const canEdit = () => ['admin', 'engineer'].includes(state.user?.role)

export async function seedDemo() {
  const result = await api('/demo/seed', { method: 'POST' })
  trackJob(result.job_id, '演示数据初始化与模型训练')
  notify(result.existing ? '演示数据已存在，可直接使用' : '已生成演示数据，正在真实训练模型…')
  await refresh()
}
