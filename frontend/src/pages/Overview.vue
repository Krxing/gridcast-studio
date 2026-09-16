<script setup>
import { computed, ref } from 'vue'
import { ArrowUpRight, ArrowRight, Activity, Zap, ShieldCheck, Target, Sparkles, Database, CircleCheck, Clock3, RefreshCw } from 'lucide-vue-next'
import { state, number, dateTime, shortTime, act, seedDemo, canEdit, kinds } from '../state'
import ForecastChart from '../components/ForecastChart.vue'

const loading = ref(false)
const forecast = computed(() => state.summary?.latest_forecast)
const model = computed(() => state.models.find(item => item.id === forecast.value?.model_id) || state.summary?.active_models?.[0])
const metrics = computed(() => model.value?.metrics)
const explanation = computed(() => forecast.value?.result.explanation.items.slice(0, 5) || [])
const contributionMax = computed(() => Math.max(...explanation.value.map(item => Math.abs(item.value)), 1))
const dataset = computed(() => state.datasets.find(item => item.id === forecast.value?.dataset_id))
async function initialize() { loading.value = true; await act(seedDemo); loading.value = false }
</script>

<template>
  <div class="page-intro"><div><div class="eyebrow">ENERGY INTELLIGENCE</div><h1>负荷预测总览<span class="title-dot"></span></h1><p>洞察负荷趋势，让每一次预测都有据可依。</p></div><a class="button primary" href="#predict">进入预测工作台 <ArrowUpRight :size="17" /></a></div>
  <div class="context-banner"><div class="context-icon"><Activity :size="21" /></div><div><strong>{{ forecast ? '预测链路已就绪' : '欢迎使用 GridCast' }}</strong><span>{{ forecast ? `${forecast.result.dataset_name} · ${forecast.result.interval_minutes} 分钟粒度` : '从一份数据开始，连接训练、预测与分析' }}</span></div><span v-if="forecast?.result.is_demo" class="tag amber">合成演示数据 · 非真实业务精度</span><span v-else class="tag green">本地数据 · 自主掌控</span><div class="banner-meta" v-if="dataset">数据截至 <strong>{{ dateTime(dataset.end) }}</strong></div></div>

  <div v-if="!forecast" class="welcome-grid">
    <div class="card welcome-card"><div class="large-icon"><Sparkles :size="34" /></div><h2>先跑通一次完整预测</h2><p>一键生成 90 天合成园区负荷数据，真实训练集成模型，并产出未来 24 小时预测、预测区间与解释分析。</p><button class="button primary" :disabled="loading || !!state.summary?.running_jobs || !canEdit()" @click="initialize"><RefreshCw v-if="loading || state.summary?.running_jobs" class="spin" :size="17" /><Sparkles v-else :size="17" />{{ state.summary?.running_jobs ? '模型正在计算，请稍候…' : '初始化演示场景' }}</button><small>合成数据仅用于验证系统流程，不代表真实场景精度。</small></div>
    <div class="card quick-start"><h3>你的预测工作流</h3><div v-for="(item, index) in [['接入数据','上传负荷与气象等历史数据'],['训练模型','时间切分、独立校准、版本追溯'],['解释预测','点预测、预测区间与敏感度分析'],['持续更新','真实值回流、监测、受控重训']]" :key="item[0]" class="workflow-step"><span>{{ String(index + 1).padStart(2, '0') }}</span><div><strong>{{ item[0] }}</strong><p>{{ item[1] }}</p></div></div><a class="text-link" href="#data">或导入自己的数据 <ArrowRight :size="15" /></a></div>
  </div>

  <template v-else>
    <div class="metrics-grid">
      <div class="metric-card"><div class="metric-label">预测峰值负荷 <Zap :size="18" /></div><div class="metric-value">{{ number(forecast.result.peak) }}<span>kW</span></div><div class="metric-foot">预计出现在 <strong>{{ shortTime(forecast.result.peak_time) }}</strong><span class="micro-line">╱╲╱╲</span></div></div>
      <div class="metric-card"><div class="metric-label">测试集平均绝对误差 <Target :size="18" /></div><div class="metric-value">{{ number(metrics?.mae, 2) }}<span>kW</span></div><div class="metric-foot"><span :class="metrics?.improvement >= 0 ? 'green-text' : 'amber-text'">较季节基线 {{ metrics?.improvement >= 0 ? '降低' : '增加' }} {{ number(Math.abs(metrics?.improvement || 0)) }}%</span></div></div>
      <div class="metric-card"><div class="metric-label">测试集区间覆盖率 <ShieldCheck :size="18" /></div><div class="metric-value">{{ number(metrics?.coverage) }}<span>%</span></div><div class="metric-foot">名义水平 95% <span class="muted">· {{ metrics?.points || 0 }} 个测试点</span></div></div>
      <div class="metric-card"><div class="metric-label">预测时段用电量 <Activity :size="18" /></div><div class="metric-value">{{ number(forecast.result.energy_kwh, 0) }}<span>kWh</span></div><div class="metric-foot">{{ forecast.result.series.length * forecast.result.interval_minutes / 60 }} 小时累计 <span class="muted">· 负荷率 {{ number(forecast.result.load_factor) }}%</span></div></div>
    </div>
    <div class="overview-charts">
      <section class="card forecast-card"><div class="card-heading"><div><h2>负荷趋势与预测</h2><p>历史观测与未来走势，在同一时间轴上</p></div><span class="tag neutral">{{ Math.round(forecast.confidence * 100) }}% 预测区间</span></div><div class="chart-legend"><span><i class="legend-line slate"></i>历史负荷</span><span><i class="legend-line green dashed"></i>预测负荷</span><span><i class="legend-band"></i>预测区间</span><span v-if="forecast.result.observed_points"><i class="legend-line amber"></i>回流实际值</span></div><ForecastChart :record="forecast" :height="313" compact /><div class="chart-caption"><span><i class="status-dot"></i>{{ forecast.result.observed_points ? `已有 ${forecast.result.observed_points} 个实际值回流` : '未来实际值尚未回流，本次预测误差暂不可计算' }}</span><a href="#predict" class="text-link">查看详细分析 <ArrowUpRight :size="14" /></a></div></section>
      <section class="card explanation-card"><div class="card-heading"><div><h2>模型为何这样预测？</h2><p>预测均值对输入特征的敏感度</p></div><Sparkles :size="18" class="green-text" /></div><div class="sensitivity-list"><div v-for="item in explanation" :key="item.name" class="sensitivity-row"><div><span>{{ item.name }}</span><strong>{{ item.value > 0 ? '+' : '' }}{{ number(item.value) }} <small>kW</small></strong></div><div class="bar-track"><i :style="{ width: Math.max(3, Math.abs(item.value) / contributionMax * 100) + '%', background: item.value >= 0 ? '#21876b' : '#b6c4b7' }"></i></div></div></div><div class="note-box"><ShieldCheck :size="16" /><p>分组扰动分析，不是因果解释。各项不要求相加等于预测值。</p></div><a href="#predict" class="text-link">查看解释方法 <ArrowRight :size="14" /></a></section>
    </div>
    <div class="overview-bottom">
      <section class="card"><div class="card-heading"><div><h2>当前预测模型</h2><p>独立测试集评估 · 可追溯版本</p></div><a href="#models" class="text-link">模型中心 <ArrowUpRight :size="14" /></a></div><div class="active-model"><div class="model-symbol"><Activity :size="24" /></div><div><h3>{{ model?.name }}</h3><p>{{ kinds[model?.kind] }} · 数据版本 v{{ model?.dataset_version }}</p></div><span :class="['tag', model?.status === 'active' ? 'green' : 'neutral']">{{ model?.status === 'active' ? '已上线' : '可用版本' }}</span></div><div class="model-stats"><div><small>RMSE</small><strong>{{ number(metrics?.rmse, 2) }} <span>kW</span></strong></div><div><small>MAPE</small><strong>{{ number(metrics?.mape, 2) }} <span>%</span></strong></div><div><small>CRPS</small><strong>{{ number(metrics?.crps, 2) }} <span>kW</span></strong></div><div><small>测试窗口</small><strong>{{ metrics?.test_windows || '—' }} <span>个</span></strong></div></div></section>
      <section class="card"><div class="card-heading"><div><h2>系统动态</h2><p>数据、训练与预测的最近记录</p></div><a href="#monitor" class="text-link">全部 <ArrowUpRight :size="14" /></a></div><div class="event-list"><div v-for="event in state.summary?.events?.slice(0, 3)" :key="event.id" class="event-row"><span class="event-mark"><CircleCheck v-if="event.level === 'info'" :size="15" /><Clock3 v-else :size="15" /></span><div><strong>{{ event.title }}</strong><p>{{ event.detail }}</p></div><time>{{ shortTime(event.created_at) }}</time></div></div></section>
    </div>
  </template>
  <div class="page-footer"><span>GRIDCAST STUDIO <b>·</b> 用电负荷预测原型</span><span>模型输出仅供分析参考，不自动执行调度控制</span></div>
</template>
