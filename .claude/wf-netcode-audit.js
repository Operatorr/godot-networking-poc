export const meta = {
  name: 'netcode-perf-audit',
  description: 'Extract the real latency budget and bottlenecks from the netcode stack to ground a performance investigation',
  phases: [
    { title: 'Map netcode', detail: 'parallel readers extract hard numbers + bottlenecks per subsystem' },
  ],
}

const FINDING_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['area', 'summary', 'metrics', 'bottlenecks'],
  properties: {
    area: { type: 'string' },
    summary: { type: 'string', description: 'Plain-language 2-4 sentence summary of how this subsystem works today' },
    metrics: {
      type: 'array',
      description: 'Hard numbers found: tick rates, send rates, buffer sizes, packet sizes, timeouts, etc.',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['name', 'value', 'evidence'],
        properties: {
          name: { type: 'string' },
          value: { type: 'string', description: 'The literal number/value, with units' },
          evidence: { type: 'string', description: 'file:line where this is defined or computed' },
        },
      },
    },
    bottlenecks: {
      type: 'array',
      description: 'Latency/throughput problems that would make the game feel sluggish, especially under added ping',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['title', 'severity', 'explanation', 'evidence', 'fix_hint', 'added_latency_ms'],
        properties: {
          title: { type: 'string' },
          severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
          explanation: { type: 'string', description: 'Why this causes perceived lag/sluggishness' },
          evidence: { type: 'string', description: 'file:line' },
          fix_hint: { type: 'string' },
          added_latency_ms: { type: 'string', description: 'Estimated ms of perceived delay this adds on localhost (0 network latency), or N/A' },
        },
      },
    },
  },
}

const AREAS = [
  {
    key: 'server-loop',
    prompt: `Read these files FULLY and extract how the server's main loop and snapshot cadence work:
- client/scripts/server/server_main.gd
- client/scripts/server/server_config.gd
- client/scripts/server/snapshot_scheduler.gd
- client/scripts/server/server_metrics.gd
Determine: the server simulation/tick rate (Hz), how the tick loop is driven (_physics_process vs _process vs Timer vs custom accumulator), the snapshot/broadcast send rate (Hz) and whether it differs from the tick rate, any per-tick O(N) or O(N^2) work, any awaits/sleeps/yields in the hot path, and the Engine.physics_ticks_per_second / max_fps settings if referenced.
Report EXACT numbers with file:line. Flag anything that adds perceived delay even at 0ms network latency (e.g. low send rate => choppy remote entities, snapshot built once per N frames).`,
  },
  {
    key: 'broadcast-delta-aoi',
    prompt: `Read these files FULLY and extract how state snapshots are built and sent:
- client/scripts/server/server_broadcast_service.gd
- client/scripts/server/delta_state_cache.gd
- client/scripts/server/player_state.gd
- client/scripts/server/monster_state.gd
- client/scripts/server/projectile_state.gd
- client/scripts/shared/networking/packets/state_update_packet.gd
Determine: is a snapshot built once and broadcast to all (global) or built per-player? Is there ANY interest management / area-of-interest / visibility culling, or does every client receive every entity every snapshot? How does delta compression work (delta masks, baseline acking)? Estimate bytes per entity and bytes per full snapshot at, say, 50 players + 50 monsters + projectiles. Is per-player serialization O(players * entities) = O(N^2)?
Report EXACT numbers with file:line. Flag scaling cliffs that would appear at 100-1000 players, AND anything that adds per-frame CPU cost that could starve the tick loop.`,
  },
  {
    key: 'transport',
    prompt: `Read client/autoload/network_manager.gd FULLY (it is the WebSocket client AND server). Also grep project.godot for any network settings.
Determine: transport is WebSocket-over-TCP (confirm). How often is the socket polled (poll() call site and frequency)? Is there outbound message batching/coalescing, or one ws send per message? Is Nagle's algorithm / TCP_NODELAY addressed at all (WebSocketPeer has no direct control, but note buffering behavior)? Is there a send queue, and is it flushed every frame or every tick? Are inbound messages drained fully each poll or one-per-frame? Note write/read buffer sizes (set_buffers / inbound_buffer_size / max_queued_packets).
Report EXACT numbers + file:line. Flag: TCP head-of-line blocking implications under packet loss, any place a message waits a frame before being sent, and one-message-per-frame drain loops.`,
  },
  {
    key: 'client-prediction',
    prompt: `Read these files FULLY:
- client/scripts/client/prediction.gd
- client/scripts/shared/player/player.gd
- client/scripts/shared/networking/packets/player_input_packet.gd
- client/scripts/shared/player/hp_component.gd
Also grep client/scripts/client for input sampling (look for an input controller / Input.get_vector / _physics_process reading input).
Determine: Is the LOCAL player client-side predicted, or does it wait for the server to move it (every input round-trips)? At what rate is input sampled and SENT to the server (Hz)? Are inputs sequence-numbered and buffered for replay? On receiving an authoritative state, does the client reconcile by replaying unacknowledged inputs, or snap? Is there smoothing on correction?
Report EXACT numbers + file:line. The MOST IMPORTANT finding: does moving the local player feel instant (predicted) or delayed by a full round-trip? If input send rate is low (e.g. 20Hz), every action has up to 50ms of sampling delay even on localhost.`,
  },
  {
    key: 'client-interpolation',
    prompt: `Read these files FULLY:
- client/scripts/client/interpolation_controller.gd
- client/scripts/client/entity_state_buffer.gd
- client/scripts/client/client_entity_manager.gd
- client/scripts/shared/player/remote_player.gd
Determine: How are remote entities (other players, monsters, projectiles) rendered between snapshots? What is the interpolation DELAY / buffer length in milliseconds or number-of-snapshots? (This is the #1 cause of "sluggish on localhost" — entities are rendered N ms in the past on purpose.) Is there extrapolation when the buffer runs dry? How are snapshot timestamps / sequence handled? Is the interpolation delay fixed or adaptive to jitter?
Report EXACT numbers + file:line. State the literal interpolation delay in ms (or derive it from buffer size * snapshot interval). This number is the headline.`,
  },
  {
    key: 'config-constants',
    prompt: `Read these files FULLY and dump EVERY numeric network/timing tunable:
- client/scripts/shared/game_constants.gd
- client/scripts/server/server_config.gd
- client/scripts/client/client_config.gd
- client/scripts/shared/test_config.gd
Also grep client/project.godot for physics_ticks_per_second, max_fps, and any [network]/[physics] settings.
List every constant relevant to performance: tick rate, snapshot rate, input send rate, interpolation delay/buffer, heartbeat interval, timeout, reconnect delay, max players, max monsters, max projectiles, movement speeds, map bounds, spatial grid cell size.
Report each as name = value with file:line. No bottleneck analysis needed unless a constant is obviously misconfigured (e.g. send rate > tick rate, or interpolation delay > 200ms).`,
  },
  {
    key: 'existing-analysis',
    prompt: `Read these existing analysis docs (read fully, they may be long) and summarize what bottlenecks have ALREADY been identified and which fixes are implemented vs pending:
- plans/NETWORK_PERFORMANCE_UPGRADES.md
- plans/CODEX_NETWORK_PERFORMANCE_UPGRADES.md
- plans/RECOMMENDATIONS.md
- docs/DESYNC_PLAN.md
Skim docs/ARCHITECTURE.md for any netcode/performance sections and note tick/send-rate numbers it claims.
Report: as 'metrics' list the target numbers these docs specify (e.g. "target tick rate = 30Hz"). As 'bottlenecks' list problems these docs ALREADY name, with severity, and in fix_hint note whether the doc says it's DONE or PLANNED. This tells us what's known vs unknown and whether docs match reality.`,
  },
]

phase('Map netcode')

const findings = await parallel(
  AREAS.map((a) => () =>
    agent(a.prompt, { label: `read:${a.key}`, phase: 'Map netcode', schema: FINDING_SCHEMA })
  )
)

return findings.filter(Boolean)
