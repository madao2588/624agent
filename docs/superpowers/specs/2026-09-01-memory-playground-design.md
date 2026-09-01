# Memory Playground Design

**Date:** 2026-09-01
**Status:** Approved

## Goal

Give a non-technical user an immediate, visual understanding of agent memory
without scores, benchmark jargon, API keys, or raw Swagger requests.

The experience must make four behaviors visible:

1. memories are written during separate sessions;
2. a later query retrieves relevant source evidence;
3. a later update can coexist with the earlier fact;
4. changing `user_id` prevents one person's memory from appearing for another.

## Chosen experience

Add a single local page at `/demo`. It is a same-origin client of the existing
official Add/Search routes and does not introduce a second memory implementation.

The page has three guided steps:

1. **Build the memory:** load a prepared three-session story or write a custom
   memory. The prepared story records a coffee preference, a meeting plan, and
   a later change to that plan. A second user receives a conflicting preference.
2. **Ask the memory:** choose a suggested query or type one. Results show the
   exact stored evidence, timestamp, and relevance order rather than generating
   a final answer.
3. **Test isolation:** switch between the two user identities and repeat a
   query to see that results stay inside the selected user's scope.

The page keeps a browser-side activity timeline for the current experience.
"Start fresh" creates a new random namespace and clears the visible timeline;
it does not add a destructive database endpoint or weaken evaluation behavior.

## Interaction contract

- `Load demo story` sends four synchronous Add calls: three for the primary
  user across distinct sessions and one for the comparison user.
- Custom memory sends one Add call using the selected user and a new session.
- Search sends `query`, selected `user_id`, and `top_k: 5`.
- Buttons are disabled while their request is in flight.
- Success and error messages use an `aria-live` region and include a recovery
  action or explanation.
- User content is rendered with `textContent`, never interpolated as HTML.
- The demo remains a presentation layer. `/v1/memories/add` and
  `/v1/memories/search` stay the source of truth and retain normal auth rules.

## Visual system

Use the UI/UX design-system recommendation for an AI developer tool:

- modern dark, content-first presentation;
- slate background and surfaces with a green run/success accent;
- semantic CSS tokens for background, surface, text, muted text, border,
  accent, warning, and error;
- system sans-serif typography so the demo has no external font dependency;
- two-column desktop layout and one-column mobile layout;
- controls at least 44px high, visible focus rings, readable contrast, and
  responsive behavior down to 375px;
- only subtle opacity/transform transitions and a reduced-motion override.

Avoid decorative dashboards, charts, scores, emoji icons, external assets,
glass effects that reduce contrast, and animations unrelated to state changes.

## Packaging

Keep the self-contained HTML, CSS, and JavaScript in
`src/aml_memory/demo.html`. Serve it with a small unlisted FastAPI route. The
file must be included in the built wheel and Docker image. No new dependency is
needed.

## Verification

- A failing route test is observed before implementation.
- Unit tests verify `/demo` is public, HTML, unlisted from OpenAPI, and contains
  the core accessible controls.
- Ruff, Mypy, all Pytest tests, and compileall pass.
- A built wheel contains `aml_memory/demo.html`.
- Docker still passes the existing 56-operation evaluation preflight.
- Real-browser QA covers prepared story loading, relevant retrieval, user
  isolation, custom memory, fresh namespace, 375px responsive layout, console
  errors, and failed network requests.
