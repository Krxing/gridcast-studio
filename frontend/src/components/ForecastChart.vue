<script setup>
import { computed } from 'vue'
import Chart from './Chart.vue'

const props = defineProps({ record: Object, height: { type: Number, default: 330 }, compact: Boolean })
const option = computed(() => {
  if (!props.record) return {}
  const history = props.record.result.history
  const rows = props.record.result.series
  const count = history.length
  const times = [...history.map(row => row.timestamp), ...rows.map(row => row.timestamp)]
  const empty = Array(count).fill(null)
  const prediction = [...empty, ...rows.map(row => row.point)]
  if (count) prediction[count - 1] = history[count - 1].load
  return {
    animationDuration: 400,
    color: ['#435c65', '#167d63', '#e2a744'],
    textStyle: { fontFamily: 'Segoe UI, Microsoft YaHei, sans-serif', color: '#75828a' },
    tooltip: { trigger: 'axis', backgroundColor: '#fff', borderColor: '#e8eeea', textStyle: { color: '#233c35', fontSize: 12 },
      formatter(parameters) {
        const index = parameters[0]?.dataIndex
        if (index === undefined) return ''
        const title = times[index].replace('T', ' ')
        if (index < count) return `${title}<br/>历史负荷：${Number(history[index].load).toFixed(2)} kW`
        const row = rows[index - count]
        return `${title}<br/>预测负荷：${row.point.toFixed(2)} kW<br/>${Math.round(props.record.confidence * 100)}% 预测区间：${row.lower.toFixed(1)} – ${row.upper.toFixed(1)} kW${row.actual != null ? '<br/>实际负荷：' + row.actual.toFixed(2) + ' kW' : '<br/>实际值：待回流'}`
      } },
    grid: { left: 57, right: 22, top: 29, bottom: props.compact ? 33 : 54 },
    xAxis: { type: 'category', data: times, boundaryGap: false, axisTick: { show: false }, axisLine: { lineStyle: { color: '#e8eeea' } },
      axisLabel: { color: '#87938d', fontSize: 10, hideOverlap: true, formatter: value => value.slice(5, 10) + '\n' + value.slice(11, 16) } },
    yAxis: { type: 'value', name: 'kW', nameTextStyle: { color: '#93a097', padding: [0, 0, 0, -30] },
      axisLabel: { fontSize: 10 }, splitLine: { lineStyle: { color: '#edf1ee', type: 'dashed' } }, min: value => Math.max(0, Math.floor(value.min / 100) * 100 - 100) },
    dataZoom: props.compact ? [] : [{ type: 'inside' }],
    series: [
      { name: '区间下界', type: 'line', data: [...empty, ...rows.map(row => row.lower)], stack: 'interval', symbol: 'none', lineStyle: { opacity: 0 }, silent: true },
      { name: '预测区间', type: 'line', data: [...empty, ...rows.map(row => row.upper - row.lower)], stack: 'interval', symbol: 'none', lineStyle: { opacity: 0 }, areaStyle: { color: '#77bda9', opacity: .22 }, silent: true },
      { name: '历史负荷', type: 'line', data: [...history.map(row => row.load), ...Array(rows.length).fill(null)], smooth: .16, symbol: 'none', lineStyle: { color: '#536d76', width: 2 }, itemStyle: { color: '#536d76' } },
      { name: '预测负荷', type: 'line', data: prediction, smooth: .16, symbol: 'none', lineStyle: { color: '#158064', width: 2.5, type: 'dashed' }, itemStyle: { color: '#158064' },
        markLine: { silent: true, symbol: 'none', data: [{ xAxis: times[count - 1], label: { formatter: '预测起点', fontSize: 10, color: '#93a097' } }], lineStyle: { color: '#a7b5aa', type: 'dashed' } } },
      { name: '回流实际值', type: 'line', data: [...empty, ...rows.map(row => row.actual ?? null)], symbol: 'none', lineStyle: { color: '#d49b31', width: 2 } },
    ],
  }
})
</script>
<template><Chart :option="option" :height="height" /></template>
