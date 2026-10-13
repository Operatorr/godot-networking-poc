import { execFile } from "node:child_process";
import { promisify } from "node:util";
import type { Plugin } from "vite";

const run = promisify(execFile);

export type Ticket = {
  id: string;
  file: string;
  path: string;
  title: string;
  type: string;
  status: string;
  blockedBy: string[];
  body: string;
};

export type MapBundle = {
  slug: string;
  title: string;
  destination: string;
  path: string;
  body: string;
  tickets: Ticket[];
};

type Comment = { body: string; author: { login: string } | null };

type IssueNode = {
  number: number;
  title: string;
  state: "OPEN" | "CLOSED";
  url: string;
  body: string;
  labels: { nodes: { name: string }[] };
  assignees: { nodes: { login: string }[] };
  blockedBy: { nodes: { number: number }[] };
  comments: { nodes: Comment[] };
};

type MapNode = Omit<IssueNode, "labels" | "assignees" | "blockedBy"> & {
  subIssues: { nodes: IssueNode[] };
};

const ISSUE_FIELDS = `
  number title state url body
  comments(first: 30) { nodes { body author { login } } }
`;

const QUERY = `
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    issues(first: 20, labels: ["wayfinder:map"], states: [OPEN, CLOSED],
           orderBy: { field: CREATED_AT, direction: DESC }) {
      nodes {
        ${ISSUE_FIELDS}
        subIssues(first: 100) {
          nodes {
            ${ISSUE_FIELDS}
            labels(first: 10) { nodes { name } }
            assignees(first: 10) { nodes { login } }
            blockedBy(first: 20) { nodes { number } }
          }
        }
      }
    }
  }
}`;

function section(raw: string, heading: string): string {
  const re = new RegExp(
    `^## ${heading}\\s*\\n([\\s\\S]*?)(?=^## |\\s*$)`,
    "m",
  );
  const match = raw.match(re);
  return match ? match[1].trim() : "";
}

function firstParagraph(text: string): string {
  return (
    text
      .split(/\n\n/)
      .map((block) => block.replace(/\s+/g, " ").trim())
      .find(Boolean) ?? ""
  );
}

function withComments(issue: { body: string; comments: { nodes: Comment[] } }) {
  const comments = issue.comments.nodes.map(
    (c) => `### ${c.author?.login ?? "ghost"}\n\n${c.body.trim()}`,
  );
  return comments.length
    ? `${issue.body.trim()}\n\n## Comments\n\n${comments.join("\n\n")}`
    : issue.body;
}

function toTicket(issue: IssueNode): Ticket {
  const typeLabel = issue.labels.nodes
    .map((label) => label.name)
    .find((name) => name.startsWith("wayfinder:"));
  const status =
    issue.state === "CLOSED"
      ? "resolved"
      : issue.assignees.nodes.length
        ? "claimed"
        : "open";
  return {
    id: String(issue.number),
    file: `#${issue.number}`,
    path: issue.url,
    title: issue.title,
    type: typeLabel ? typeLabel.slice("wayfinder:".length) : "task",
    status,
    blockedBy: issue.blockedBy.nodes.map((b) => String(b.number)),
    body: withComments(issue),
  };
}

// The repo never changes while the server runs, so resolve it once rather
// than spending a GitHub API call on every sync.
let slug: Promise<[string, string]> | null = null;

function repoSlug(repoRoot: string): Promise<[string, string]> {
  slug ??= resolveRepoSlug(repoRoot).catch((error) => {
    slug = null;
    throw error;
  });
  return slug;
}

async function resolveRepoSlug(repoRoot: string): Promise<[string, string]> {
  const { stdout } = await run(
    "gh",
    ["repo", "view", "--json", "owner,name", "--jq", '.owner.login + "/" + .name'],
    { cwd: repoRoot },
  );
  const [owner, name] = stdout.trim().split("/");
  return [owner, name];
}

async function loadMaps(repoRoot: string): Promise<MapBundle[]> {
  const [owner, name] = await repoSlug(repoRoot);
  const { stdout } = await run(
    "gh",
    ["api", "graphql", "-f", `query=${QUERY}`, "-F", `owner=${owner}`, "-F", `name=${name}`],
    { cwd: repoRoot, maxBuffer: 32 * 1024 * 1024 },
  );
  const nodes: MapNode[] = JSON.parse(stdout).data.repository.issues.nodes;
  // Open maps first, newest first within each group.
  nodes.sort(
    (a, b) =>
      Number(a.state === "CLOSED") - Number(b.state === "CLOSED") ||
      b.number - a.number,
  );
  return nodes.map((map) => ({
    slug: String(map.number),
    title: map.state === "CLOSED" ? `${map.title} (closed)` : map.title,
    destination: firstParagraph(section(map.body, "Destination")),
    path: map.url,
    body: withComments(map),
    tickets: map.subIssues.nodes.map(toTicket),
  }));
}

// The client keeps its own snapshot and only calls this when the user presses
// Sync, so every request goes to GitHub; concurrent requests share one call.
export function wayfinderPlugin(repoRoot: string): Plugin {
  let inflight: Promise<string> | null = null;

  const fetchJson = () => {
    inflight ??= loadMaps(repoRoot)
      .then((maps) => JSON.stringify({ maps }))
      .finally(() => {
        inflight = null;
      });
    return inflight;
  };

  return {
    name: "wayfinder-tickets",
    configureServer(server) {
      server.middlewares.use("/api/maps", async (_req, res) => {
        try {
          const json = await fetchJson();
          res.setHeader("Content-Type", "application/json; charset=utf-8");
          res.setHeader("Cache-Control", "no-store");
          res.end(json);
        } catch (error) {
          res.statusCode = 500;
          res.setHeader("Content-Type", "application/json; charset=utf-8");
          res.end(JSON.stringify({ error: String(error) }));
        }
      });
    },
  };
}
