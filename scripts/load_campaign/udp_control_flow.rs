//! Diagnostic copy of article_flow.rs SHA-256 a8d0e7fb1ecef028dc174db8fb4c103dca1b0fa0db7bfb0397ed4c242206dd9b
//! Diagnostic v2: bounded sequence history, window counters, graph points, fingerprints.
use std::collections::{BTreeMap, HashMap};
use std::fs::{self, File};
use std::io::{self, BufWriter, Write};

// At most 8192 streams * 4096 bitmap bytes (32 MiB), independent of command rate.
// ENet's u16 sequence is extended to the nearest half-range. Missing half a full
// sequence cycle or port reuse cannot be disambiguated from passive captures.
struct SequenceWindow {
    maximum: Option<i64>,
    seen: Box<[u64; 512]>,
}
impl Default for SequenceWindow {
    fn default() -> Self {
        Self {
            maximum: None,
            seen: Box::new([0; 512]),
        }
    }
}
impl SequenceWindow {
    fn observe(&mut self, sequence: u16) -> Option<bool> {
        let old = self.maximum.unwrap_or(i64::from(sequence));
        let extended = old + (i64::from(sequence) - old + 32768).rem_euclid(65536) - 32768;
        if extended > old {
            // Clear slots that enter the window, in word-sized chunks. Even a
            // large observed jump costs at most 512 word operations.
            let mut next = old + 1;
            while next <= extended {
                let slot = next.rem_euclid(32768) as usize;
                let n = (64 - slot % 64).min((extended - next + 1) as usize);
                let mask = if n == 64 {
                    u64::MAX
                } else {
                    ((1_u64 << n) - 1) << (slot % 64)
                };
                self.seen[slot / 64] &= !mask;
                next += n as i64;
            }
        }
        let maximum = old.max(extended);
        self.maximum = Some(maximum);
        // The exactly-half-range case lies outside retained history. Do not
        // overwrite its aliased newest slot; it is not an observed retry.
        if extended <= maximum - 32768 {
            return None;
        }
        let slot = extended.rem_euclid(32768) as usize;
        let mask = 1_u64 << (slot % 64);
        let retry = self.seen[slot / 64] & mask != 0;
        self.seen[slot / 64] |= mask;
        Some(retry)
    }
}

#[derive(Default)]
struct Counts {
    packets: u64,
    bytes: u64,
    reliable: u64,
    acks: u64,
    retry_bytes: u64,
    unclassified_reliable: u64,
    retry_payload: u64,
    first_payload: u64,
    types: BTreeMap<u8, u64>,
}

#[cfg(test)]
mod sustained_tests {
    use super::*;

    #[test]
    fn sequence_window_tracks_wrap_reorder_and_half_range_ambiguity() {
        let mut seen = SequenceWindow::default();
        assert_eq!(seen.observe(65534), Some(false));
        assert_eq!(seen.observe(0), Some(false));
        assert_eq!(seen.observe(65535), Some(false));
        assert_eq!(seen.observe(65534), Some(true));
        assert_eq!(seen.observe(0), Some(true));
        assert_eq!(seen.observe(32768), None);
        assert_eq!(seen.observe(0), Some(true));
        for n in 1..=65535 {
            assert_eq!(seen.observe(n), Some(false));
        }
        assert_eq!(seen.observe(0), Some(false));
        assert_eq!(seen.observe(65535), Some(true));
    }

    #[test]
    fn sequence_window_matches_bounded_reference_with_jumps_and_reordering() {
        let mut window = SequenceWindow::default();
        let mut history = std::collections::HashSet::new();
        let mut maximum = 0_i64;
        for i in 0..100_000_i64 {
            let sequence = if i % 7 == 0 {
                maximum - 400
            } else {
                maximum + i % 200
            };
            maximum = maximum.max(sequence);
            history.retain(|s| *s > maximum - 32768);
            let expected = !history.insert(sequence);
            assert_eq!(window.observe(sequence as u16), Some(expected));
        }
    }

    #[test]
    fn sustained_reliable_stream_does_not_exhaust_command_history() {
        let path = std::env::temp_dir().join(format!("omega-flow-history-{}", std::process::id()));
        fs::create_dir(&path).unwrap();
        let mut flow = ArticleFlow::new(path.to_str().unwrap()).unwrap();
        let result = (|| -> io::Result<()> {
            for i in 0..2_000_010_u64 {
                let mut row = [0_u8; 16];
                row[0] = 0x86; // Reliable application command; sequence wraps repeatedly.
                row[1] = 1;
                row[2..4].copy_from_slice(&(i as u16).to_be_bytes());
                row[6..8].copy_from_slice(&1_u16.to_be_bytes());
                row[12] = 67;
                flow.observe(10_000_000_000 + i * 10_000, 8081, 40001, 64, &[row])?;
            }
            flow.finish()
        })();
        fs::remove_dir_all(path).unwrap();
        assert!(
            result.is_ok(),
            "sustained stream lost its collector: {result:?}"
        );
    }
}
impl Counts {
    fn json(&self) -> String {
        let types = self
            .types
            .iter()
            .map(|(k, v)| format!("\"{k}\":{v}"))
            .collect::<Vec<_>>()
            .join(",");
        format!("{{\"packets\":{},\"ip_bytes\":{},\"reliable_commands\":{},\"unclassified_reliable_commands\":{},\"acks\":{},\"reliable_retry_command_bytes\":{},\"reliable_retry_payload_bytes\":{},\"first_transmission_payload_bytes\":{},\"first_message_counts_by_type\":{{{types}}},\"outstanding_commands_end\":null}}", self.packets,self.bytes,self.reliable,self.unclassified_reliable,self.acks,self.retry_bytes,self.retry_payload,self.first_payload)
    }
}
pub struct ArticleFlow {
    directory: String,
    window: Option<(u64, u64)>,
    poll_second: u64,
    schedule_stamp: Option<u64>,
    first: Option<u64>,
    last: u64,
    backstep: u64,
    counts: [Counts; 2],
    unclassified_total: [u64; 2],
    inputs: BTreeMap<u16, u64>,
    reliable: HashMap<(usize, u16, u8), SequenceWindow>,
    mappings: BufWriter<File>,
    bins: BufWriter<File>,
    bin_stamp: u64,
    bin: [u64; 6],
    port_points: BufWriter<File>,
    port_counts: BTreeMap<u16, u64>,
    bot_ids: BTreeMap<u16, u16>,
    points: BufWriter<File>,
    second: u64,
    point: [u64; 8],
}
impl ArticleFlow {
    pub fn new(directory: &str) -> io::Result<Self> {
        let mut points = BufWriter::new(File::create_new(format!("{directory}/flow-points.csv"))?);
        writeln!(points,"utc_second,out_packets,out_ip_bytes,in_packets,in_ip_bytes,input_commands,reliable_retry_command_bytes,out_acks,in_acks")?;
        let mut port_points =
            BufWriter::new(File::create_new(format!("{directory}/input-ports.csv"))?);
        writeln!(port_points, "utc_second,port,input_commands")?;
        let mut bins = BufWriter::new(File::create_new(format!("{directory}/flow-bins.csv"))?);
        writeln!(
            bins,
            "utc_10ms,out_packets,in_packets,inputs,retry_command_bytes,out_acks,in_acks"
        )?;
        let mut mappings = BufWriter::new(File::create_new(format!("{directory}/port-bot.csv"))?);
        writeln!(mappings, "port,bot_id")?;
        mappings.flush()?;
        Ok(Self {
            directory: directory.into(),
            window: None,
            poll_second: 0,
            schedule_stamp: None,
            first: None,
            last: 0,
            backstep: 0,
            counts: Default::default(),
            unclassified_total: [0; 2],
            inputs: Default::default(),
            reliable: Default::default(),
            mappings,
            bins,
            bin_stamp: 0,
            bin: [0; 6],
            port_points,
            port_counts: Default::default(),
            bot_ids: Default::default(),
            points,
            second: 0,
            point: [0; 8],
        })
    }
    fn flush_bin(&mut self) -> io::Result<()> {
        if self.bin_stamp != 0 {
            writeln!(
                self.bins,
                "{},{},{},{},{},{},{}",
                self.bin_stamp,
                self.bin[0],
                self.bin[1],
                self.bin[2],
                self.bin[3],
                self.bin[4],
                self.bin[5]
            )?;
        }
        self.bin = [0; 6];
        Ok(())
    }
    fn flush_point(&mut self) -> io::Result<()> {
        if self.second != 0 {
            writeln!(
                self.points,
                "{},{},{},{},{},{},{},{},{}",
                self.second,
                self.point[0],
                self.point[1],
                self.point[2],
                self.point[3],
                self.point[4],
                self.point[5],
                self.point[6],
                self.point[7]
            )?;
        }
        for (port, count) in &self.port_counts {
            writeln!(self.port_points, "{},{},{}", self.second, port, count)?;
        }
        self.port_counts.clear();
        self.point = [0; 8];
        self.points.flush()?;
        self.port_points.flush()?;
        self.bins.flush()?;
        Ok(())
    }
    pub fn observe(
        &mut self,
        stamp: u64,
        source: u16,
        target: u16,
        bytes: u64,
        rows: &[[u8; 16]],
    ) -> io::Result<()> {
        self.first.get_or_insert(stamp);
        self.backstep = self.backstep.max(self.last.saturating_sub(stamp));
        self.last = stamp;
        let sec = stamp / 1_000_000_000;
        if sec != self.poll_second {
            self.poll_second = sec;
            if self.window.is_none() {
                // Controller writes a tiny, atomic schedule before the measured window.
                let dir = if self.directory.ends_with("/prequeue") {
                    self.directory.trim_end_matches("/prequeue")
                } else {
                    &self.directory
                };
                if let Ok(text) = fs::read_to_string(format!("{dir}/window.json")) {
                    let numbers = text
                        .split(|c: char| !c.is_ascii_digit())
                        .filter(|s| !s.is_empty())
                        .filter_map(|s| s.parse::<u64>().ok())
                        .collect::<Vec<_>>();
                    if text.trim_end().ends_with('}')
                        && numbers.len() == 2
                        && numbers[0] < numbers[1]
                    {
                        self.window = Some((numbers[0], numbers[1]));
                        self.schedule_stamp = Some(stamp);
                    }
                }
            }
        }
        if sec != self.second {
            self.flush_point()?;
            self.second = sec;
        }
        if stamp / 10_000_000 != self.bin_stamp {
            self.flush_bin()?;
            self.bin_stamp = stamp / 10_000_000;
        }
        let d = usize::from(source != 8081);
        self.bin[d] += 1;
        let p = if d == 0 { target } else { source };
        self.point[d * 2] += 1;
        self.point[d * 2 + 1] += bytes;
        let included = self.window.is_some_and(|(a, b)| a <= stamp && stamp < b);
        if included {
            self.counts[d].packets += 1;
            self.counts[d].bytes += bytes;
        }
        for row in rows {
            let kind = row[0] & 15;
            if d == 1 && kind == 6 && row[12] == 1 && row[15] == 1 {
                let id = u16::from_le_bytes([row[13], row[14]]);
                if self.bot_ids.insert(p, id) != Some(id) {
                    writeln!(self.mappings, "{p},{id}")?;
                    self.mappings.flush()?;
                }
            }
            let channel = row[1];
            let sequence = u16::from_be_bytes([row[2], row[3]]);
            let length = u64::from(u16::from_be_bytes([row[6], row[7]]));
            let fragment = u32::from_be_bytes(row[8..12].try_into().unwrap());
            if kind == 7 && included {
                *self.counts[d].types.entry(row[12]).or_default() += 1;
                self.counts[d].first_payload += length;
            }
            if d == 1 && row[12] == 2 && matches!(kind, 6 | 7) && length == 22 {
                self.point[4] += 1;
                self.bin[2] += 1;
                *self.port_counts.entry(p).or_default() += 1;
                if included {
                    *self.inputs.entry(p).or_default() += 1;
                }
            }
            if kind == 1 {
                self.point[6 + d] += 1;
                self.bin[4 + d] += 1;
                if included {
                    self.counts[d].acks += 1;
                }
            } else if row[0] & 128 != 0 && matches!(kind, 6 | 8) {
                let key = (d, p, channel);
                if self.reliable.len() >= 8192 && !self.reliable.contains_key(&key) {
                    return Err(io::Error::other("diagnostic reliable-stream limit"));
                }
                let retry = self.reliable.entry(key).or_default().observe(sequence);
                if retry.is_none() {
                    self.unclassified_total[d] += 1;
                }
                if retry == Some(true) {
                    self.point[5] += length + if kind == 6 { 6 } else { 24 };
                    self.bin[3] += length + if kind == 6 { 6 } else { 24 };
                }
                if included {
                    self.counts[d].reliable += 1;
                    if retry == Some(true) {
                        self.counts[d].retry_bytes += length + if kind == 6 { 6 } else { 24 };
                        self.counts[d].retry_payload += length;
                    } else if retry == Some(false) {
                        self.counts[d].first_payload += length;
                        if kind == 6 || fragment == 0 {
                            *self.counts[d].types.entry(row[12]).or_default() += 1;
                        }
                    } else {
                        self.counts[d].unclassified_reliable += 1;
                    }
                }
            }
        }
        Ok(())
    }
    pub fn finish(mut self) -> io::Result<()> {
        self.flush_point()?;
        self.flush_bin()?;
        self.bins.flush()?;
        self.points.flush()?;
        self.port_points.flush()?;
        self.mappings.flush()?;
        let inputs = self
            .inputs
            .iter()
            .map(|(k, v)| format!("\"{k}\":{v}"))
            .collect::<Vec<_>>()
            .join(",");
        let schedule_stamp = self.schedule_stamp.map_or("null".into(), |x| x.to_string());
        let first = self.first.map_or("null".into(), |x| x.to_string());
        let window = self.window.map_or("null".into(), |(a, b)| {
            format!("{{\"start\":{a},\"end\":{b}}}")
        });
        let mut file = File::create_new(format!("{}/flow-summary.json", self.directory))?;
        writeln!(file,"{{\"format\":\"udp-diagnostic-points-v2\",\"window\":{window},\"sample_modulus\":64,\"retry_semantics\":\"Observed repeated reliable sequence within a 32768-sequence sliding window per direction/port/channel; nearest-half-range extension from observed data only; no time TTL. Assumes no unseen advance of 32768 or more and no port reuse. First means first observed in retained window, not proven original transmission. Not equivalent to v1 60-second history.\",\"unclassified_reliable_all_capture\":[{},{}],\"reliable_streams\":{},\"reliable_history_bytes\":{},\"schedule_observed_utc_ns\":{schedule_stamp},\"out\":{},\"in\":{},\"wire_input_counts_by_port\":{{{inputs}}},\"capture_first_timestamp_ns\":{first},\"capture_last_timestamp_ns\":{},\"max_timestamp_backstep_ns\":{},\"outstanding_semantics\":\"Not collected: cumulative retries and delivery samples retained instead of per-command ACK state\"}}", self.unclassified_total[0],self.unclassified_total[1],self.reliable.len(),self.reliable.len() * 4096,self.counts[0].json(),self.counts[1].json(),self.last,self.backstep)
    }
}
