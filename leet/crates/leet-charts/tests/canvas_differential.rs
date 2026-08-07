//! Canvas-dump differential: the Phase 3 exit gate for leet-charts.
//!
//! Regenerates the deterministic chart scenario table of the Go oracle
//! (`core/internal/leet/fixturegen/chartdump.go` — the SPEC for this file;
//! case names and construction are mirrored 1:1) through the Rust ports and
//! compares rune grids char-for-char against the committed golden produced
//! by the Go tool:
//!
//!     cd core && go run ./internal/leet/fixturegen -chartdump \
//!         > ../leet/fixtures/chartdump/golden.txt
//!
//! Go renders `View()` (ANSI stripped); the Rust ports render into
//! `Canvas` and dump `text_rows()` — the style-stripped equivalent
//! (docs/PORTING.md, Canvas render-target row).
//!
//! Known one-ULP divergences, if ever proven, are recorded in the golden
//! header as `# divergence: <case> <WxH> row=<r> col=<c> <note>` lines and
//! excluded cell-by-cell (never blanket-excluded).

use std::time::{Duration, UNIX_EPOCH};

use leet_charts::epoch_line_chart::{AxisScaleMode, EpochLineChart, MetricData};
use leet_charts::french_fries_chart::{FrenchFriesChart, FrenchFriesChartParams};
use leet_data::system_metrics::{MetricChartKind, MetricDef};
use leet_data::units::UNIT_PERCENT;

/// Go `chartDumpViewports`.
const CHART_DUMP_VIEWPORTS: [(i64, i64); 3] = [(36, 10), (60, 16), (100, 24)];

/// Go `chartDumpCases` (same names, same order).
const CHART_DUMP_CASES: [&str; 13] = [
    "linear-50",
    "noisy-sine-200",
    "nan-poisoned",
    "single-point",
    "flat",
    "overlay-two-series",
    "overlay-promoted",
    "zoom-in-x2",
    "zoom-then-pan",
    "logy-positive",
    "logy-rejected-mixed",
    "french-fries-3x40",
    "french-fries-single",
];

// --- chart constructors (Go chartdump.go equivalents) -----------------------

fn new_epoch_chart(title: &str, w: i64, h: i64) -> EpochLineChart {
    let mut c = EpochLineChart::new(title);
    c.resize(w, h);
    c
}

fn render_epoch(c: &mut EpochLineChart) -> Vec<String> {
    c.draw();
    c.canvas.text_rows()
}

fn french_fries_def() -> MetricDef {
    // Go: &leet.MetricDef{Name: "GPU Utilization", Unit: leet.UnitPercent,
    // MinY: 0, MaxY: 100, Percentage: true} — omitted fields keep Go zero
    // values.
    MetricDef {
        name: "GPU Utilization".to_string(),
        unit: UNIT_PERCENT,
        min_y: 0.0,
        max_y: 100.0,
        percentage: true,
        auto_range: false,
        chart_kind: MetricChartKind::Line,
        regex: None,
    }
}

fn new_french_fries_chart(w: i64, h: i64) -> FrenchFriesChart {
    FrenchFriesChart::new(&FrenchFriesChartParams {
        width: w,
        height: h,
        def: &french_fries_def(),
        colors: &[],
        now: UNIX_EPOCH + Duration::from_secs(1_700_000_000),
    })
}

// --- closed-form data (Go chartdump.go, explicit temporaries) ---------------

/// Go `parabolaSine`: deterministic sine-like wave over phase p in [0, 1).
fn parabola_sine(p: f64) -> f64 {
    if p < 0.5 {
        let a = p * (0.5 - p);
        return 16.0 * a;
    }
    let a = (p - 0.5) * (1.0 - p);
    -16.0 * a
}

fn linear_data(n: usize) -> MetricData {
    let mut d = MetricData {
        x: vec![0.0; n],
        y: vec![0.0; n],
    };
    for i in 0..n {
        let x = i as f64;
        let t = 0.35 * x;
        let y = t + 2.0;
        d.x[i] = x;
        d.y[i] = y;
    }
    d
}

fn noisy_sine_data(n: usize) -> MetricData {
    let mut d = MetricData {
        x: vec![0.0; n],
        y: vec![0.0; n],
    };
    for i in 0..n {
        let x = i as f64;
        let p = (i % 40) as f64 / 40.0;
        let s = parabola_sine(p);
        let q = ((i * 7) % 23) as f64 / 23.0;
        let wob = parabola_sine(q);
        let t1 = s * 10.0;
        let t2 = wob * 1.5;
        let amp = 1.0 + i as f64 / 400.0;
        let base = t1 + t2;
        let scaled = base * amp;
        let y = scaled + 12.0;
        d.x[i] = x;
        d.y[i] = y;
    }
    d
}

fn nan_poisoned_data(n: usize) -> MetricData {
    let mut d = linear_data(n);
    for i in 0..n {
        if i % 7 == 3 {
            d.y[i] = f64::NAN;
        } else if i == 20 {
            d.y[i] = f64::INFINITY;
        } else if i == 35 {
            d.y[i] = f64::NEG_INFINITY;
        }
    }
    d
}

fn flat_data(n: usize, v: f64) -> MetricData {
    let mut d = MetricData {
        x: vec![0.0; n],
        y: vec![0.0; n],
    };
    for i in 0..n {
        d.x[i] = i as f64;
        d.y[i] = v;
    }
    d
}

fn overlay_train_data(n: usize) -> MetricData {
    let mut d = MetricData {
        x: vec![0.0; n],
        y: vec![0.0; n],
    };
    for i in 0..n {
        let x = i as f64;
        let t = 0.5 * x;
        let y = t + 1.0;
        d.x[i] = x;
        d.y[i] = y;
    }
    d
}

fn overlay_val_data(n: usize) -> MetricData {
    let mut d = MetricData {
        x: vec![0.0; n],
        y: vec![0.0; n],
    };
    for i in 0..n {
        let x = i as f64;
        let t = 0.4 * x;
        let y = 30.0 - t;
        d.x[i] = x;
        d.y[i] = y;
    }
    d
}

fn log_positive_data(n: usize) -> MetricData {
    let mut d = MetricData {
        x: vec![0.0; n],
        y: vec![0.0; n],
    };
    for i in 0..n {
        d.x[i] = i as f64;
        d.y[i] = 1000.0 / (i + 1) as f64;
    }
    d
}

fn log_rejected_data(n: usize) -> MetricData {
    let mut d = MetricData {
        x: vec![0.0; n],
        y: vec![0.0; n],
    };
    for i in 0..n {
        d.x[i] = i as f64;
        d.y[i] = match i % 3 {
            0 => -5.0,
            1 => 0.0,
            _ => f64::NAN,
        };
    }
    d
}

fn french_fries_value(i: i64, g: i64) -> f64 {
    let p = ((i + g * 13) % 40) as f64 / 40.0;
    let s = parabola_sine(p);
    let t = s * 45.0;
    50.0 + t
}

fn french_fries_single_value(i: i64) -> f64 {
    let p = (i % 25) as f64 / 25.0;
    let s = parabola_sine(p);
    let t = s * 25.0;
    30.0 + t
}

// --- case rendering ----------------------------------------------------------

/// Mirrors Go `chartDumpCases[name].render(w, h)` + ANSI strip: returns the
/// rune-grid rows.
fn render_case(name: &str, w: i64, h: i64) -> Vec<String> {
    match name {
        "linear-50" => {
            let mut c = new_epoch_chart("loss", w, h);
            c.add_data("loss", linear_data(50));
            render_epoch(&mut c)
        }
        "noisy-sine-200" => {
            let mut c = new_epoch_chart("accuracy", w, h);
            c.add_data("accuracy", noisy_sine_data(200));
            render_epoch(&mut c)
        }
        "nan-poisoned" => {
            let mut c = new_epoch_chart("loss", w, h);
            c.add_data("loss", nan_poisoned_data(50));
            render_epoch(&mut c)
        }
        "single-point" => {
            let mut c = new_epoch_chart("loss", w, h);
            c.add_data(
                "loss",
                MetricData {
                    x: vec![5.0],
                    y: vec![3.7],
                },
            );
            render_epoch(&mut c)
        }
        "flat" => {
            let mut c = new_epoch_chart("loss", w, h);
            c.add_data("loss", flat_data(30, 42.0));
            render_epoch(&mut c)
        }
        "overlay-two-series" => {
            let mut c = new_epoch_chart("metrics", w, h);
            c.add_data("train", overlay_train_data(60));
            c.add_data("val", overlay_val_data(60));
            render_epoch(&mut c)
        }
        "overlay-promoted" => {
            let mut c = new_epoch_chart("metrics", w, h);
            c.add_data("train", overlay_train_data(60));
            c.add_data("val", overlay_val_data(60));
            c.promote_series_to_top("train");
            render_epoch(&mut c)
        }
        "zoom-in-x2" => {
            let mut c = new_epoch_chart("loss", w, h);
            c.add_data("loss", linear_data(50));
            let gw = c.graph_width();
            c.handle_zoom("in", gw / 2);
            c.handle_zoom("in", gw / 2);
            render_epoch(&mut c)
        }
        "zoom-then-pan" => {
            let mut c = new_epoch_chart("loss", w, h);
            c.add_data("loss", linear_data(50));
            let gw = c.graph_width();
            c.handle_zoom("in", gw / 2);
            c.handle_zoom("in", gw / 2);
            // Pan left by a quarter of the zoomed view span (Go: explicit
            // temporaries; SetViewXRange is the exported linechart API).
            let vmin = c.view_min_x();
            let vmax = c.view_max_x();
            let span = vmax - vmin;
            let shift = span * 0.25;
            let new_min = vmin - shift;
            let new_max = vmax - shift;
            c.set_view_x_range(new_min, new_max);
            render_epoch(&mut c)
        }
        "logy-positive" => {
            let mut c = new_epoch_chart("lr", w, h);
            c.add_data("lr", log_positive_data(40));
            c.set_y_scale(AxisScaleMode::Log);
            render_epoch(&mut c)
        }
        "logy-rejected-mixed" => {
            let mut c = new_epoch_chart("delta", w, h);
            c.add_data("delta", log_rejected_data(20));
            // No strictly positive sample: set_y_scale must reject and the
            // chart must render linear.
            assert!(
                !c.set_y_scale(AxisScaleMode::Log),
                "logy-rejected-mixed: log scale unexpectedly accepted"
            );
            render_epoch(&mut c)
        }
        "french-fries-3x40" => {
            let mut c = new_french_fries_chart(w, h);
            let base: i64 = 1_700_000_000;
            for i in 0..40 {
                let ts = base + i * 30;
                for g in 0..3 {
                    c.add_data_point(&format!("GPU {g}"), ts, french_fries_value(i, g));
                }
            }
            // Widen the bucketing window to the full sample range (see the
            // Go tool's comment).
            c.set_view_window(base as f64, (base + 39 * 30) as f64);
            c.view().text_rows()
        }
        "french-fries-single" => {
            let mut c = new_french_fries_chart(w, h);
            let base: i64 = 1_700_000_000;
            for i in 0..25 {
                let ts = base + i * 60;
                c.add_data_point("", ts, french_fries_single_value(i));
            }
            c.set_view_window(base as f64, (base + 24 * 60) as f64);
            c.view().text_rows()
        }
        _ => panic!("unknown chartdump case {name:?}"),
    }
}

// --- golden parsing ----------------------------------------------------------

struct GoldenSection {
    case_name: String,
    w: i64,
    h: i64,
    rows: Vec<String>,
}

/// A cell excluded as a recorded known-divergence
/// (`# divergence: <case> <WxH> row=<r> col=<c> <note>`).
#[derive(PartialEq)]
struct DivergentCell {
    case_name: String,
    w: i64,
    h: i64,
    row: usize,
    col: usize,
}

fn parse_viewport(s: &str) -> (i64, i64) {
    let (w, h) = s
        .split_once('x')
        .unwrap_or_else(|| panic!("bad viewport {s:?}"));
    (w.parse().unwrap(), h.parse().unwrap())
}

fn parse_golden(text: &str) -> (Vec<GoldenSection>, Vec<DivergentCell>) {
    let mut sections = Vec::new();
    let mut divergences = Vec::new();
    let mut lines = text.lines().peekable();

    while let Some(line) = lines.next() {
        if let Some(rest) = line.strip_prefix("# divergence: ") {
            let toks: Vec<&str> = rest.split_whitespace().collect();
            assert!(toks.len() >= 4, "bad divergence line {line:?}");
            let (w, h) = parse_viewport(toks[1]);
            let row = toks[2].strip_prefix("row=").unwrap().parse().unwrap();
            let col = toks[3].strip_prefix("col=").unwrap().parse().unwrap();
            divergences.push(DivergentCell {
                case_name: toks[0].to_string(),
                w,
                h,
                row,
                col,
            });
            continue;
        }
        if line.starts_with('#') || line.is_empty() {
            continue;
        }

        // "=== case <name> viewport <W>x<H> ==="
        let toks: Vec<&str> = line.split_whitespace().collect();
        assert!(
            toks.len() == 6 && toks[0] == "===" && toks[1] == "case" && toks[3] == "viewport",
            "unexpected golden line {line:?}"
        );
        let (w, h) = parse_viewport(toks[4]);
        let mut rows = Vec::with_capacity(h as usize);
        for _ in 0..h {
            rows.push(
                lines
                    .next()
                    .unwrap_or_else(|| panic!("golden truncated inside case {:?}", toks[2]))
                    .to_string(),
            );
        }
        sections.push(GoldenSection {
            case_name: toks[2].to_string(),
            w,
            h,
            rows,
        });
    }
    (sections, divergences)
}

// --- the differential --------------------------------------------------------

#[test]
fn canvas_differential_matches_go_golden() {
    let golden_path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../fixtures/chartdump/golden.txt"
    );
    let text = std::fs::read_to_string(golden_path)
        .unwrap_or_else(|e| panic!("reading {golden_path}: {e}"));
    let (sections, divergences) = parse_golden(&text);

    // The golden must cover exactly the case table (guards a stale golden).
    let want_sections: Vec<(String, i64, i64)> = CHART_DUMP_CASES
        .iter()
        .flat_map(|name| {
            CHART_DUMP_VIEWPORTS
                .iter()
                .map(|&(w, h)| (name.to_string(), w, h))
        })
        .collect();
    let got_sections: Vec<(String, i64, i64)> = sections
        .iter()
        .map(|s| (s.case_name.clone(), s.w, s.h))
        .collect();
    assert_eq!(
        got_sections, want_sections,
        "golden case table out of date; regenerate (see file header)"
    );

    let mut failures = Vec::new();
    for section in &sections {
        let got = render_case(&section.case_name, section.w, section.h);
        if got.len() != section.rows.len() {
            failures.push(format!(
                "case {} viewport {}x{}: row count mismatch: go {} rust {}",
                section.case_name,
                section.w,
                section.h,
                section.rows.len(),
                got.len()
            ));
            continue;
        }
        let mut diffs = Vec::new();
        for (r, (want_row, got_row)) in section.rows.iter().zip(got.iter()).enumerate() {
            if want_row == got_row {
                continue;
            }
            let want_chars: Vec<char> = want_row.chars().collect();
            let got_chars: Vec<char> = got_row.chars().collect();
            let n = want_chars.len().max(got_chars.len());
            for c in 0..n {
                let wc = want_chars.get(c).copied().unwrap_or(' ');
                let gc = got_chars.get(c).copied().unwrap_or(' ');
                if wc == gc {
                    continue;
                }
                let excluded = DivergentCell {
                    case_name: section.case_name.clone(),
                    w: section.w,
                    h: section.h,
                    row: r,
                    col: c,
                };
                if divergences.contains(&excluded) {
                    continue;
                }
                diffs.push(format!("  row {r} col {c}: go {wc:?} rust {gc:?}"));
            }
            if !diffs.is_empty() && diffs.len() <= 200 {
                diffs.push(format!("  go   row {r}: {want_row:?}"));
                diffs.push(format!("  rust row {r}: {got_row:?}"));
            }
        }
        if !diffs.is_empty() {
            failures.push(format!(
                "case {} viewport {}x{}:\n{}",
                section.case_name,
                section.w,
                section.h,
                diffs.join("\n")
            ));
        }
    }

    assert!(
        failures.is_empty(),
        "canvas differential mismatches:\n{}",
        failures.join("\n\n")
    );
}
