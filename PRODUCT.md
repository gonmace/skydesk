# Product

## Register

product

## Users

Developers who want to deploy Django on a VPS without starting from scratch. They know Python and Django, are comfortable with Docker and the command line, and want infrastructure decisions already made — sensibly, not arbitrarily. They use this skeleton to bootstrap new projects quickly and trust it to be opinionated in the right places.

## Product Purpose

A production-ready Django starter kit: Tailwind v4 + DaisyUI v5, PostgreSQL/Redis via Docker Compose, Gunicorn behind nginx, optional n8n automation and n8n-MCP integration. The skeleton handles the boilerplate (deploy scripts, settings, static files, security headers) so the developer can focus on the app. Success means a developer goes from `git clone` to a working production deploy in under 30 minutes.

## Brand Personality

Modern, elegant, opinionated. The project has clear ideas about how things should work and doesn't apologize for them. It looks as good as it functions. Tone: confident and direct, like good documentation written by someone who actually uses the tool.

## Anti-references

- Generic Bootstrap templates: navy navbar, gradient hero, identical feature cards. Anonymous by design.
- Inflated SaaS landing pages: testimonials, pricing tables, noisy CTAs, gratuitous wow effects. The skeleton is a tool, not a pitch.
- Unmaintained projects: weak README, inconsistent styles, "last updated 3 years ago" energy. This is actively maintained and it shows.

## Design Principles

1. **Earn every pixel.** No decorative chrome. Every UI element earns its place by doing a job.
2. **Opinionated defaults, easy overrides.** Choices are visible and documented; developers can change them without reverse-engineering mysteries.
3. **Dark mode is a first-class citizen.** The dark theme is as considered as the light theme — not an afterthought toggle.
4. **Density over spaciousness.** Developer tools are used in focused sessions. Information density beats airy whitespace.
5. **Predictable before clever.** Interactions and layouts follow patterns developers already know. Clever surprises belong in the app code, not the skeleton UI.

## Accessibility & Inclusion

WCAG AA minimum. Color contrast checked for both light and dark themes. No motion assumed — any animations respect `prefers-reduced-motion`. Language: Spanish as primary (`lang="es"`).
