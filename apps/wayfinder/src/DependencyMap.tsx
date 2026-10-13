import {
	useCallback,
	useEffect,
	useMemo,
	useRef,
	useState,
	type PointerEvent,
} from "react";
import { FitIcon } from "./icons";
import {
	kindOf,
	layoutTickets,
	NODE_H,
	NODE_W,
	type Direction,
	type Ticket,
} from "./model";
import { TicketCard } from "./TicketCard";

type Props = {
	tickets: Ticket[];
	byId: Record<string, Ticket>;
	depth: Record<string, number>;
	direction: Direction;
	selectedId: string | null;
	onSelect: (id: string | null) => void;
	activeStage: number | null;
	onStageHandled: () => void;
};
const MIN_ZOOM = 0.005;
const MAX_ZOOM = 1.8;

export function DependencyMap({
	tickets,
	byId,
	depth,
	direction,
	selectedId,
	onSelect,
	activeStage,
	onStageHandled,
}: Props) {
	const viewportRef = useRef<HTMLDivElement>(null);
	const [size, setSize] = useState({ width: 1, height: 1 });
	const [view, setView] = useState({ x: 40, y: 48, k: 1 });
	const [panning, setPanning] = useState(false);
	const drag = useRef<{
		x: number;
		y: number;
		tx: number;
		ty: number;
		moved: boolean;
	} | null>(null);
	const layout = useMemo(
		() => layoutTickets(tickets, direction, depth),
		[tickets, direction, depth],
	);
	const stageLabels = useMemo(
		() =>
			[...new Set(tickets.map((ticket) => depth[ticket.id]))].map((level) => {
				const members = tickets.filter((ticket) => depth[ticket.id] === level);
				return {
					level,
					count: members.length,
					x: Math.min(...members.map((ticket) => layout.pos[ticket.id].x)),
					y: Math.min(...members.map((ticket) => layout.pos[ticket.id].y)) - 28,
				};
			}),
		[tickets, depth, layout],
	);
	const related = useMemo(() => {
		const ids = new Set<string>();
		if (!selectedId || !byId[selectedId]) return ids;
		ids.add(selectedId);
		// Trace ancestors and descendants separately; siblings stay quiet.
		const visitParents = (id: string) => {
			for (const parent of byId[id]?.blockedBy ?? []) {
				if (ids.has(parent)) continue;
				ids.add(parent);
				visitParents(parent);
			}
		};
		visitParents(selectedId);
		const descendants = new Set([selectedId]);
		const visitChildren = (id: string) => {
			for (const ticket of Object.values(byId)) {
				if (!ticket.blockedBy.includes(id) || descendants.has(ticket.id))
					continue;
				descendants.add(ticket.id);
				ids.add(ticket.id);
				visitChildren(ticket.id);
			}
		};
		visitChildren(selectedId);
		return ids;
	}, [selectedId, byId]);

	useEffect(() => {
		const el = viewportRef.current;
		if (!el) return;
		const observer = new ResizeObserver(() =>
			setSize({ width: el.clientWidth, height: el.clientHeight }),
		);
		observer.observe(el);
		return () => observer.disconnect();
	}, []);

	useEffect(() => {
		const el = viewportRef.current;
		if (!el) return;
		// Large maps open at reading size. Overview is always an explicit action.
		const fitK = Math.min(
			(el.clientWidth - 80) / layout.width,
			(el.clientHeight - 96) / layout.height,
			1,
		);
		const k = Math.max(0.85, fitK);
		setView({
			k,
			x: Math.max(40, (el.clientWidth - layout.width * k) / 2),
			y: Math.max(48, (el.clientHeight - layout.height * k) / 2),
		});
	}, [layout]);

	const centerOn = useCallback(
		(x: number, y: number, k = 1) =>
			setView({ k, x: size.width / 2 - x * k, y: size.height / 2 - y * k }),
		[size.width, size.height],
	);
	useEffect(() => {
		if (!selectedId) return;
		const point = layout.pos[selectedId];
		if (point) centerOn(point.x + NODE_W / 2, point.y + NODE_H / 2);
	}, [selectedId, layout, centerOn]);

	useEffect(() => {
		if (activeStage === null) return;
		const first = tickets.find((ticket) => depth[ticket.id] === activeStage);
		const point = first ? layout.pos[first.id] : null;
		if (point) centerOn(point.x + NODE_W / 2, point.y + NODE_H / 2);
		onStageHandled();
	}, [activeStage, tickets, depth, layout, centerOn, onStageHandled]);

	const fit = () => {
		const k = Math.max(
			MIN_ZOOM,
			Math.min(
				(size.width - 80) / layout.width,
				(size.height - 96) / layout.height,
				1,
			),
		);
		setView({
			k,
			x: (size.width - layout.width * k) / 2,
			y: (size.height - layout.height * k) / 2,
		});
	};
	const zoom = (factor: number) =>
		setView((current) => {
			const k = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, current.k * factor));
			const ratio = k / current.k;
			return {
				k,
				x: size.width / 2 - (size.width / 2 - current.x) * ratio,
				y: size.height / 2 - (size.height / 2 - current.y) * ratio,
			};
		});

	useEffect(() => {
		const el = viewportRef.current;
		if (!el) return;
		const onWheel = (event: WheelEvent) => {
			if ((event.target as Element).closest(".map-controls, .minimap")) return;
			event.preventDefault();
			if (!event.ctrlKey && !event.metaKey) {
				setView((current) => ({
					...current,
					x: current.x - event.deltaX,
					y: current.y - event.deltaY,
				}));
				return;
			}
			const rect = el.getBoundingClientRect();
			const mx = event.clientX - rect.left;
			const my = event.clientY - rect.top;
			setView((current) => {
				const k = Math.max(
					MIN_ZOOM,
					Math.min(MAX_ZOOM, current.k * Math.exp(-event.deltaY * 0.01)),
				);
				const ratio = k / current.k;
				return {
					k,
					x: mx - (mx - current.x) * ratio,
					y: my - (my - current.y) * ratio,
				};
			});
		};
		el.addEventListener("wheel", onWheel, { passive: false });
		return () => el.removeEventListener("wheel", onWheel);
	}, []);

	const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
		if (
			event.button !== 0 ||
			(event.target as Element).closest("button, select")
		)
			return;
		drag.current = {
			x: event.clientX,
			y: event.clientY,
			tx: view.x,
			ty: view.y,
			moved: false,
		};
		setPanning(true);
		event.currentTarget.setPointerCapture(event.pointerId);
	};
	const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
		const start = drag.current;
		if (!start) return;
		const dx = event.clientX - start.x;
		const dy = event.clientY - start.y;
		if (Math.hypot(dx, dy) > 4) start.moved = true;
		setView((current) => ({ ...current, x: start.tx + dx, y: start.ty + dy }));
	};
	const endPan = (event: PointerEvent<HTMLDivElement>) => {
		if (!drag.current) return;
		if (!drag.current.moved && event.type !== "pointercancel") onSelect(null);
		drag.current = null;
		setPanning(false);
	};
	const miniScale = Math.min(164 / layout.width, 96 / layout.height);
	const miniX = (184 - layout.width * miniScale) / 2;
	const miniY = (116 - layout.height * miniScale) / 2;
	const overviewX = Math.max(0, -view.x / view.k);
	const overviewY = Math.max(0, -view.y / view.k);
	const overviewRight = Math.min(layout.width, (size.width - view.x) / view.k);
	const overviewBottom = Math.min(
		layout.height,
		(size.height - view.y) / view.k,
	);

	return (
		<div
			ref={viewportRef}
			className={`viewport${panning ? " panning" : ""}`}
			onPointerDown={onPointerDown}
			onPointerMove={onPointerMove}
			onPointerUp={endPan}
			onPointerCancel={endPan}
		>
			<div
				className="world"
				style={{
					transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})`,
				}}
			>
				<svg
					className="edges"
					width={layout.width}
					height={layout.height}
					aria-hidden="true"
				>
					{tickets.flatMap((ticket) =>
						ticket.blockedBy.flatMap((parentId) => {
							const from = layout.pos[parentId];
							const to = layout.pos[ticket.id];
							if (!from || !to) return [];
							const horizontal = direction === "horizontal";
							const x1 = from.x + (horizontal ? NODE_W : NODE_W / 2);
							const y1 = from.y + (horizontal ? NODE_H / 2 : NODE_H);
							const x2 = to.x + (horizontal ? 0 : NODE_W / 2);
							const y2 = to.y + (horizontal ? NODE_H / 2 : 0);
							const mx = (x1 + x2) / 2;
							const my = (y1 + y2) / 2;
							const path = horizontal
								? `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`
								: `M${x1},${y1} C${x1},${my} ${x2},${my} ${x2},${y2}`;
							const traced = related.has(parentId) && related.has(ticket.id);
							return (
								<path
									key={`${parentId}-${ticket.id}`}
									className={`edge${byId[parentId]?.status === "resolved" ? " done" : ""}${related.size ? (traced ? " traced" : " unrelated") : ""}`}
									d={path}
								/>
							);
						}),
					)}
				</svg>
				{stageLabels.map((stage) => (
					<span
						key={stage.level}
						className="map-stage-label"
						style={{ left: stage.x, top: stage.y }}
					>
						Stage {String(stage.level + 1).padStart(2, "0")} · {stage.count}{" "}
						tasks
					</span>
				))}

				{tickets.map((ticket) => (
					<TicketCard
						key={ticket.id}
						ticket={ticket}
						point={layout.pos[ticket.id]}
						kind={kindOf(ticket, byId)}
						selected={selectedId === ticket.id}
						onSelect={onSelect}
						muted={related.size > 0 && !related.has(ticket.id)}
						onFocus={() => {
							const point = layout.pos[ticket.id];
							if (point && !panning)
								centerOn(
									point.x + NODE_W / 2,
									point.y + NODE_H / 2,
									Math.max(0.85, view.k),
								);
						}}
					/>
				))}
			</div>
			<fieldset className="map-controls" aria-label="Map navigation">
				<button
					type="button"
					aria-label="Zoom out"
					disabled={view.k <= MIN_ZOOM}
					onClick={() => zoom(1 / 1.2)}
				>
					−
				</button>
				<button
					type="button"
					className="zoom-readout"
					title="Reset to readable size"
					aria-label="Readable size"
					onClick={() =>
						centerOn(
							(size.width / 2 - view.x) / view.k,
							(size.height / 2 - view.y) / view.k,
						)
					}
				>
					{Math.round(view.k * 100)}%
				</button>
				<button
					type="button"
					aria-label="Zoom in"
					disabled={view.k >= MAX_ZOOM}
					onClick={() => zoom(1.2)}
				>
					+
				</button>
				<span className="control-divider" />
				<button type="button" onClick={fit}>
					<FitIcon />
					Fit map
				</button>
			</fieldset>
			<div className="minimap">
				<span>Overview</span>
				<button
					type="button"
					aria-label="Navigate map overview"
					title="Click to jump; Enter to fit map"
					onClick={(event) => {
						if (event.detail === 0) {
							fit();
							return;
						}
						const rect = event.currentTarget.getBoundingClientRect();
						centerOn(
							(((event.clientX - rect.left) * 184) / rect.width - miniX) /
								miniScale,
							(((event.clientY - rect.top) * 116) / rect.height - miniY) /
								miniScale,
							view.k,
						);
					}}
				>
					<svg
						width="184"
						height="116"
						viewBox="0 0 184 116"
						aria-hidden="true"
					>
						{tickets.map((ticket) => {
							const p = layout.pos[ticket.id];
							return (
								<rect
									key={ticket.id}
									className={`mini-node kind-${kindOf(ticket, byId)}`}
									x={miniX + p.x * miniScale}
									y={miniY + p.y * miniScale}
									width={NODE_W * miniScale}
									height={NODE_H * miniScale}
									rx={Math.min(2, 6 * miniScale)}
								/>
							);
						})}
						<rect
							className="mini-window"
							x={miniX + overviewX * miniScale}
							y={miniY + overviewY * miniScale}
							width={Math.max(0, overviewRight - overviewX) * miniScale}
							height={Math.max(0, overviewBottom - overviewY) * miniScale}
						/>
					</svg>
				</button>
			</div>
			<p className="map-hint">
				Drag or scroll to pan · Ctrl / ⌘ + scroll to zoom
			</p>
		</div>
	);
}
