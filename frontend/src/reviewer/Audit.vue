<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import Banner from '../components/Banner.vue'
import { api } from '../lib/api'
import { formatDateTime } from '../lib/format'
import type { AuditEntry } from '../lib/reviewTypes'

const ACTION_LABELS: Record<AuditEntry['action'], string> = {
  login: 'Sign-in',
  decision: 'Decision or shortlist',
  video_view: 'Video viewed',
  video_purged: 'Video deleted',
  admin: 'Setup action',
}

const { data, isPending, isError } = useQuery({
  queryKey: ['audit'],
  queryFn: () => api<{ entries: AuditEntry[] }>('/api/review/audit'),
})
</script>

<template>
  <p v-if="isPending" role="status">Loading the audit log...</p>
  <Banner v-else-if="isError" tone="bad" role="alert"><p>Could not load the audit log.</p></Banner>
  <template v-else-if="data">
    <h1>Audit log</h1>
    <p class="muted">Sign-ins, decisions, video views, setup actions and deletions, newest first.</p>
    <div class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th>When</th>
            <th>Who</th>
            <th>Action</th>
            <th>Candidate</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="entry in data.entries" :key="entry.id">
            <td>{{ formatDateTime(entry.ts) }}</td>
            <td>{{ entry.reviewer }}</td>
            <td>{{ ACTION_LABELS[entry.action] }}</td>
            <td>{{ entry.candidate_id ?? '' }}</td>
            <td>{{ entry.detail }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </template>
</template>
