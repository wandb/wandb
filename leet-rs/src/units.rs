//! Number formatting for axis labels and titles.

/// Formats a float with `prec` significant digits, matching Go's
/// `strconv.FormatFloat(v, 'g', prec, 64)` closely enough for display:
/// trailing zeros are removed and very small/large numbers switch to
/// scientific notation.
pub fn format_sig_figs(v: f64, prec: usize) -> String {
    if v == 0.0 {
        return "0".to_string();
    }
    if v.is_nan() {
        return "NaN".to_string();
    }
    if v.is_infinite() {
        return if v > 0.0 { "+Inf" } else { "-Inf" }.to_string();
    }

    let exp = v.abs().log10().floor() as i32;
    // Go's 'g' format uses scientific notation when the exponent is < -4 or
    // >= precision.
    if exp < -4 || exp >= prec as i32 {
        let s = format!("{:.*e}", prec.saturating_sub(1), v);
        // Rust formats as "1.23e4"; Go as "1.23e+04". Normalize to Go style.
        if let Some(epos) = s.find('e') {
            let (mantissa, exp_str) = s.split_at(epos);
            let exp_num: i32 = exp_str[1..].parse().unwrap_or(0);
            let mantissa = trim_trailing_zeros(mantissa);
            return format!(
                "{mantissa}e{}{:02}",
                if exp_num < 0 { '-' } else { '+' },
                exp_num.abs()
            );
        }
        s
    } else {
        let decimals = (prec as i32 - 1 - exp).max(0) as usize;
        trim_trailing_zeros(&format!("{v:.decimals$}"))
    }
}

fn trim_trailing_zeros(s: &str) -> String {
    if s.contains('.') {
        s.trim_end_matches('0').trim_end_matches('.').to_string()
    } else {
        s.to_string()
    }
}

/// Formats a scalar for axis labels and exposes the base unit for titles.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
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
    /// Bytes; value provided pre-scaled by the factor.
    Bytes(u64),
    /// Byte rates; value provided pre-scaled by the factor.
    BytesPerSecond(u64),
}

pub const UNIT_SCALAR: Unit = Unit::Scalar;
pub const UNIT_PERCENT: Unit = Unit::Percent;
pub const UNIT_CELSIUS: Unit = Unit::Celsius;
pub const UNIT_WATT: Unit = Unit::Watt;
pub const UNIT_MHZ: Unit = Unit::MHz;
pub const UNIT_BYTES: Unit = Unit::Bytes(1);
pub const UNIT_MIB: Unit = Unit::Bytes(1024 * 1024);
pub const UNIT_GIB: Unit = Unit::Bytes(1024 * 1024 * 1024);
pub const UNIT_BPS: Unit = Unit::BytesPerSecond(1);
pub const UNIT_MIBPS: Unit = Unit::BytesPerSecond(1024 * 1024);
#[allow(dead_code)]
pub const UNIT_GIBPS: Unit = Unit::BytesPerSecond(1024 * 1024 * 1024);

impl Unit {
    /// Base unit symbol without prefixes.
    pub fn name(&self) -> &'static str {
        match self {
            Unit::Scalar => "",
            Unit::Percent => "%",
            Unit::Celsius => "°C",
            Unit::Watt => "W",
            Unit::MHz => "Hz",
            Unit::Bytes(_) => "B",
            Unit::BytesPerSecond(_) => "B/s",
        }
    }

    /// Formats a value in this unit's native measurement.
    pub fn format(&self, v: f64) -> String {
        if v == 0.0 {
            return "0".to_string();
        }
        match self {
            Unit::Scalar => format_sig_figs(v, 3),
            Unit::Percent => format!("{}%", format_sig_figs(v, 3)),
            Unit::Celsius => format!("{}°C", format_sig_figs(v, 3)),
            Unit::Watt => {
                if v.abs() >= 1000.0 {
                    format!("{}kW", format_sig_figs(v / 1000.0, 3))
                } else {
                    format!("{}W", format_sig_figs(v, 3))
                }
            }
            Unit::MHz => {
                if v.abs() >= 1000.0 {
                    format!("{}GHz", format_sig_figs(v / 1000.0, 3))
                } else {
                    format!("{}MHz", format_sig_figs(v, 3))
                }
            }
            Unit::Bytes(factor) => format_bytes_binary(v * *factor as f64),
            Unit::BytesPerSecond(factor) => format_rate_decimal(v * *factor as f64),
        }
    }
}

/// Binary prefixes: B, KiB, MiB, GiB, TiB.
fn format_bytes_binary(bytes: f64) -> String {
    const UNITS: [&str; 5] = ["B", "KiB", "MiB", "GiB", "TiB"];
    let mut idx = 0;
    let mut value = bytes;
    while idx < UNITS.len() - 1 && value.abs() >= 1024.0 {
        value /= 1024.0;
        idx += 1;
    }
    format!("{}{}", format_sig_figs(value, 3), UNITS[idx])
}

/// Decimal prefixes for rates: B/s, KB/s, MB/s, GB/s.
fn format_rate_decimal(bps: f64) -> String {
    let abs = bps.abs();
    if abs >= 1e9 {
        format!("{}GB/s", format_sig_figs(bps / 1e9, 3))
    } else if abs >= 1e6 {
        format!("{}MB/s", format_sig_figs(bps / 1e6, 3))
    } else if abs >= 1e3 {
        format!("{}KB/s", format_sig_figs(bps / 1e3, 3))
    } else {
        format!("{}B/s", format_sig_figs(bps, 3))
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

/// Human-friendly representation of an X axis tick value using SI metric
/// prefixes, up to two decimal places, trailing zeros trimmed.
pub fn format_x_axis_tick(v: f64, max_width: usize) -> String {
    if v.is_nan() || v.is_infinite() {
        return String::new();
    }
    if v == 0.0 {
        return "0".to_string();
    }

    let (sign, mut v) = if v < 0.0 { ("-", -v) } else { ("", v) };

    let mut idx = 0;
    while idx + 1 < SCALES.len() && v >= SCALES[idx + 1].0 {
        idx += 1;
    }

    'scale: loop {
        let (factor, suffix) = SCALES[idx];
        let scaled = v / factor;

        for decimals in (0..=2usize).rev() {
            let num = trim_trailing_zeros(&format!("{scaled:.decimals$}"));

            // Rounding crossed into the next tier (e.g. 999.6k -> 1000k).
            if num == "1000" && idx + 1 < SCALES.len() {
                idx += 1;
                continue 'scale;
            }

            let out = format!("{sign}{num}{suffix}");
            if max_width == 0 || out.chars().count() <= max_width {
                return out;
            }
        }

        // Nothing fit; return minimum precision anyway.
        let _ = &mut v;
        return format!(
            "{sign}{}{suffix}",
            trim_trailing_zeros(&format!("{scaled:.0}", scaled = v / factor))
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn x_axis_ticks() {
        assert_eq!(format_x_axis_tick(42.0, 5), "42");
        assert_eq!(format_x_axis_tick(1234.0, 5), "1.23k");
        assert_eq!(format_x_axis_tick(-1234.0, 5), "-1.2k");
        assert_eq!(format_x_axis_tick(50000.0, 5), "50k");
        assert_eq!(format_x_axis_tick(1234567.0, 5), "1.23M");
        assert_eq!(format_x_axis_tick(0.0, 5), "0");
    }

    #[test]
    fn sig_figs() {
        assert_eq!(format_sig_figs(0.5, 3), "0.5");
        assert_eq!(format_sig_figs(1234.0, 3), "1.23e+03");
        assert_eq!(format_sig_figs(123.0, 3), "123");
        assert_eq!(format_sig_figs(0.000012345, 3), "1.23e-05");
        assert_eq!(format_sig_figs(12.345, 3), "12.3");
    }

    #[test]
    fn byte_units() {
        assert_eq!(UNIT_BYTES.format(1536.0), "1.5KiB");
        assert_eq!(UNIT_MIB.format(2048.0), "2GiB");
        assert_eq!(UNIT_BPS.format(1_500_000.0), "1.5MB/s");
        assert_eq!(UNIT_PERCENT.format(42.5), "42.5%");
        assert_eq!(UNIT_WATT.format(1500.0), "1.5kW");
        assert_eq!(UNIT_MHZ.format(2400.0), "2.4GHz");
    }
}
