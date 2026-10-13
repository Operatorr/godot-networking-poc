import { type KeyboardEvent, useRef } from "react";
import { type MapBundle, counts, tabLabel } from "./model";

type Props = {
	maps: MapBundle[];
	current: string | undefined;
	onSelect: (slug: string) => void;
};

const STEP: Record<string, (index: number, length: number) => number> = {
	ArrowRight: (index, length) => (index + 1) % length,
	ArrowLeft: (index, length) => (index - 1 + length) % length,
	Home: () => 0,
	End: (_index, length) => length - 1,
};

export function MapTabs({ maps, current, onSelect }: Props) {
	const list = useRef<HTMLDivElement>(null);

	// Arrow keys, Home and End move between maps, per the WAI-ARIA tabs pattern.
	const onKeyDown = (event: KeyboardEvent) => {
		const step = STEP[event.key];
		if (!step) return;
		event.preventDefault();
		const index = maps.findIndex((map) => map.slug === current);
		const next = step(Math.max(index, 0), maps.length);
		onSelect(maps[next].slug);
		list.current
			?.querySelectorAll<HTMLButtonElement>('[role="tab"]')
			[next]?.focus();
	};

	return (
		<div
			className="tabs"
			role="tablist"
			aria-label="Maps"
			ref={list}
			onKeyDown={onKeyDown}
		>
			{maps.map((map) => {
				const selected = map.slug === current;
				const unresolved = counts(map.tickets).unresolved;
				return (
					<button
						key={map.slug}
						type="button"
						role="tab"
						className="tab"
						aria-selected={selected}
						aria-controls="tree"
						tabIndex={selected ? 0 : -1}
						title={map.title}
						onClick={() => onSelect(map.slug)}
					>
						{tabLabel(map.title)}
						<span className="n" title="Unresolved tickets">
							{unresolved}
						</span>
					</button>
				);
			})}
		</div>
	);
}
