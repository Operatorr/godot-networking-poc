# Omega Realm Wayfinder

Local dashboard copied from J3boardgame. Displays GitHub Wayfinder maps as a
dependency tree, with ticket filters, issue details and comments, GitHub links,
and copyable agent prompts.

## Run

Requires Node.js 22.18+ (or 24+), pnpm, and the GitHub CLI (`gh`) authenticated
with access to this repository. From the repository root:

```bash
pnpm install
pnpm dev:wayfinder
```

Open http://localhost:5175. Port 5175 is separate from J3boardgame's dashboard
on 5174, so both can run together.

The server resolves the GitHub repository using `gh repo view` from this
checkout, so it reads `Operatorr/godot-networking-poc`, not J3boardgame. No
GitHub credentials are sent to the browser.

## Maps and syncing

- Each map is a GitHub issue labelled `wayfinder:map`.
- Its GitHub sub-issues become tickets; GitHub blocking relationships become
  dependency edges.
- Closed tickets are resolved; assigned open tickets are claimed; unassigned
  open tickets are blocked or on the frontier according to their dependencies.
- A map's `## Destination` section supplies the dashboard's description.
- Issue bodies and comments appear in the detail panel.

The first visit fetches maps from GitHub. Later visits use a browser snapshot;
press **Sync** to refresh it. This dashboard uses its own IndexedDB database,
separate from J3boardgame's snapshots. An empty repository shows **No wayfinder
map** until map issues and sub-issues exist.

Use `pnpm dev:wayfinder` for viewing live issues. `pnpm build:wayfinder` checks
TypeScript and builds the UI, but the static output does not include the local
GitHub API middleware.

## Checks

```bash
pnpm test:wayfinder
pnpm build:wayfinder
```
