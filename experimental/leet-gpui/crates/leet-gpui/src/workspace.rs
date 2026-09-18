//! The workspace view: runs sidebar, metrics grid, status bar, and help
//! overlay. State and key handling follow `core/internal/leet/workspace.go`
//! and `workspacehandlers.go`; rendering is GPUI.

use std::collections::{BTreeSet, HashMap, HashSet};
use std::ops::Range;
use std::path::PathBuf;
use std::time::Duration;

use futures::StreamExt;
use futures::channel::mpsc;
use gpui::prelude::*;
use gpui::{
    Context, Div, FocusHandle, KeyDownEvent, ScrollStrategy, SharedString, Stateful,
    UniformListScrollHandle, Window, div, hsla, px, uniform_list,
};
use leet_data::history_source::{MetricData, SourceMsg};

use crate::actions::{self, *};
use crate::chart;
use crate::source::{self, RunDir};
use crate::theme;

const SMOOTHING: [f64; 4] = [0.0, 0.6, 0.9, 0.99];
const RESCAN_INTERVAL: Duration = Duration::from_secs(5);
const RUNS_PAGE: usize = 20;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RunState {
    Unknown,
    Loading,
    Running,
    Finished,
    Failed,
}

pub struct Run {
    pub dir: RunDir,
    pub name: String,
    pub state: RunState,
    pub color: usize,
    pub metrics: HashMap<String, MetricData>,
    reading: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Pane {
    Runs,
    Metrics,
}

#[derive(Default)]
struct Filter {
    text: String,
    editing: bool,
}

impl Filter {
    fn matches(&self, candidate: &str) -> bool {
        self.text.is_empty() || candidate.to_lowercase().contains(&self.text.to_lowercase())
    }
}

struct Grid {
    rows: usize,
    cols: usize,
    page: usize,
    focused: usize,
}

pub struct Workspace {
    pub focus_handle: FocusHandle,
    pub log_y: BTreeSet<String>,
    wandb_dir: PathBuf,
    help: actions::Help,
    runs: Vec<Run>,
    cursor: usize,
    selected: BTreeSet<String>,
    focus: Pane,
    show_runs: bool,
    show_metrics: bool,
    runs_filter: Filter,
    metrics_filter: Filter,
    grid: Grid,
    smoothing: usize,
    show_help: bool,
    list_scroll: UniformListScrollHandle,
}

impl Workspace {
    pub fn new(
        wandb_dir: PathBuf,
        run: Option<String>,
        help: actions::Help,
        cx: &mut Context<Self>,
    ) -> Self {
        let mut workspace = Self {
            focus_handle: cx.focus_handle(),
            log_y: BTreeSet::new(),
            wandb_dir,
            help,
            runs: Vec::new(),
            cursor: 0,
            selected: BTreeSet::new(),
            focus: Pane::Runs,
            show_runs: true,
            show_metrics: true,
            runs_filter: Filter::default(),
            metrics_filter: Filter::default(),
            grid: Grid {
                rows: 3,
                cols: 3,
                page: 0,
                focused: 0,
            },
            smoothing: 0,
            show_help: false,
            list_scroll: UniformListScrollHandle::new(),
        };
        workspace.rescan(cx);
        let initial = run.or_else(|| workspace.runs.first().map(|run| run.dir.dir_name.clone()));
        if let Some(name) = initial {
            workspace.select(&name, cx);
            let cursor = workspace
                .runs
                .iter()
                .position(|run| run.dir.dir_name == name)
                .unwrap_or(0);
            workspace.set_cursor(cursor);
        }
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

    pub fn smoothing_weight(&self) -> f64 {
        SMOOTHING[self.smoothing]
    }

    pub fn selected_runs(&self) -> impl Iterator<Item = &Run> {
        self.runs
            .iter()
            .filter(|run| self.selected.contains(&run.dir.dir_name))
    }

    fn run_mut(&mut self, dir_name: &str) -> Option<&mut Run> {
        self.runs
            .iter_mut()
            .find(|run| run.dir.dir_name == dir_name)
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
        self.runs.extend(added.into_iter().map(|dir| Run {
            name: dir.id.clone(),
            dir,
            state: RunState::Unknown,
            color: 0,
            metrics: HashMap::new(),
            reading: false,
        }));
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
            while let Some((name, run)) = rx.next().await {
                let applied = this.update(cx, |workspace, cx| {
                    if let Some(entry) = workspace.run_mut(&name)
                        && !run.display_name.is_empty()
                    {
                        entry.name = run.display_name;
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
        let used: HashSet<usize> = self.selected_runs().map(|run| run.color).collect();
        let color = (0..).find(|c| !used.contains(c)).unwrap_or(0);
        self.selected.insert(dir_name.to_string());
        let Some(run) = self.run_mut(dir_name) else {
            return;
        };
        run.color = color;
        if run.reading {
            return;
        }
        run.reading = true;
        let (tx, mut rx) = mpsc::unbounded();
        source::spawn_reader(&run.dir, tx);
        let dir_name = dir_name.to_string();
        cx.spawn(async move |this, cx| {
            while let Some(batch) = rx.next().await {
                let applied = this.update(cx, |workspace, cx| {
                    workspace.apply(&dir_name, batch);
                    cx.notify();
                });
                if applied.is_err() {
                    return;
                }
            }
        })
        .detach();
    }

    fn apply(&mut self, dir_name: &str, batch: Vec<SourceMsg>) {
        let Some(run) = self.run_mut(dir_name) else {
            return;
        };
        if batch.is_empty() && matches!(run.state, RunState::Unknown | RunState::Loading) {
            run.state = RunState::Running;
        }
        for msg in batch {
            match msg {
                SourceMsg::History(history) => {
                    if run.state == RunState::Unknown {
                        run.state = RunState::Loading;
                    }
                    for (key, data) in history.metrics {
                        let metric = run.metrics.entry(key).or_default();
                        metric.x.extend(data.x);
                        metric.y.extend(data.y);
                    }
                }
                SourceMsg::Run(record) if !record.display_name.is_empty() => {
                    run.name = record.display_name;
                }
                SourceMsg::FileComplete(done) => {
                    run.state = if done.exit_code == 0 {
                        RunState::Finished
                    } else {
                        RunState::Failed
                    };
                }
                _ => {}
            }
        }
    }

    /// Indices of the runs that pass the runs filter, newest first.
    fn visible(&self) -> Vec<usize> {
        self.runs
            .iter()
            .enumerate()
            .filter(|(_, run)| {
                self.runs_filter.matches(&run.name) || self.runs_filter.matches(&run.dir.id)
            })
            .map(|(ix, _)| ix)
            .collect()
    }

    /// Metric names charted for the selected runs, after the metrics filter.
    fn metric_names(&self) -> Vec<String> {
        let mut names = BTreeSet::new();
        for run in self.selected_runs() {
            names.extend(
                run.metrics
                    .keys()
                    .filter(|key| self.metrics_filter.matches(key))
                    .cloned(),
            );
        }
        names.into_iter().collect()
    }

    fn page_count(&self, metrics: usize) -> usize {
        metrics.div_ceil(self.grid.rows * self.grid.cols).max(1)
    }

    fn editing(&self) -> bool {
        self.runs_filter.editing || self.metrics_filter.editing
    }

    fn set_cursor(&mut self, cursor: usize) {
        let count = self.visible().len();
        self.cursor = cursor.min(count.saturating_sub(1));
        self.list_scroll
            .scroll_to_item(self.cursor, ScrollStrategy::Center);
    }

    fn move_focus(&mut self, drow: isize, dcol: isize, cx: &mut Context<Self>) {
        match self.focus {
            Pane::Runs => {
                if drow != 0 {
                    self.set_cursor(self.cursor.saturating_add_signed(drow));
                }
            }
            Pane::Metrics => {
                let cols = self.grid.cols as isize;
                let row = (self.grid.focused as isize / cols + drow)
                    .clamp(0, self.grid.rows as isize - 1);
                let col = (self.grid.focused as isize % cols + dcol).clamp(0, cols - 1);
                self.grid.focused = (row * cols + col) as usize;
            }
        }
        cx.notify();
    }

    fn set_page(&mut self, page: isize, cx: &mut Context<Self>) {
        match self.focus {
            Pane::Runs => {
                self.set_cursor(self.cursor.saturating_add_signed(page * RUNS_PAGE as isize))
            }
            Pane::Metrics => {
                let pages = self.page_count(self.metric_names().len()) as isize;
                self.grid.page = (self.grid.page as isize + page).clamp(0, pages - 1) as usize;
            }
        }
        cx.notify();
    }

    fn move_up(&mut self, _: &MoveUp, _: &mut Window, cx: &mut Context<Self>) {
        self.move_focus(-1, 0, cx);
    }

    fn move_down(&mut self, _: &MoveDown, _: &mut Window, cx: &mut Context<Self>) {
        self.move_focus(1, 0, cx);
    }

    fn move_left(&mut self, _: &MoveLeft, _: &mut Window, cx: &mut Context<Self>) {
        self.move_focus(0, -1, cx);
    }

    fn move_right(&mut self, _: &MoveRight, _: &mut Window, cx: &mut Context<Self>) {
        self.move_focus(0, 1, cx);
    }

    fn page_up(&mut self, _: &PageUp, _: &mut Window, cx: &mut Context<Self>) {
        self.set_page(-1, cx);
    }

    fn page_down(&mut self, _: &PageDown, _: &mut Window, cx: &mut Context<Self>) {
        self.set_page(1, cx);
    }

    fn home(&mut self, _: &Home, _: &mut Window, cx: &mut Context<Self>) {
        self.set_page(-(isize::MAX / 2), cx);
    }

    fn end(&mut self, _: &End, _: &mut Window, cx: &mut Context<Self>) {
        self.set_page(isize::MAX / 2, cx);
    }

    fn toggle_select(&mut self, _: &ToggleSelect, _: &mut Window, cx: &mut Context<Self>) {
        let Some(&ix) = self.visible().get(self.cursor) else {
            return;
        };
        let dir_name = self.runs[ix].dir.dir_name.clone();
        if !self.selected.remove(&dir_name) {
            self.select(&dir_name, cx);
        }
        cx.notify();
    }

    fn focus_next(&mut self, _: &FocusNext, _: &mut Window, cx: &mut Context<Self>) {
        self.focus = match self.focus {
            Pane::Runs if self.show_metrics => Pane::Metrics,
            _ => Pane::Runs,
        };
        cx.notify();
    }

    fn focus_prev(&mut self, _: &FocusPrev, window: &mut Window, cx: &mut Context<Self>) {
        self.focus_next(&FocusNext, window, cx);
    }

    fn toggle_runs_sidebar(
        &mut self,
        _: &ToggleRunsSidebar,
        _: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.show_runs = !self.show_runs;
        if !self.show_runs {
            self.focus = Pane::Metrics;
        }
        cx.notify();
    }

    fn toggle_metrics(&mut self, _: &ToggleMetrics, _: &mut Window, cx: &mut Context<Self>) {
        self.show_metrics = !self.show_metrics;
        if !self.show_metrics {
            self.focus = Pane::Runs;
        }
        cx.notify();
    }

    fn toggle_log_y(&mut self, _: &ToggleLogY, _: &mut Window, cx: &mut Context<Self>) {
        let names = self.metric_names();
        let Some(name) =
            names.get(self.grid.page * self.grid.rows * self.grid.cols + self.grid.focused)
        else {
            return;
        };
        if !self.log_y.remove(name) {
            self.log_y.insert(name.clone());
        }
        cx.notify();
    }

    fn cycle_smoothing(&mut self, _: &CycleSmoothing, _: &mut Window, cx: &mut Context<Self>) {
        self.smoothing = (self.smoothing + 1) % SMOOTHING.len();
        cx.notify();
    }

    fn filter_runs(&mut self, _: &FilterRuns, _: &mut Window, cx: &mut Context<Self>) {
        self.focus = Pane::Runs;
        self.runs_filter.editing = true;
        cx.notify();
    }

    fn filter_metrics(&mut self, _: &FilterMetrics, _: &mut Window, cx: &mut Context<Self>) {
        self.focus = Pane::Metrics;
        self.metrics_filter.editing = true;
        cx.notify();
    }

    fn focused_filter(&mut self) -> &mut Filter {
        match self.focus {
            Pane::Runs => &mut self.runs_filter,
            Pane::Metrics => &mut self.metrics_filter,
        }
    }

    fn clear_filter(&mut self, _: &ClearFilter, _: &mut Window, cx: &mut Context<Self>) {
        *self.focused_filter() = Filter::default();
        self.grid.page = 0;
        self.set_cursor(self.cursor);
        cx.notify();
    }

    fn escape(&mut self, _: &Escape, _: &mut Window, cx: &mut Context<Self>) {
        if self.show_help {
            self.show_help = false;
        } else if self.editing() {
            self.runs_filter.editing = false;
            self.metrics_filter.editing = false;
        } else {
            self.focus = Pane::Runs;
        }
        cx.notify();
    }

    fn confirm(&mut self, _: &Confirm, _: &mut Window, cx: &mut Context<Self>) {
        self.runs_filter.editing = false;
        self.metrics_filter.editing = false;
        cx.notify();
    }

    fn backspace(&mut self, _: &Backspace, _: &mut Window, cx: &mut Context<Self>) {
        self.focused_filter().text.pop();
        self.filter_changed(cx);
    }

    fn key_down(&mut self, event: &KeyDownEvent, _: &mut Window, cx: &mut Context<Self>) {
        let modifiers = event.keystroke.modifiers;
        if !self.editing() || modifiers.control || modifiers.platform || modifiers.alt {
            return;
        }
        if let Some(text) = &event.keystroke.key_char {
            self.focused_filter().text.push_str(text);
            self.filter_changed(cx);
        }
    }

    fn filter_changed(&mut self, cx: &mut Context<Self>) {
        self.grid.page = 0;
        self.set_cursor(self.cursor);
        cx.notify();
    }

    fn toggle_help(&mut self, _: &ToggleHelp, _: &mut Window, cx: &mut Context<Self>) {
        self.show_help = !self.show_help;
        cx.notify();
    }

    fn render_runs(&self, cx: &mut Context<Self>) -> Stateful<Div> {
        let visible = self.visible();
        let focused = self.focus == Pane::Runs;
        let header = format!("runs {}/{}", visible.len(), self.runs.len());
        div()
            .id("runs")
            .w(px(280.))
            .h_full()
            .flex()
            .flex_col()
            .border_r_1()
            .border_color(if focused {
                theme::focus()
            } else {
                theme::border()
            })
            .child(pane_header(header, &self.runs_filter, focused))
            .child(
                uniform_list(
                    "runs-list",
                    visible.len(),
                    cx.processor(move |workspace, range: Range<usize>, _, cx| {
                        range
                            .map(|pos| workspace.render_run_row(visible[pos], pos, cx))
                            .collect()
                    }),
                )
                .flex_1()
                .track_scroll(self.list_scroll.clone()),
            )
    }

    fn render_run_row(&self, ix: usize, pos: usize, cx: &mut Context<Self>) -> Stateful<Div> {
        let run = &self.runs[ix];
        let selected = self.selected.contains(&run.dir.dir_name);
        let mark_color = if selected {
            theme::run_color(run.color)
        } else {
            theme::muted()
        };
        let (state, state_color) = match run.state {
            RunState::Unknown => ("", theme::muted()),
            RunState::Loading => ("…", theme::muted()),
            RunState::Running => ("▶", theme::accent()),
            RunState::Finished => ("✓", theme::muted()),
            RunState::Failed => ("✗", theme::run_color(3)),
        };
        div()
            .id(pos)
            .h(px(22.))
            .px_2()
            .flex()
            .items_center()
            .gap_2()
            .when(pos == self.cursor, |row| row.bg(theme::cursor()))
            .on_click(cx.listener(move |workspace, _, _, cx| {
                workspace.focus = Pane::Runs;
                workspace.set_cursor(pos);
                cx.notify();
            }))
            .child(
                div()
                    .text_color(mark_color)
                    .child(if selected { "●" } else { "○" }),
            )
            .child(
                div()
                    .flex_1()
                    .overflow_hidden()
                    .whitespace_nowrap()
                    .text_ellipsis()
                    .child(run.name.clone()),
            )
            .child(div().text_color(state_color).child(state))
    }

    fn render_grid(&self, cx: &mut Context<Self>) -> Stateful<Div> {
        let names = self.metric_names();
        let per_page = self.grid.rows * self.grid.cols;
        let pages = self.page_count(names.len());
        let page = self.grid.page.min(pages - 1);
        let start = page * per_page;
        let focused = self.focus == Pane::Metrics;
        let header = format!(
            "metrics {}  page {}/{}  smoothing {}",
            names.len(),
            page + 1,
            pages,
            self.smoothing_weight()
        );
        let workspace = cx.entity();
        div()
            .id("metrics")
            .flex_1()
            .min_w_0()
            .flex()
            .flex_col()
            .on_mouse_move(cx.listener(|_, _, _, cx| cx.notify()))
            .child(pane_header(header, &self.metrics_filter, focused))
            .children((0..self.grid.rows).map(|row| {
                div()
                    .flex_1()
                    .min_h_0()
                    .flex()
                    .flex_row()
                    .children((0..self.grid.cols).map(|col| {
                        let cell = row * self.grid.cols + col;
                        let name = names.get(start + cell).cloned();
                        let is_focused = focused && cell == self.grid.focused;
                        let log = name.as_ref().is_some_and(|name| self.log_y.contains(name));
                        div()
                            .flex_1()
                            .min_w_0()
                            .m(px(3.))
                            .rounded(px(4.))
                            .border_1()
                            .border_color(if is_focused {
                                theme::focus()
                            } else {
                                theme::border()
                            })
                            .bg(theme::panel())
                            .flex()
                            .flex_col()
                            .when_some(name, |cell, name| {
                                cell.child(
                                    div()
                                        .h(px(22.))
                                        .px_2()
                                        .flex()
                                        .items_center()
                                        .gap_2()
                                        .text_color(theme::text())
                                        .child(
                                            div()
                                                .flex_1()
                                                .overflow_hidden()
                                                .whitespace_nowrap()
                                                .text_ellipsis()
                                                .child(name.clone()),
                                        )
                                        .when(log, |title| {
                                            title.child(
                                                div().text_color(theme::muted()).child("log"),
                                            )
                                        }),
                                )
                                .child(
                                    div().flex_1().min_h_0().child(chart::chart(
                                        workspace.clone(),
                                        SharedString::from(name),
                                    )),
                                )
                            })
                    }))
            }))
    }

    fn render_status(&self) -> Div {
        div()
            .h(px(24.))
            .px_2()
            .flex()
            .items_center()
            .gap_4()
            .border_t_1()
            .border_color(theme::border())
            .text_color(theme::muted())
            .whitespace_nowrap()
            .child(div().text_color(theme::accent()).child("LEET"))
            .child(self.wandb_dir.to_string_lossy().into_owned())
            .child(format!("{} selected", self.selected.len()))
            .child(div().flex_1())
            .child("space select  f runs  / metrics  n/N page  y log  m smooth  ? help  q quit")
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
                                    .w(px(180.))
                                    .text_color(theme::focus())
                                    .child(keys.trim()),
                            )
                            .child(*desc)
                    })),
            )
    }
}

fn pane_header(title: String, filter: &Filter, focused: bool) -> Div {
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
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let context = if self.editing() { FILTER } else { WORKSPACE };
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
            .on_action(cx.listener(Self::toggle_runs_sidebar))
            .on_action(cx.listener(Self::toggle_metrics))
            .on_action(cx.listener(Self::toggle_log_y))
            .on_action(cx.listener(Self::cycle_smoothing))
            .on_action(cx.listener(Self::filter_runs))
            .on_action(cx.listener(Self::filter_metrics))
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
                    .when(self.show_runs, |main| main.child(self.render_runs(cx)))
                    .when(self.show_metrics, |main| main.child(self.render_grid(cx))),
            )
            .child(self.render_status())
            .when(self.show_help, |root| root.child(self.render_help()))
    }
}
