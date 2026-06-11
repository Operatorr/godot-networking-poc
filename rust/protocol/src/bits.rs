//! Byte- and bit-level writer/reader. Bit fields are packed LSB-first into the byte stream;
//! byte-aligned writes after bit writes pad the current byte with zeros (`align`).

use crate::error::DecodeError;

#[derive(Default)]
pub struct BitWriter {
    out: Vec<u8>,
    cur: u8,
    nbits: u8,
}

impl BitWriter {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_capacity(cap: usize) -> Self {
        Self {
            out: Vec::with_capacity(cap),
            cur: 0,
            nbits: 0,
        }
    }

    /// Write the low `n` bits of `value`, LSB-first. `n` must be 1..=32.
    pub fn write_bits(&mut self, value: u32, n: u8) {
        debug_assert!((1..=32).contains(&n));
        for i in 0..n {
            let bit = (value >> i) & 1;
            self.cur |= (bit as u8) << self.nbits;
            self.nbits += 1;
            if self.nbits == 8 {
                self.out.push(self.cur);
                self.cur = 0;
                self.nbits = 0;
            }
        }
    }

    pub fn write_bit(&mut self, v: bool) {
        self.write_bits(v as u32, 1);
    }

    /// Pad the in-progress byte with zero bits so the next write is byte-aligned.
    pub fn align(&mut self) {
        if self.nbits > 0 {
            self.out.push(self.cur);
            self.cur = 0;
            self.nbits = 0;
        }
    }

    pub fn write_u8(&mut self, v: u8) {
        self.align();
        self.out.push(v);
    }

    pub fn write_u16(&mut self, v: u16) {
        self.align();
        self.out.extend_from_slice(&v.to_le_bytes());
    }

    pub fn write_i16(&mut self, v: i16) {
        self.align();
        self.out.extend_from_slice(&v.to_le_bytes());
    }

    pub fn write_u32(&mut self, v: u32) {
        self.align();
        self.out.extend_from_slice(&v.to_le_bytes());
    }

    pub fn write_u64(&mut self, v: u64) {
        self.align();
        self.out.extend_from_slice(&v.to_le_bytes());
    }

    pub fn write_bytes(&mut self, b: &[u8]) {
        self.align();
        self.out.extend_from_slice(b);
    }

    /// u8-length-prefixed UTF-8 string; the name fields are short by design. Longer input is
    /// truncated at a char boundary to at most 255 bytes (the old protocol's unclamped u16
    /// prefix could corrupt a frame — see extraction/wire-protocol.md §5.3).
    pub fn write_str8(&mut self, s: &str) {
        let mut end = s.len().min(255);
        while !s.is_char_boundary(end) {
            end -= 1;
        }
        let bytes = &s.as_bytes()[..end];
        self.write_u8(bytes.len() as u8);
        self.write_bytes(bytes);
    }

    pub fn len(&self) -> usize {
        self.out.len() + if self.nbits > 0 { 1 } else { 0 }
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    pub fn finish(mut self) -> Vec<u8> {
        self.align();
        self.out
    }
}

pub struct BitReader<'a> {
    data: &'a [u8],
    byte_pos: usize,
    bit_pos: u8,
}

impl<'a> BitReader<'a> {
    pub fn new(data: &'a [u8]) -> Self {
        Self {
            data,
            byte_pos: 0,
            bit_pos: 0,
        }
    }

    /// Read `n` bits, LSB-first. `n` must be 1..=32.
    pub fn read_bits(&mut self, n: u8) -> Result<u32, DecodeError> {
        debug_assert!((1..=32).contains(&n));
        let mut v: u32 = 0;
        for i in 0..n {
            if self.byte_pos >= self.data.len() {
                return Err(DecodeError::UnexpectedEof);
            }
            let bit = (self.data[self.byte_pos] >> self.bit_pos) & 1;
            v |= (bit as u32) << i;
            self.bit_pos += 1;
            if self.bit_pos == 8 {
                self.bit_pos = 0;
                self.byte_pos += 1;
            }
        }
        Ok(v)
    }

    pub fn read_bit(&mut self) -> Result<bool, DecodeError> {
        Ok(self.read_bits(1)? != 0)
    }

    /// Skip any padding bits so the next read is byte-aligned. The padding must be zero
    /// (strict decode).
    pub fn align(&mut self) -> Result<(), DecodeError> {
        if self.bit_pos > 0 {
            let pad = self.data[self.byte_pos] >> self.bit_pos;
            if pad != 0 {
                return Err(DecodeError::TrailingData);
            }
            self.bit_pos = 0;
            self.byte_pos += 1;
        }
        Ok(())
    }

    fn take(&mut self, n: usize) -> Result<&'a [u8], DecodeError> {
        self.align()?;
        if self.byte_pos + n > self.data.len() {
            return Err(DecodeError::UnexpectedEof);
        }
        let s = &self.data[self.byte_pos..self.byte_pos + n];
        self.byte_pos += n;
        Ok(s)
    }

    pub fn read_u8(&mut self) -> Result<u8, DecodeError> {
        Ok(self.take(1)?[0])
    }

    pub fn read_u16(&mut self) -> Result<u16, DecodeError> {
        Ok(u16::from_le_bytes(self.take(2)?.try_into().unwrap()))
    }

    pub fn read_i16(&mut self) -> Result<i16, DecodeError> {
        Ok(i16::from_le_bytes(self.take(2)?.try_into().unwrap()))
    }

    pub fn read_u32(&mut self) -> Result<u32, DecodeError> {
        Ok(u32::from_le_bytes(self.take(4)?.try_into().unwrap()))
    }

    pub fn read_u64(&mut self) -> Result<u64, DecodeError> {
        Ok(u64::from_le_bytes(self.take(8)?.try_into().unwrap()))
    }

    pub fn read_bytes(&mut self, n: usize) -> Result<&'a [u8], DecodeError> {
        self.take(n)
    }

    pub fn read_str8(&mut self) -> Result<String, DecodeError> {
        let len = self.read_u8()? as usize;
        let bytes = self.take(len)?;
        String::from_utf8(bytes.to_vec()).map_err(|_| DecodeError::BadUtf8)
    }

    pub fn remaining_bytes(&self) -> usize {
        self.data.len() - self.byte_pos - if self.bit_pos > 0 { 1 } else { 0 }
    }

    /// Strict end-of-packet check: no full bytes may remain, and any padding bits in the final
    /// partially-read byte must be zero.
    pub fn expect_end(&self) -> Result<(), DecodeError> {
        let (byte_pos, bit_pos) = (self.byte_pos, self.bit_pos);
        if bit_pos > 0 {
            if byte_pos + 1 != self.data.len() {
                return Err(DecodeError::TrailingData);
            }
            if self.data[byte_pos] >> bit_pos != 0 {
                return Err(DecodeError::TrailingData);
            }
            return Ok(());
        }
        if byte_pos != self.data.len() {
            return Err(DecodeError::TrailingData);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bits_round_trip() {
        let mut w = BitWriter::new();
        w.write_bits(0b101, 3);
        w.write_bits(0x3FF, 10);
        w.write_bit(true);
        w.write_u16(0xBEEF);
        w.write_bits(7, 5);
        let buf = w.finish();

        let mut r = BitReader::new(&buf);
        assert_eq!(r.read_bits(3).unwrap(), 0b101);
        assert_eq!(r.read_bits(10).unwrap(), 0x3FF);
        assert!(r.read_bit().unwrap());
        assert_eq!(r.read_u16().unwrap(), 0xBEEF);
        assert_eq!(r.read_bits(5).unwrap(), 7);
        r.expect_end().unwrap();
    }

    #[test]
    fn trailing_data_detected() {
        let mut w = BitWriter::new();
        w.write_u8(1);
        let mut buf = w.finish();
        buf.push(0);
        let mut r = BitReader::new(&buf);
        r.read_u8().unwrap();
        assert_eq!(r.expect_end(), Err(DecodeError::TrailingData));
    }

    #[test]
    fn nonzero_padding_rejected() {
        // 3 bits written, but the padding region holds garbage.
        let buf = vec![0b1111_1101];
        let mut r = BitReader::new(&buf);
        assert_eq!(r.read_bits(3).unwrap(), 0b101);
        assert_eq!(r.expect_end(), Err(DecodeError::TrailingData));
    }

    #[test]
    fn str8_truncates_at_char_boundary() {
        let long = "é".repeat(200); // 400 bytes of UTF-8
        let mut w = BitWriter::new();
        w.write_str8(&long);
        let buf = w.finish();
        let mut r = BitReader::new(&buf);
        let s = r.read_str8().unwrap();
        assert!(s.len() <= 255);
        assert!(long.starts_with(&s));
    }
}
