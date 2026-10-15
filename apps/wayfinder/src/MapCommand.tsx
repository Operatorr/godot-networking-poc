import { useEffect, useRef, useState } from "react";
import { CheckIcon, CopyIcon } from "./icons";
import { mapPrompt } from "./model";

export function MapCommand({ slug }: { slug: string }) {
	const command = mapPrompt({ slug });
	const [feedback, setFeedback] = useState("");
	const timer = useRef<number>(0);

	useEffect(() => () => window.clearTimeout(timer.current), []);

	const copy = async () => {
		let copied = false;
		try {
			await navigator.clipboard.writeText(command);
			copied = true;
		} catch {
			const active = document.activeElement;
			const field = document.createElement("textarea");
			field.value = command;
			field.readOnly = true;
			field.style.position = "fixed";
			field.style.opacity = "0";
			document.body.append(field);
			try {
				field.select();
				copied = document.execCommand("copy");
			} catch {
				copied = false;
			} finally {
				field.remove();
				if (active instanceof HTMLElement)
					active.focus({ preventScroll: true });
			}
		}
		setFeedback(
			copied ? "Copied" : "Couldn’t copy. Select and copy the command.",
		);
		window.clearTimeout(timer.current);
		timer.current = window.setTimeout(() => setFeedback(""), 2000);
	};

	return (
		<div className="map-command">
			<button
				type="button"
				className="chip map-command-copy"
				aria-label={feedback === "Copied" ? "Copied" : `Copy ${command}`}
				title={feedback || "Copy command to run the next frontier ticket"}
				onClick={() => void copy()}
			>
				<code>{command}</code>
				{feedback === "Copied" ? (
					<CheckIcon strokeWidth={2} />
				) : (
					<CopyIcon strokeWidth={2} />
				)}
			</button>
			<div className="status" role="status">
				{feedback}
			</div>
		</div>
	);
}
