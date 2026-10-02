//! Reimplementation of Go's `strconv.FormatFloat` for the formats leet
//! uses: `'g'` (significant digits, auto-scientific) and `'f'` (fixed
//! decimals). Axis labels and legends are formatted text — a one-character
//! difference shifts a whole gutter — so every float that reaches a frame
//! must go through this module, never through bare `format!`.
//!
//! Property-tested against a Go-generated dump in Phase 2 (see
//! docs/PARITY.md, unit-diff layer).

/// `strconv.FormatFloat(v, 'g', prec, 64)` for `prec >= 1`.
///
/// Go picks scientific notation when the decimal exponent is `< -4` or
/// `>= prec`, and always trims trailing zeros in 'g' mode.
pub fn format_float_g(v: f64, prec: usize) -> String {
    debug_assert!(prec >= 1);
    if v.is_nan() {
        return "NaN".to_string();
    }
    if v.is_infinite() {
        return if v > 0.0 {
            "+Inf".to_string()
        } else {
            "-Inf".to_string()
        };
    }
    if v == 0.0 {
        return "0".to_string();
    }

    let neg = v < 0.0;
    let abs = v.abs();

    // Round to `prec` significant digits via Rust's correctly-rounded
    // scientific formatting, then re-render in Go's chosen form. Using the
    // rounded digit string for both forms avoids double-rounding.
    let sci = format!("{:.*e}", prec - 1, abs); // e.g. "1.23e3", "1e0"
    let (mantissa, exp10) = split_scientific(&sci);
    let digits: String = mantissa.chars().filter(|c| c.is_ascii_digit()).collect();
    let digits = digits.trim_end_matches('0');
    let digits = if digits.is_empty() { "0" } else { digits };

    let mut out = String::new();
    if neg {
        out.push('-');
    }

    if exp10 < -4 || exp10 >= prec as i32 {
        // Scientific: d[.ddd]e±dd (exponent sign always, min two digits).
        out.push_str(&digits[..1]);
        if digits.len() > 1 {
            out.push('.');
            out.push_str(&digits[1..]);
        }
        out.push('e');
        if exp10 < 0 {
            out.push('-');
        } else {
            out.push('+');
        }
        let e = exp10.unsigned_abs();
        if e < 10 {
            out.push('0');
        }
        out.push_str(&e.to_string());
    } else if exp10 >= 0 {
        // Fixed with the decimal point inside/after the digit string.
        let int_len = (exp10 + 1) as usize;
        if digits.len() <= int_len {
            out.push_str(digits);
            for _ in digits.len()..int_len {
                out.push('0');
            }
        } else {
            out.push_str(&digits[..int_len]);
            out.push('.');
            out.push_str(&digits[int_len..]);
        }
    } else {
        // 0.0…digits
        out.push_str("0.");
        for _ in 0..(-exp10 - 1) {
            out.push('0');
        }
        out.push_str(digits);
    }
    out
}

/// `strconv.FormatFloat(v, 'f', decimals, 64)`.
pub fn format_float_f(v: f64, decimals: usize) -> String {
    if v.is_nan() {
        return "NaN".to_string();
    }
    if v.is_infinite() {
        return if v > 0.0 {
            "+Inf".to_string()
        } else {
            "-Inf".to_string()
        };
    }
    // Rust's `{:.N}` is correctly rounded from the binary value, matching Go.
    format!("{v:.decimals$}")
}

/// Parse Rust `{:e}` output like "1.23e3" / "5e-7" into (mantissa, exponent).
fn split_scientific(s: &str) -> (&str, i32) {
    let (m, e) = s
        .split_once('e')
        .expect("scientific format always has an exponent");
    (m, e.parse().expect("valid exponent"))
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Expectations produced by Go: strconv.FormatFloat(v, 'g', 3, 64).
    #[test]
    fn g_matches_go_prec3() {
        for (v, want) in [
            (0.0, "0"),
            (1.0, "1"),
            (-1.0, "-1"),
            (42.0, "42"),
            (1.5, "1.5"),
            (100.0, "100"),
            (999.0, "999"),
            (999.9, "1e+03"),
            (1000.0, "1e+03"),
            (1234.0, "1.23e+03"),
            (0.5, "0.5"),
            (0.05, "0.05"),
            (0.0005, "0.0005"),
            (0.00005, "5e-05"),
            (0.000123, "0.000123"),
            (0.0001234, "0.000123"),
            (1.234e20, "1.23e+20"),
            (-1234.0, "-1.23e+03"),
            #[expect(clippy::approx_constant, reason = "test vector, not a PI stand-in")]
            (3.14159, "3.14"),
            (2.5, "2.5"),
            (99.95, "100"), // binary 99.95 is 99.9500…028, above the tie
            (101.0, "101"),
            (0.1, "0.1"),
            (12.34, "12.3"),
        ] {
            assert_eq!(format_float_g(v, 3), want, "v={v}");
        }
    }

    /// Expectations produced by Go: strconv.FormatFloat(v, 'f', d, 64).
    #[test]
    fn f_matches_go() {
        for (v, d, want) in [
            (1.005, 2, "1.00"), // 1.005 in binary is 1.00499…
            (2.5, 0, "2"),
            (3.5, 0, "4"),
            (-1.5, 0, "-2"),
            (42.0, 2, "42.00"),
            (0.125, 2, "0.12"),
            (999.999, 2, "1000.00"),
        ] {
            assert_eq!(format_float_f(v, d), want, "v={v} d={d}");
        }
    }

    #[test]
    fn specials() {
        assert_eq!(format_float_g(f64::NAN, 3), "NaN");
        assert_eq!(format_float_g(f64::INFINITY, 3), "+Inf");
        assert_eq!(format_float_g(f64::NEG_INFINITY, 3), "-Inf");
        assert_eq!(format_float_f(f64::NAN, 2), "NaN");
    }
}
