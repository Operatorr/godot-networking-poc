//! Virtual-clock parity/accounting validation. Never opens a network socket.
use std::time::Instant;

#[derive(Clone, Copy, Debug)]
enum Fault {
    None,
    Zero,
    Partial,
    Error,
}
#[derive(Clone, Copy, Debug)]
struct Scenario {
    jitter: bool,
    batch: bool,
    fault: Fault,
    reset: bool,
}
#[derive(Debug, PartialEq, Eq)]
struct Wire {
    at: u64,
    from: u16,
    to: u16,
    bytes: Vec<u8>,
    result: i32,
}
#[derive(Debug, Default, Clone, Copy)]
struct Counts {
    admitted: u64,
    pending: u64,
    throttle: u64,
    reset: u64,
    full: u64,
    zero: u64,
    partial: u64,
    error: u64,
    unknown: u64,
    errors: u64,
    hook_ns: u64,
}
impl Counts {
    fn balanced(self) -> bool {
        self.errors == 0
            && self.admitted
                == self.pending
                    + self.throttle
                    + self.reset
                    + self.full
                    + self.zero
                    + self.partial
                    + self.error
                    + self.unknown
    }
}
#[derive(Debug)]
struct Replay {
    wire: Vec<Wire>,
    events: Vec<(u64, u8, Vec<u8>)>,
    offered: u64,
    delivered: u64,
    counts: Counts,
}

mod reference {
    use enet_reference as enet;
    fn enable(_: &mut enet::Host<Endpoint>, _: bool) {}
    fn counts(_: &enet::Host<Endpoint>) -> super::Counts {
        super::Counts::default()
    }
    include!("replay.rs");
}
mod observed {
    use enet_observed as enet;
    fn enable(host: &mut enet::Host<Endpoint>, enabled: bool) {
        if enabled {
            host.enable_input_diagnostic().unwrap();
        }
    }
    fn counts(host: &enet::Host<Endpoint>) -> super::Counts {
        let c = host.input_counters();
        assert!(c.balanced(), "unbalanced native counters: {c:?}");
        super::Counts {
            admitted: c.admitted,
            pending: c.pending,
            throttle: c.throttle_retired,
            reset: c.reset_retired,
            full: c.full_handoffs,
            zero: c.zero_handoffs,
            partial: c.partial_handoffs,
            error: c.error_handoffs,
            unknown: c.unknown_dispositions,
            errors: c.accounting_errors,
            hook_ns: c.completed_hook_ns,
        }
    }
    include!("replay.rs");
}

fn scenarios() -> Vec<Scenario> {
    vec![
        Scenario {
            jitter: false,
            batch: false,
            fault: Fault::None,
            reset: false,
        },
        Scenario {
            jitter: true,
            batch: false,
            fault: Fault::None,
            reset: false,
        },
        Scenario {
            jitter: false,
            batch: true,
            fault: Fault::None,
            reset: false,
        },
        Scenario {
            jitter: false,
            batch: true,
            fault: Fault::Zero,
            reset: false,
        },
        Scenario {
            jitter: false,
            batch: true,
            fault: Fault::Partial,
            reset: false,
        },
        Scenario {
            jitter: false,
            batch: true,
            fault: Fault::Error,
            reset: false,
        },
        Scenario {
            jitter: false,
            batch: true,
            fault: Fault::None,
            reset: true,
        },
    ]
}
fn validate() -> serde_json::Value {
    let mut results = vec![];
    for s in scenarios() {
        let a = reference::run(s, false, true);
        let b = observed::run(s, false, true);
        let c = observed::run(s, true, true);
        assert_eq!(a.wire, b.wire, "reference/off bytes or timing: {s:?}");
        assert_eq!(a.wire, c.wire, "reference/on bytes or timing: {s:?}");
        assert_eq!(a.events, b.events, "reference/off events: {s:?}");
        assert_eq!(a.events, c.events, "reference/on events: {s:?}");
        assert_eq!((a.offered, a.delivered), (b.offered, b.delivered));
        assert_eq!((a.offered, a.delivered), (c.offered, c.delivered));
        assert!(c.counts.balanced());
        assert_eq!(c.counts.admitted, c.offered);
        assert_eq!(c.counts.pending, 0);
        assert_eq!(c.counts.unknown, 0);
        if s.jitter {
            assert!(c.counts.throttle > 0);
        }
        if s.reset {
            assert!(c.counts.reset > 0);
        }
        match s.fault {
            Fault::Zero => assert!(c.counts.zero > 0),
            Fault::Partial => assert!(c.counts.partial > 0),
            Fault::Error => assert!(c.counts.error > 0),
            _ => {}
        }
        results.push(
            serde_json::json!({"scenario":format!("{s:?}"),"offered":c.offered,
            "delivered":c.delivered,"wire_records":c.wire.len(),"event_records":c.events.len(),
            "counter_balance":c.counts.balanced(),"counts":format!("{:?}",c.counts),
            "bytes_events_virtual_timing_equal":true}),
        );
    }
    serde_json::json!({"parity_pass":true,"scenarios":results,
        "observer_state_bytes_per_bot":std::mem::size_of::<enet_observed::InputCounters>()+8,
        "observer_storage_cap_bytes":2*1024*1024,
        "io":"in-memory only; no UDP socket or host access"})
}
fn benchmark() -> serde_json::Value {
    let s = Scenario {
        jitter: true,
        batch: false,
        fault: Fault::None,
        reset: false,
    };
    // Fixed work: 25 identical virtual-clock runs per arm; order alternates.
    // Five pairs are the entire preregistered overhead assessment, with no retry.
    let mut pairs = vec![];
    let mut totals = [0u128; 2];
    for pair in 0..5 {
        let mut durations = [0u128; 2];
        for enabled in if pair % 2 == 0 {
            [false, true]
        } else {
            [true, false]
        } {
            let start = Instant::now();
            for _ in 0..25 {
                let r = observed::run(s, enabled, false);
                std::hint::black_box((r.offered, r.delivered, r.counts.hook_ns));
            }
            durations[usize::from(enabled)] = start.elapsed().as_nanos();
        }
        for i in 0..2 {
            totals[i] += durations[i];
        }
        pairs.push(
            serde_json::json!({"pair":pair+1,"order":if pair%2==0 {"off,on"} else {"on,off"},
            "off_ns":durations[0],"on_ns":durations[1],
            "overhead_fraction":durations[1] as f64/durations[0] as f64-1.0}),
        );
    }
    let overhead = totals[1] as f64 / totals[0] as f64 - 1.0;
    serde_json::json!({"pairs":pairs,"off_total_ns":totals[0],"on_total_ns":totals[1],
        "overhead_fraction":overhead,"limit_fraction":0.02,"overhead_pass":overhead<=0.02,
        "replays_per_arm":25,"virtual_ms_per_replay":361000,"retry_count":0})
}
fn main() {
    match std::env::args().nth(1).as_deref() {
        Some("validate") => println!("{}", validate()),
        Some("benchmark") => {
            let result = benchmark();
            println!("{result}");
            if result["overhead_pass"] != true {
                std::process::exit(1);
            }
        }
        _ => {
            eprintln!("usage: idle150-diagnostic validate|benchmark");
            std::process::exit(2);
        }
    }
}
