import { useEffect, useId, useRef, useState } from "react";
import { HelpIcon } from "./icons";

export function AboutTip({ text }: { text: string }) {
	const [open, setOpen] = useState(false);
	const wrapRef = useRef<HTMLDivElement>(null);
	const panelId = useId();
	const headingId = useId();

	useEffect(() => {
		if (!open) return;
		const onKey = (event: KeyboardEvent) => {
			if (event.key !== "Escape") return;
			event.preventDefault();
			event.stopImmediatePropagation();
			setOpen(false);
		};
		const onPointer = (event: PointerEvent) => {
			const target = event.target;
			if (target instanceof Node && wrapRef.current?.contains(target)) return;
			setOpen(false);
		};
		window.addEventListener("keydown", onKey, true);
		document.addEventListener("pointerdown", onPointer);
		return () => {
			window.removeEventListener("keydown", onKey, true);
			document.removeEventListener("pointerdown", onPointer);
		};
	}, [open]);

	return (
		<div className="about" ref={wrapRef}>
			<button
				type="button"
				className="icon-btn about-btn"
				aria-label="Show destination"
				aria-expanded={open}
				aria-controls={panelId}
				onClick={() => setOpen((current) => !current)}
			>
				<HelpIcon strokeWidth={2} />
			</button>
			{open ? (
				<div
					id={panelId}
					className="about-tip"
					role="dialog"
					aria-modal="false"
					aria-labelledby={headingId}
				>
					<p id={headingId} className="about-kicker">
						Destination
					</p>
					<p className="about-body">{text}</p>
				</div>
			) : null}
		</div>
	);
}
