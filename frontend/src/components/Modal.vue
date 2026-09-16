<script setup>
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { X } from 'lucide-vue-next'
defineProps({ title: String, wide: Boolean })
const emit = defineEmits(['close'])
const dialog = ref(null)
onMounted(() => dialog.value.showModal())
onBeforeUnmount(() => dialog.value?.close())
</script>
<template>
  <dialog ref="dialog" :class="['modal', { wide }]" @cancel.prevent="emit('close')" @click="event => { if (event.target === dialog) emit('close') }">
    <div class="modal-head"><h2>{{ title }}</h2><button class="icon-button" aria-label="关闭对话框" @click="emit('close')"><X :size="19" /></button></div>
    <div class="modal-body"><slot /></div>
  </dialog>
</template>
