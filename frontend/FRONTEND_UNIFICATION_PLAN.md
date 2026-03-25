# Frontend Unification - Technical Change Plan

This is an implementation plan with concrete file edits and dependency actions.

## 0) Current Technical Snapshot

- Legacy runtime entry: `src/main.jsx` + `src/App.jsx` (state-driven pages, no router)
- Phase2 runtime entry: `src/Phase2App.jsx` + `src/phase2/App.tsx` (React Router)
- Temporary split boot: route-conditional loading in `src/main.jsx`
- Dependencies already aligned to modern stack (`react`, `react-dom`, `react-router-dom`, Tailwind plugin)

Target:

- One root app and one router tree
- No conditional bootstrap in `src/main.jsx`
- Legacy and phase2 features mounted as route components
- Shared API layer + shared UI primitives

---

## 1) Libraries / Tooling to Keep and Standardize

## 1.1 Keep versions (do not downgrade)

In `frontend/package.json`, keep:

- `react` and `react-dom` at latest compatible patch
- `react-router-dom` (phase2-compatible)
- `@tailwindcss/vite` + `tailwindcss`
- `react-markdown`, `remark-gfm`

## 1.2 Add TypeScript build safety for migrated TS/TSX

Add dev deps:

- `typescript`
- `@types/react`
- `@types/react-dom`
- `@types/node`

Add files:

- `frontend/tsconfig.json`
- `frontend/tsconfig.node.json`

Set `"allowJs": true` so existing `.jsx` legacy code keeps compiling while TS files are validated.

---

## 2) Remove Split Bootstrap (main hard requirement)

Current file: `src/main.jsx` (conditional dynamic imports by pathname)

## 2.1 Create unified app router

Create `src/AppRouter.tsx`:

- Wrap app in `BrowserRouter`
- Mount two route groups:
  - legacy routes (`/`, `/about`, etc.) via adapter components
  - phase2 routes under `/phase2/*` using `src/phase2` pages/layout

## 2.2 Change `src/main.jsx`

Replace conditional bootstrap with:

- static import `./index.css`
- static import `./phase2/index.css` (or load through router layout if preferred)
- render `<AppRouter />`

Result: one runtime, one style graph, no path-based app boot.

---

## 3) Legacy App Routing Migration (state -> route components)

Current `src/App.jsx` switches pages with `currentPage` state.
This must be decomposed so router controls navigation.

## 3.1 Create route wrappers

Add:

- `src/legacy/routes/ChatRoute.jsx`
- `src/legacy/routes/AboutRoute.jsx`
- `src/legacy/routes/SandboxLoginRoute.jsx`
- `src/legacy/routes/SandboxRoute.jsx`

Each wrapper should pass old callbacks/props expected by existing components.

## 3.2 Build legacy route tree

In `src/AppRouter.tsx`, define:

- `/` -> chat route
- `/about`
- `/developer/login`
- `/developer/sandbox`

Then remove page-switch logic from `src/App.jsx` (or retire `src/App.jsx` once wrappers are stable).

---

## 4) Phase2 Router Integration

`src/phase2/App.tsx` currently creates its own `BrowserRouter`.
This must become route-only.

## 4.1 Refactor `src/phase2/App.tsx`

Change from:

- app component that returns `UiAgentsProvider + BrowserRouter + Routes`

To:

- exported `Phase2Routes` component returning only `<Routes>...</Routes>`
- keep `UiAgentsProvider` outside or wrap only phase2 subtree in `AppRouter.tsx`

## 4.2 Keep paths stable initially

In unified router keep:

- `/phase2/chat`
- `/phase2/chat/:conversationId`
- `/phase2/new`
- `/phase2/conversations`
- `/phase2/agents`
- `/phase2/agents/:agentId/contexts`

Add redirects from old phase2 defaults as needed.

---

## 5) CSS Conflict Elimination (core cause class)

Potential conflicts come from global selectors in legacy `src/index.css`.

## 5.1 Scope legacy globals

In `src/index.css`, migrate broad selectors:

- `*`, `body`, `h1..h6`, `a`, `button`

to scoped wrapper class for legacy routes (e.g. `.legacy-root ...`).

Implementation:

- add wrapper div class in legacy route layout
- update selectors accordingly

## 5.2 Keep phase2 base styles isolated

`src/phase2/index.css` should remain phase2-focused.
If global selectors remain, gate them by a route wrapper class (e.g. `.phase2-root`).

---

## 6) API Layer Merge

You currently have:

- legacy API usages scattered in legacy components
- `src/phase2/api/client.ts` for phase2

## 6.1 Create shared service folder

Add:

- `src/services/http.ts` (base `fetch` wrapper + credentials + error normalization)
- `src/services/chat.ts`
- `src/services/agents.ts`

Then gradually switch both legacy and phase2 callers to shared services.

## 6.2 Deprecate old direct fetch calls

For each migrated feature, remove direct endpoint calls from component files.

---

## 7) Component Convergence (dedupe plan)

Duplicate candidates to merge first:

- conversation list cards
- agent cards/modals
- chat message bubble + markdown renderers
- side/context panel

## 7.1 Create shared UI primitives

Add folder:

- `src/components/shared/`

Start with:

- `Button`
- `Card`
- `Modal`
- `Spinner`

Then use in both legacy and phase2 pages.

---

## 8) Incremental PR Plan (recommended order)

## PR-1: Router foundation

- add `src/AppRouter.tsx`
- refactor `src/main.jsx` to single root
- mount legacy + phase2 route trees
- no visual redesign yet

Acceptance:

- `/` works
- `/phase2/*` works
- no conditional bootstrap code remains

## PR-2: Phase2 router extraction

- refactor `src/phase2/App.tsx` to route-only exports
- move provider wrapping to `AppRouter.tsx`

Acceptance:

- phase2 nav and deep links unchanged

## PR-3: Legacy state-navigation removal

- introduce legacy route wrappers
- remove `currentPage` state switching in `src/App.jsx`

Acceptance:

- all legacy pages reachable via URL routes

## PR-4: CSS scoping

- scope legacy global CSS under `.legacy-root`
- ensure phase2 styling unaffected

Acceptance:

- no style regression on `/phase2`
- legacy pages still styled

## PR-5: Shared API/services + shared UI primitives

- add services layer
- migrate 1-2 features from each side to shared services
- add and adopt shared primitives

Acceptance:

- no endpoint behavior changes
- reduced duplicate UI blocks

---

## 9) Final Cleanup Tasks

After all above are done:

- delete `src/Phase2App.jsx`
- remove any leftover split-boot logic
- remove dead legacy-only CSS/selectors
- remove duplicated files under `src/phase2` that are replaced by shared modules

---

## 10) Verification Checklist Per Step

Run on each PR:

- `npm run build`
- `npm run lint`
- manual checks:
  - `/`
  - legacy subroutes
  - `/phase2/chat`
  - `/phase2/agents`
  - `/phase2/conversations`

Optional:

- add Playwright smoke tests for these routes before large refactors.

