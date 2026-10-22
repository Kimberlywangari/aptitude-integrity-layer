<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { AdminSitting, QuestionBankSummary } from '../lib/adminTypes'
import Icon from '../components/Icon.vue'
import { setupSteps } from './setup'
import type { StepState } from './setup'

const props = defineProps<{ bank: QuestionBankSummary; sittings: AdminSitting[] }>()

const STATE_LABEL: Record<StepState, string> = {
  done: 'Done',
  todo: 'To do',
  later: 'Waiting',
}

const steps = computed(() => setupSteps(props.bank, props.sittings))
</script>

<template>
  <section class="panel" aria-labelledby="setup-title">
    <h2 id="setup-title">Setup</h2>
    <ol class="setup-steps">
      <li v-for="(step, index) in steps" :key="step.key" class="setup-step" :class="step.state">
        <span class="setup-mark" aria-hidden="true">
          <Icon v-if="step.state === 'done'" name="check" size="0.95rem" />
          <template v-else>{{ index + 1 }}</template>
        </span>
        <div>
          <p class="setup-title">
            {{ step.title }} <span class="setup-state">{{ STATE_LABEL[step.state] }}</span>
          </p>
          <p class="muted">
            {{ step.detail }}
            <template v-if="step.link">
              <a v-if="step.link.to.startsWith('#')" :href="step.link.to">{{ step.link.label }}</a>
              <RouterLink v-else :to="step.link.to">{{ step.link.label }}</RouterLink>
            </template>
          </p>
        </div>
      </li>
    </ol>
  </section>
</template>
