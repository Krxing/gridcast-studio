<script setup>
import { computed, ref, watch } from 'vue'
import { Activity, ArrowRight, Eye, EyeOff, ShieldCheck, Sparkles, Zap } from 'lucide-vue-next'
import { api, notify } from '../state'
const props = defineProps({ setupRequired: Boolean })
const emit = defineEmits(['authenticated'])
const setupMode = ref(props.setupRequired)
watch(() => props.setupRequired, value => { setupMode.value = value })
const username = ref('')
const password = ref('')
const setupToken = ref('')
const showPassword = ref(false)
const loading = ref(false)
const errorMessage = ref('')
const title = computed(() => setupMode.value ? '创建管理员' : '进入预测工作台')
async function submit() {
  errorMessage.value = ''
  loading.value = true
  let result = null
  try {
    result = await api(setupMode.value ? '/auth/setup' : '/auth/login', { method: 'POST', body: { username: username.value, password: password.value, setup_token: setupToken.value } })
  } catch (error) {
    errorMessage.value = error.message || '操作失败，请检查输入后重试'
  }
  loading.value = false
  if (result) { notify(setupMode.value ? '管理员已创建，欢迎进入工作台' : '登录成功'); emit('authenticated') }
}
</script>
<template>
<main class="auth-page"><div class="auth-visual"><div class="auth-grid"></div><div class="auth-logo"><div class="brand-mark"><Zap :size="19" /></div><strong>GRIDCAST</strong><span>ENERGY INTELLIGENCE</span></div><div class="auth-visual-copy"><div class="eyebrow">LOAD FORECASTING STUDIO</div><h1>让每一次预测<br /><em>都有据可依。</em></h1><p>连接数据、模型与决策，让园区负荷的每一个波动都清晰可见。</p></div><div class="auth-stat-row"><div><strong>24 h</strong><span>默认演示窗口</span></div><div><strong>95%</strong><span>名义区间</span></div><div><strong>4</strong><span>核心模块</span></div></div></div><div class="auth-panel"><div class="auth-panel-inner"><div class="mobile-auth-brand"><div class="brand-mark"><Zap :size="18" /></div><b>GRIDCAST</b></div><div class="auth-heading"><div class="auth-icon"><Activity :size="21" /></div><span class="eyebrow">{{ setupMode ? 'FIRST RUN SETUP' : 'SECURE WORKSPACE' }}</span><h2>{{ title }}</h2><p>{{ setupMode ? '首次运行需要创建一个管理员账号。' : '输入账号信息，继续查看预测与模型分析。' }}</p></div><form @submit.prevent="submit"><label>用户名<input v-model="username" autocomplete="username" placeholder="例如 admin" required /></label><label>密码<div class="password-input"><input v-model="password" :type="showPassword ? 'text' : 'password'" autocomplete="current-password" placeholder="至少 8 个字符" minlength="8" required /><button type="button" class="icon-button" :aria-label="showPassword ? '隐藏密码' : '显示密码'" @click="showPassword = !showPassword"><EyeOff v-if="showPassword" :size="17" /><Eye v-else :size="17" /></button></div></label><label v-if="setupMode">初始化令牌（本机可留空）<input v-model="setupToken" type="password" placeholder="云端或远程访问需填 APP_SETUP_TOKEN" autocomplete="off" /></label><p v-if="errorMessage" class="auth-error" role="alert">{{ errorMessage }}</p><button class="button primary auth-submit" :disabled="loading"><span>{{ loading ? '正在验证…' : (setupMode ? '创建管理员并进入' : '登录工作台') }}</span><ArrowRight :size="17" /></button></form><div v-if="!setupMode" class="auth-switch">本地首次使用？<button class="text-link" @click="setupMode = true">创建管理员</button></div><div v-if="setupMode && !setupRequired" class="auth-switch"><button class="text-link" @click="setupMode = false">返回登录</button></div><div class="auth-note"><ShieldCheck :size="16" /><span>本地模式下，账号、数据与模型文件保存在当前部署目录；模型输出仅供分析参考。</span></div></div></div></main>
</template>
