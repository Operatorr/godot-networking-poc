## RegionInfo - Region data structure for server regions
## Fetched from API and used for region selection UI
class_name RegionInfo
extends RefCounted

var id: String              ## e.g., "asia", "europe", "us-west"
var name: String            ## Display name, e.g., "Asia"
var websocket_url: String   ## Game server WebSocket URL
var status: String          ## "online", "offline", "maintenance"
var active_players: int     ## Current player count
var max_players: int        ## Maximum capacity


## Create RegionInfo from API response dictionary
static func from_dict(data: Dictionary) -> RegionInfo:
	var region := RegionInfo.new()
	region.id = data.get("id", "")
	region.name = data.get("name", "")
	region.websocket_url = data.get("websocket_url", "")
	region.status = data.get("status", "offline")
	region.active_players = data.get("active_players", 0)
	region.max_players = data.get("max_players", 1000)
	return region


## Check if region is available for connection
func is_available() -> bool:
	return status == "online" and active_players < max_players


## Get display string for dropdown (name with player count)
func get_display_text() -> String:
	if not is_available():
		return "%s (%s)" % [name, status]
	return "%s (%d/%d)" % [name, active_players, max_players]
