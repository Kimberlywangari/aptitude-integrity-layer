<script setup lang="ts">
import { ref } from 'vue'
import BaseButton from '../components/BaseButton.vue'
import type { Invite } from '../lib/adminTypes'
import { inviteLink } from '../lib/inviteCode'

// A candidate's new link, shown once: the server keeps only a hash of the code, so this is the only
// time it can be copied.
const props = defineProps<{ invite: Invite }>()
defineEmits<{ hide: [] }>()

const copied = ref(false)

async function copy() {
  try {
    await navigator.clipboard.writeText(inviteLink(props.invite.code))
    copied.value = true
  } catch {
    copied.value = false // the link is on screen, so it can still be selected and copied by hand
  }
}
</script>

<template>
  <div class="tokenbox" role="status">
    <span>
      New link for <b>{{ invite.candidate_id }}</b
      >, shown once. The old code no longer works.
    </span>
    <code>{{ inviteLink(invite.code) }}</code>
    <BaseButton variant="secondary" @click="copy">{{ copied ? 'Copied' : 'Copy link' }}</BaseButton>
    <BaseButton variant="ghost" @click="$emit('hide')">Hide</BaseButton>
  </div>
</template>
