use std::fmt;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DecodeError {
    /// Packet ended before the field could be read.
    UnexpectedEof,
    /// Unknown or direction-invalid packet type byte.
    BadPacketType(u8),
    /// A field held a value outside its valid range.
    BadValue(&'static str),
    /// Bytes (or non-zero padding bits) remained after the packet was fully decoded.
    TrailingData,
    /// A string field was not valid UTF-8.
    BadUtf8,
}

impl fmt::Display for DecodeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            DecodeError::UnexpectedEof => write!(f, "unexpected end of packet"),
            DecodeError::BadPacketType(t) => write!(f, "bad packet type {t}"),
            DecodeError::BadValue(what) => write!(f, "bad value for {what}"),
            DecodeError::TrailingData => write!(f, "trailing data after packet"),
            DecodeError::BadUtf8 => write!(f, "invalid utf-8 in string field"),
        }
    }
}

impl std::error::Error for DecodeError {}
