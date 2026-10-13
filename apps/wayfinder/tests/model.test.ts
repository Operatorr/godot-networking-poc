import assert from "node:assert/strict";
import { test } from "node:test";
import { layoutTickets, NODE_H, NODE_W, type Ticket } from "../src/model.ts";

function ticket(id: string, blockedBy: string[] = []): Ticket {
	return {
		id,
		blockedBy,
		file: id,
		path: "",
		title: id,
		type: "task",
		status: "open",
		body: "",
	};
}

function assertNoOverlap(
	tickets: Ticket[],
	direction: "horizontal" | "vertical",
) {
	const layout = layoutTickets(tickets, direction);
	for (let i = 0; i < tickets.length; i++) {
		const a = layout.pos[tickets[i].id];
		assert.ok(a.x >= 0 && a.y >= 0);
		assert.ok(a.x + NODE_W <= layout.width && a.y + NODE_H <= layout.height);
		for (let j = i + 1; j < tickets.length; j++) {
			const b = layout.pos[tickets[j].id];
			assert.ok(
				a.x + NODE_W <= b.x ||
					b.x + NODE_W <= a.x ||
					a.y + NODE_H <= b.y ||
					b.y + NODE_H <= a.y,
				`${tickets[i].id} overlaps ${tickets[j].id} in ${direction}`,
			);
		}
	}
	for (const t of tickets)
		for (const parentId of t.blockedBy) {
			const parent = layout.pos[parentId];
			if (!parent) continue;
			const child = layout.pos[t.id];
			assert.ok(
				direction === "horizontal"
					? parent.x + NODE_W < child.x
					: parent.y + NODE_H < child.y,
			);
		}
}

test("tall and wide maps keep full-size cards separate in both directions", () => {
	const tall = [
		...Array.from({ length: 60 }, (_, i) => ticket(String(i))),
		ticket("end", ["0", "59"]),
	];
	const wide = Array.from({ length: 40 }, (_, i) =>
		ticket(String(i), i ? [String(i - 1)] : []),
	);
	for (const direction of ["horizontal", "vertical"] as const) {
		assertNoOverlap(tall, direction);
		assertNoOverlap(wide, direction);
	}
});

test("filters preserve original stages while packing only visible tasks", () => {
	const tickets = [ticket("a"), ticket("b", ["a"]), ticket("c", ["b"])];
	const full = layoutTickets(tickets);
	for (const direction of ["horizontal", "vertical"] as const) {
		const filtered = layoutTickets([tickets[2]], direction, full.depth);
		assert.equal(filtered.depth.c, 2);
		assert.deepEqual(filtered.pos.c, { x: 0, y: 0 });
		assert.equal(filtered.width, NODE_W);
		assert.equal(filtered.height, NODE_H);
	}
});

test("multiple dependencies place a task after its deepest prerequisite", () => {
	const tickets = [
		ticket("a"),
		ticket("b", ["a"]),
		ticket("c", ["a", "b"]),
		ticket("d", ["outside-map"]),
	];
	assert.deepEqual(layoutTickets(tickets).depth, { a: 0, b: 1, c: 2, d: 0 });
});

test("empty maps have finite bounds", () => {
	for (const direction of ["horizontal", "vertical"] as const) {
		const layout = layoutTickets([], direction);
		assert.ok(Number.isFinite(layout.width) && layout.width > 0);
		assert.ok(Number.isFinite(layout.height) && layout.height > 0);
	}
});
