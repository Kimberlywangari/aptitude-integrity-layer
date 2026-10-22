<script setup lang="ts">
// The one button. `busy` shows a spinner, keeps the label (so the width does not jump) and
// disables the button until the work is done.
withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
    size?: 'md' | 'lg'
    type?: 'button' | 'submit'
    busy?: boolean
    disabled?: boolean
    block?: boolean
  }>(),
  { variant: 'primary', size: 'md', type: 'button', busy: false, disabled: false, block: false },
)
</script>

<template>
  <button
    class="btn"
    :class="[variant === 'primary' ? '' : variant, size === 'lg' ? 'lg' : '', block ? 'block' : '']"
    :type="type"
    :disabled="disabled || busy"
    :aria-busy="busy ? 'true' : undefined"
  >
    <span v-if="busy" class="spinner" aria-hidden="true" />
    <slot />
  </button>
</template>
