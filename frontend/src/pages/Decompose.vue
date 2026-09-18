<script setup>
import { ref, watch } from 'vue'
import Chart from '../components/Chart.vue'
import { act, api, state } from '../state'
import { PALETTE } from '../charts.js'
const selected = ref(state.datasets[0]?.id || '')
const result = ref(null)
const loading = ref(false)
const fields = [{ key: 'load', label: '原始负荷', color: PALETTE.decompose.load }, { key: 'trend', label: '长期趋势', color: PALETTE.decompose.trend }, { key: 'seasonal', label: '周期成分', color: PALETTE.decompose.seasonal }, { key: 'residual', label: '剩余波动', color: PALETTE.decompose.residual }]
watch(() => state.datasets, values => { if (!selected.value) selected.value = values[0]?.id || '' })
watch(selected, async value => {
  result.value = null
  if (!value) return
  loading.value = true
  const data = await act(() => api(`/datasets/${value}/decomposition`))
  if (selected.value === value) { result.value = data; loading.value = false }
}, { immediate: true })
function option(field) { return { color: [field.color], tooltip: { trigger: 'axis' }, grid: { left: 55, right: 20, top: 25, bottom: 35 }, xAxis: { type: 'category', data: result.value.series.map(item => item.timestamp), axisLabel: { formatter: value => value.slice(5, 16).replace('T', ' ') } }, yAxis: { type: 'value', name: 'kW', scale: true, splitLine: { lineStyle: { color: PALETTE.axis.split, type: 'dashed' } } }, dataZoom: [{ type: 'inside' }], series: [{ name: field.label, type: 'line', symbol: 'none', data: result.value.series.map(item => item[field.key]), lineStyle: { width: 1.5 } }] } }
</script>
<template><div class="page-intro"><div><div class="eyebrow">TIME SERIES INSIGHTS</div><h1>时序分解<span class="title-dot"></span></h1><p>分离趋势、周期与残差，理解历史负荷的组成。</p></div><select v-model="selected" aria-label="选择分解数据集"><option v-for="item in state.datasets" :key="item.id" :value="item.id">{{ item.name }}</option></select></div><div class="note-box"><p>STL 鲁棒分解是历史数据的事后探索，不构成因果解释，也不会将未来分解值输入模型。仅分析最近 6,000 条记录，图表最多展示 1,200 点。</p></div><div v-if="loading || !result" class="card empty-state spaced"><strong>{{ loading ? '正在计算时序分解…' : '请选择具有至少三个完整周期的数据集' }}</strong></div><div v-else class="two-column spaced"><section v-for="field in fields" :key="field.key" class="card"><h2>{{ field.label }}</h2><Chart :option="option(field)" :height="260" /></section></div></template>
