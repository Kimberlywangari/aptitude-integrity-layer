<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { humaniseKind } from '../lib/format'
import type { QueueItem } from '../lib/reviewTypes'
import { FLAG_LABELS, OUTCOME_LABELS, orderBasis } from './copy'

defineProps<{ items: QueueItem[] }>()

const kindsOf = (item: QueueItem) => [...new Set(item.flag_kinds)]
</script>

<template>
  <div class="table-wrap">
    <table class="table">
      <thead>
        <tr>
          <th>Rank</th>
          <th>Candidate</th>
          <th>Flags</th>
          <th>Order set by</th>
          <th>Rule score</th>
          <th>Decision</th>
          <th>Shortlist</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in items" :key="item.candidate_id">
          <td><span class="rank">{{ item.rank }}</span></td>
          <td class="nowrap">
            <RouterLink :to="`/review/candidates/${item.candidate_id}`">{{ item.candidate_id }}</RouterLink>
          </td>
          <td>
            <span v-for="kind in kindsOf(item)" :key="kind" class="chip">
              {{ FLAG_LABELS[kind] ?? humaniseKind(kind) }}
            </span>
          </td>
          <td>
            <span class="badge" :class="{ ai: item.ai_strength !== null }">
              {{ orderBasis(item.ai_status, item.ai_strength) }}
            </span>
          </td>
          <td>{{ item.rule_score }}</td>
          <td class="nowrap">{{ item.decision ? OUTCOME_LABELS[item.decision] : 'Not decided' }}</td>
          <td>{{ item.shortlisted ? 'Shortlisted' : '' }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
