import { useEffect, useRef } from "react";
import { CloseIcon, KIND_LABEL } from "./icons";
import { agentPrompt, indexById, kindOf, type MapBundle, mapPrompt } from "./model";
import { renderMarkdown } from "./markdown";
import { PromptField } from "./Prompt";

type Props = {
	map: MapBundle;
	selectedId: string | null;
	onSelect: (id: string | null) => void;
};

export function TicketPanel({ map, selectedId, onSelect }: Props) {
	const closeRef = useRef<HTMLButtonElement>(null);
	const bodyRef = useRef<HTMLDivElement>(null);
	const lastFocus = useRef<HTMLElement | null>(null);
	const prevSelected = useRef<string | null>(null);
	const byId = indexById(map.tickets);
	const selected = selectedId ? byId[selectedId] : null;
	const selectedKind = selected ? kindOf(selected, byId) : null;
	const unlocked = selected
		? map.tickets.filter((ticket) => ticket.blockedBy.includes(selected.id))
		: [];
	useEffect(() => {
		bodyRef.current?.scrollTo({ top: 0 });
		if (selectedId && !prevSelected.current) {
			lastFocus.current = document.activeElement as HTMLElement;
			closeRef.current?.focus();
		} else if (!selectedId && prevSelected.current) {
			lastFocus.current?.focus();
		}
		prevSelected.current = selectedId;
	}, [selectedId]);
	const closePanel = () => onSelect(null);
	return (
		<aside
			className="panel"
			hidden={!selectedId}
			role="dialog"
			aria-modal="false"
			aria-labelledby="ticket-title"
		>
			{selectedId ? (
				<div className="panel-card">
					<div className="panel-head">
						<div>
							<h2 id="ticket-title">
								{selected ? `${selected.id} — ${selected.title}` : map.title}
							</h2>
							<div className="badges">
								{selected && selectedKind ? (
									<>
										<span className={`badge kind-${selectedKind}`}>
											{KIND_LABEL[selectedKind]}
										</span>
										<span className="badge">{selected.type}</span>
										{selected.blockedBy.length ? (
											<span className="badge">
												Needs{" "}
												{selected.blockedBy.map((id) => `#${id}`).join(", ")}
											</span>
										) : null}
									</>
								) : (
									<span className="badge">Map #{map.slug}</span>
								)}
							</div>
						</div>
						<button
							ref={closeRef}
							type="button"
							className="icon-btn"
							aria-label="Close ticket"
							onClick={closePanel}
						>
							<CloseIcon />
						</button>
					</div>
					<div className="panel-body" ref={bodyRef}>
						<PromptField
							text={selected ? agentPrompt(selected) : mapPrompt(map)}
						/>
						<p className="path">
							<a
								href={selected ? selected.path : map.path}
								target="_blank"
								rel="noreferrer"
							>
								{selected ? selected.path : map.path}
							</a>
						</p>
						{selected?.blockedBy.length ? (
							<p>
								Depends on{" "}
								{selected.blockedBy.map((id, i) => (
									<span key={id}>
										{i ? ", " : ""}
										<button
											type="button"
											className="map-btn"
											onClick={() => onSelect(id)}
											disabled={!byId[id]}
										>
											{id}
											{byId[id] ? ` ${byId[id].title}` : ""}
										</button>
									</span>
								))}
							</p>
						) : null}
						{unlocked.length ? (
							<div className="relationships">
								<h3>
									Unlocks {unlocked.length}{" "}
									{unlocked.length === 1 ? "task" : "tasks"}
								</h3>
								{unlocked.map((ticket) => (
									<button
										type="button"
										className="map-btn"
										key={ticket.id}
										onClick={() => onSelect(ticket.id)}
									>
										#{ticket.id} {ticket.title}
									</button>
								))}
							</div>
						) : null}

						<div
							dangerouslySetInnerHTML={{
								__html: renderMarkdown(selected ? selected.body : map.body),
							}}
						/>
					</div>
				</div>
			) : null}
		</aside>
	);
}
