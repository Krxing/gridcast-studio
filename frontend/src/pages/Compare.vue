<script setup>
import { computed, ref, watch } from 'vue'
import { GitCompare, ShieldCheck } from 'lucide-vue-next'
import Chart from '../components/Chart.vue'
import { dateTime, kinds, number, state } from '../state'
const selected = ref('')
const groups = computed(() => {
  const result = new Map()
  for (const model of state.models) {
    const key = model.metrics?.evaluation_key
    if (key && !result.has(key)) result.set(key, { key, model, dataset: state.datasets.find(item => item.id === model.dataset_id)?.name || model.dataset_id })
  }
  return [...result.values()]
})
watch(groups, values => { if (!values.some(item => item.key === selected.value)) selected.value = values[0]?.key || '' }, { immediate: true })
const comparable = computed(() => state.models.filter(item => item.metrics?.evaluation_key === selected.value && selected.value).sort((first, second) => first.metrics.mae - second.metrics.mae))
const reference = computed(() => comparable.value[0]?.metrics)
const option = computed(() => ({ color: ['#21876b', '#a9c9bb'], tooltip: { trigger: 'axis' }, legend: { top: 0 }, grid: { left: 55, right: 20, top: 45, bottom: 70 }, xAxis: { type: 'category', data: comparable.value.map(item => item.name), axisLabel: { width: 120, overflow: 'truncate', rotate: 12 } }, yAxis: { type: 'value', name: 'kW', splitLine: { lineStyle: { type: 'dashed', color: '#edf1ee' } } }, series: ['mae', 'rmse'].map(key => ({ name: key.toUpperCase(), type: 'bar', data: comparable.value.map(item => item.metrics[key]), barMaxWidth: 36, itemStyle: { borderRadius: [4, 4, 0, 0] } })) }))
</script>
<template>
  <div class="page-intro"><div><div class="eyebrow">EVALUATION LAB</div><h1>评估对比<span class="title-dot"></span></h1><p>在同一份证据上比较，而不是拼凑不同实验的数字。</p></div><a class="button primary" href="#models"><GitCompare :size="16" />训练对照模型</a></div>
  <div class="card filter-card"><label>可比实验组<select v-model="selected"><option v-if="!groups.length" value="">暂无已完成评估</option><option v-for="group in groups" :key="group.key" :value="group.key">{{ group.dataset }} · v{{ group.model.dataset_version }} · {{ group.model.horizon }} 步 · {{ dateTime(group.model.metrics.test_start) }} 至 {{ dateTime(group.model.metrics.test_end) }}</option></select></label><div class="note-box"><ShieldCheck :size="18" /><p>只对相同数据集、版本、预测步数和测试时段进行排名。覆盖率需与区间宽度、区间评分一起解读，不能仅靠扩大区间追求高覆盖。</p></div></div>
  <div v-if="!comparable.length" class="card empty-state spaced"><GitCompare :size="30" /><strong>尚无可比较的实验</strong><span>完成模型训练后，真实测试集指标会显示在这里。</span></div>
  <template v-else><div class="section-heading"><h2>点预测误差</h2><span class="tag neutral">{{ comparable.length }} 个版本 · {{ reference.points }} 个测试点</span></div><section class="card"><Chart :option="option" :height="320" /></section><section class="card table-card spaced"><div class="table-wrap"><table><thead><tr><th>模型</th><th>MAE ↓</th><th>RMSE ↓</th><th>WAPE ↓</th><th>覆盖率</th><th>平均宽度</th><th>区间评分 ↓</th><th>CRPS ↓</th></tr></thead><tbody><tr v-for="model in comparable" :key="model.id"><td><strong>{{ model.name }}</strong><small class="cell-sub">{{ kinds[model.kind] }}</small></td><td>{{ number(model.metrics.mae, 2) }}</td><td>{{ number(model.metrics.rmse, 2) }}</td><td>{{ number(model.metrics.wape, 2) }}%</td><td>{{ number(model.metrics.coverage) }}%</td><td>{{ number(model.metrics.mean_width, 2) }}</td><td>{{ number(model.metrics.interval_score, 2) }}</td><td>{{ number(model.metrics.crps, 2) }}</td></tr></tbody></table></div></section><div class="two-column spaced"><div class="card"><h3>数据隔离与复现</h3><p class="body-copy">按时间顺序划分训练 60%、验证 15%、独立校准 12.5%、测试 12.5%。校准和测试目标窗口不重叠；预处理参数只从训练段估计。版本和随机种子随模型保存。</p></div><div class="card"><h3>指标解释</h3><p class="body-copy">除 WAPE、覆盖率为百分比外，其余指标单位为 kW。CRPS 使用校准残差抽样估计；名义区间为 95%。{{ reference.is_demo ? '本组为合成数据，不代表真实业务精度。' : '精度结论仅限当前留出测试时段。' }}</p></div></div></template>
</template>
