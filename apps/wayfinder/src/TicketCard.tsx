import { KIND_LABEL, kindIcon } from "./icons";
import { excerpt, type Kind, type Point, type Ticket } from "./model";

type Props = {
	ticket: Ticket;
	kind: Kind;
	selected: boolean;
	onSelect: (id: string) => void;
	point?: Point;
	muted?: boolean;
	onFocus?: () => void;
};

export function TicketCard({
	ticket,
	kind,
	selected,
	onSelect,
	point,
	muted,
	onFocus,
}: Props) {
	const Icon = kindIcon(kind);
	return (
		<button
			type="button"
			data-ticket-id={ticket.id}
			className={`${point ? "node" : "task-card"} kind-${kind}${muted ? " unrelated" : ""}`}
			style={point ? { left: point.x, top: point.y } : undefined}
			aria-pressed={selected}
			aria-label={`#${ticket.id}. ${ticket.title}. ${KIND_LABEL[kind]}. ${ticket.type}.`}
			title={excerpt(ticket.body) || ticket.title}
			onClick={() => onSelect(ticket.id)}
			onFocus={(event) => {
				if (event.currentTarget.matches(":focus-visible")) onFocus?.();
			}}
		>
			<span className="node-index">{point ? ticket.id : `#${ticket.id}`}</span>
			<p className="node-title">{ticket.title}</p>
			<span className="node-meta">
				<Icon />
				<span>{KIND_LABEL[kind]}</span>
				<span aria-hidden="true">·</span>
				<span className="type">{ticket.type}</span>
			</span>
			{!point && ticket.blockedBy.length > 0 ? (
				<span className="task-deps">
					Needs {ticket.blockedBy.map((id) => `#${id}`).join(", ")}
				</span>
			) : null}
		</button>
	);
}
