import type { SVGProps } from "react";
import type { Filter, Kind } from "./model";

type IconProps = SVGProps<SVGSVGElement> & { strokeWidth?: number };

function Icon({ strokeWidth = 1.5, ...props }: IconProps) {
	return (
		<svg
			viewBox="0 0 24 24"
			width="1em"
			height="1em"
			fill="none"
			stroke="currentColor"
			strokeWidth={strokeWidth}
			strokeLinecap="round"
			strokeLinejoin="round"
			aria-hidden="true"
			{...props}
		/>
	);
}

export function CheckIcon(props: IconProps) {
	return (
		<Icon {...props}>
			<path d="M5 12.5 9.5 17 19 7" />
		</Icon>
	);
}

export function ProgressIcon(props: IconProps) {
	return (
		<Icon {...props}>
			<circle cx="12" cy="12" r="8" />
			<path d="M12 8v4l3 2" />
		</Icon>
	);
}

export function FrontierIcon(props: IconProps) {
	return (
		<Icon {...props}>
			<circle cx="12" cy="12" r="8" />
			<circle cx="12" cy="12" r="3" />
		</Icon>
	);
}

export function LockIcon(props: IconProps) {
	return (
		<Icon {...props}>
			<rect x="5" y="11" width="14" height="10" rx="2" />
			<path d="M8 11V8a4 4 0 0 1 8 0v3" />
		</Icon>
	);
}

export function CloseIcon(props: IconProps) {
	return (
		<Icon strokeWidth={2} {...props}>
			<path d="M6 6 18 18M18 6 6 18" />
		</Icon>
	);
}

export function MapIcon(props: IconProps) {
	return (
		<Icon {...props}>
			<path d="M9 4 3 6.5v14L9 18l6 2.5L21 18V4L15 6.5 9 4z" />
			<path d="M9 4v14M15 6.5v14" />
		</Icon>
	);
}

export function OpenIcon(props: IconProps) {
	return (
		<Icon {...props}>
			<circle cx="12" cy="12" r="8" />
		</Icon>
	);
}

export function CopyIcon(props: IconProps) {
	return (
		<Icon {...props}>
			<rect x="9" y="9" width="13" height="13" rx="2" />
			<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
		</Icon>
	);
}

export function HelpIcon(props: IconProps) {
	return (
		<Icon {...props}>
			<circle cx="12" cy="12" r="8" />
			<path d="M9.6 9.6a2.4 2.4 0 1 1 3.3 2.2c-.7.4-1.1.8-1.1 1.6V14" />
			<path d="M12 17.2v.2" />
		</Icon>
	);
}

export function SyncIcon(props: IconProps) {
	return (
		<Icon {...props}>
			<path d="M20 11a8 8 0 0 0-14.3-4.3L4 8.5" />
			<path d="M4 4v4.5h4.5" />
			<path d="M4 13a8 8 0 0 0 14.3 4.3L20 15.5" />
			<path d="M20 20v-4.5h-4.5" />
		</Icon>
	);
}

export function kindIcon(kind: Kind) {
	switch (kind) {
		case "resolved":
			return CheckIcon;
		case "claimed":
			return ProgressIcon;
		case "frontier":
			return FrontierIcon;
		case "blocked":
			return LockIcon;
	}
}

export const KIND_LABEL: Record<Kind, string> = {
	resolved: "Resolved",
	claimed: "Claimed",
	frontier: "Frontier",
	blocked: "Blocked",
};

export const FILTER_LABEL: Record<Filter, string> = {
	all: "All",
	unresolved: "Unresolved",
	...KIND_LABEL,
};

export function SearchIcon(props: IconProps) {
	return (
		<Icon {...props}>
			<circle cx="10.5" cy="10.5" r="6.5" />
			<path d="m16 16 4 4" />
		</Icon>
	);
}

export function StagesIcon(props: IconProps) {
	return (
		<Icon {...props}>
			<rect x="3" y="4" width="7" height="16" rx="2" />
			<rect x="14" y="4" width="7" height="10" rx="2" />
			<path d="M6 8h1M6 12h1M17 8h1" />
		</Icon>
	);
}

export function FitIcon(props: IconProps) {
	return (
		<Icon {...props}>
			<path d="M8 3H3v5M16 3h5v5M21 16v5h-5M3 16v5h5" />
		</Icon>
	);
}
