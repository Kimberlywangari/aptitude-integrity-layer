<script setup lang="ts">
import { ref } from 'vue'
import { MIN_PASSWORD_CHARS } from '../lib/signIn'

// The fields of the start page and the upload page. The code comes from the invitation link; the
// password is typed once they have one, or chosen (and repeated) at their first sign-in.
defineProps<{ creating: boolean; busy: boolean }>()
const token = defineModel<string>('token', { required: true })
const email = defineModel<string>('email', { required: true })
const password = defineModel<string>('password', { required: true })
const repeat = defineModel<string>('repeat', { required: true })

const codeInput = ref<HTMLInputElement | null>(null)
const emailInput = ref<HTMLInputElement | null>(null)
const show = ref(false)

defineExpose({
  focusCode: () => codeInput.value?.focus(),
  focusEmail: () => emailInput.value?.focus(),
})
</script>

<template>
  <label class="field" for="invitation">Invitation code</label>
  <input
    id="invitation"
    ref="codeInput"
    v-model="token"
    class="code"
    autocomplete="off"
    autocapitalize="characters"
    autocorrect="off"
    spellcheck="false"
    placeholder="XXXX-XXXX"
    :disabled="busy"
  />

  <label class="field" for="email">Email address</label>
  <input
    id="email"
    ref="emailInput"
    v-model="email"
    class="address"
    type="email"
    autocomplete="email"
    autocapitalize="none"
    spellcheck="false"
    placeholder="name@example.com"
    :disabled="busy"
  />

  <template v-if="creating">
    <label class="field" for="new-password">Choose a password</label>
    <input
      id="new-password"
      v-model="password"
      class="address"
      :type="show ? 'text' : 'password'"
      autocomplete="new-password"
      autocapitalize="none"
      spellcheck="false"
      :minlength="MIN_PASSWORD_CHARS"
      :disabled="busy"
    />
    <label class="field" for="repeat-password">Type it again</label>
    <input
      id="repeat-password"
      v-model="repeat"
      class="address"
      :type="show ? 'text' : 'password'"
      autocomplete="new-password"
      autocapitalize="none"
      spellcheck="false"
      :disabled="busy"
    />
    <p class="muted hint">At least {{ MIN_PASSWORD_CHARS }} characters. Keep it to yourself.</p>
  </template>
  <template v-else>
    <label class="field" for="password">Password</label>
    <input
      id="password"
      v-model="password"
      class="address"
      :type="show ? 'text' : 'password'"
      autocomplete="current-password"
      autocapitalize="none"
      spellcheck="false"
      :disabled="busy"
    />
    <p class="muted hint">First time? Leave this empty: you will be asked to choose one.</p>
  </template>

  <label class="show">
    <input v-model="show" type="checkbox" />
    <span>Show the password</span>
  </label>
</template>

<style scoped>
.code {
  margin-bottom: 1rem;
  font-family: var(--font-mono);
  font-size: max(16px, 1.35rem);
  letter-spacing: 0.12em;
  text-align: center;
  text-transform: uppercase;
}

.code::placeholder {
  color: var(--field-line);
  text-transform: none;
}

.address {
  margin-bottom: 1rem;
}

.hint {
  margin: -0.5rem 0 0.75rem;
  font-size: 0.9rem;
}

.show {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  margin-bottom: 1rem;
  font-size: 0.95rem;
  cursor: pointer;
}
</style>
