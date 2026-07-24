# SkyDesk

**A self-hosted, role-driven ticket management system with a real-time Kanban board — built with Django, Channels, Tailwind CSS v4 and DaisyUI v5.**

SkyDesk is what you reach for when Jira is too much and a spreadsheet is too little: a fast, opinionated ticket tracker for small teams where a coordinator distributes work, executors get it done, experts advise, and everyone sees the same live board.

![Django](https://img.shields.io/badge/Django-6.0-092E20?logo=django&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-v4-06B6D4?logo=tailwindcss&logoColor=white)
![DaisyUI](https://img.shields.io/badge/DaisyUI-v5-1AD1A5)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-4169E1?logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)

---

## Features

### Kanban board, live
- **Real-time updates** over WebSockets (Django Channels + Redis): when anyone moves, comments or closes a ticket, every open board refreshes itself — no polling, no F5.
- **Drag & drop** between columns (Backlog → To do → In progress → Done → Suspended), gated by role permissions.
- Cards encode a lot at a glance: status-colored border, priority bars, due-date glow when overdue, activity-type chips, avatar stacks, attachment/comment counters.

### Roles that match how teams actually work
| Role | What they do |
|---|---|
| **Coordinator** | Creates and assigns tickets, approves/rejects conclusions, suspends, archives, manages projects and activity types |
| **Executor** | Works the tickets assigned to them; sees the board as *their* subtickets |
| **Expert** | Consulted on tickets they participate in |
| **Follow-up** | Read-only visibility over everything |

Permissions are capability-based (not hardcoded role checks), editable from an admin UI — so you can reshape roles without touching code.

### Work-splitting that mirrors reality
- **Multiproduct tickets**: one ticket, one independent subticket per executor — each moves through the board on its own, and the parent aggregates their state.
- **Divide**: clone a ticket into an identical sibling part (same content, state and assignees) to split the same work.
- **Derive**: spin off an empty subtask that hangs from the parent.
- Derived/divided tickets **inherit the parent's conversation and history live** — context is never lost, and it stays read-only where it belongs.

### Conversation-first tickets
- A **follow-up chat** per ticket with drag & drop file uploads, image thumbnails and a gallery.
- **Draw on images**: annotate any uploaded image right in the browser (freehand, colors, stroke sizes); the annotated version is posted to the chat as a new attachment version.
- **Pluggable attachment storage**: Nextcloud (WebDAV) out of the box — files land in human-browsable folders per ticket — plus local-disk and in-memory backends. Adding S3 or anything else is one small class.

### Built-in workflow guarantees
- Conclusion → **approval flow**: an executor concludes with an optional result note; the coordinator approves or rejects with feedback (which lands in the chat and notifies the executor).
- **Time tracking** per assignment: how long each subticket spent in *To do* and *In progress*, computed automatically.
- Full **audit history** per ticket, in-app **notifications** + email, due-date reminders via cron.

### Pleasant to look at, day and night
- Dark mode is a first-class citizen — surfaces, avatars and badges are tuned for both themes, not just inverted.
- Dense, keyboard-friendly UI with DaisyUI components; every animation respects `prefers-reduced-motion`.

> **Note:** the UI is currently in Spanish (`LANGUAGE_CODE = 'es'`). The codebase is standard Django, so translating via `gettext` is straightforward.

---

## Quick start (local)

Requires Python 3.12+ and Node.js (for the Tailwind build). SQLite by default — no containers needed.

```bash
git clone https://github.com/gonmace/skydesk.git && cd skydesk
make install     # Python deps + Tailwind
make setup       # interactive wizard → generates .env (choose SQLite for dev)
make dev         # migrate + Tailwind watcher + runserver
```

Then load demo data and log in:

```bash
python manage.py seed_demo   # demo users for all 4 roles + sample tickets
```

See [TESTING-ROLES.md](TESTING-ROLES.md) for the demo credentials and a dev-only impersonation tool to browse as any user.

Projects can also be bulk-imported from an Excel file with `python manage.py load_proyectos --file yourfile.xlsx` (idempotent, upserts by project code).

Want the full stack locally (PostgreSQL 17 + Redis 7 in Docker)? `make dev-up` before `make dev`.

---

## Production deploy (VPS)

One VPS, nginx as reverse proxy, everything else in Docker Compose:

```bash
git clone https://github.com/gonmace/skydesk.git && cd skydesk
make setup                            # wizard → .env (domain, PostgreSQL, secrets)
make nginx                            # install nginx config (FIRST TIME ONLY)
sudo certbot --nginx -d yourdomain.com
make deploy                           # build + migrate + up
```

Subsequent deploys are just `make deploy` (git pull + port checks + rebuild). Highlights:

- **Gunicorn + Daphne** behind nginx; static files via Whitenoise with hashed filenames, pre-compressed `.gz` and 1-year immutable cache.
- **Security by default**: strict CSP, HSTS, brute-force lockout (django-axes on Redis), randomized admin URL.
- **Ports bind to 127.0.0.1** — only nginx is exposed. Redis is never exposed.
- **Optional n8n automation** (own subdomain, shared PostgreSQL) and an **n8n-MCP server** to drive your automations from Claude Code or any MCP client — both toggled purely from `.env` via Compose profiles.

---

## Stack

| Layer | Choice |
|---|---|
| Framework | Django 6 + Channels 4 (WebSockets) |
| Database | PostgreSQL 17 (or SQLite for dev) |
| Cache / sessions / realtime | Redis 7 |
| Frontend | Server-rendered templates + Tailwind CSS v4 + DaisyUI v5, vanilla JS (no build step for JS, CSP-safe) |
| Files | Pluggable storage backends: Nextcloud/WebDAV, local disk |
| PDF thumbnails | PyMuPDF |
| Deploy | Docker Compose + nginx + Let's Encrypt, single `make deploy` |

No SPA, no REST framework, no node_modules in production — the JS is a handful of small dependency-free files, and the production image compiles CSS in an isolated Node stage.

---

## Project layout

```
core/            Django settings (env-driven: SQLite↔PostgreSQL, console↔SMTP, dev↔prod security)
accounts/        Auth, roles, capability-based permissions + admin UI
tickets/         Board, tickets, subtickets, chat, history, dashboard, projects, activity types
attachments/     Storage backends (Nextcloud/local/memory), thumbnails, image versioning
notifications/   In-app notifications + email
theme/           Tailwind v4 + DaisyUI v5 sources
```

~180 tests cover visibility rules, workflow transitions, permissions and the attachment layer:

```bash
python manage.py test tickets attachments accounts
```

---

## Configuration

Everything is driven by `.env` (generated by `make setup`). The important switches:

| Variable | Effect |
|---|---|
| `POSTGRES_DB` unset | SQLite (dev) — set it and you get PostgreSQL |
| `EMAIL_HOST` unset | Emails print to console — set it for SMTP |
| `NEXTCLOUD_URL/USER/TOKEN` | Enables the Nextcloud attachment backend (also configurable from the admin) |
| `N8N_DOMAIN` | Enables the n8n container |
| `DEBUG` | Toggles dev conveniences vs. HSTS/CSP hardening |

---

## Contributing

Issues and PRs are welcome. The codebase favors boring, readable Django — server-rendered views, small focused JS files, and tests for every behavior change. Run the test suite before submitting.

---

Built by [@gonmace](https://github.com/gonmace).
