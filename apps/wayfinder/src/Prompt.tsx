import { useEffect, useId, useRef, useState } from "react";
import { CheckIcon, CopyIcon } from "./icons";

export function PromptField({ text }: { text: string }) {
	const fieldId = useId();
	const [copied, setCopied] = useState(false);
	const timer = useRef<number>(0);

	useEffect(() => {
		setCopied(false);
		return () => window.clearTimeout(timer.current);
	}, [text]);

	const copy = async () => {
		try {
			await navigator.clipboard.writeText(text);
		} catch {
			const field = document.getElementById(fieldId);
			if (!(field instanceof HTMLTextAreaElement)) return;
			field.focus();
			field.select();
			document.execCommand("copy");
		}
		setCopied(true);
		window.clearTimeout(timer.current);
		timer.current = window.setTimeout(() => setCopied(false), 1500);
	};

	return (
		<div className="prompt">
			<div className="prompt-head">
				<label htmlFor={fieldId}>AI prompt</label>
				<button
					type="button"
					className="icon-btn"
					aria-label={copied ? "Copied" : "Copy prompt"}
					onClick={() => void copy()}
				>
					<span className="icon-swap">
						<span className={`icon-swap-layer${copied ? "" : " is-off"}`}>
							<CheckIcon strokeWidth={2} />
						</span>
						<span className={`icon-swap-layer${copied ? " is-off" : ""}`}>
							<CopyIcon strokeWidth={2} />
						</span>
					</span>
				</button>
			</div>
			<textarea
				id={fieldId}
				className="prompt-field"
				value={text}
				readOnly
				spellCheck={false}
				rows={2}
			/>
			<div className="status" role="status">
				{copied ? "Copied" : ""}
			</div>
		</div>
	);
}
