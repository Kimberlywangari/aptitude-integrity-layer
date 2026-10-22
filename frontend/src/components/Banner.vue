<script setup lang="ts">
import { computed } from 'vue'
import type { IconName } from './icons'
import Icon from './Icon.vue'

const props = withDefaults(
  defineProps<{
    /** warn is the default yellow notice; bad is an error; good is a success; info is neutral. */
    tone?: 'warn' | 'info' | 'bad' | 'good'
    /** status is announced politely, alert at once. Leave it off for text that is always there. */
    role?: 'status' | 'alert'
    icon?: IconName | null
  }>(),
  { tone: 'warn', role: undefined, icon: undefined },
)

const cssTone = computed(() => (props.tone === 'warn' ? '' : props.tone))
const iconName = computed<IconName | null>(() => {
  if (props.icon !== undefined) return props.icon
  return { warn: 'alert', info: 'info', bad: 'alert', good: 'check' }[props.tone] as IconName
})
</script>

<template>
  <div class="banner" :class="cssTone" :role="role">
    <Icon v-if="iconName" :name="iconName" class="lead-icon" />
    <div class="body"><slot /></div>
  </div>
</template>

<style scoped>
.lead-icon {
  margin-top: 0.1rem;
}

.body {
  min-width: 0;
}

.body :deep(p) {
  margin: 0;
}

.body :deep(p + p) {
  margin-top: 0.4rem;
}
</style>
