<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { crumbsFor } from './crumbs'

// Shown only below the top of a section, where "where am I, and how do I get back" matters.
const route = useRoute()
const crumbs = computed(() => crumbsFor(route.path))
</script>

<template>
  <nav v-if="crumbs.length >= 2" aria-label="Breadcrumb" class="breadcrumbs">
    <ol>
      <li v-for="(crumb, index) in crumbs" :key="crumb.label">
        <RouterLink v-if="crumb.to && index < crumbs.length - 1" :to="crumb.to">{{ crumb.label }}</RouterLink>
        <span v-else aria-current="page">{{ crumb.label }}</span>
      </li>
    </ol>
  </nav>
</template>
