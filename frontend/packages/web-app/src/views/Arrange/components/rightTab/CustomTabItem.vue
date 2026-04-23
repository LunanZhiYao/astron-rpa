<script lang="ts" setup>
import { computed, inject, onMounted, ref, watch } from 'vue'
import type { Ref } from 'vue'

type Position = 'top' | 'left' | 'right' | 'bottom'

interface Tab {
  name: string
  value: PropertyKey
  size?: string | number
}

interface TabsContext {
  activeTab: Ref<Tab['value']>
  position: Ref<Position>
  registerTab: (tab: Tab) => void
}

const props = defineProps<Tab>()

const context = inject<TabsContext>('tabsContext')
const isActive = computed(() => context?.activeTab.value === props.value)
const mountedOnce = ref(false)

watch(isActive, (active) => {
  if (active) {
    mountedOnce.value = true
  }
}, { immediate: true })

onMounted(() => {
  if (!context)
    return
  const { name, value, size } = props
  context?.registerTab({ name, value, size })
})
</script>

<template>
  <div v-if="mountedOnce" v-show="isActive" class="custom-tab-panel">
    <slot />
  </div>
</template>

<style lang="scss" scoped>
.custom-tab-panel {
  width: 100%;
  height: 100%;
}
</style>
