# Backlog

Things we've deliberately deferred. Each item has enough context that
someone can pick it up cold, in any order, when there's time.

For shipped issues, see the
[closed issues list](https://github.com/mahadevaiahrashmi/explainer-bot/issues?q=is%3Aissue+state%3Aclosed).
For the live priority view, see
[project board #6](https://github.com/users/mahadevaiahrashmi/projects/6).

---

## 1. Apply this repo's doc treatment to the maintainer's other repos

**Tracking issue:** [#3](https://github.com/mahadevaiahrashmi/explainer-bot/issues/3)

**Why it's deferred:** every target repo wants docs that *reflect what
it actually does*, not a copy-pasted template. Doing this honestly is
one focused session per repo. Drive-by template-filling would produce
docs that age badly and erode trust.

### Target shape per repo

Each repo should end up with the same six artifacts that explainer-bot
has:

| File | Owns |
| ---- | ---- |
| `README.md` | Project overview · Tech stack table · "For non-technical readers" · "For technical readers" · pointer to the others |
| `USER_MANUAL.md` | Install · run · common flows · troubleshooting · cost |
| `PRD.md` | Problem · personas · requirements · success metrics · risks |
| `PRODUCT_DESIGN.md` | UX flows · screens · component inventory · interaction patterns |
| `SYSTEM_DESIGN.md` | Architecture diagram · components · API contracts · sequence diagrams · decision log · failure modes |
| `TESTING.md` | Strategy · UAT checklist · bug-report workflow |
| `.github/ISSUE_TEMPLATE/` | Bug · feature · config |

Reuse explainer-bot's structure; **edit content per project**.

### Repos in scope (own-built, not forks)

Ordered by how much code is in each (rough proxy for doc effort):

- [ ] `mahadevaiahrashmi.github.io` — portfolio site
- [ ] `cli_todo_app`
- [ ] `todo_app_windows_and_web`
- [ ] `job-search-bot`
- [ ] `job-chatbot-single-call`
- [ ] `job-chatbot-anthropic-sdk`
- [ ] `job-chatbot-langchain`
- [ ] `job-chatbot-crewai`
- [ ] `job-chatbot-vteam-hybrid`
- [ ] `sales_lead_research`
- [ ] `analyst`
- [ ] `play`
- [ ] `play2`
- [ ] `drone`
- [ ] `vedicmath` *(private)*
- [ ] `studio` *(private)*

### Out of scope

- Forks (`mempalace`, `OpenEnv`, `claurst`, `nano-claude-code`, etc.) —
  we don't own them; their upstream owns the docs.
- README polish / TIL-style repos that aren't shippable software.

### Order of operations (per repo)

1. Clone, read the code top-to-bottom (1 hr).
2. Sketch the PRD section by section *talking to yourself in your
   head* — what problem does this actually solve? Who is the user?
   Skip if blank.
3. Draft `SYSTEM_DESIGN.md` from the code, not from imagination.
4. `TESTING.md` follows the system design's component map.
5. Distil `README.md` last — it's the front door, hardest to write
   well.
6. Single PR per repo; commit message links back to this BACKLOG item.

### Definition of done (per repo)

- Six artifacts created.
- Every link in `README.md` clicks through to a real file.
- A teammate-equivalent (or future-you in 6 months) can install + run
  the repo from `USER_MANUAL.md` alone.

---

## (Future items — keep this list short)

When something gets deferred from a session and is too big for a
single issue, add it here as a numbered section above. Keep it under
~5 items; trim aggressively. If a backlog item ages a year without
movement, prefer closing it over keeping it warm.
