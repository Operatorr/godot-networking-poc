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

// This repo prefixes map titles with 'Map:'; show the actual map name.
export function tabLabel(title: string): string {
	const closed = title.endsWith(" (closed)");
	const name = title
		.replace(/ \(closed\)$/, "")
		.replace(/^Map:\s*/i, "")
		.split(":")[0]
		.trim();
	return closed ? `${name} (closed)` : name;
}

export type Kind = "resolved" | "claimed" | "frontier" | "blocked";

export type Filter = "all" | "unresolved" | Kind;

export function matchesFilter(kind: Kind, filter: Filter): boolean {
	if (filter === "all") return true;
	if (filter === "unresolved") return kind !== "resolved";
	return kind === filter;
}

export function kindOf(ticket: Ticket, byId: Record<string, Ticket>): Kind {
	if (ticket.status === "resolved") return "resolved";
	if (ticket.status === "claimed") return "claimed";
	const blocked = ticket.blockedBy.some(
		(id) => byId[id] && byId[id].status !== "resolved",
	);
	return blocked ? "blocked" : "frontier";
}

export function indexById(tickets: Ticket[]): Record<string, Ticket> {
	return Object.fromEntries(tickets.map((ticket) => [ticket.id, ticket]));
}

export function counts(tickets: Ticket[]) {
	const byId = indexById(tickets);
	const tally = {
		resolved: 0,
		claimed: 0,
		frontier: 0,
		blocked: 0,
		total: tickets.length,
		unresolved: 0,
	};
	for (const ticket of tickets) tally[kindOf(ticket, byId)] += 1;
	tally.unresolved = tally.claimed + tally.frontier + tally.blocked;
	return tally;
}

export const NODE_W = 228;
export const NODE_H = 92;
export const GAP_X = 88;
export const GAP_Y = 24;

export type Point = { x: number; y: number };

export type Layout = {
	pos: Record<string, Point>;
	depth: Record<string, number>;
	width: number;
	height: number;
};

export type Direction = "horizontal" | "vertical";

// Supply the complete map's depths when filtering, so stages keep their meaning.
export function layoutTickets(
	tickets: Ticket[],
	direction: Direction = "horizontal",
	fullDepth?: Record<string, number>,
): Layout {
	const byId = indexById(tickets);
	const depth: Record<string, number> = fullDepth ? { ...fullDepth } : {};
	const walk = (ticket: Ticket): number => {
		if (depth[ticket.id] != null) return depth[ticket.id];
		const parents = ticket.blockedBy
			.map((id) => byId[id])
			.filter((parent): parent is Ticket => Boolean(parent));
		depth[ticket.id] = parents.length ? 1 + Math.max(...parents.map(walk)) : 0;
		return depth[ticket.id];
	};
	tickets.forEach(walk);

	const layers: Ticket[][] = [];
	for (const ticket of tickets) {
		const level = depth[ticket.id];
		layers[level] ??= [];
		layers[level].push(ticket);
	}
	const stages = layers.filter(Boolean);
	stages.forEach((layer) => {
		layer.sort((a, b) => a.id.localeCompare(b.id));
	});

	const order: Record<string, number> = {};
	stages.forEach((layer, level) => {
		if (level === 0) {
			layer.forEach((ticket, i) => {
				order[ticket.id] = i;
			});
			return;
		}
		const scored = layer.map((ticket) => {
			const parents = ticket.blockedBy
				.map((id) => order[id])
				.filter((n): n is number => n != null);
			const mean = parents.length
				? parents.reduce((sum, n) => sum + n, 0) / parents.length
				: 0;
			return { ticket, mean };
		});
		scored.sort(
			(a, b) => a.mean - b.mean || a.ticket.id.localeCompare(b.ticket.id),
		);
		scored.forEach((item, i) => {
			order[item.ticket.id] = i;
			layer[i] = item.ticket;
		});
	});

	const widest = Math.max(1, ...stages.map((layer) => layer.length));
	const crossSize = direction === "horizontal" ? NODE_H : NODE_W;
	const crossGap = GAP_Y;
	const mainSize = direction === "horizontal" ? NODE_W : NODE_H;
	const mainGap = direction === "horizontal" ? GAP_X : 72;
	const span = widest * crossSize + (widest - 1) * crossGap;
	const pos: Record<string, Point> = {};
	stages.forEach((layer, level) => {
		const layerSpan = layer.length * crossSize + (layer.length - 1) * crossGap;
		layer.forEach((ticket, i) => {
			const main = level * (mainSize + mainGap);
			const cross = (span - layerSpan) / 2 + i * (crossSize + crossGap);
			pos[ticket.id] =
				direction === "horizontal"
					? { x: main, y: cross }
					: { x: cross, y: main };
		});
	});
	const nStages = Math.max(1, stages.length);
	const length = nStages * mainSize + (nStages - 1) * mainGap;
	const width = direction === "horizontal" ? length : span;
	const height = direction === "horizontal" ? span : length;
	return { pos, depth, width, height };
}

export function agentPrompt(ticket: Ticket): string {
	return `/wayfinder work on issue #${ticket.id} — ${ticket.title}`;
}

export function excerpt(body: string): string {
	const after = body.split(/^## Question\s*$/m)[1] ?? body;
	const lines = after
		.split("\n")
		.map((line) => line.trim())
		.filter(
			(line) =>
				line &&
				!/^#/.test(line) &&
				!/^(Type|Status|Blocked by|Map|Label):/.test(line),
		);
	return lines[0] ?? "";
}
