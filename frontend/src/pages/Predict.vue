<script setup>
import { computed, ref, watch } from 'vue'
import { Activity, Download, Play, Printer, ShieldCheck } from 'lucide-vue-next'
import ForecastChart from '../components/ForecastChart.vue'
import Chart from '../components/Chart.vue'
import { api, act, dateTime, number, notify, refresh, state, trackJob } from '../state'
import { PALETTE } from '../charts.js'

const datasetId = ref(state.datasets[0]?.id || '')
const modelId = ref('')
const mode = ref('future')
const confidence = ref(.95)
const selectedId = ref(state.forecasts[0]?.id || '')
const record = ref(null)
const busy = ref(false)
const available = computed(() => state.models.filter(model => model.dataset_id === datasetId.value && ['active', 'ready', 'archived'].includes(model.status)))
const model = computed(() => available.value.find(item => item.id === modelId.value))
const dataset = computed(() => state.datasets.find(item => item.id === datasetId.value))
const explanation = computed(() => record.value?.result.explanation.items || [])
const explanationMax = computed(() => Math.max(...explanation.value.map(item => Math.abs(item.value)), 1))
const widthOption = computed(() => ({ color: [PALETTE.primary], grid: { left: 48, right: 15, top: 30, bottom: 30 }, tooltip: { trigger: 'axis' }, xAxis: { type: 'category', data: record.value?.result.series.map((item, index) => index + 1), name: '步' }, yAxis: { type: 'value', name: '区间宽度 kW', splitLine: { lineStyle: { color: PALETTE.axis.split, type: 'dashed' } } }, series: [{ type: 'bar', data: record.value?.result.series.map(item => item.upper - item.lower), barMaxWidth: 14, itemStyle: { borderRadius: [3, 3, 0, 0] } }] }))
watch(available, values => { if (!values.some(item => item.id === modelId.value)) modelId.value = (values.find(item => item.status === 'active') || values[0])?.id || '' }, { immediate: true })
watch(() => state.datasets, values => { if (!datasetId.value) datasetId.value = values[0]?.id || '' })
watch(() => state.forecasts, values => { if (!selectedId.value) selectedId.value = values[0]?.id || '' })
async function loadRecord() {
  const requested = selectedId.value
  if (!requested) return
  const result = await act(() => api(`/predictions/${requested}`))
  if (requested === selectedId.value && result) record.value = result
}
watch(selectedId, loadRecord, { immediate: true })
watch(() => state.lastUpdated, loadRecord)
async function run() {
  busy.value = true
  await act(async () => {
    const result = await api('/predictions/run', { method: 'POST', body: { model_id: modelId.value, dataset_id: datasetId.value, mode: mode.value, confidence: confidence.value } })
    trackJob(result.job_id, '预测计算', result => { selectedId.value = result.forecast_id })
    notify('预测任务已进入计算队列')
    await refresh()
  })
  busy.value = false
}
function printReport() { window.print() }
</script>

<template>
  <div class="page-intro"><div><div class="eyebrow">FORECAST EXPLORER</div><h1>预测分析<span class="title-dot"></span></h1><p>不仅预测一个数值，还展示范围、依据与实际检验。</p></div><div v-if="record" class="page-actions no-print"><a class="button ghost" :href="`/api/predictions/${record.id}/export`"><Download :size="16" />导出 CSV</a><button class="button ghost" @click="printReport"><Printer :size="16" />打印报告</button></div></div>
  <form class="card prediction-controls no-print" @submit.prevent="run"><label>数据集<select v-model="datasetId" required><option disabled value="">请先导入数据</option><option v-for="item in state.datasets" :key="item.id" :value="item.id">{{ item.name }}</option></select></label><label>模型版本<select v-model="modelId" required><option disabled value="">请先完成训练</option><option v-for="item in available" :key="item.id" :value="item.id">{{ item.name }}{{ item.status === 'active' ? ' · 上线中' : '' }}</option></select></label><label>任务类型<select v-model="mode"><option value="future">未来滚动预测</option><option value="backtest">最近留出窗口回测</option></select></label><label>名义区间<select v-model.number="confidence"><option :value=".8">80%</option><option :value=".9">90%</option><option :value=".95">95%</option></select></label><button class="button primary" :disabled="busy || !modelId"><Play :size="15" />{{ busy ? '提交中…' : '开始预测' }}</button><p class="form-hint">{{ model ? `${model.horizon} 步 × ${dataset?.interval_minutes} 分钟，预测 ${number(model.horizon * dataset.interval_minutes / 60)} 小时。` : '预测窗口由模型训练配置决定。' }}未来气象实测值不作为输入；回测只使用预测起点之前的信息。</p></form>
  <div class="section-heading"><h2>预测记录</h2><select v-model="selectedId" class="record-select no-print" aria-label="选择预测记录"><option v-for="item in state.forecasts" :key="item.id" :value="item.id">{{ dateTime(item.created_at) }} · {{ item.model_name }} · {{ item.mode === 'future' ? '未来预测' : '回测' }} · {{ item.id.slice(0, 6) }}</option></select></div>
  <div v-if="!record" class="card empty-state"><Activity :size="30" /><strong>等待第一次预测</strong><span>选择已训练模型并开始预测，或在总览初始化演示场景。</span></div>
  <template v-else><div class="context-banner"><ShieldCheck :size="22" /><div><strong>{{ record.result.dataset_name }}</strong><span>{{ record.result.model_name }} · 数据版本 v{{ record.dataset_version }}</span></div><span :class="['tag', record.result.is_demo ? 'amber' : 'green']">{{ record.result.is_demo ? '合成演示 · 非业务精度' : '用户导入数据' }}</span><span class="banner-meta">预测起点 {{ dateTime(record.origin) }}</span></div>
    <div class="metrics-grid"><div class="metric-card"><small>预测峰值</small><div class="metric-value">{{ number(record.result.peak) }}<span>kW</span></div><small>{{ dateTime(record.result.peak_time) }} · 峰谷差 {{ number(record.result.peak - record.result.valley) }} kW</small></div><div class="metric-card"><small>预测累计用电量</small><div class="metric-value">{{ number(record.result.energy_kwh, 0) }}<span>kWh</span></div><small>负荷率 {{ number(record.result.load_factor) }}%</small></div><div class="metric-card"><small>预测区间平均宽度</small><div class="metric-value">{{ number(record.result.mean_width) }}<span>kW</span></div><small>名义水平 {{ record.confidence * 100 }}%，不等于实测覆盖率</small></div><div class="metric-card"><small>本次预测已观测 MAE</small><div class="metric-value">{{ number(record.result.actual_metrics?.mae, 2) }}<span>kW</span></div><small>{{ record.result.observed_points }} / {{ record.result.series.length }} 个实际值 · {{ record.result.evaluation_status === 'pending' ? '待回流' : record.result.evaluation_status === 'partial' ? '部分评估' : '完整评估' }}</small></div></div>
    <section class="card"><div class="card-heading"><div><h2>负荷轨迹与不确定性</h2><p>阴影代表经验预测区间；橙色曲线代表已回流实际值。</p></div><span class="tag neutral">{{ record.mode === 'future' ? '未来预测' : '历史回测' }}</span></div><ForecastChart :record="record" :height="365" /><div class="chart-caption">{{ record.result.interval_method }}</div></section>
    <div class="two-column spaced"><section class="card"><div class="card-heading"><div><h2>输入敏感度</h2><p>扰动输入后，预测均值的变化量</p></div></div><div class="sensitivity-list"><div v-for="item in explanation" :key="item.name" class="sensitivity-row"><div><span>{{ item.name }}</span><strong>{{ item.value > 0 ? '+' : '' }}{{ number(item.value) }} kW</strong></div><div class="bar-track"><i :style="{ width: Math.max(2, Math.abs(item.value) / explanationMax * 100) + '%' }"></i></div></div></div><div class="note-box"><p>{{ record.result.explanation.method }}。各项不要求加和等于预测值。</p></div></section><section class="card"><div class="card-heading"><div><h2>各预测步的不确定性</h2><p>越宽表示该步的经验预测范围越大</p></div></div><Chart :option="widthOption" :height="280" /><div class="detail-note">{{ record.result.feature_policy }}</div></section></div>
    <div class="requirements-strip"><strong>结果溯源</strong><span class="mono">预测 {{ record.id }}</span><span class="mono">模型 {{ record.model_id }}</span><span>数据 v{{ record.dataset_version }}</span><span>推理 {{ number(record.result.inference_ms, 0) }} ms</span><span>输出仅供分析参考</span></div>
  </template>
</template>
