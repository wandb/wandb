//! Chart geometry shared by every leet-gpui chart: axis scales, tick
//! placement, pixel-bucket decimation, and smoothing. Pure `f64` math with
//! no GUI dependency, so it is unit-testable and reusable from a wasm build.

/// A closed data interval.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Range {
    pub min: f64,
    pub max: f64,
}

impl Range {
    /// The extent of the finite values in `values`, or `None` when there are none.
    pub fn of(values: impl IntoIterator<Item = f64>) -> Option<Range> {
        let mut range: Option<Range> = None;
        for v in values.into_iter().filter(|v| v.is_finite()) {
            range = Some(match range {
                None => Range { min: v, max: v },
                Some(r) => Range {
                    min: r.min.min(v),
                    max: r.max.max(v),
                },
            });
        }
        range
    }

    /// The smallest range covering both.
    pub fn union(self, other: Range) -> Range {
        Range {
            min: self.min.min(other.min),
            max: self.max.max(other.max),
        }
    }

    /// Widens a degenerate range so that it can be mapped onto an axis.
    pub fn non_degenerate(self) -> Range {
        if self.max > self.min {
            return self;
        }
        let pad = if self.min == 0.0 {
            1.0
        } else {
            self.min.abs() * 0.1
        };
        Range {
            min: self.min - pad,
            max: self.max + pad,
        }
    }

    /// Adds `fraction` of the span on each side.
    pub fn padded(self, fraction: f64) -> Range {
        let pad = (self.max - self.min) * fraction;
        Range {
            min: self.min - pad,
            max: self.max + pad,
        }
    }

    pub fn span(self) -> f64 {
        self.max - self.min
    }
}

/// How data values map onto an axis.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum Scale {
    #[default]
    Linear,
    Log10,
}

impl Scale {
    /// Maps `v` in `range` onto `[0, 1]`. Callers ensure `range` is positive for `Log10`.
    pub fn normalize(self, range: Range, v: f64) -> f64 {
        match self {
            Scale::Linear => (v - range.min) / range.span(),
            Scale::Log10 => {
                (v.log10() - range.min.log10()) / (range.max.log10() - range.min.log10())
            }
        }
    }

    /// The inverse of [`Scale::normalize`].
    pub fn denormalize(self, range: Range, t: f64) -> f64 {
        match self {
            Scale::Linear => range.min + t * range.span(),
            Scale::Log10 => {
                let (lo, hi) = (range.min.log10(), range.max.log10());
                10f64.powf(lo + t * (hi - lo))
            }
        }
    }

    /// Tick positions inside `range`, roughly `count` of them.
    pub fn ticks(self, range: Range, count: usize) -> Vec<f64> {
        match self {
            Scale::Linear => linear_ticks(range, count),
            Scale::Log10 => log_ticks(range, count),
        }
    }
}

/// Heckbert's "nice numbers": a step of 1, 2, or 5 times a power of ten.
fn nice_step(span: f64, count: usize) -> f64 {
    let raw = span / count.max(1) as f64;
    let magnitude = 10f64.powf(raw.log10().floor());
    let fraction = raw / magnitude;
    let nice = if fraction < 1.5 {
        1.0
    } else if fraction < 3.0 {
        2.0
    } else if fraction < 7.0 {
        5.0
    } else {
        10.0
    };
    nice * magnitude
}

fn linear_ticks(range: Range, count: usize) -> Vec<f64> {
    if range.span() <= 0.0 || !range.span().is_finite() {
        return Vec::new();
    }
    let step = nice_step(range.span(), count);
    let first = (range.min / step).ceil() as i64;
    let last = (range.max / step).floor() as i64;
    let decimals = (-step.log10().floor()).max(0.0);
    let snap = 10f64.powf(decimals);
    (first..=last)
        .map(|i| (i as f64 * step * snap).round() / snap)
        .collect()
}

fn log_ticks(range: Range, count: usize) -> Vec<f64> {
    if range.min <= 0.0 || range.max <= range.min {
        return Vec::new();
    }
    let (lo, hi) = (
        range.min.log10().floor() as i32,
        range.max.log10().ceil() as i32,
    );
    let decades = (hi - lo).max(1) as usize;
    let mantissas: &[f64] = if decades <= count / 2 {
        &[1.0, 2.0, 5.0]
    } else {
        &[1.0]
    };
    let stride = (decades / count.max(1)).max(1) as i32;
    let mut ticks = Vec::new();
    let mut exp = lo;
    while exp <= hi {
        for m in mantissas {
            let v = m * 10f64.powi(exp);
            if v >= range.min && v <= range.max {
                ticks.push(v);
            }
        }
        exp += stride;
    }
    ticks
}

/// Formats `v` compactly for an axis label: SI suffixes above 10k, scientific
/// notation below 1e-3, at most four significant digits otherwise.
pub fn format_tick(v: f64) -> String {
    if v == 0.0 {
        return "0".to_string();
    }
    let a = v.abs();
    if a >= 1e4 {
        let (div, suffix) = if a >= 1e12 {
            (1e12, "T")
        } else if a >= 1e9 {
            (1e9, "G")
        } else if a >= 1e6 {
            (1e6, "M")
        } else {
            (1e3, "k")
        };
        return format!("{}{}", trim_zeros(&format!("{:.2}", v / div)), suffix);
    }
    if a < 1e-3 {
        return format!("{v:.1e}");
    }
    let digits = 3 - a.log10().floor().clamp(-3.0, 3.0) as i32;
    trim_zeros(&format!("{v:.*}", digits.max(0) as usize))
}

fn trim_zeros(s: &str) -> String {
    if !s.contains('.') {
        return s.to_string();
    }
    s.trim_end_matches('0').trim_end_matches('.').to_string()
}

/// A point of a series after decimation.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Point {
    pub x: f64,
    pub y: f64,
}

/// Reduces `(xs, ys)` to at most two points per pixel column over `x_range`:
/// the minimum and the maximum of each column, in x order, so spikes survive.
/// Non-finite values are dropped. Series shorter than the budget pass through.
pub fn decimate(xs: &[f64], ys: &[f64], x_range: Range, columns: usize) -> Vec<Point> {
    let n = xs.len().min(ys.len());
    let finite = |i: usize| xs[i].is_finite() && ys[i].is_finite();
    if n <= columns * 2 || x_range.span() <= 0.0 {
        return (0..n)
            .filter(|&i| finite(i))
            .map(|i| Point { x: xs[i], y: ys[i] })
            .collect();
    }
    let mut out: Vec<Point> = Vec::with_capacity(columns * 2 + 2);
    let mut column = usize::MAX;
    let mut lo = 0usize;
    let mut hi = 0usize;
    let flush = |out: &mut Vec<Point>, lo: usize, hi: usize| {
        let (a, b) = if lo <= hi { (lo, hi) } else { (hi, lo) };
        out.push(Point { x: xs[a], y: ys[a] });
        if a != b {
            out.push(Point { x: xs[b], y: ys[b] });
        }
    };
    for i in (0..n).filter(|&i| finite(i)) {
        let c = (((xs[i] - x_range.min) / x_range.span()) * columns as f64).floor() as usize;
        if c != column {
            if column != usize::MAX {
                flush(&mut out, lo, hi);
            }
            column = c;
            lo = i;
            hi = i;
            continue;
        }
        if ys[i] < ys[lo] {
            lo = i;
        }
        if ys[i] > ys[hi] {
            hi = i;
        }
    }
    if column != usize::MAX {
        flush(&mut out, lo, hi);
    }
    out
}

/// The index of the point whose x is nearest to `x` in an ascending `xs`.
pub fn nearest(xs: &[f64], x: f64) -> Option<usize> {
    if xs.is_empty() {
        return None;
    }
    let i = xs.partition_point(|&v| v < x);
    let candidates = [i.checked_sub(1), (i < xs.len()).then_some(i)];
    candidates
        .into_iter()
        .flatten()
        .min_by(|&a, &b| (xs[a] - x).abs().total_cmp(&(xs[b] - x).abs()))
}

/// Exponential moving average with the bias correction the W&B UI applies,
/// so the first points are not pulled toward zero. `weight` is in `[0, 1)`;
/// a weight of zero returns the input. Non-finite values are passed through
/// without moving the average.
pub fn ema(ys: &[f64], weight: f64) -> Vec<f64> {
    if weight <= 0.0 {
        return ys.to_vec();
    }
    let mut last = 0.0;
    let mut debias = 0.0;
    ys.iter()
        .map(|&y| {
            if !y.is_finite() {
                return y;
            }
            last = last * weight + (1.0 - weight) * y;
            debias = debias * weight + (1.0 - weight);
            last / debias
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn linear_ticks_are_nice_and_inside_the_range() {
        assert_eq!(
            Scale::Linear.ticks(Range { min: 0.0, max: 1.0 }, 5),
            vec![0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
        );
        assert_eq!(
            Scale::Linear.ticks(
                Range {
                    min: -3.0,
                    max: 17.0
                },
                4
            ),
            vec![0.0, 5.0, 10.0, 15.0]
        );
        assert!(
            Scale::Linear
                .ticks(Range { min: 2.0, max: 2.0 }, 4)
                .is_empty()
        );
    }

    #[test]
    fn log_ticks_are_decades() {
        assert_eq!(
            Scale::Log10.ticks(
                Range {
                    min: 0.001,
                    max: 1000.0
                },
                4
            ),
            vec![0.001, 0.01, 0.1, 1.0, 10.0, 100.0, 1000.0]
        );
        assert!(
            Scale::Log10
                .ticks(
                    Range {
                        min: -1.0,
                        max: 10.0
                    },
                    4
                )
                .is_empty()
        );
    }

    #[test]
    fn tick_labels_are_compact() {
        assert_eq!(format_tick(0.0), "0");
        assert_eq!(format_tick(12345.0), "12.35k");
        assert_eq!(format_tick(2_000_000.0), "2M");
        assert_eq!(format_tick(0.25), "0.25");
        assert_eq!(format_tick(3.0), "3");
        assert_eq!(format_tick(0.00004), "4.0e-5");
    }

    #[test]
    fn decimation_keeps_extremes_in_order() {
        let xs: Vec<f64> = (0..1000).map(f64::from).collect();
        let mut ys = vec![0.0; 1000];
        ys[500] = 100.0;
        ys[501] = -100.0;
        let points = decimate(
            &xs,
            &ys,
            Range {
                min: 0.0,
                max: 999.0,
            },
            10,
        );
        assert!(points.len() <= 20);
        assert!(points.windows(2).all(|w| w[0].x <= w[1].x));
        assert!(points.iter().any(|p| p.y == 100.0) && points.iter().any(|p| p.y == -100.0));
    }

    #[test]
    fn nearest_picks_the_closer_neighbor() {
        let xs = [0.0, 10.0, 20.0];
        assert_eq!(nearest(&xs, 4.0), Some(0));
        assert_eq!(nearest(&xs, 6.0), Some(1));
        assert_eq!(nearest(&xs, 99.0), Some(2));
        assert_eq!(nearest(&[], 1.0), None);
    }

    #[test]
    fn ema_is_debiased() {
        let smoothed = ema(&[1.0, 1.0, 1.0], 0.9);
        assert!(smoothed.iter().all(|v| (v - 1.0).abs() < 1e-12));
        assert_eq!(ema(&[1.0, 2.0], 0.0), vec![1.0, 2.0]);
    }
}
