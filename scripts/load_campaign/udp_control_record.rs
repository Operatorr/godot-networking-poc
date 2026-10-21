//! Parser copy source SHA-256 00ac4747185ad5c98065adc35c5815055cae808b11f38ebcd3fee29bf0cb9064
//! Full-datagram ENet inspection with bounded retained payload. Original headers are
//! retained as pcap (128 bytes); command descriptors and full UDP fingerprints are raw
//! observations, allowing packet matching and reliable sequence/retry/ACK accounting.
#[path = "udp_control_flow.rs"]
mod article_flow;
use std::fs::File;
use std::hash::Hasher;
use std::io::{self, BufReader, BufWriter, Read, Write};

fn be16(bytes: &[u8]) -> u16 {
    u16::from_be_bytes([bytes[0], bytes[1]])
}
fn le32(bytes: &[u8]) -> u32 {
    u32::from_le_bytes(bytes[..4].try_into().unwrap())
}

fn commands(data: &[u8]) -> io::Result<Vec<[u8; 16]>> {
    if data.len() < 2 {
        return Err(io::Error::other("short ENet header"));
    }
    let mut offset = if be16(data) & 0x8000 != 0 { 4 } else { 2 };
    let sizes = [0, 8, 48, 44, 8, 4, 6, 8, 24, 8, 12, 16, 24];
    let mut result = Vec::new();
    while offset < data.len() {
        if offset + 4 > data.len() {
            return Err(io::Error::other("short command"));
        }
        let kind = usize::from(data[offset] & 15);
        if kind == 0 || kind >= sizes.len() {
            return Err(io::Error::other("bad command"));
        }
        let size = sizes[kind];
        if offset + size > data.len() {
            return Err(io::Error::other("short command body"));
        }
        let command = &data[offset..offset + size];
        let length = match kind {
            6 => usize::from(be16(&command[4..])),
            7 | 8 | 9 | 12 => usize::from(be16(&command[6..])),
            _ => 0,
        };
        if offset + size + length > data.len() {
            return Err(io::Error::other("truncated ENet payload"));
        }
        let mut row = [0_u8; 16];
        row[0] = command[0];
        row[1] = command[1];
        row[2..4].copy_from_slice(&command[2..4]);
        if matches!(kind, 1 | 7 | 8 | 9 | 12) {
            row[4..6].copy_from_slice(&command[4..6]);
        }
        row[6..8].copy_from_slice(&(length as u16).to_be_bytes());
        if matches!(kind, 8 | 12) {
            row[8..12].copy_from_slice(&command[12..16]);
        }
        row[12] = if length > 0 { data[offset + size] } else { 0 };
        // Diagnostic metadata only: map this test's unsigned LoadBot handshake to its port.
        // Payload layout is protocol ConnectAuth; no ticket/name bytes are retained.
        if kind == 6 && length >= 5 && row[12] == 1 {
            let body = &data[offset + size..offset + size + length];
            let ticket_len = usize::from(u16::from_le_bytes([body[2], body[3]]));
            if ticket_len == 0 {
                let name_len = usize::from(body[4]);
                if let Some(name) = body.get(5..5 + name_len).and_then(|b| std::str::from_utf8(b).ok()) {
                    if let Some(id) = name.strip_prefix("LoadBot").and_then(|s| s.parse::<u16>().ok()) {
                        row[13..15].copy_from_slice(&id.to_le_bytes());
                        row[15] = 1;
                    }
                }
            }
        }
        result.push(row);
        offset += size + length;
    }
    Ok(result)
}

fn main() -> io::Result<()> {
    let directory = std::env::args().nth(1).expect("evidence directory");
    let compact = std::env::args().any(|arg| arg == "--article");
    let mut article = if compact {
        Some(article_flow::ArticleFlow::new(&directory)?)
    } else {
        None
    };
    let mut input = BufReader::with_capacity(1024 * 1024, io::stdin().lock());
    let mut headers: Box<dyn Write> = if compact {
        Box::new(io::sink())
    } else {
        Box::new(BufWriter::new(File::create_new(format!(
            "{directory}/headers.pcap"
        ))?))
    };
    let mut output = BufWriter::with_capacity(
        1024 * 1024,
        File::create_new(format!("{directory}/datagrams.bin"))?,
    );
    let mut global = [0; 24];
    input.read_exact(&mut global)?;
    if global[..4] != [0xd4, 0xc3, 0xb2, 0xa1] || le32(&global[20..]) != 1 {
        return Err(io::Error::other(
            "expected little-endian microsecond Ethernet pcap",
        ));
    }
    global[16..20].copy_from_slice(&128_u32.to_le_bytes());
    headers.write_all(&global)?;
    output.write_all(b"ORF1")?;
    let (mut packets, mut parse_errors) = (0_u64, 0_u64);
    loop {
        let mut record = [0; 16];
        match input.read_exact(&mut record) {
            Ok(()) => {}
            Err(e) if e.kind() == io::ErrorKind::UnexpectedEof => break,
            Err(e) => return Err(e),
        }
        let cap_len = le32(&record[8..]) as usize;
        if cap_len > 65536 {
            return Err(io::Error::other("oversized capture record"));
        }
        let mut bytes = vec![0; cap_len];
        input.read_exact(&mut bytes)?;
        let retained = cap_len.min(128);
        let mut retained_record = record;
        retained_record[8..12].copy_from_slice(&(retained as u32).to_le_bytes());
        headers.write_all(&retained_record)?;
        headers.write_all(&bytes[..retained])?;
        packets += 1;
        if bytes.len() < 42 || be16(&bytes[12..]) != 0x0800 {
            parse_errors += 1;
            continue;
        }
        let ip = &bytes[14..];
        let ip_header = usize::from(ip[0] & 15) * 4;
        let ip_length = usize::from(be16(&ip[2..]));
        if ip.len() < ip_length || ip[9] != 17 || ip_header < 20 || ip_header + 8 > ip_length {
            parse_errors += 1;
            continue;
        }
        let udp = &ip[ip_header..ip_length];
        let udp_length = usize::from(be16(&udp[4..]));
        if udp_length < 8 || udp_length > udp.len() {
            parse_errors += 1;
            continue;
        }
        let payload = &udp[8..udp_length];
        let mut hash = std::collections::hash_map::DefaultHasher::new();
        hash.write(payload);
        let command_rows = match commands(payload) {
            Ok(rows) => rows,
            Err(_) => {
                parse_errors += 1;
                Vec::new()
            }
        };
        let stamp = u64::from(le32(&record)) * 1_000_000_000 + u64::from(le32(&record[4..])) * 1000;
        if let Some(stats) = article.as_mut() {
            stats.observe(
                stamp,
                be16(&udp[..2]),
                be16(&udp[2..4]),
                ip_length as u64,
                &command_rows,
            )?;
        }
        // The same UDP fingerprint is selected at both endpoints, including retries.
        // No headers or command descriptors are retained in article mode.
        if !compact || hash.finish() % 64 == 0 {
            output.write_all(&stamp.to_le_bytes())?;
            output.write_all(&udp[..4])?;
            output.write_all(&(ip_length as u16).to_le_bytes())?;
            output.write_all(&(udp_length as u16).to_le_bytes())?;
            output.write_all(&hash.finish().to_le_bytes())?;
            output.write_all(
                &(if compact {
                    0
                } else {
                    command_rows.len() as u16
                })
                .to_le_bytes(),
            )?;
            if !compact {
                for row in command_rows {
                    output.write_all(&row)?;
                }
            }
        }
    }
    headers.flush()?;
    output.flush()?;
    if let Some(stats) = article {
        stats.finish()?;
    }
    eprintln!("flow recorder packets={packets} parse_errors={parse_errors}");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn reliable_unreliable_and_ack_in_one_datagram() {
        let data = [
            0, 1, 0x86, 1, 0, 7, 0, 2, 65, 0, 7, 0, 0, 8, 0, 9, 0, 1, 2, 1, 1, 0, 10, 0, 7, 0, 0,
        ];
        let rows = commands(&data).unwrap();
        assert_eq!(rows.len(), 3);
        assert_eq!(rows[0][12], 65);
        assert_eq!(rows[1][12], 2);
        assert_eq!(&rows[2][4..6], &[0, 7]);
    }
    #[test]
    fn truncated_payload_is_an_observation_failure() {
        assert!(commands(&[0, 1, 6, 1, 0, 1, 0, 4, 65]).is_err());
    }
}
