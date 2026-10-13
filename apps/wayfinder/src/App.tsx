import { useEffect, useRef, useState } from "react";
import { AboutTip } from "./AboutTip";
import { Graph, MapTrigger } from "./Graph";
import { DisableThemeTransitions } from "./Theme";
import { FILTER_LABEL, OpenIcon, SyncIcon, kindIcon } from "./icons";
import { MapTabs } from "./MapTabs";
import { type Filter, type Kind, type MapBundle, counts, mapPrompt } from "./model";
import { MapCommand } from "./Prompt";
import { loadSnapshot, saveSnapshot } from "./store";

const KINDS: Kind[] = ["resolved", "claimed", "frontier", "blocked"];

// The open map lives in the URL (?map=<issue number>) so links open the same tab.
function slugFromUrl(): string | null {
	return new URLSearchParams(window.location.search).get("map");
}

function ago(ms: number): string {
	const minutes = Math.floor(ms / 60_000);
	if (minutes < 1) return "just now";
	if (minutes < 60) return `${minutes}m ago`;
	const hours = Math.floor(minutes / 60);
	if (hours < 24) return `${hours}h ago`;
	return `${Math.floor(hours / 24)}d ago`;
}

export function App() {
	const [maps, setMaps] = useState<MapBundle[] | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [slug, setSlug] = useState<string | null>(slugFromUrl);
	const [filter, setFilter] = useState<Filter>("all");
	const [selectedId, setSelectedId] = useState<string | null>(null);

	const [syncedAt, setSyncedAt] = useState<number | null>(null);
	const [syncing, setSyncing] = useState(false);
	const [now, setNow] = useState(() => Date.now());

	const show = (next: MapBundle[], at: number) => {
		setMaps(next);
		setSyncedAt(at);
		setNow(Date.now());
		setSlug((current) => current ?? next[0]?.slug ?? null);
	};

	// GitHub is only queried here: on the Sync button, or once when the
	// browser has no stored snapshot yet.
	const inflight = useRef(false);
	const sync = async () => {
		if (inflight.current) return;
		inflight.current = true;
		setSyncing(true);
		try {
			const res = await fetch("/api/maps");
			if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
			const data = (await res.json()) as { maps: MapBundle[] };
			const at = Date.now();
			show(data.maps, at);
			setError(null);
			await saveSnapshot({ maps: data.maps, syncedAt: at }).catch(() => {});
		} catch (err) {
			setError(String(err));
		} finally {
			inflight.current = false;
			setSyncing(false);
		}
	};

	useEffect(() => {
		let cancelled = false;
		void loadSnapshot()
			.catch(() => null)
			.then((stored) => {
				if (cancelled) return;
				if (stored) show(stored.maps, stored.syncedAt);
				else void sync();
			});
		const timer = window.setInterval(() => setNow(Date.now()), 30_000);
		return () => {
			cancelled = true;
			window.clearInterval(timer);
		};
	}, []);

	const map = maps?.find((item) => item.slug === slug) ?? maps?.[0] ?? null;
	const tally = map ? counts(map.tickets) : null;

	const selectMap = (next: string) => {
		setSlug(next);
		setSelectedId(null);
		const url = new URL(window.location.href);
		url.searchParams.set("map", next);
		window.history.replaceState(null, "", url);
	};

	useEffect(() => {
		const onKey = (event: KeyboardEvent) => {
			if (event.key === "Escape") setSelectedId(null);
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, []);

	return (
		<div className="app">
			<DisableThemeTransitions />
			<a className="skip" href="#tree">
				Skip to map
			</a>
			<header className="chrome">
				{maps && maps.length > 1 ? (
					<MapTabs maps={maps} current={map?.slug} onSelect={selectMap} />
				) : null}
				<div className="chrome-row">
					<div className="brand">
						<div className="brand-row">
							<h1>{map?.title ?? "Wayfinder"}</h1>
							<AboutTip
								text={
									map?.destination ||
									"Omega Realm decision tickets as a skill tree. Status comes from the GitHub issues labelled wayfinder:map."
								}
							/>
						</div>
						{map ? <MapCommand id={map.slug} text={mapPrompt(map)} /> : null}
					</div>
					<div className="stats" role="group" aria-label="Filter tickets">
						{tally ? (
							<>
								<button
									type="button"
									className="chip"
									aria-pressed={filter === "all"}
									onClick={() => setFilter("all")}
								>
									<span className="n">{tally.total}</span>
									All
								</button>
								<button
									type="button"
									className="chip"
									aria-pressed={filter === "unresolved"}
									onClick={() =>
										setFilter((current) =>
											current === "unresolved" ? "all" : "unresolved",
										)
									}
								>
									<OpenIcon strokeWidth={2} />
									<span className="n">{tally.unresolved}</span>
									Unresolved
								</button>
								{KINDS.map((kind) => {
									const Icon = kindIcon(kind);
									return (
										<button
											key={kind}
											type="button"
											className={`chip kind-${kind}`}
											aria-pressed={filter === kind}
											onClick={() =>
												setFilter((current) =>
													current === kind ? "all" : kind,
												)
											}
										>
											<Icon strokeWidth={2} />
											<span className="n">{tally[kind]}</span>
											{FILTER_LABEL[kind]}
										</button>
									);
								})}
								<MapTrigger onOpen={() => setSelectedId("map")} />
							</>
						) : null}
						<button
							type="button"
							className="chip sync"
							onClick={() => void sync()}
							disabled={syncing}
							aria-busy={syncing}
							title={
								error && maps
									? `Last sync failed: ${error}`
									: "Fetch the latest issues from GitHub"
							}
						>
							<SyncIcon strokeWidth={2} />
							{syncing
								? "Syncing…"
								: error && maps
									? "Sync failed, retry"
									: syncedAt
										? `Synced ${ago(now - syncedAt)}`
										: "Sync"}
						</button>
					</div>
				</div>
			</header>
			<main className="stage" id="tree">
				{error && !maps ? (
					<div className="banner">
						<h2>Can’t reach the ticket API</h2>
						<p>
							Start the dashboard with <code>pnpm dev:wayfinder</code> and make
							sure <code>gh</code> is logged in (<code>gh auth status</code>).
						</p>
					</div>
				) : !maps ? (
					<div className="empty">
						<h2>Reading tickets</h2>
						<p>Loading maps from GitHub issues.</p>
					</div>
				) : !map ? (
					<div className="empty">
						<h2>No wayfinder map</h2>
						<p>
							Expected an issue labelled <code>wayfinder:map</code> with
							sub-issues as tickets.
						</p>
					</div>
				) : (
					<Graph
						key={map.slug}
						map={map}
						filter={filter}
						selectedId={selectedId}
						onSelect={setSelectedId}
						onFilter={setFilter}
					/>
				)}
			</main>
			<div className="status" role="status">
				{tally
					? filter === "all"
						? `${tally.total} tickets. ${tally.frontier} on the frontier, ${tally.claimed} claimed, ${tally.resolved} resolved, ${tally.blocked} blocked.`
						: `Showing ${tally[filter]} ${FILTER_LABEL[filter].toLowerCase()} ${tally[filter] === 1 ? "ticket" : "tickets"}.`
					: ""}
			</div>
		</div>
	);
}
