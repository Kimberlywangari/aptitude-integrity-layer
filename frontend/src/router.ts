import { createRouter, createWebHistory } from 'vue-router'
import type { RouteLocationNormalized, RouteRecordRaw } from 'vue-router'
import Complaint from './candidate/Complaint.vue'
import Done from './candidate/Done.vue'
import Integrity from './candidate/Integrity.vue'
import PreCheck from './candidate/PreCheck.vue'
import Resume from './candidate/Resume.vue'
import Start from './candidate/Start.vue'
import TestRunner from './candidate/TestRunner.vue'
import UploadStatus from './candidate/UploadStatus.vue'
import Entry from './entry/Entry.vue'
import { CANDIDATE_PATH, homeFor, LOGIN_PATH, loginPathFor } from './lib/routes'
import { getStaff } from './lib/staffSession'

// The candidate's screens are in the main bundle on purpose: a chunk that has to be fetched in the
// middle of a test is a chunk that can fail on a weak connection. Everything staff-facing is lazy,
// so none of it (nor TanStack Query) reaches a candidate's browser.
export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: Entry,
    // Invitation links written before the entry page existed (/?t=CODE) still work.
    beforeEnter: (to) =>
      typeof to.query.t === 'string' && to.query.t
        ? { path: CANDIDATE_PATH, query: { t: to.query.t }, replace: true }
        : true,
  },
  { path: CANDIDATE_PATH, component: Start },
  { path: '/precheck', component: PreCheck },
  { path: '/integrity', component: Integrity },
  { path: '/test', component: TestRunner },
  { path: '/done', component: Done },
  { path: '/uploading', component: UploadStatus },
  { path: '/resume', component: Resume },
  { path: '/complaint', component: Complaint },

  {
    path: LOGIN_PATH.reviewer,
    component: () => import('./staff/SignIn.vue'),
    props: { area: 'reviewer' },
  },
  {
    path: LOGIN_PATH.admin,
    component: () => import('./staff/SignIn.vue'),
    props: { area: 'admin' },
  },
  { path: '/login/:rest(.*)*', redirect: '/' },
  // The old reviewer sign-in address keeps working, and keeps where the person was going.
  { path: '/review/login', redirect: (to) => ({ path: LOGIN_PATH.reviewer, query: to.query }) },

  {
    path: '/review',
    component: () => import('./staff/StaffLayout.vue'),
    meta: { staff: true },
    children: [
      { path: '', component: () => import('./reviewer/Queue.vue') },
      {
        path: 'candidates/:id',
        component: () => import('./reviewer/CandidateDetail.vue'),
        props: true,
      },
      { path: 'audit', component: () => import('./reviewer/Audit.vue') },
      { path: ':rest(.*)*', redirect: '/review' },
    ],
  },
  {
    path: '/admin',
    component: () => import('./staff/StaffLayout.vue'),
    meta: { staff: true, role: 'admin' },
    children: [
      { path: '', component: () => import('./admin/Sittings.vue') },
      { path: 'invites', component: () => import('./admin/Invites.vue') },
      { path: 'questions', component: () => import('./admin/Questions.vue') },
      { path: ':rest(.*)*', redirect: '/admin' },
    ],
  },

  { path: '/:pathMatch(.*)*', redirect: '/' },
]

/** Signed-out (or too-low-privilege) visitors are sent to the matching sign-in, with a way back. */
export function staffGuard(to: RouteLocationNormalized) {
  if (!to.matched.some((record) => record.meta?.staff)) return true
  const staff = getStaff()
  if (!staff) return { path: loginPathFor(to.path), query: { next: to.fullPath } }
  if (to.matched.some((record) => record.meta?.role === 'admin') && staff.role !== 'admin') {
    return homeFor(staff.role)
  }
  return true
}

export function createAppRouter(history = createWebHistory()) {
  const router = createRouter({ history, routes })
  router.beforeEach(staffGuard)
  return router
}

export default createAppRouter()
