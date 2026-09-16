<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Activity, BarChart3, BrainCircuit, Database, Gauge, LogOut, Menu, PanelLeftClose, PanelLeftOpen, Settings, SlidersHorizontal, Sparkles, Zap, X } from 'lucide-vue-next'
import { api, act, dateTime, notify, refresh, roles, state } from './state'
import Auth from './pages/Auth.vue'
import Overview from './pages/Overview.vue'
import DataPage from './pages/DataPage.vue'
import Models from './pages/Models.vue'
import Predict from './pages/Predict.vue'
import Compare from './pages/Compare.vue'
import Decompose from './pages/Decompose.vue'
import Monitor from './pages/Monitor.vue'
import SettingsPage from './pages/SettingsPage.vue'

const route = ref(location.hash.slice(1) || 'dashboard')
const collapsed = ref(false)
const mobileOpen = ref(false)
let poll
const nav = [
  { id: 'dashboard', label: '总览', note: '系统状态与核心指标', icon: Gauge },
  { id: 'data', label: '数据管理', note: '数据集与质量校验', icon: Database },
  { id: 'models', label: '训练与模型', note: '训练任务与版本管理', icon: BrainCircuit },
  { id: 'predict', label: '预测分析', note: '在线推理与结果解释', icon: Activity },
  { id: 'decompose', label: '时序分解', note: '趋势、周期与剩余波动', icon: BarChart3 },
  { id: 'compare', label: '评估对比', note: '模型表现横向比较', icon: BarChart3 },
  { id: 'monitor', label: '运行监测', note: '实时更新与学习策略', icon: SlidersHorizontal },
]
const utility = [{ id: 'settings', label: '系统设置', icon: Settings }]
const current = computed(() => [...nav, ...utility].find(item => item.id === route.value) || nav[0])
const component = computed(() => ({ dashboard: Overview, data: DataPage, models: Models, predict: Predict, compare: Compare, decompose: Decompose, monitor: Monitor, settings: SettingsPage }[route.value] || Overview))
function navigate(id) { location.hash = id; mobileOpen.value = false }
function onHash() { route.value = location.hash.slice(1) || 'dashboard'; mobileOpen.value = false }
async function boot() {
  const status = await api('/status').catch(() => null)
  state.status = status
  if (status?.setup_required) return
  state.user = await api('/me').catch(() => null)
  if (state.user) await refresh()
}
async function logout() { await act(() => api('/auth/logout', { method: 'POST' })); state.user = null; state.summary = null }
onMounted(() => { window.addEventListener('hashchange', onHash); act(boot); poll = setInterval(() => act(refresh), 4000) })
onUnmounted(() => { window.removeEventListener('hashchange', onHash); clearInterval(poll) })
watch(() => state.user, async value => { if (value && !state.summary) await act(refresh) })
</script>

<template>
  <Auth v-if="!state.user" :setup-required="state.status?.setup_required" @authenticated="boot" />
  <div v-else class="app-shell">
    <div v-if="mobileOpen" class="mobile-scrim" @click="mobileOpen = false"></div>
    <aside :class="['sidebar', { collapsed, mobileOpen }]">
      <div class="brand"><div class="brand-mark"><Zap :size="19" /></div><div class="brand-copy"><strong>GRIDCAST</strong><span>ENERGY INTELLIGENCE</span></div><button class="icon-button sidebar-close" aria-label="关闭侧边栏" @click="mobileOpen = false"><X :size="18" /></button></div>
      <div class="workspace-switch"><span class="workspace-dot"></span><div><b>用电负荷工作台</b><small>{{ state.settings?.mode === 'cloud' ? '云端部署' : '本地部署' }} · {{ state.datasets.length }} 个数据集</small></div><span class="live-pill">LIVE</span></div>
      <nav class="main-nav" aria-label="主导航"><div class="nav-section-label">WORKSPACE</div><a v-for="item in nav" :key="item.id" :href="'#' + item.id" :class="['nav-item', { active: route === item.id }]" :title="collapsed ? item.label : ''"><component :is="item.icon" :size="18" /><span class="nav-copy"><b>{{ item.label }}</b><small>{{ item.note }}</small></span><i v-if="item.id === 'monitor' && state.settings?.learning?.enabled" class="nav-live-dot"></i></a><div class="nav-section-label secondary">SYSTEM</div><a v-for="item in utility" :key="item.id" :href="'#' + item.id" :class="['nav-item', { active: route === item.id }]" :title="collapsed ? item.label : ''"><component :is="item.icon" :size="18" /><span class="nav-copy"><b>{{ item.label }}</b></span></a></nav>
      <div class="sidebar-bottom"><div class="support-box"><Sparkles :size="16" /><div><b>科研模式</b><span>实验记录可追溯</span></div></div><div class="user-block"><div class="avatar">{{ state.user.username.slice(0, 1).toUpperCase() }}</div><div class="user-copy"><b>{{ state.user.username }}</b><span>{{ roles[state.user.role] }}</span></div><button class="icon-button" aria-label="退出登录" title="退出登录" @click="logout"><LogOut :size="16" /></button></div></div>
    </aside>
    <main class="main-content">
      <header class="topbar"><button class="icon-button mobile-menu" aria-label="打开导航" @click="mobileOpen = true"><Menu :size="20" /></button><button class="icon-button collapse-button" :aria-label="collapsed ? '展开侧边栏' : '收起侧边栏'" @click="collapsed = !collapsed"><PanelLeftOpen v-if="collapsed" :size="18" /><PanelLeftClose v-else :size="18" /></button><div class="breadcrumbs"><span>工作台</span><i>/</i><strong>{{ current.label }}</strong></div><div class="topbar-actions"><span class="system-state"><i :class="['state-dot', { warning: !state.summary?.worker_alive }]" />{{ state.summary?.worker_alive ? '计算服务在线' : '计算服务离线' }}</span><span class="topbar-time">{{ dateTime(new Date()) }}</span></div></header>
      <div class="page-wrap"><component :is="component" @navigate="navigate" /></div>
    </main>
  </div>
    <div class="toast-stack" aria-live="polite"><TransitionGroup name="toast"><div v-for="item in state.notifications" :key="item.id" :class="['toast', item.kind]"><span class="toast-mark">{{ item.kind === 'error' ? '!' : '✓' }}</span>{{ item.message }}</div></TransitionGroup></div>
</template>
