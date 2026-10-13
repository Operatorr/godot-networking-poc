import { useEffect } from "react";

export function DisableThemeTransitions() {
	useEffect(() => {
		const media = window.matchMedia("(prefers-color-scheme: dark)");
		const handleChange = () => {
			const style = document.createElement("style");
			style.append(
				document.createTextNode(
					"*,*::before,*::after{transition:none !important}",
				),
			);
			document.head.append(style);
			const _flushReflow = document.body.offsetHeight;
			void _flushReflow;
			requestAnimationFrame(() => {
				requestAnimationFrame(() => style.remove());
			});
		};
		media.addEventListener("change", handleChange);
		return () => media.removeEventListener("change", handleChange);
	}, []);
	return null;
}
