## PermanentProgression - Account-wide Glory meta-progression view.
##
## Read-side view of the player's account-level meta currency, Glory:
##   Glory = floor(lifetimeXP / 100)
## Persisted and spent server-side via the Go API — the client requests, the server
## decides. This node displays the current/earned Glory balance and unlock state; it
## NEVER grants or deducts Glory locally. Spend requests go to the API and the
## resulting authoritative balance is reflected back here.
##
## Data-driven pattern (GDD: JSON definition -> Factory -> base scene -> configured
## entity): the meta-unlock catalogue (costs, effects) comes from a JSON definition;
## the balance and owned-unlock set come from the API.
##
## Governing docs: docs/adr/0006-*, docs/gdd/progression/, docs/systems/PROGRESSION.md.
##
## # TODO:
##   - Fetch lifetimeXP / Glory / owned unlocks from the Go API; cache for display.
##   - request_spend(): POST to the API, await authoritative balance, refresh view.
##   - Emit a signal when the balance or unlock set changes (UI refresh).
class_name PermanentProgression
extends Node

## Glory granularity: 1 Glory per 100 lifetime XP.
const GLORY_PER_XP: int = 100


## Glory earned for a lifetime XP total: floor(lifetimeXP / 100). Display only.
func glory_for_lifetime_xp(lifetime_xp: int) -> int:
	# TODO: return lifetime_xp / GLORY_PER_XP (integer floor).
	return 0


## Ask the Go API to spend Glory on an unlock (server is authoritative).
func request_spend(unlock_id: String) -> void:
	# TODO: POST spend to the API; on success refresh the cached balance/unlocks.
	pass


## Pull the authoritative balance + owned unlocks from the API into the view.
func sync_from_api() -> void:
	# TODO: fetch account meta-progression; emit changed signal.
	pass
