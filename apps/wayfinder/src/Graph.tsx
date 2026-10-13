import { useEffect, useMemo, useRef, useState } from "react";
import { DependencyMap } from "./DependencyMap";
import { FILTER_LABEL, MapIcon, SearchIcon, StagesIcon } from "./icons";
import {
	indexById,
	kindOf,
	layoutTickets,
	matchesFilter,
	type Direction,
	type Filter,
	type MapBundle,
} from "./model";
import { TicketCard } from "./TicketCard";
import { TicketPanel } from "./TicketPanel";

type Props = {
	map: MapBundle;
	filter: Filter;
	selectedId: string | null;
	onSelect: (id: string | null) => void;
	onFilter: (filter: Filter) => void;
};

export function Graph({ map, filter, selectedId, onSelect, onFilter }: Props) {
	const [mode, setMode] = useState<"stages" | "map">("stages");
	const [query, setQuery] = useState("");
	const [direction, setDirection] = useState<Direction>("horizontal");
	const [activeStage, setActiveStage] = useState<number | null>(null);
	const boardRef = useRef<HTMLDivElement>(null);
	const byId = useMemo(() => indexById(map.tickets), [map.tickets]);
	const fullLayout = useMemo(() => layoutTickets(map.tickets), [map.tickets]);
	const visible = useMemo(
		() =>
			map.tickets.filter(
				(ticket) =>
					matchesFilter(kindOf(ticket, byId), filter) &&
					`${ticket.id} ${ticket.title} ${ticket.type}`
						.toLowerCase()
						.includes(query.trim().toLowerCase().replace(/^#/, "")),
			),
		[map.tickets, byId, filter, query],
	);
	const stages = useMemo(
		() => [...new Set(Object.values(fullLayout.depth))].sort((a, b) => a - b),
		[fullLayout],
	);
	const visibleStages = stages.filter((depth) =>
		visible.some((ticket) => fullLayout.depth[ticket.id] === depth),
	);

	useEffect(() => {
		if (selectedId && selectedId !== "map" && !byId[selectedId]) onSelect(null);
	}, [selectedId, byId, onSelect]);

	useEffect(() => {
		if (mode !== "stages" || !selectedId) return;
		const card = Array.from(
			boardRef.current?.querySelectorAll<HTMLElement>("[data-ticket-id]") ?? [],
		).find((el) => el.dataset.ticketId === selectedId);
		card?.scrollIntoView({ block: "nearest", inline: "nearest" });
	}, [selectedId, mode]);

	const selectTicket = (id: string | null) => {
		const ticket = id ? byId[id] : null;
		if (ticket && !visible.some((item) => item.id === id)) {
			setQuery("");
			if (!matchesFilter(kindOf(ticket, byId), filter)) onFilter("all");
		}
		onSelect(id);
	};

	const jumpToStage = (depth: number) => {
		if (mode === "map") setActiveStage(depth);
		else {
			const lane = boardRef.current?.querySelector<HTMLElement>(
				`[data-stage="${depth}"]`,
			);
			if (!lane) return;
			boardRef.current?.scrollTo({
				left: lane.offsetLeft - 20,
				behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
					? "instant"
					: "smooth",
			});
			lane.focus({ preventScroll: true });
		}
	};

	return (
		<div className={`workspace${selectedId ? " has-detail" : ""}`}>
			<div className="workspace-toolbar">
				<fieldset className="view-switch" aria-label="View mode">
					<button
						type="button"
						aria-pressed={mode === "stages"}
						onClick={() => setMode("stages")}
					>
						<StagesIcon />
						Stages
					</button>
					<button
						type="button"
						aria-pressed={mode === "map"}
						onClick={() => setMode("map")}
					>
						<MapIcon />
						Dependencies
					</button>
				</fieldset>
				<label className="task-search">
					<SearchIcon />
					<input
						type="search"
						aria-label="Search tasks"
						placeholder="Search tasks by title or #issue"
						value={query}
						onChange={(event) => setQuery(event.target.value)}
					/>
				</label>
				<span className="result-count" aria-live="polite">
					{visible.length} of {map.tickets.length} tasks
				</span>
				{mode === "map" ? (
					<label className="direction-control">
						Flow{" "}
						<select
							aria-label="Map direction"
							value={direction}
							onChange={(event) =>
								setDirection(event.target.value as Direction)
							}
						>
							<option value="horizontal">Left to right</option>
							<option value="vertical">Top to bottom</option>
						</select>
					</label>
				) : null}
			</div>
			<div className="workspace-content">
				<nav className="stage-nav" aria-label="Jump to stage">
					<div className="stage-nav-heading">
						<span>Stages</span>
						<span>{stages.length}</span>
					</div>
					<p>Dependencies flow in order.</p>
					{stages.map((depth) => {
						const tickets = map.tickets.filter(
							(ticket) => fullLayout.depth[ticket.id] === depth,
						);
						const resolved = tickets.filter(
							(ticket) => kindOf(ticket, byId) === "resolved",
						).length;
						const available = tickets.filter(
							(ticket) => kindOf(ticket, byId) === "frontier",
						).length;
						return (
							<button
								type="button"
								key={depth}
								className="stage-jump"
								aria-current={
									selectedId && fullLayout.depth[selectedId] === depth
										? "step"
										: undefined
								}
								disabled={!visibleStages.includes(depth)}
								onClick={() => jumpToStage(depth)}
							>
								<span className="stage-number">
									{String(depth + 1).padStart(2, "0")}
								</span>
								<span className="stage-jump-body">
									<strong>
										{depth === 0 ? "Start here" : `Stage ${depth + 1}`}
									</strong>
									<small>
										{tickets.length} tasks ·{" "}
										{available ? `${available} ready` : `${resolved} resolved`}
									</small>
									<span className="stage-progress">
										<span
											style={{ width: `${(resolved / tickets.length) * 100}%` }}
										/>
									</span>
								</span>
							</button>
						);
					})}
					<div className="stage-nav-note">
						{mode === "stages"
							? "Scroll each stage to browse. Select a task to see its details and dependencies."
							: "Select a task to highlight its connections. Jump to a stage to explore at a readable size."}
					</div>
				</nav>
				<div className="work-area">
					{visible.length === 0 ? (
						<div className="empty">
							<h2>
								{query.trim()
									? "No matching tasks"
									: `No ${FILTER_LABEL[filter].toLowerCase()} tasks`}
							</h2>
							<p>Try another search or status filter.</p>
							{query ? (
								<button
									type="button"
									className="chip"
									onClick={() => setQuery("")}
								>
									Clear search
								</button>
							) : null}
						</div>
					) : mode === "stages" ? (
						<>
							<section
								className="board"
								ref={boardRef}
								aria-label="Tasks by dependency stage"
							>
								{visibleStages.map((depth) => {
									const tickets = visible.filter(
										(ticket) => fullLayout.depth[ticket.id] === depth,
									);
									return (
										<section
											key={depth}
											className="stage-lane"
											data-stage={depth}
											tabIndex={-1}
											aria-label={`Stage ${depth + 1}`}
										>
											<header className="lane-head">
												<div>
													<span className="lane-kicker">
														Stage {String(depth + 1).padStart(2, "0")}
													</span>
													<h2>
														{depth === 0
															? "Start here"
															: `After stage ${depth}`}
													</h2>
												</div>
												<span className="lane-count">{tickets.length}</span>
											</header>
											<div className="lane-tasks">
												{tickets.map((ticket) => (
													<TicketCard
														key={ticket.id}
														ticket={ticket}
														kind={kindOf(ticket, byId)}
														selected={selectedId === ticket.id}
														onSelect={selectTicket}
													/>
												))}
											</div>
										</section>
									);
								})}
							</section>
							<div className="board-footer">
								<span>Each stage scrolls independently</span>
								<span>Later stages →</span>
							</div>
						</>
					) : (
						<DependencyMap
							tickets={visible}
							byId={byId}
							depth={fullLayout.depth}
							direction={direction}
							selectedId={selectedId}
							onSelect={selectTicket}
							activeStage={activeStage}
							onStageHandled={() => setActiveStage(null)}
						/>
					)}
				</div>
				<TicketPanel
					map={map}
					selectedId={selectedId}
					onSelect={selectTicket}
				/>
			</div>
		</div>
	);
}

export function MapTrigger({ onOpen }: { onOpen: () => void }) {
	return (
		<button type="button" className="chip" onClick={onOpen}>
			<MapIcon strokeWidth={2} />
			Map brief
		</button>
	);
}
