<script setup lang="ts">
// Three doors, one per kind of person. This is part of the main bundle, which a candidate on a
// weak connection downloads, so it stays plain: no data, no staff code.
import BrandMark from '../components/BrandMark.vue'
import Icon from '../components/Icon.vue'
import type { IconName } from '../components/icons'
import { CANDIDATE_PATH, LOGIN_PATH } from '../lib/routes'

const CHOICES: { to: string; title: string; text: string; icon: IconName }[] = [
  {
    to: CANDIDATE_PATH,
    title: 'Candidate',
    text: 'I am taking the aptitude test and have an invitation code.',
    icon: 'user',
  },
  {
    to: LOGIN_PATH.reviewer,
    title: 'Reviewer',
    text: 'I look at flagged candidates and record what I find.',
    icon: 'clipboard',
  },
  {
    to: LOGIN_PATH.admin,
    title: 'Admin',
    text: 'I set up sittings, questions and invitations.',
    icon: 'sliders',
  },
]
</script>

<template>
  <main class="page entry">
    <BrandMark />
    <h1>Aptitude test</h1>
    <p class="lead">Choose who you are to continue.</p>
    <ul class="cards">
      <li v-for="(choice, index) in CHOICES" :key="choice.to" class="rise" :style="{ '--d': `${index * 50}ms` }">
        <RouterLink :to="choice.to" class="entry-card">
          <span class="ico"><Icon :name="choice.icon" size="1.35rem" /></span>
          <span class="txt">
            <strong>{{ choice.title }}</strong>
            <span>{{ choice.text }}</span>
          </span>
          <Icon name="arrow-right" class="go" />
        </RouterLink>
      </li>
    </ul>
  </main>
</template>

<style scoped>
.cards {
  display: grid;
  gap: 0.8rem;
  padding: 0;
  margin: 1.5rem 0 0;
  list-style: none;
}

.entry-card {
  display: flex;
  gap: 1rem;
  align-items: center;
  padding: 1rem 1.15rem;
  color: inherit;
  text-decoration: none;
  background: var(--surface);
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  transition:
    transform 160ms var(--ease-out),
    border-color 160ms var(--ease-out),
    box-shadow 160ms var(--ease-out);
}

.ico {
  display: grid;
  flex: none;
  place-items: center;
  width: 2.75rem;
  height: 2.75rem;
  color: var(--accent);
  background: var(--accent-tint);
  border-radius: var(--radius);
}

.txt {
  display: grid;
  flex: 1;
  gap: 0.1rem;
  min-width: 0;
}

.txt strong {
  font-size: 1.08rem;
  letter-spacing: -0.01em;
}

.txt span {
  color: var(--muted);
  font-size: 0.94rem;
}

.go {
  flex: none;
  color: var(--muted);
  transition:
    transform 160ms var(--ease-out),
    color 160ms var(--ease-out);
}

.entry-card:active {
  transform: scale(0.985);
}

@media (hover: hover) and (pointer: fine) {
  .entry-card:hover {
    border-color: var(--accent);
    box-shadow: var(--shadow-md);
    transform: translateY(-2px);
  }

  .entry-card:hover .go {
    color: var(--accent);
    transform: translateX(3px);
  }
}

@media (prefers-reduced-motion: reduce) {
  .entry-card:active,
  .entry-card:hover {
    transform: none;
  }

  .entry-card:hover .go {
    transform: none;
  }
}
</style>
