//! Port of `core/internal/leet/units.go`: axis-label formatters and the
//! X-axis tick formatter.
//!
//! Go models formatters as an interface with seven value-type impls exposed
//! as package vars; the set is closed, so it ports as an enum (PORTING.md:
//! closed-set interfaces with value semantics → enum).

use crate::go_fmt::{format_float_f, format_float_g};

/// formatSigFigs formats the float with 'prec' significant digits.
///
/// It uses 'g' format, which removes trailing zeros and handles switching
/// to scientific notation for very small/large numbers automatically.
fn format_sig_figs(v: f64, prec: usize) -> String {
    format_float_g(v, prec)
}

/// UnitFormatter formats a scalar for axis labels and exposes the base unit
/// to show in titles.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Unit {
    /// Dimensionless numbers (epoch charts, counters, etc.).
    Scalar,
    /// Percentages (0..100).
    Percent,
    /// Temperature in Celsius.
    Celsius,
    /// Power in Watts.
    Watt,
    /// Frequency measured in MHz, titled in Hz.
    MHz,
    /// Bytes; the value is multiplied by `factor_to_bytes` first
    /// (1 for B, 1024² for MiB, 1024³ for GiB).
    Bytes { factor_to_bytes: f64 },
    /// Byte rates; the value is multiplied by `factor_to_bps` first.
    BytesPerSecond { factor_to_bps: f64 },
}

pub const UNIT_SCALAR: Unit = Unit::Scalar;
pub const UNIT_PERCENT: Unit = Unit::Percent;
pub const UNIT_CELSIUS: Unit = Unit::Celsius;
pub const UNIT_WATT: Unit = Unit::Watt;
pub const UNIT_MHZ: Unit = Unit::MHz;
pub const UNIT_BYTES: Unit = Unit::Bytes {
    factor_to_bytes: 1.0,
};
pub const UNIT_MIB: Unit = Unit::Bytes {
    factor_to_bytes: 1024.0 * 1024.0,
};
pub const UNIT_GIB: Unit = Unit::Bytes {
    factor_to_bytes: 1024.0 * 1024.0 * 1024.0,
};
pub const UNIT_BPS: Unit = Unit::BytesPerSecond { factor_to_bps: 1.0 };
pub const UNIT_MIBPS: Unit = Unit::BytesPerSecond {
    factor_to_bps: 1024.0 * 1024.0,
};
pub const UNIT_GIBPS: Unit = Unit::BytesPerSecond {
    factor_to_bps: 1024.0 * 1024.0 * 1024.0,
};

impl Unit {
    /// Base unit symbol without prefixes, e.g. "B", "Hz", "W", "%", "°C", "".
    pub fn name(&self) -> &'static str {
        match self {
            Unit::Scalar => "",
            Unit::Percent => "%",
            Unit::Celsius => "°C",
            Unit::Watt => "W",
            Unit::MHz => "Hz",
            Unit::Bytes { .. } => "B",
            Unit::BytesPerSecond { .. } => "B/s",
        }
    }

    /// Format a value in this unit's native measurement.
    pub fn format(&self, v: f64) -> String {
        if v == 0.0 {
            return "0".to_string();
        }
        match self {
            Unit::Scalar => format_sig_figs(v, 3),
            Unit::Percent => format_sig_figs(v, 3) + "%",
            Unit::Celsius => format_sig_figs(v, 3) + "°C",
            Unit::Watt => {
                let abs_v = v.abs();
                if abs_v >= 1000.0 {
                    format_sig_figs(v / 1000.0, 3) + "kW"
                } else {
                    format_sig_figs(v, 3) + "W"
                }
            }
            Unit::MHz => {
                // v is in MHz.
                let abs_v = v.abs();
                if abs_v >= 1000.0 {
                    format_sig_figs(v / 1000.0, 3) + "GHz"
                } else {
                    format_sig_figs(v, 3) + "MHz"
                }
            }
            Unit::Bytes { factor_to_bytes } => format_bytes_binary(v * factor_to_bytes),
            Unit::BytesPerSecond { factor_to_bps } => format_rate_decimal(v * factor_to_bps),
        }
    }
}

/// Binary prefixes: B, KiB, MiB, GiB, TiB.
fn format_bytes_binary(bytes: f64) -> String {
    const UNITS: [&str; 5] = ["B", "KiB", "MiB", "GiB", "TiB"];
    let mut unit_index = 0;
    let mut value = bytes;
    while unit_index < UNITS.len() - 1 && value.abs() >= 1024.0 {
        value /= 1024.0;
        unit_index += 1;
    }
    format_sig_figs(value, 3) + UNITS[unit_index]
}

/// Decimal prefixes for rates: B/s, KB/s, MB/s, GB/s.
fn format_rate_decimal(bps: f64) -> String {
    let abs_bps = bps.abs();
    if abs_bps >= 1e9 {
        format_sig_figs(bps / 1e9, 3) + "GB/s"
    } else if abs_bps >= 1e6 {
        format_sig_figs(bps / 1e6, 3) + "MB/s"
    } else if abs_bps >= 1e3 {
        format_sig_figs(bps / 1e3, 3) + "KB/s"
    } else {
        format_sig_figs(bps, 3) + "B/s"
    }
}

const SCALES: [(f64, &str); 11] = [
    (1e-6, "μ"),
    (1e-3, "m"),
    (1.0, ""),
    (1e3, "k"),
    (1e6, "M"),
    (1e9, "G"),
    (1e12, "T"),
    (1e15, "P"),
    (1e18, "E"),
    (1e21, "Z"),
    (1e24, "Y"),
];

/// FormatXAxisTick returns a human-friendly representation of an X axis
/// tick value.
///
/// Uses SI metric prefixes, up to two decimal places, and trims trailing
/// zeros.
///
/// Examples assume max_width of 5:
///
/// ```text
/// 42.0    -> "42"
/// 1234    -> "1.23k"
/// -1234   -> "-1.2k"
/// 50000   -> "50k"
/// 1234567 -> "1.23M"
/// ```
pub fn format_x_axis_tick(v: f64, max_width: isize) -> String {
    if v.is_nan() || v.is_infinite() {
        return String::new();
    }
    if v == 0.0 {
        return "0".to_string();
    }

    let mut v = v;
    let sign = if v < 0.0 {
        v = -v;
        "-"
    } else {
        ""
    };

    // Pick a scale so scaled is roughly in [1, 1000).
    let mut idx = 0;
    while idx + 1 < SCALES.len() && v >= SCALES[idx + 1].0 {
        idx += 1;
    }

    'scale: loop {
        let (factor, suffix) = SCALES[idx];
        let scaled = v / factor;

        let mut decimals: isize = 2;
        while decimals >= 0 {
            let num = trim_trailing_zeros(&format_float_f(scaled, decimals as usize));

            // Rounding crossed into next tier (e.g., 999.6k -> 1000k); bump suffix.
            if num == "1000" && idx + 1 < SCALES.len() {
                idx += 1;
                continue 'scale;
            }

            let out = format!("{sign}{num}{suffix}");
            // PARITY: Go compares len(out) — BYTES — so "μ" counts as 2.
            if max_width <= 0 || out.len() as isize <= max_width {
                return out;
            }
            decimals -= 1;
        }

        // Nothing fit; return minimum precision anyway.
        return format!(
            "{sign}{}{suffix}",
            trim_trailing_zeros(&format_float_f(scaled, 0))
        );
    }
}

fn trim_trailing_zeros(s: &str) -> String {
    if s.contains('.') {
        s.trim_end_matches('0').trim_end_matches('.').to_string()
    } else {
        s.to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unit_formatting_matches_go() {
        assert_eq!(UNIT_SCALAR.format(0.0), "0");
        assert_eq!(UNIT_SCALAR.format(1234.0), "1.23e+03");
        assert_eq!(UNIT_PERCENT.format(42.5), "42.5%");
        assert_eq!(UNIT_CELSIUS.format(71.0), "71°C");
        assert_eq!(UNIT_WATT.format(250.0), "250W");
        assert_eq!(UNIT_WATT.format(1500.0), "1.5kW");
        assert_eq!(UNIT_MHZ.format(999.0), "999MHz");
        assert_eq!(UNIT_MHZ.format(2400.0), "2.4GHz");
        assert_eq!(UNIT_BYTES.format(512.0), "512B");
        assert_eq!(UNIT_BYTES.format(2048.0), "2KiB");
        assert_eq!(UNIT_MIB.format(1.5), "1.5MiB");
        assert_eq!(UNIT_GIB.format(2.0), "2GiB");
        assert_eq!(UNIT_BPS.format(1500.0), "1.5KB/s");
        assert_eq!(UNIT_MIBPS.format(1.0), "1.05MB/s"); // 1048576 B/s
    }

    #[test]
    fn x_axis_ticks_match_go_docs() {
        assert_eq!(format_x_axis_tick(42.0, 5), "42");
        assert_eq!(format_x_axis_tick(1234.0, 5), "1.23k");
        assert_eq!(format_x_axis_tick(-1234.0, 5), "-1.2k");
        assert_eq!(format_x_axis_tick(50000.0, 5), "50k");
        assert_eq!(format_x_axis_tick(1234567.0, 5), "1.23M");
        assert_eq!(format_x_axis_tick(0.0, 5), "0");
        assert_eq!(format_x_axis_tick(f64::NAN, 5), "");
        assert_eq!(format_x_axis_tick(0.5, 5), "500m");
        assert_eq!(format_x_axis_tick(999_600.0, 5), "1M");
    }

    #[test]
    fn tick_width_is_byte_length_like_go() {
        // "μ" is 2 UTF-8 bytes: 1e-5 -> "10μ" (3 cols but 4 bytes).
        let s = format_x_axis_tick(0.00001, 4);
        assert_eq!(s, "10μ");
        assert_eq!(s.len(), 4);
    }
}
