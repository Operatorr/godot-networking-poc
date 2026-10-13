function escapeHtml(value: string): string {
	return value
		.replaceAll("&", "&amp;")
		.replaceAll("<", "&lt;")
		.replaceAll(">", "&gt;")
		.replaceAll('"', "&quot;");
}

function inline(value: string): string {
	return escapeHtml(value)
		.replace(/`([^`]+)`/g, "<code>$1</code>")
		.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
		.replace(
			/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
			'<a href="$2" target="_blank" rel="noreferrer">$1</a>',
		);
}

export function renderMarkdown(raw: string): string {
	const lines = raw.split("\n");
	let html = "";
	let inList = false;
	const closeList = () => {
		if (inList) {
			html += "</ul>";
			inList = false;
		}
	};
	for (const line of lines) {
		if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
			if (!inList) {
				html += "<ul>";
				inList = true;
			}
			html += `<li>${inline(line.replace(/^\s*([-*]|\d+\.)\s+/, ""))}</li>`;
			continue;
		}
		closeList();
		if (/^###\s/.test(line)) html += `<h3>${inline(line.slice(4))}</h3>`;
		else if (/^##\s/.test(line)) html += `<h2>${inline(line.slice(3))}</h2>`;
		else if (/^#\s/.test(line)) html += `<h1>${inline(line.slice(2))}</h1>`;
		else if (/^(Type|Status|Blocked by|Map|Label):/.test(line)) continue;
		else if (line.trim()) html += `<p>${inline(line)}</p>`;
	}
	closeList();
	return html;
}
