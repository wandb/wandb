//! A run as the UI sees it: metric and system series with the caches that
//! keep painting cheap (running extents, incremental smoothing, decimated
//! polylines), console lines, and the overview metadata.

use std::collections::BTreeMap;

use leet_data::run_overview::{self, RunOverview};
use leet_ingest::{Batch, ColumnSet, ConsoleLine, RunInfo};
use leet_plot::{Point, Range, decimate, nearest};

use crate::source::RunDir;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RunState {
    Unknown,
    Loading,
    Running,
    Finished,
    Failed,
}

/// Running min and max of the finite values seen, plus the smallest positive
/// one for log axes.
#[derive(Debug, Clone, Copy, Default)]
pub struct Extent {
    range: Option<Range>,
    min_positive: Option<f64>,
}

impl Extent {
    fn add(&mut self, v: f64) {
        if !v.is_finite() {
            return;
        }
        self.range = Some(match self.range {
            None => Range { min: v, max: v },
            Some(r) => Range {
                min: r.min.min(v),
                max: r.max.max(v),
            },
        });
        if v > 0.0 && self.min_positive.is_none_or(|m| v < m) {
            self.min_positive = Some(v);
        }
    }

    /// The range to plot; on a log axis only the positive values count.
    pub fn range(&self, log: bool) -> Option<Range> {
        let range = self.range?;
        if log {
            return Some(Range {
                min: self.min_positive?,
                max: range.max,
            });
        }
        Some(range)
    }
}

#[derive(Default)]
struct Smooth {
    weight: f64,
    y: Vec<f64>,
    last: f64,
    debias: f64,
    extent: Extent,
}

impl Smooth {
    /// Extends the smoothed values to cover all of `y`; the state carries the
    /// average so appends cost only the new points.
    fn extend(&mut self, y: &[f64]) {
        for &v in &y[self.y.len()..] {
            if v.is_finite() {
                self.last = self.last * self.weight + (1.0 - self.weight) * v;
                self.debias = self.debias * self.weight + (1.0 - self.weight);
                let s = self.last / self.debias;
                self.extent.add(s);
                self.y.push(s);
            } else {
                self.y.push(v);
            }
        }
    }

    fn ensure(&mut self, weight: f64, y: &[f64]) {
        if self.weight != weight {
            *self = Smooth {
                weight,
                ..Default::default()
            };
        }
        self.extend(y);
    }
}

struct Decimated {
    len: usize,
    weight: f64,
    x_range: Range,
    columns: usize,
    points: Vec<Point>,
}

#[derive(Default)]
pub struct Series {
    pub x: Vec<f64>,
    pub y: Vec<f64>,
    pub x_extent: Extent,
    y_extent: Extent,
    smooth: Smooth,
    decimated: Option<Decimated>,
    raw: Option<Decimated>,
}

fn refresh(
    slot: &mut Option<Decimated>,
    len: usize,
    weight: f64,
    x_range: Range,
    columns: usize,
    build: impl FnOnce() -> Vec<Point>,
) -> &[Point] {
    let fresh = slot.as_ref().is_some_and(|d| {
        d.len == len && d.weight == weight && d.x_range == x_range && d.columns == columns
    });
    if !fresh {
        *slot = Some(Decimated {
            len,
            weight,
            x_range,
            columns,
            points: build(),
        });
    }
    &slot.as_ref().expect("decimation was just refreshed").points
}

impl Series {
    fn extend(&mut self, x: &[f64], y: &[f64]) {
        self.x.extend_from_slice(x);
        self.y.extend_from_slice(y);
        x.iter().for_each(|&v| self.x_extent.add(v));
        y.iter().for_each(|&v| self.y_extent.add(v));
    }

    /// The extent of the values as plotted with `weight` smoothing.
    pub fn y_extent(&mut self, weight: f64) -> Extent {
        if weight <= 0.0 {
            return self.y_extent;
        }
        self.smooth.ensure(weight, &self.y);
        self.smooth.extent
    }

    /// The polyline for `x_range` at `columns` pixels, reused across frames
    /// until the series grows or the view changes.
    pub fn decimated(&mut self, weight: f64, x_range: Range, columns: usize) -> &[Point] {
        let ys = if weight <= 0.0 {
            &self.y
        } else {
            self.smooth.ensure(weight, &self.y);
            &self.smooth.y
        };
        let (x, len) = (&self.x, self.y.len());
        refresh(&mut self.decimated, len, weight, x_range, columns, || {
            decimate(x, ys, x_range, columns)
        })
    }

    /// The raw polyline, for ghosting under a smoothed one.
    pub fn raw(&mut self, x_range: Range, columns: usize) -> &[Point] {
        let (x, y) = (&self.x, &self.y);
        refresh(&mut self.raw, y.len(), 0.0, x_range, columns, || {
            decimate(x, y, x_range, columns)
        })
    }

    /// The point nearest to `x`, with its value as plotted.
    pub fn nearest(&mut self, weight: f64, x: f64) -> Option<(f64, f64)> {
        let i = nearest(&self.x, x)?;
        let y = if weight <= 0.0 {
            self.y[i]
        } else {
            self.smooth.ensure(weight, &self.y);
            self.smooth.y[i]
        };
        Some((self.x[i], y))
    }
}

/// Series addressed by name and by the ingest key id.
#[derive(Default)]
pub struct Table {
    pub by_name: BTreeMap<String, usize>,
    pub series: Vec<Series>,
}

impl Table {
    fn extend(&mut self, set: &ColumnSet) {
        for key in set.new_keys.iter().cloned() {
            self.by_name.insert(key, self.series.len());
            self.series.push(Series::default());
        }
        for column in &set.columns {
            let (x, y) = set.slices(column);
            self.series[column.key].extend(x, y);
        }
    }
}

pub struct Run {
    pub dir: RunDir,
    pub name: String,
    pub state: RunState,
    pub color: usize,
    pub metrics: Table,
    pub system: Table,
    pub console: Vec<ConsoleLine>,
    pub overview: RunOverview,
    pub reading: bool,
}

impl Run {
    pub fn new(dir: RunDir) -> Self {
        Run {
            name: dir.id.clone(),
            dir,
            state: RunState::Unknown,
            color: 0,
            metrics: Table::default(),
            system: Table::default(),
            console: Vec::new(),
            overview: RunOverview::new(),
            reading: false,
        }
    }

    pub fn apply_info(&mut self, info: RunInfo) {
        if !info.display_name.is_empty() {
            self.name = info.display_name.clone();
        }
        self.overview.process_run_msg(run_overview::RunMsg {
            run_path: String::new(),
            id: info.id,
            project: info.project,
            display_name: info.display_name,
            notes: info.notes,
            tags: info.tags,
            config: info.config,
        });
    }

    pub fn apply(&mut self, batch: &mut Batch) {
        if let Some(info) = batch.run.take() {
            self.apply_info(info);
        }
        if let Some(environment) = &batch.environment {
            self.overview.process_system_info_msg(Some(environment));
        }
        if !batch.summary.is_empty() {
            self.overview
                .process_summary_msg(&std::mem::take(&mut batch.summary));
        }
        self.metrics.extend(&batch.metrics);
        self.system.extend(&batch.system);
        self.console.append(&mut batch.console);

        self.state = match (self.state, batch.exit_code, batch.caught_up) {
            (_, Some(0), _) => RunState::Finished,
            (_, Some(_), _) => RunState::Failed,
            (RunState::Finished | RunState::Failed, None, _) => self.state,
            (_, None, true) => RunState::Running,
            (RunState::Unknown, None, false) => RunState::Loading,
            (state, None, false) => state,
        };
        self.overview.set_run_state(match self.state {
            RunState::Unknown | RunState::Loading => run_overview::RunState::Unknown,
            RunState::Running => run_overview::RunState::Running,
            RunState::Finished => run_overview::RunState::Finished,
            RunState::Failed => run_overview::RunState::Failed,
        });
    }
}
