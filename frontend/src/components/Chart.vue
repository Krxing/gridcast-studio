<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart, BarChart, HeatmapChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, VisualMapComponent, MarkLineComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([LineChart, BarChart, HeatmapChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, VisualMapComponent, MarkLineComponent, CanvasRenderer])
const props = defineProps({ option: { type: Object, required: true }, height: { type: [Number, String], default: 300 } })
const element = ref(null)
let chart
let observer
function update() { if (chart) chart.setOption(props.option, { notMerge: true }) }
onMounted(() => {
  chart = echarts.init(element.value)
  update()
  observer = new ResizeObserver(() => chart?.resize())
  observer.observe(element.value)
})
watch(() => props.option, update, { deep: true })
onBeforeUnmount(() => { observer?.disconnect(); chart?.dispose() })
</script>

<template><div ref="element" class="chart" :style="{ height: typeof height === 'number' ? height + 'px' : height }" role="img" aria-label="可交互数据图表"></div></template>
