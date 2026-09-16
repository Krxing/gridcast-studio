<script setup>
import { computed, onMounted, ref } from 'vue'
import { AlertTriangle, ArrowDownToLine, ArrowUpRight, Check, Database, FileSpreadsheet, Plus, RefreshCw, Search, Trash2, Upload, X } from 'lucide-vue-next'
import Chart from '../components/Chart.vue'
import Modal from '../components/Modal.vue'
import { api, act, canEdit, dateTime, number, notify, refresh, state, trackJob } from '../state'

const selected = ref(null)
const query = ref('')
const showUpload = ref(false)
const uploadFile = ref(null)
const uploadName = ref('')
const uploadScene = ref('园区')
const uploading = ref(false)
const detail = ref(null)
const appendFile = ref(null)
const appending = ref(false)
async function appendRows() {
  if (!appendFile.value || !selected.value) return
  appending.value = true
  await act(async () => {
    const payload = new FormData(); payload.append('file', appendFile.value)
    const result = await api('/datasets/' + selected.value.id + '/append-file', { method: 'POST', body: payload })
    trackJob(result.job_id, '数据回流监测'); appendFile.value = null; notify('新观测已追加，数据版本已更新'); await refresh(); await inspect(result.dataset)
  })
  appending.value = false
}
const filtered = computed(() => state.datasets.filter(item => !query.value || `${item.name} ${item.scene}`.toLowerCase().includes(query.value.toLowerCase())))
const chartOption = computed(() => ({
  color: ['#198067'], grid: { left: 42, right: 18, top: 18, bottom: 32 }, tooltip: { trigger: 'axis' },
  xAxis: { type: 'category', data: detail.value?.series?.map(item => item.timestamp) || [], axisLabel: { formatter: value => value.slice(5, 10) } },
  yAxis: { type: 'value', name: 'kW', splitLine: { lineStyle: { type: 'dashed', color: '#edf1ee' } } },
  series: [{ name: '负荷', type: 'line', smooth: .2, symbol: 'none', data: detail.value?.series?.map(item => item.load) || [], areaStyle: { color: '#cae8dc', opacity: .35 } }],
}))
function chooseFile(event) { uploadFile.value = event.target.files?.[0] || null; if (uploadFile.value && !uploadName.value) uploadName.value = uploadFile.value.name.replace(/\.csv$/i, '') }
async function upload() {
  if (!uploadFile.value || !uploadName.value.trim()) return notify('请选择 CSV 并填写数据集名称', 'error')
  uploading.value = true
  const form = new FormData(); form.append('file', uploadFile.value); form.append('name', uploadName.value); form.append('scene', uploadScene.value)
  const result = await act(() => api('/datasets/upload', { method: 'POST', body: form }))
  uploading.value = false
  if (result) { showUpload.value = false; uploadFile.value = null; uploadName.value = ''; notify('数据集已导入'); await refresh() }
}
async function inspect(dataset) { detail.value = await act(() => api(`/datasets/${dataset.id}`)); selected.value = dataset }
async function deleteDataset(dataset) { if (!confirm(`确认删除未被引用的数据集“${dataset.name}”？`)) return; await act(async () => { await api(`/datasets/${dataset.id}`, { method: 'DELETE' }); notify('数据集已删除'); await refresh() }) }
async function advance(dataset) { await act(async () => { const result = await api(`/demo/${dataset.id}/advance`, { method: 'POST' }); notify('已追加 24 小时演示观测，正在更新监测'); await refresh(); return result }) }
function downloadTemplate() { window.location.href = '/api/datasets/template' }
onMounted(() => act(refresh))
</script>

<template>
  <div class="page-intro"><div><div class="eyebrow">DATA FOUNDATION</div><h1>数据管理<span class="title-dot"></span></h1><p>先让数据可信，再让预测有意义。</p></div><div class="page-actions"><button class="button ghost" @click="downloadTemplate"><ArrowDownToLine :size="16" />下载模板</button><button v-if="canEdit()" class="button primary" @click="showUpload = true"><Plus :size="17" />导入数据</button></div></div>
  <div class="data-summary"><div><Database :size="19" /><span>数据集</span><strong>{{ state.datasets.length }}</strong></div><div><FileSpreadsheet :size="19" /><span>总记录数</span><strong>{{ number(state.datasets.reduce((sum, item) => sum + item.rows, 0), 0) }}</strong></div><div><Check :size="19" /><span>最新版本</span><strong>{{ state.datasets[0] ? `v${state.datasets[0].version}` : '—' }}</strong></div><div><AlertTriangle :size="19" /><span>质量提醒</span><strong>{{ state.datasets.filter(item => item.quality?.warnings?.length).length }}</strong></div></div>
  <section class="card table-card"><div class="table-toolbar"><div class="search-box"><Search :size="16" /><input v-model="query" placeholder="搜索数据集名称或场景" /></div><button class="icon-button" aria-label="刷新数据集" title="刷新" @click="act(refresh)"><RefreshCw :size="17" /></button></div><div class="table-wrap"><table><thead><tr><th>数据集</th><th>场景</th><th>时间范围</th><th>规模</th><th>质量状态</th><th>版本</th><th>最近更新</th><th></th></tr></thead><tbody><tr v-for="dataset in filtered" :key="dataset.id" @click="inspect(dataset)"><td><div class="primary-cell"><span class="dataset-icon"><Database :size="15" /></span><div><strong>{{ dataset.name }}</strong><small>{{ dataset.is_demo ? '合成演示数据 · 仅用于流程验证' : '真实数据集' }}</small></div></div></td><td>{{ dataset.scene }}</td><td><span class="mono">{{ dateTime(dataset.start) }} – {{ dateTime(dataset.end) }}</span></td><td><strong>{{ number(dataset.rows, 0) }}</strong><small class="cell-sub">条 · {{ dataset.interval_minutes }} min</small></td><td><span :class="['tag', dataset.quality?.warnings?.length ? 'amber' : 'green']"><i></i>{{ dataset.quality?.warnings?.length ? `${dataset.quality.warnings.length} 项提醒` : '校验通过' }}</span></td><td class="mono">v{{ dataset.version }}</td><td class="muted">{{ dateTime(dataset.created_at) }}</td><td><div class="row-actions"><button class="icon-button" aria-label="查看详情" title="查看详情" @click.stop="inspect(dataset)"><ArrowUpRight :size="16" /></button><button v-if="dataset.is_demo && canEdit()" class="icon-button" aria-label="追加演示数据" title="追加 24 小时演示观测" @click.stop="advance(dataset)"><RefreshCw :size="15" /></button><button v-if="!dataset.is_demo && state.user.role === 'admin'" class="icon-button danger" aria-label="删除数据集" title="删除" @click.stop="deleteDataset(dataset)"><Trash2 :size="15" /></button></div></td></tr><tr v-if="!filtered.length"><td colspan="8" class="empty-state"><Database :size="26" /><strong>还没有匹配的数据集</strong><span>上传一个 CSV 或初始化演示场景开始。</span></td></tr></tbody></table></div></section>
  <div class="requirements-strip"><strong>CSV 最小字段</strong><span><code>timestamp</code> 时间戳</span><span><code>load</code> 负荷（kW）</span><span class="muted">可选：temperature · humidity · price · is_holiday</span><span class="muted push-right">系统拒绝不连续时间序列和空负荷标签</span></div>

  <Modal v-if="showUpload" title="导入历史负荷数据" @close="showUpload = false"><form class="form-stack" @submit.prevent="upload"><div class="upload-drop"><Upload :size="25" /><strong>选择 CSV 文件</strong><span>{{ uploadFile ? uploadFile.name : '支持 UTF-8 / GB18030，最大 20 MB' }}</span><input type="file" accept=".csv,text/csv" @change="chooseFile" /></div><label>数据集名称<input v-model="uploadName" placeholder="例如：XX 园区 2025 年负荷" required /></label><label>业务场景<select v-model="uploadScene"><option>园区</option><option>企业</option><option>台区</option><option>城市虚拟电厂</option></select></label><div class="modal-actions"><button type="button" class="button ghost" @click="showUpload = false">取消</button><button class="button primary" :disabled="uploading"><RefreshCw v-if="uploading" class="spin" :size="16" />{{ uploading ? '正在校验…' : '校验并导入' }}</button></div></form></Modal>
  <Modal v-if="detail" :title="`${selected?.name} · 数据详情`" wide @close="detail = null"><div class="detail-head"><div><span class="tag green">v{{ selected.version }} · {{ selected.interval_minutes }} 分钟</span><p>{{ dateTime(selected.start) }} – {{ dateTime(selected.end) }} · {{ number(selected.rows, 0) }} 条</p></div><span :class="['tag', selected.quality?.warnings?.length ? 'amber' : 'green']">{{ selected.quality?.warnings?.length ? '需要关注' : '质量良好' }}</span></div><Chart :option="chartOption" :height="300" /><details><summary>查看前 12 条原始样本与缺失率</summary><p class="body-copy">可选字段缺失比例：{{ Object.entries(selected.quality.missing_percent || {}).map(([key, value]) => `${key}: ${value}%`).join(' · ') || '无可选字段' }}</p><div class="table-wrap"><table><thead><tr><th v-for="column in detail.columns" :key="column">{{ column }}</th></tr></thead><tbody><tr v-for="row in detail.preview" :key="row.timestamp"><td v-for="column in detail.columns" :key="column">{{ row[column] ?? '缺失' }}</td></tr></tbody></table></div></details><form v-if="canEdit()" class="form-stack" @submit.prevent="appendRows"><label>追加观测 CSV（从现有末尾连续追加，至少 2 条）<input type="file" accept=".csv" @change="appendFile = $event.target.files?.[0] || null" /></label><button class="button primary" :disabled="!appendFile || appending">{{ appending ? '正在追加…' : '追加并更新版本' }}</button></form><div class="quality-grid"><div><small>均值</small><strong>{{ number(selected.quality.mean) }} kW</strong></div><div><small>最小值</small><strong>{{ number(selected.quality.min) }} kW</strong></div><div><small>最大值</small><strong>{{ number(selected.quality.max) }} kW</strong></div><div><small>异常点</small><strong>{{ selected.quality.outliers }} 个</strong></div></div><div v-if="selected.quality.warnings?.length" class="warning-list"><div v-for="warning in selected.quality.warnings" :key="warning"><AlertTriangle :size="15" />{{ warning }}</div></div></Modal>
</template>
