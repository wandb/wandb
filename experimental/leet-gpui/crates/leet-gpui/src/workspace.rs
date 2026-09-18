//! The workspace view. State and key handling follow
//! `core/internal/leet/workspace.go` and `workspacehandlers.go`; the layout
//! follows its `computeViewports`: runs sidebar, a central column of metrics
//! over a lower tier of system metrics and console logs, the overview sidebar,
//! and a status bar.

use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::path::PathBuf;
use std::time::Duration;

use futures::StreamExt;
use futures::channel::mpsc;
use gpui::prelude::*;
use gpui::{
    Context, Div, FocusHandle, KeyDownEvent, ScrollStrategy, UniformListScrollHandle, Window, div,
    hsla, px,
};
use leet_data::system_metrics::{
    MetricDef, extract_base_key, extract_series_name, match_metric_def,
};
use leet_plot::{Range, Scale};

use crate::actions::{self, *};
use crate::chart::{ChartData, ChartSpec, SeriesDraw, SeriesRef, Table, XAxis};
use crate::config::{Config, ConfigFile};
use crate::console::render_console;
use crate::dir_state::DirState;
use crate::grid::{Cell, Grid, GridView, render_grid};
use crate::overview::{self, render_overview};
use crate::run::{Run, RunState, Series};
use crate::runs_list::{render_runs, state_glyph};
use crate::source::{self, RunDir};
use crate::theme;

const SMOOTHING: [f64; 4] = [0.0, 0.6, 0.9, 0.99];
const RESCAN_INTERVAL: Duration = Duration::from_secs(5);
const LIST_PAGE: usize = 20;
const STATUS_BAR_HEIGHT: f32 = 24.;
/// Share of the central column below the metrics grid (`LowerTierRatio`).
const LOWER_TIER: f32 = 0.382;
const LEFT_SIDEBAR: f32 = 0.2;
const RIGHT_SIDEBAR: f32 = 0.22;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Pane {
    Runs,
    Metrics,
    System,
    Console,
    Overview,
}

const PANES: [Pane; 5] = [
    Pane::Runs,
    Pane::Metrics,
    Pane::System,
    Pane::Console,
    Pane::Overview,
];

/// One system chart: a base key such as `gpu.memory`, its definition, and
/// the `(series name, series index)` pairs of the devices reporting it.
struct SystemGroup {
    base: String,
    def: &'static MetricDef,
    series: Vec<(String, usize)>,
}

#[derive(Default)]
pub struct Filter {
    pub text: String,
    pub editing: bool,
}

impl Filter {
    fn saved(text: String) -> Self {
        Filter {
            text,
            editing: false,
        }
    }

    pub fn matches(&self, candidate: &str) -> bool {
        self.text.is_empty() || candidate.to_lowercase().contains(&self.text.to_lowercase())
    }
}

#[derive(Default)]
pub struct Filters {
    pub runs: Filter,
    pub metrics: Filter,
    pub system: Filter,
    pub console: Filter,
    pub overview: Filter,
}

pub struct Workspace {
    pub focus_handle: FocusHandle,
    pub runs: Vec<Run>,
    pub cursor: usize,
    pub selected: BTreeSet<String>,
    pub pinned: Option<String>,
    pub focus: Pane,
    pub filters: Filters,
    pub runs_scroll: UniformListScrollHandle,
    pub console_scroll: UniformListScrollHandle,
    pub overview_scroll: UniformListScrollHandle,
    /// `None` follows new output.
    pub console_cursor: Option<usize>,
    pub overview_cursor: usize,
    wandb_dir: PathBuf,
    help: actions::Help,
    config: ConfigFile,
    dir_state: DirState,
    show_runs: bool,
    metrics_grid: Grid,
    system_grid: Grid,
    metrics_log: BTreeSet<String>,
    system_log: BTreeSet<String>,
    smoothing: usize,
    show_help: bool,
}

impl Workspace {
    pub fn new(
        wandb_dir: PathBuf,
        run: Option<String>,
        help: actions::Help,
        config: ConfigFile,
        cx: &mut Context<Self>,
    ) -> Self {
        let dir_state = DirState::load(&wandb_dir);
        let filters = Filters {
            runs: Filter::saved(dir_state.filter("runs_filter")),
            metrics: Filter::saved(dir_state.filter("metrics_filter")),
            system: Filter::saved(dir_state.filter("system_metrics_filter")),
            console: Filter::saved(dir_state.filter("console_filter")),
            overview: Filter::saved(dir_state.filter("overview_filter")),
        };
        let smoothing = SMOOTHING
            .iter()
            .position(|w| *w == config.config.smoothing)
            .unwrap_or(0);
        let mut workspace = Self {
            focus_handle: cx.focus_handle(),
            runs: Vec::new(),
            cursor: 0,
            selected: BTreeSet::new(),
            pinned: None,
            focus: Pane::Runs,
            filters,
            runs_scroll: UniformListScrollHandle::new(),
            console_scroll: UniformListScrollHandle::new(),
            overview_scroll: UniformListScrollHandle::new(),
            console_cursor: None,
            overview_cursor: 0,
            wandb_dir,
            help,
            metrics_grid: Grid::new(config.config.workspace_metrics_grid),
            system_grid: Grid::new(config.config.workspace_system_grid),
            config,
            dir_state,
            show_runs: true,
            metrics_log: BTreeSet::new(),
            system_log: BTreeSet::new(),
            smoothing,
            show_help: false,
        };
        workspace.rescan(cx);

        let names: HashSet<String> = workspace
            .runs
            .iter()
            .map(|r| r.dir.dir_name.clone())
            .collect();
        let latest = workspace.runs.first().map(|r| r.dir.dir_name.clone());
        let mut initial: Vec<String> = workspace
            .dir_state
            .selected_runs()
            .into_iter()
            .filter(|name| names.contains(name))
            .collect();
        if let Some(latest) = &latest
            && workspace.dir_state.latest_run().as_deref() != Some(latest)
        {
            initial.push(latest.clone());
        }
        if let Some(pinned) = workspace
            .dir_state
            .pinned_run()
            .filter(|p| names.contains(p))
        {
            workspace.pinned = Some(pinned);
        }
        if let Some(run) = &run {
            initial.push(run.clone());
        }
        for name in initial {
            workspace.select(&name, cx);
        }
        let cursor_run = run.or_else(|| workspace.pinned.clone()).or(latest);
        let cursor = cursor_run
            .and_then(|name| workspace.runs.iter().position(|r| r.dir.dir_name == name))
            .unwrap_or(0);
        workspace.set_cursor(cursor);
        workspace.save_selection();

        cx.spawn(async move |this, cx| {
            loop {
                cx.background_executor().timer(RESCAN_INTERVAL).await;
                if this
                    .update(cx, |workspace, cx| workspace.rescan(cx))
                    .is_err()
                {
                    return;
                }
            }
        })
        .detach();
        workspace
    }

    fn cfg(&self) -> &Config {
        &self.config.config
    }

    pub fn smoothing_weight(&self) -> f64 {
        SMOOTHING[self.smoothing]
    }

    pub fn selected_runs(&self) -> impl Iterator<Item = (usize, &Run)> {
        self.runs
            .iter()
            .enumerate()
            .filter(|(_, run)| self.selected.contains(&run.dir.dir_name))
    }

    /// The run the overview, system, and console panes show: the pinned run,
    /// else the run under the cursor.
    pub fn context_run(&self) -> Option<usize> {
        if let Some(pinned) = &self.pinned
            && let Some(ix) = self.runs.iter().position(|r| &r.dir.dir_name == pinned)
        {
            return Some(ix);
        }
        self.visible().get(self.cursor).copied()
    }

    fn run_index(&self, dir_name: &str) -> Option<usize> {
        self.runs
            .iter()
            .position(|run| run.dir.dir_name == dir_name)
    }

    fn rescan(&mut self, cx: &mut Context<Self>) {
        let known: HashSet<String> = self
            .runs
            .iter()
            .map(|run| run.dir.dir_name.clone())
            .collect();
        let added: Vec<RunDir> = source::scan(&self.wandb_dir)
            .into_iter()
            .filter(|run| !known.contains(&run.dir_name))
            .collect();
        if added.is_empty() {
            return;
        }
        let cursor_run = self
            .visible()
            .get(self.cursor)
            .map(|&ix| self.runs[ix].dir.dir_name.clone());
        let probe: Vec<(String, PathBuf)> = added
            .iter()
            .map(|run| (run.dir_name.clone(), run.wandb_file.clone()))
            .collect();
        self.runs.extend(added.into_iter().map(Run::new));
        self.runs
            .sort_by(|a, b| b.dir.dir_name.cmp(&a.dir.dir_name));
        if let Some(name) = cursor_run {
            let visible = self.visible();
            self.cursor = visible
                .iter()
                .position(|&ix| self.runs[ix].dir.dir_name == name)
                .unwrap_or(0);
        }

        let (tx, mut rx) = mpsc::unbounded();
        source::spawn_probe(probe, tx);
        cx.spawn(async move |this, cx| {
            while let Some((name, info)) = rx.next().await {
                let applied = this.update(cx, |workspace, cx| {
                    if let Some(ix) = workspace.run_index(&name) {
                        workspace.runs[ix].apply_info(info);
                    }
                    cx.notify();
                });
                if applied.is_err() {
                    return;
                }
            }
        })
        .detach();
        cx.notify();
    }

    fn select(&mut self, dir_name: &str, cx: &mut Context<Self>) {
        let Some(ix) = self.run_index(dir_name) else {
            return;
        };
        let used: HashSet<usize> = self.selected_runs().map(|(_, run)| run.color).collect();
        let color = (0..).find(|c| !used.contains(c)).unwrap_or(0);
        self.selected.insert(dir_name.to_string());
        let run = &mut self.runs[ix];
        run.color = color;
        if run.reading {
            return;
        }
        run.reading = true;
        if run.state == RunState::Unknown {
            run.state = RunState::Loading;
        }
        let (tx, mut rx) = mpsc::unbounded();
        source::spawn_follow(&run.dir, tx);
        let dir_name = dir_name.to_string();
        cx.spawn(async move |this, cx| {
            while let Some(batch) = rx.next().await {
                let applied = this.update(cx, |workspace, cx| {
                    if let Some(ix) = workspace.run_index(&dir_name) {
                        workspace.runs[ix].apply(batch);
                    }
                    cx.notify();
                });
                if applied.is_err() {
                    return;
                }
            }
        })
        .detach();
    }

    fn save_selection(&mut self) {
        let latest = self.runs.first().map(|run| run.dir.dir_name.clone());
        self.dir_state
            .set_selection(&self.selected, self.pinned.as_deref(), latest.as_deref());
    }

    fn save_config(&self) {
        self.config.save();
    }

    /// Indices of the runs that pass the runs filter, newest first.
    pub fn visible(&self) -> Vec<usize> {
        self.runs
            .iter()
            .enumerate()
            .filter(|(_, run)| {
                self.filters.runs.matches(&run.name) || self.filters.runs.matches(&run.dir.id)
            })
            .map(|(ix, _)| ix)
            .collect()
    }

    /// Metric names charted for the selected runs, after the metrics filter.
    fn metric_names(&self) -> Vec<&str> {
        let mut names = BTreeSet::new();
        for (_, run) in self.selected_runs() {
            names.extend(
                run.metrics
                    .by_name
                    .keys()
                    .map(String::as_str)
                    .filter(|k| self.filters.metrics.matches(k)),
            );
        }
        names.into_iter().collect()
    }

    fn metric_cells(&self) -> (usize, Vec<Cell>) {
        let names = self.metric_names();
        let per_page = self.metrics_grid.per_page();
        let start = self
            .metrics_grid
            .page
            .min(self.metrics_grid.pages(names.len()) - 1)
            * per_page;
        let cells = names
            .iter()
            .skip(start)
            .take(per_page)
            .map(|name| {
                let log = self.metrics_log.contains(*name);
                let series = self
                    .selected_runs()
                    .filter_map(|(ix, run)| {
                        Some(SeriesRef {
                            run: ix,
                            table: Table::Metrics,
                            series: *run.metrics.by_name.get(*name)?,
                            name: run.name.clone().into(),
                            color: theme::run_color(run.color),
                        })
                    })
                    .collect();
                Cell {
                    title: name.to_string().into(),
                    badge: log.then_some("log"),
                    spec: ChartSpec {
                        x_axis: XAxis::Step,
                        log,
                        fixed_y: None,
                        series,
                    },
                }
            })
            .collect();
        (names.len(), cells)
    }

    /// System charts of the context run, grouped the way leet groups them:
    /// one chart per base key, one series per device.
    fn system_groups(&self) -> Vec<SystemGroup> {
        let Some(ix) = self.context_run() else {
            return Vec::new();
        };
        let mut groups: BTreeMap<String, SystemGroup> = BTreeMap::new();
        for (key, &series) in &self.runs[ix].system.by_name {
            let Some(def) = match_metric_def(key) else {
                continue;
            };
            let base = extract_base_key(key);
            groups
                .entry(base.clone())
                .or_insert_with(|| SystemGroup {
                    base,
                    def,
                    series: Vec::new(),
                })
                .series
                .push((extract_series_name(key), series));
        }
        groups
            .into_values()
            .filter(|group| {
                self.filters.system.matches(&group.def.title())
                    || self.filters.system.matches(&group.base)
            })
            .collect()
    }

    fn system_cells(&self) -> (usize, Vec<Cell>) {
        let Some(ix) = self.context_run() else {
            return (0, Vec::new());
        };
        let groups = self.system_groups();
        let per_page = self.system_grid.per_page();
        let start = self
            .system_grid
            .page
            .min(self.system_grid.pages(groups.len()) - 1)
            * per_page;
        let cells = groups
            .iter()
            .skip(start)
            .take(per_page)
            .map(|SystemGroup { base, def, series }| {
                let log = self.system_log.contains(base);
                let fixed_y = (!def.auto_range && def.max_y > def.min_y).then_some(Range {
                    min: def.min_y,
                    max: def.max_y,
                });
                let series = series
                    .iter()
                    .enumerate()
                    .map(|(i, (name, series))| SeriesRef {
                        run: ix,
                        table: Table::System,
                        series: *series,
                        name: name.clone().into(),
                        color: theme::run_color(i),
                    })
                    .collect();
                Cell {
                    title: def.title().into(),
                    badge: log.then_some("log"),
                    spec: ChartSpec {
                        x_axis: XAxis::Time,
                        log,
                        fixed_y,
                        series,
                    },
                }
            })
            .collect();
        (groups.len(), cells)
    }

    /// Everything a chart paints, from the series caches.
    pub fn chart_data(
        &mut self,
        spec: &ChartSpec,
        columns: usize,
        hover_t: Option<f64>,
    ) -> Option<ChartData> {
        let weight = self.smoothing_weight();
        let mut x_range: Option<Range> = None;
        let mut y_range: Option<Range> = None;
        for r in &spec.series {
            let Some(series) = series_mut(&mut self.runs, r) else {
                continue;
            };
            x_range = merge(x_range, series.x_extent.range(false));
            y_range = merge(y_range, series.y_extent(weight).range(spec.log));
        }
        let x_range = x_range?.non_degenerate();
        let y_range = match (spec.fixed_y, spec.log) {
            (Some(fixed), false) => y_range.map_or(fixed, |r| r.union(fixed)),
            (_, false) => y_range?.non_degenerate().padded(0.05),
            (_, true) => y_range?.non_degenerate(),
        };
        let hover_x = hover_t.map(|t| Scale::Linear.denormalize(x_range, t));
        let series = spec
            .series
            .iter()
            .filter_map(|r| {
                let series = series_mut(&mut self.runs, r)?;
                Some(SeriesDraw {
                    name: r.name.clone(),
                    color: r.color,
                    line: series.decimated(weight, x_range, columns).to_vec(),
                    raw: (weight > 0.0).then(|| series.raw(x_range, columns).to_vec()),
                    hover: hover_x.and_then(|x| series.nearest(weight, x)),
                })
            })
            .collect();
        Some(ChartData {
            x_range,
            y_range,
            series,
        })
    }

    fn visible_panes(&self) -> Vec<Pane> {
        let cfg = self.cfg();
        PANES
            .into_iter()
            .filter(|pane| match pane {
                Pane::Runs => self.show_runs,
                Pane::Metrics => cfg.workspace_metrics_grid_visible,
                Pane::System => cfg.workspace_system_metrics_visible,
                Pane::Console => cfg.workspace_console_logs_visible,
                Pane::Overview => cfg.workspace_overview_visible,
            })
            .collect()
    }

    fn editing(&self) -> bool {
        let f = &self.filters;
        [&f.runs, &f.metrics, &f.system, &f.console, &f.overview]
            .iter()
            .any(|f| f.editing)
    }

    fn filter_for(&mut self, pane: Pane) -> (&mut Filter, &'static str) {
        match pane {
            Pane::Runs => (&mut self.filters.runs, "runs_filter"),
            Pane::Metrics => (&mut self.filters.metrics, "metrics_filter"),
            Pane::System => (&mut self.filters.system, "system_metrics_filter"),
            Pane::Console => (&mut self.filters.console, "console_filter"),
            Pane::Overview => (&mut self.filters.overview, "overview_filter"),
        }
    }

    pub fn set_cursor(&mut self, cursor: usize) {
        let count = self.visible().len();
        self.cursor = cursor.min(count.saturating_sub(1));
        self.runs_scroll
            .scroll_to_item(self.cursor, ScrollStrategy::Center);
    }

    fn console_len(&self) -> usize {
        self.context_run()
            .map_or(0, |ix| self.runs[ix].console.len())
    }

    fn move_by(&mut self, drow: isize, dcol: isize, cx: &mut Context<Self>) {
        match self.focus {
            Pane::Runs => {
                if drow != 0 {
                    self.set_cursor(self.cursor.saturating_add_signed(drow));
                }
            }
            Pane::Metrics => self.metrics_grid.move_focus(drow, dcol),
            Pane::System => self.system_grid.move_focus(drow, dcol),
            Pane::Console => {
                let last = self.console_len().saturating_sub(1);
                let cursor = self
                    .console_cursor
                    .unwrap_or(last)
                    .saturating_add_signed(drow)
                    .min(last);
                self.console_cursor = (cursor < last).then_some(cursor);
            }
            Pane::Overview => {
                let last = overview::rows(self).len().saturating_sub(1);
                self.overview_cursor = self.overview_cursor.saturating_add_signed(drow).min(last);
            }
        }
        cx.notify();
    }

    fn turn_page(&mut self, delta: isize, cx: &mut Context<Self>) {
        match self.focus {
            Pane::Runs => self.set_cursor(
                self.cursor
                    .saturating_add_signed(delta * LIST_PAGE as isize),
            ),
            Pane::Metrics => {
                let total = self.metric_names().len();
                self.metrics_grid.turn_page(delta, total);
            }
            Pane::System => {
                let total = self.system_groups().len();
                self.system_grid.turn_page(delta, total);
            }
            Pane::Console | Pane::Overview => self.move_by(delta * LIST_PAGE as isize, 0, cx),
        }
        cx.notify();
    }

    fn move_up(&mut self, _: &MoveUp, _: &mut Window, cx: &mut Context<Self>) {
        self.move_by(-1, 0, cx);
    }

    fn move_down(&mut self, _: &MoveDown, _: &mut Window, cx: &mut Context<Self>) {
        self.move_by(1, 0, cx);
    }

    fn move_left(&mut self, _: &MoveLeft, _: &mut Window, cx: &mut Context<Self>) {
        self.move_by(0, -1, cx);
    }

    fn move_right(&mut self, _: &MoveRight, _: &mut Window, cx: &mut Context<Self>) {
        self.move_by(0, 1, cx);
    }

    fn page_up(&mut self, _: &PageUp, _: &mut Window, cx: &mut Context<Self>) {
        self.turn_page(-1, cx);
    }

    fn page_down(&mut self, _: &PageDown, _: &mut Window, cx: &mut Context<Self>) {
        self.turn_page(1, cx);
    }

    fn home(&mut self, _: &Home, _: &mut Window, cx: &mut Context<Self>) {
        match self.focus {
            Pane::Console => self.console_cursor = Some(0),
            Pane::Overview => self.overview_cursor = 0,
            _ => self.turn_page(-(isize::MAX / 2), cx),
        }
        cx.notify();
    }

    fn end(&mut self, _: &End, _: &mut Window, cx: &mut Context<Self>) {
        match self.focus {
            Pane::Console => self.console_cursor = None,
            Pane::Overview => self.overview_cursor = usize::MAX / 2,
            _ => self.turn_page(isize::MAX / 2, cx),
        }
        cx.notify();
    }

    fn toggle_select(&mut self, _: &ToggleSelect, _: &mut Window, cx: &mut Context<Self>) {
        let Some(&ix) = self.visible().get(self.cursor) else {
            return;
        };
        let dir_name = self.runs[ix].dir.dir_name.clone();
        if !self.selected.remove(&dir_name) {
            self.select(&dir_name, cx);
        }
        self.save_selection();
        cx.notify();
    }

    fn pin_run(&mut self, _: &PinRun, _: &mut Window, cx: &mut Context<Self>) {
        let Some(&ix) = self.visible().get(self.cursor) else {
            return;
        };
        let dir_name = self.runs[ix].dir.dir_name.clone();
        if self.pinned.as_deref() == Some(dir_name.as_str()) {
            self.pinned = None;
        } else {
            if !self.selected.contains(&dir_name) {
                self.select(&dir_name, cx);
            }
            self.pinned = Some(dir_name);
        }
        self.console_cursor = None;
        self.overview_cursor = 0;
        self.save_selection();
        cx.notify();
    }

    fn cycle_focus(&mut self, delta: isize, cx: &mut Context<Self>) {
        let panes = self.visible_panes();
        if panes.is_empty() {
            return;
        }
        let current = panes
            .iter()
            .position(|p| *p == self.focus)
            .map_or(0, |i| i as isize + delta);
        self.focus = panes[current.rem_euclid(panes.len() as isize) as usize];
        cx.notify();
    }

    fn focus_next(&mut self, _: &FocusNext, _: &mut Window, cx: &mut Context<Self>) {
        self.cycle_focus(1, cx);
    }

    fn focus_prev(&mut self, _: &FocusPrev, _: &mut Window, cx: &mut Context<Self>) {
        self.cycle_focus(-1, cx);
    }

    fn toggle_pane(&mut self, pane: Pane, cx: &mut Context<Self>) {
        let config = &mut self.config.config;
        let flag = match pane {
            Pane::Runs => &mut self.show_runs,
            Pane::Metrics => &mut config.workspace_metrics_grid_visible,
            Pane::System => &mut config.workspace_system_metrics_visible,
            Pane::Console => &mut config.workspace_console_logs_visible,
            Pane::Overview => &mut config.workspace_overview_visible,
        };
        *flag = !*flag;
        if pane != Pane::Runs {
            self.save_config();
        }
        if !self.visible_panes().contains(&self.focus) {
            self.focus = self.visible_panes().first().copied().unwrap_or(Pane::Runs);
        }
        cx.notify();
    }

    fn toggle_runs_sidebar(
        &mut self,
        _: &ToggleRunsSidebar,
        _: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.toggle_pane(Pane::Runs, cx);
    }

    fn toggle_metrics(&mut self, _: &ToggleMetrics, _: &mut Window, cx: &mut Context<Self>) {
        self.toggle_pane(Pane::Metrics, cx);
    }

    fn toggle_system(&mut self, _: &ToggleSystem, _: &mut Window, cx: &mut Context<Self>) {
        self.toggle_pane(Pane::System, cx);
    }

    fn toggle_console(&mut self, _: &ToggleConsole, _: &mut Window, cx: &mut Context<Self>) {
        self.toggle_pane(Pane::Console, cx);
    }

    fn toggle_overview(&mut self, _: &ToggleOverview, _: &mut Window, cx: &mut Context<Self>) {
        self.toggle_pane(Pane::Overview, cx);
    }

    fn toggle_log_y(&mut self, _: &ToggleLogY, _: &mut Window, cx: &mut Context<Self>) {
        match self.focus {
            Pane::Metrics => {
                let names = self.metric_names();
                let Some(name) = names
                    .get(self.metrics_grid.focused_index(names.len()))
                    .map(|n| n.to_string())
                else {
                    return;
                };
                if !self.metrics_log.remove(&name) {
                    self.metrics_log.insert(name);
                }
            }
            Pane::System => {
                let groups = self.system_groups();
                let Some(group) = groups.get(self.system_grid.focused_index(groups.len())) else {
                    return;
                };
                let base = group.base.clone();
                if !self.system_log.remove(&base) {
                    self.system_log.insert(base);
                }
            }
            _ => return,
        }
        cx.notify();
    }

    fn cycle_smoothing(&mut self, _: &CycleSmoothing, _: &mut Window, cx: &mut Context<Self>) {
        self.smoothing = (self.smoothing + 1) % SMOOTHING.len();
        self.config.config.smoothing = self.smoothing_weight();
        self.save_config();
        cx.notify();
    }

    fn start_filter(&mut self, pane: Pane, cx: &mut Context<Self>) {
        self.focus = pane;
        self.filter_for(pane).0.editing = true;
        cx.notify();
    }

    fn filter_runs(&mut self, _: &FilterRuns, _: &mut Window, cx: &mut Context<Self>) {
        self.start_filter(Pane::Runs, cx);
    }

    fn filter_metrics(&mut self, _: &FilterMetrics, _: &mut Window, cx: &mut Context<Self>) {
        let pane = if self.focus == Pane::Console {
            Pane::Console
        } else {
            Pane::Metrics
        };
        self.start_filter(pane, cx);
    }

    fn filter_system(&mut self, _: &FilterSystem, _: &mut Window, cx: &mut Context<Self>) {
        self.start_filter(Pane::System, cx);
    }

    fn filter_overview(&mut self, _: &FilterOverview, _: &mut Window, cx: &mut Context<Self>) {
        self.start_filter(Pane::Overview, cx);
    }

    fn clear_filter(&mut self, _: &ClearFilter, _: &mut Window, cx: &mut Context<Self>) {
        self.filter_for(self.focus).0.text.clear();
        self.filter_changed(cx);
    }

    fn stop_editing(&mut self) {
        for pane in PANES {
            self.filter_for(pane).0.editing = false;
        }
    }

    fn escape(&mut self, _: &Escape, _: &mut Window, cx: &mut Context<Self>) {
        if self.show_help {
            self.show_help = false;
        } else if self.editing() {
            self.stop_editing();
        } else {
            self.focus = Pane::Runs;
        }
        cx.notify();
    }

    fn confirm(&mut self, _: &Confirm, _: &mut Window, cx: &mut Context<Self>) {
        self.stop_editing();
        cx.notify();
    }

    fn backspace(&mut self, _: &Backspace, _: &mut Window, cx: &mut Context<Self>) {
        self.filter_for(self.focus).0.text.pop();
        self.filter_changed(cx);
    }

    fn key_down(&mut self, event: &KeyDownEvent, _: &mut Window, cx: &mut Context<Self>) {
        let modifiers = event.keystroke.modifiers;
        if !self.editing() || modifiers.control || modifiers.platform || modifiers.alt {
            return;
        }
        if let Some(text) = &event.keystroke.key_char {
            self.filter_for(self.focus).0.text.push_str(text);
            self.filter_changed(cx);
        }
    }

    fn filter_changed(&mut self, cx: &mut Context<Self>) {
        let (filter, key) = self.filter_for(self.focus);
        let text = filter.text.clone();
        self.dir_state.set_filter(key, &text);
        self.metrics_grid.page = 0;
        self.system_grid.page = 0;
        self.overview_cursor = 0;
        self.console_cursor = None;
        self.set_cursor(self.cursor);
        cx.notify();
    }

    fn toggle_help(&mut self, _: &ToggleHelp, _: &mut Window, cx: &mut Context<Self>) {
        self.show_help = !self.show_help;
        cx.notify();
    }

    fn render_status(&self) -> Div {
        let (state, state_color) = self.context_run().map(|ix| self.runs[ix].state).map_or(
            ("○", theme::muted()),
            |state| match state_glyph(state) {
                ("", color) => ("○", color),
                glyph => glyph,
            },
        );
        let pinned = self
            .pinned
            .as_ref()
            .and_then(|p| self.run_index(p))
            .map(|ix| format!("pinned {}", self.runs[ix].name));
        div()
            .h(px(STATUS_BAR_HEIGHT))
            .px_2()
            .flex()
            .items_center()
            .gap_4()
            .border_t_1()
            .border_color(theme::border())
            .text_color(theme::muted())
            .whitespace_nowrap()
            .child(div().text_color(state_color).child(state))
            .child(div().text_color(theme::accent()).child("LEET"))
            .child(self.wandb_dir.to_string_lossy().into_owned())
            .child(format!("{} selected", self.selected.len()))
            .when_some(pinned, |bar, pinned| bar.child(pinned))
            .child(div().flex_1())
            .child("space select  p pin  f / \\ o filter  n/N page  y log  m smooth  1 2 4 [ ] panes  ? help  q quit")
    }

    fn render_help(&self) -> Div {
        div()
            .absolute()
            .top_0()
            .left_0()
            .size_full()
            .bg(hsla(0., 0., 0., 0.6))
            .flex()
            .items_center()
            .justify_center()
            .child(
                div()
                    .bg(theme::panel())
                    .border_1()
                    .border_color(theme::border())
                    .rounded(px(6.))
                    .p_4()
                    .flex()
                    .flex_col()
                    .gap_1()
                    .child(div().text_color(theme::accent()).pb_2().child("W&B LEET"))
                    .children(self.help.iter().map(|(keys, desc)| {
                        div()
                            .flex()
                            .gap_4()
                            .child(
                                div()
                                    .w(px(220.))
                                    .text_color(theme::focus())
                                    .child(keys.trim()),
                            )
                            .child(*desc)
                    })),
            )
    }
}

fn series_mut<'a>(runs: &'a mut [Run], r: &SeriesRef) -> Option<&'a mut Series> {
    let run = runs.get_mut(r.run)?;
    let table = match r.table {
        Table::Metrics => &mut run.metrics,
        Table::System => &mut run.system,
    };
    table.series.get_mut(r.series)
}

fn merge(acc: Option<Range>, next: Option<Range>) -> Option<Range> {
    match (acc, next) {
        (Some(a), Some(b)) => Some(a.union(b)),
        (a, b) => a.or(b),
    }
}

pub fn pane_header(title: String, filter: &Filter, focused: bool) -> Div {
    let filter_text = match (filter.editing, filter.text.is_empty()) {
        (true, _) => format!("filter: {}▏", filter.text),
        (false, false) => format!("filter: {}", filter.text),
        (false, true) => String::new(),
    };
    div()
        .h(px(26.))
        .px_2()
        .flex()
        .items_center()
        .gap_3()
        .flex_shrink_0()
        .border_b_1()
        .border_color(theme::border())
        .text_color(if focused {
            theme::text()
        } else {
            theme::muted()
        })
        .whitespace_nowrap()
        .child(title)
        .child(div().text_color(theme::accent()).child(filter_text))
}

impl Render for Workspace {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let context = if self.editing() { FILTER } else { WORKSPACE };
        let cfg = self.cfg();
        let layout = cfg.workspace_layout;
        let viewport = window.viewport_size();
        let content_h = viewport.height - px(STATUS_BAR_HEIGHT);
        let fraction = |value: f64, default: f32| if value > 0.0 { value as f32 } else { default };
        let left_w = viewport.width * fraction(layout.left_sidebar, LEFT_SIDEBAR);
        let right_w = viewport.width * fraction(layout.right_sidebar, RIGHT_SIDEBAR);
        let lower_panes = cfg.workspace_system_metrics_visible as usize
            + cfg.workspace_console_logs_visible as usize;
        let lower_total = if cfg.workspace_metrics_grid_visible {
            content_h * LOWER_TIER
        } else {
            content_h
        };
        let each = if lower_panes > 0 {
            lower_total / lower_panes as f32
        } else {
            px(0.)
        };
        let system_h = if layout.system > 0.0 {
            viewport.height * layout.system as f32
        } else {
            each
        };
        let logs_h = if layout.logs > 0.0 {
            viewport.height * layout.logs as f32
        } else {
            each
        };
        let (show_metrics, show_system, show_console, show_overview) = (
            cfg.workspace_metrics_grid_visible,
            cfg.workspace_system_metrics_visible,
            cfg.workspace_console_logs_visible,
            cfg.workspace_overview_visible,
        );
        let show_runs = self.show_runs;
        let header = px(26.);
        let metrics_h = content_h
            - if show_system { system_h } else { px(0.) }
            - if show_console { logs_h } else { px(0.) };
        self.metrics_grid.fit(f32::from(metrics_h - header));
        self.system_grid.fit(f32::from(system_h - header));
        let workspace = cx.entity();

        div()
            .id("workspace")
            .key_context(context)
            .track_focus(&self.focus_handle)
            .on_action(cx.listener(Self::toggle_help))
            .on_action(cx.listener(Self::escape))
            .on_action(cx.listener(Self::confirm))
            .on_action(cx.listener(Self::backspace))
            .on_action(cx.listener(Self::move_up))
            .on_action(cx.listener(Self::move_down))
            .on_action(cx.listener(Self::move_left))
            .on_action(cx.listener(Self::move_right))
            .on_action(cx.listener(Self::page_up))
            .on_action(cx.listener(Self::page_down))
            .on_action(cx.listener(Self::home))
            .on_action(cx.listener(Self::end))
            .on_action(cx.listener(Self::focus_next))
            .on_action(cx.listener(Self::focus_prev))
            .on_action(cx.listener(Self::toggle_select))
            .on_action(cx.listener(Self::pin_run))
            .on_action(cx.listener(Self::toggle_runs_sidebar))
            .on_action(cx.listener(Self::toggle_metrics))
            .on_action(cx.listener(Self::toggle_system))
            .on_action(cx.listener(Self::toggle_console))
            .on_action(cx.listener(Self::toggle_overview))
            .on_action(cx.listener(Self::toggle_log_y))
            .on_action(cx.listener(Self::cycle_smoothing))
            .on_action(cx.listener(Self::filter_runs))
            .on_action(cx.listener(Self::filter_metrics))
            .on_action(cx.listener(Self::filter_system))
            .on_action(cx.listener(Self::filter_overview))
            .on_action(cx.listener(Self::clear_filter))
            .on_key_down(cx.listener(Self::key_down))
            .relative()
            .size_full()
            .flex()
            .flex_col()
            .bg(theme::bg())
            .text_color(theme::text())
            .font_family(theme::FONT)
            .text_size(px(12.))
            .child(
                div()
                    .flex_1()
                    .min_h_0()
                    .flex()
                    .flex_row()
                    .when(show_runs, |main| main.child(render_runs(self, left_w, cx)))
                    .child(
                        div()
                            .flex_1()
                            .min_w_0()
                            .min_h_0()
                            .flex()
                            .flex_col()
                            .when(show_metrics, |column| {
                                let (total, cells) = self.metric_cells();
                                column.child(render_grid(
                                    GridView {
                                        id: "metrics",
                                        title: format!(
                                            "metrics {total}  smoothing {}",
                                            self.smoothing_weight()
                                        ),
                                        filter: &self.filters.metrics,
                                        focused: self.focus == Pane::Metrics,
                                        grid: &self.metrics_grid,
                                        cells,
                                        total,
                                        height: None,
                                    },
                                    workspace.clone(),
                                    cx,
                                ))
                            })
                            .when(show_system, |column| {
                                let (total, cells) = self.system_cells();
                                let run = self
                                    .context_run()
                                    .map(|ix| self.runs[ix].name.clone())
                                    .unwrap_or_default();
                                column.child(render_grid(
                                    GridView {
                                        id: "system",
                                        title: format!("system  {run}  {total} charts"),
                                        filter: &self.filters.system,
                                        focused: self.focus == Pane::System,
                                        grid: &self.system_grid,
                                        cells,
                                        total,
                                        height: Some(system_h),
                                    },
                                    workspace.clone(),
                                    cx,
                                ))
                            })
                            .when(show_console, |column| {
                                column.child(render_console(self, logs_h, cx))
                            }),
                    )
                    .when(show_overview, |main| {
                        main.child(render_overview(self, right_w, cx))
                    }),
            )
            .child(self.render_status())
            .when(self.show_help, |root| root.child(self.render_help()))
    }
}
