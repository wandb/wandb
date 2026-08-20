//! The multi-run workspace view.

pub mod runcolors;
pub mod runfilter;
pub mod syspane;

use std::cell::RefCell;
use std::collections::{HashMap, HashSet, VecDeque};
use std::rc::Rc;
use std::sync::mpsc::Sender;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use crossterm::event::{KeyCode, KeyEvent, KeyModifiers, MouseButton, MouseEvent, MouseEventKind};
use ratatui::buffer::Buffer;
use ratatui::layout::Rect;

use crate::animation::AnimatedValue;
use crate::config::{Config, ConfigManager, GridConfigTarget, LayoutOverrides};
use crate::consolelogs::{CONSOLE_LOGS_PANE_MIN_HEIGHT, ConsoleLogsPane, RunConsoleLogs};
use crate::filter::{Filter, FilterKey};
use crate::flexlayout::{
    StackSection, StackSectionSpec, compute_vertical_stack_layout, sidebar_content_width,
    sidebar_width_for,
};
use crate::focusmanager::{FocusContext, FocusManager, FocusTarget};
use crate::grid::FocusType;
use crate::media::pane::{LOWER_TIER_RATIO, MEDIA_PANE_MIN_HEIGHT, MediaPane, MediaPaneViewState};
use crate::media::store::MediaStore;
use crate::metricsgrid::{MetricsGrid, render_metrics_empty_state};
use crate::msg::{Msg, RecordMsg, RunMsg};
use crate::nav::{NavIntent, decode_nav};
use crate::pagedlist::{KeyValuePair, PagedList};
use crate::runoverview::{RunOverview, RunState};
use crate::sidebar::{RunOverviewSidebar, SidebarSide};
use crate::store::live::{
    ReaderHandle, run_wandb_file, spawn_dir_scanner, spawn_reader, spawn_run_preload,
};
use crate::systemgrid::{SystemGridSettings, SystemMetricsGrid};
use crate::textwrap::truncate_value;
use crate::theme::{
    self, Adaptive, BOX_LIGHT_VERTICAL, CONTENT_PADDING, MEDIUM_SHADE_BLOCK,
    MIN_METRIC_CHART_HEIGHT, MIN_METRIC_CHART_WIDTH, SIDEBAR_BOTTOM_PADDING, SIDEBAR_MIN_WIDTH,
    SIDEBAR_OVERHEAD, STATUS_BAR_HEIGHT,
};

use runcolors::WorkspaceRunColors;
use runfilter::{RunFilterQuery, WorkspaceRunFilterData};
use syspane::{
    SYSTEM_METRICS_PANE_HEADER_LINES, SYSTEM_METRICS_PANE_MIN_HEIGHT, SystemMetricsPane,
};

pub const RUN_MARK: &str = "○";
pub const SELECTED_RUN_MARK: &str = "●";
pub const PINNED_RUN_MARK: &str = "▶";

const WORKSPACE_HEADER_LINES: i32 = 1;
const STATUS_BAR_PADDING: u16 = 1;

/// Minimum height kept for the flexible metrics grid while dragging the
/// separator directly below it.
const MIN_FLEX_METRICS_HEIGHT: i32 = 5;

/// Limits the number of concurrent run record preloads.
const MAX_CONCURRENT_PRELOADS: usize = 4;

/// An action the parent model should take after an input event.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WorkspaceAction {
    None,
    Quit,
    /// Open the single-run view for this `.wandb` file.
    OpenRun {
        run_key: String,
        wandb_file: String,
    },
}

/// Computed layout for the workspace view.
#[derive(Debug, Clone, Copy, Default)]
pub struct WorkspaceLayout {
    pub left_sidebar_width: i32,
    pub main_content_area_width: i32,
    pub right_sidebar_width: i32,
    pub total_content_area_height: i32,
    /// Metrics grid height.
    pub height: i32,
    pub system_metrics_y: i32,
    pub system_metrics_height: i32,
    pub media_y: i32,
    pub media_height: i32,
    pub console_logs_y: i32,
    pub console_logs_height: i32,
}

/// Per-run streaming state for the workspace multi-run view.
struct WorkspaceRun {
    reader: Option<ReaderHandle>,
    wandb_path: String,
    state: RunState,
}

/// Bounded-concurrency FIFO preload queue with dedupe.
#[derive(Default)]
struct RunOverviewPreloader {
    pending: HashSet<String>,
    in_flight: HashSet<String>,
    queue: VecDeque<String>,
}

impl RunOverviewPreloader {
    fn enqueue(&mut self, run_key: &str) {
        if run_key.is_empty() || self.pending.contains(run_key) {
            return;
        }
        self.pending.insert(run_key.to_string());
        self.queue.push_back(run_key.to_string());
    }

    fn drop_queued_not_present(&mut self, present: &HashSet<String>) {
        let pending = &mut self.pending;
        self.queue.retain(|key| {
            if present.contains(key) {
                true
            } else {
                pending.remove(key);
                false
            }
        });
    }

    fn dequeue_startable(&mut self) -> Vec<String> {
        let available = MAX_CONCURRENT_PRELOADS.saturating_sub(self.in_flight.len());
        let n = available.min(self.queue.len());
        let mut keys = Vec::with_capacity(n);
        for _ in 0..n {
            let key = self.queue.pop_front().unwrap();
            self.in_flight.insert(key.clone());
            keys.push(key);
        }
        keys
    }

    fn mark_done(&mut self, run_key: &str) {
        self.in_flight.remove(run_key);
        self.pending.remove(run_key);
    }
}

/// The multi-run workspace view.
pub struct WorkspaceView {
    wandb_dir: String,
    width: i32,
    height: i32,

    tx: Option<Sender<Msg>>,
    scanner: Option<ReaderHandle>,

    focus_mgr: FocusManager,

    runs_anim: AnimatedValue,
    runs: PagedList,
    selected_runs: HashSet<String>,
    pinned_run: String,
    auto_selected_latest: bool,

    run_overview: HashMap<String, RunOverview>,
    pub overview_sidebar: RunOverviewSidebar,
    empty_overview: RunOverview,
    preloader: RunOverviewPreloader,

    filter: Filter,
    runs_filter_index: HashMap<String, WorkspaceRunFilterData>,

    metrics_grid_anim: AnimatedValue,
    pub metrics_grid: MetricsGrid,
    run_colors: Rc<RefCell<WorkspaceRunColors>>,

    system_metrics: HashMap<String, SystemMetricsGrid>,
    pub system_metrics_pane: SystemMetricsPane,

    console_logs: HashMap<String, RunConsoleLogs>,
    pub console_logs_pane: ConsoleLogsPane,
    /// (run key, revision) last pushed into the pane, to skip re-syncing.
    console_logs_synced: (String, u64),

    media: HashMap<String, MediaStore>,
    pub media_pane: MediaPane,
    media_pane_states: HashMap<String, MediaPaneViewState>,
    current_media_run_key: String,
    empty_media: MediaStore,

    /// Per-run streaming state keyed by run directory name.
    runs_by_key: HashMap<String, WorkspaceRun>,
    /// Maps reader source ids to run keys for message attribution.
    source_to_run: HashMap<u64, String>,

    /// User-set pane proportions (mirrors `config.workspace_layout`).
    layout: LayoutOverrides,
    /// The boundary being dragged with the mouse, if any.
    drag: Option<DragBoundary>,
}

/// A draggable layout boundary.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum DragBoundary {
    LeftSidebar,
    RightSidebar,
    /// The separator row directly above the given stack section.
    Separator(StackSection),
}

fn workspace_system_grid_settings(cfg: &Config) -> SystemGridSettings {
    SystemGridSettings {
        rows: cfg.workspace_system_grid.rows,
        cols: cfg.workspace_system_grid.cols,
        color_scheme: cfg.system_color_scheme.clone(),
        color_mode: cfg.system_color_mode.clone(),
        french_fries_scheme: cfg.french_fries_color_scheme.clone(),
        tail_window_secs: cfg.system_tail_window_secs(),
    }
}

impl WorkspaceView {
    pub fn new(wandb_dir: String, config: &ConfigManager) -> Self {
        let cfg = config.config();

        let run_colors = Rc::new(RefCell::new(WorkspaceRunColors::new(theme::graph_colors(
            &cfg.color_scheme,
        ))));

        let mut metrics_grid = MetricsGrid::new(
            cfg.workspace_metrics_grid.rows,
            cfg.workspace_metrics_grid.cols,
            &cfg.color_scheme,
            &cfg.per_plot_color_scheme,
        );
        let provider_colors = Rc::clone(&run_colors);
        metrics_grid.set_series_color_provider(Some(Box::new(move |run_path: &str| {
            provider_colors.borrow_mut().assign(run_path)
        })));

        let mut runs = PagedList::new("Runs", true);
        runs.set_items_per_page(1);

        let mut overview_sidebar = RunOverviewSidebar::new(
            AnimatedValue::new(cfg.workspace_overview_visible, SIDEBAR_MIN_WIDTH),
            SidebarSide::Right,
        );
        overview_sidebar.set_tag_color_scheme(&cfg.tag_color_scheme);

        let mut media_pane = MediaPane::new(AnimatedValue::new(
            cfg.workspace_media_visible,
            MEDIA_PANE_MIN_HEIGHT,
        ));
        media_pane.set_grid_config(cfg.workspace_media_grid.rows, cfg.workspace_media_grid.cols);

        let mut ws = Self {
            wandb_dir,
            width: 0,
            height: 0,
            tx: None,
            scanner: None,
            focus_mgr: FocusManager::new(vec![
                FocusTarget::RunsList,
                FocusTarget::MetricsGrid,
                FocusTarget::SystemMetrics,
                FocusTarget::Media,
                FocusTarget::ConsoleLogs,
                FocusTarget::Overview,
            ]),
            runs_anim: AnimatedValue::new(true, SIDEBAR_MIN_WIDTH),
            runs,
            selected_runs: HashSet::new(),
            pinned_run: String::new(),
            auto_selected_latest: false,
            run_overview: HashMap::new(),
            overview_sidebar,
            empty_overview: RunOverview::new(),
            preloader: RunOverviewPreloader::default(),
            filter: Filter::new(),
            runs_filter_index: HashMap::new(),
            metrics_grid_anim: AnimatedValue::new(cfg.workspace_metrics_grid_visible, 1),
            metrics_grid,
            run_colors,
            system_metrics: HashMap::new(),
            system_metrics_pane: SystemMetricsPane::new(AnimatedValue::new(
                cfg.workspace_system_metrics_visible,
                SYSTEM_METRICS_PANE_MIN_HEIGHT,
            )),
            console_logs: HashMap::new(),
            console_logs_pane: ConsoleLogsPane::new(AnimatedValue::new(
                cfg.workspace_console_logs_visible,
                CONSOLE_LOGS_PANE_MIN_HEIGHT,
            )),
            console_logs_synced: (String::new(), 0),
            media: HashMap::new(),
            media_pane,
            media_pane_states: HashMap::new(),
            current_media_run_key: String::new(),
            empty_media: MediaStore::new(),
            runs_by_key: HashMap::new(),
            source_to_run: HashMap::new(),
            layout: cfg.workspace_layout,
            drag: None,
        };
        ws.overview_sidebar
            .set_width_fraction(ws.layout.right_sidebar);
        // The runs list starts focused by default.
        ws.with_focus_mgr(|fm, view| fm.set_target(view, FocusTarget::RunsList, 1));
        ws
    }

    /// Starts the wandb directory scanner.
    pub fn start(&mut self, tx: Sender<Msg>) {
        self.scanner = Some(spawn_dir_scanner(self.wandb_dir.clone(), tx.clone()));
        self.tx = Some(tx);
    }

    /// Stops all background threads.
    pub fn cleanup(&mut self) {
        self.scanner = None;
        for run in self.runs_by_key.values_mut() {
            run.reader = None;
        }
    }

    pub fn wandb_dir(&self) -> &str {
        &self.wandb_dir
    }

    pub fn media_fullscreen(&self) -> bool {
        self.media_pane.is_fullscreen()
    }

    /// Reports whether any workspace-level filter UI is active.
    pub fn is_filtering(&self) -> bool {
        if self.metrics_grid.is_filter_mode()
            || self.overview_sidebar.is_filter_mode()
            || self.filter.is_active()
        {
            return true;
        }
        self.active_system_metrics_grid_ref()
            .is_some_and(|g| g.is_filter_mode())
    }

    // ---- Run selection / current run ----

    fn current_run_key(&self) -> Option<String> {
        self.runs.current_item().map(|it| it.key.clone())
    }

    /// The run key (directory name) of the currently highlighted run.
    pub fn selected_run_key(&self) -> String {
        self.current_run_key().unwrap_or_default()
    }

    /// The full path to the `.wandb` file for the highlighted run.
    pub fn selected_run_wandb_file(&self) -> String {
        let Some(key) = self.current_run_key() else {
            return String::new();
        };
        self.run_path_for_key(&key)
    }

    /// Reports whether the runs list sidebar is focused, visible, and has
    /// items. Gates Enter (switch to single-run view).
    pub fn run_selector_active(&self) -> bool {
        self.focus_mgr.is_target(FocusTarget::RunsList)
            && self.runs_anim.is_visible()
            && !self.runs.filtered_items.is_empty()
    }

    fn run_overview_active(&self) -> bool {
        self.focus_mgr.is_target(FocusTarget::Overview) && self.overview_sidebar.is_visible()
    }

    fn run_path_for_key(&self, run_key: &str) -> String {
        if run_key.is_empty() {
            return String::new();
        }
        run_wandb_file(&self.wandb_dir, run_key)
            .map(|p| p.to_string_lossy().into_owned())
            .unwrap_or_default()
    }

    fn run_color_for_key(&self, run_key: &str) -> Adaptive {
        let run_path = self.run_path_for_key(run_key);
        self.run_colors.borrow_mut().assign(&run_path)
    }

    fn active_system_metrics_grid_ref(&self) -> Option<&SystemMetricsGrid> {
        let key = self.current_run_key()?;
        self.system_metrics.get(&key)
    }

    fn active_system_metrics_grid(&mut self) -> Option<&mut SystemMetricsGrid> {
        let key = self.current_run_key()?;
        self.system_metrics.get_mut(&key)
    }

    // ---- Per-run state ----

    fn get_or_create_run_overview(&mut self, run_key: &str) -> &mut RunOverview {
        self.run_overview.entry(run_key.to_string()).or_default()
    }

    fn get_or_create_console_logs(&mut self, run_key: &str) -> &mut RunConsoleLogs {
        self.console_logs.entry(run_key.to_string()).or_default()
    }

    fn get_or_create_media_store(&mut self, run_key: &str) -> &mut MediaStore {
        self.media.entry(run_key.to_string()).or_default()
    }

    fn get_or_create_system_metrics_grid(
        &mut self,
        run_key: &str,
        config: &ConfigManager,
    ) -> &mut SystemMetricsGrid {
        self.system_metrics
            .entry(run_key.to_string())
            .or_insert_with(|| {
                let cfg = config.config();
                let init_w = MIN_METRIC_CHART_WIDTH as i32 * cfg.workspace_system_grid.cols;
                let init_h = MIN_METRIC_CHART_HEIGHT as i32 * cfg.workspace_system_grid.rows;
                SystemMetricsGrid::new(init_w, init_h, workspace_system_grid_settings(cfg))
            })
    }

    /// Ensures the pinned run (if any) is drawn on top in all charts.
    fn refresh_pinned_run(&mut self) {
        if self.pinned_run.is_empty() {
            return;
        }
        let Some(run) = self.runs_by_key.get(&self.pinned_run) else {
            return;
        };
        if run.wandb_path.is_empty() {
            return;
        }
        let path = run.wandb_path.clone();
        self.metrics_grid.promote_series_to_top(&path);
    }

    fn drop_run(&mut self, run_key: &str) {
        self.selected_runs.remove(run_key);
        if self.pinned_run == run_key {
            self.pinned_run.clear();
        }

        if let Some(run) = self.runs_by_key.remove(run_key) {
            if !run.wandb_path.is_empty() {
                self.metrics_grid.remove_series(&run.wandb_path);
            }
            self.console_logs.remove(run_key);
            self.system_metrics.remove(run_key);
            self.media.remove(run_key);
            self.media_pane_states.remove(run_key);
        }
        self.source_to_run.retain(|_, key| key != run_key);
    }

    fn toggle_run_selected(&mut self, run_key: &str) {
        if run_key.is_empty() {
            return;
        }
        if self.selected_runs.contains(run_key) {
            self.drop_run(run_key);
            return;
        }

        // Resolve the run file before mutating selection state so we don't
        // end up "selected but unloadable".
        let wandb_file = self.run_path_for_key(run_key);
        if wandb_file.is_empty() {
            return;
        }
        let Some(tx) = self.tx.clone() else { return };

        self.selected_runs.insert(run_key.to_string());
        if self.pinned_run.is_empty() {
            self.pinned_run = run_key.to_string();
        }

        let reader = spawn_reader(wandb_file.clone(), tx);
        self.source_to_run
            .insert(reader.source_id, run_key.to_string());
        self.runs_by_key.insert(
            run_key.to_string(),
            WorkspaceRun {
                reader: Some(reader),
                wandb_path: wandb_file,
                state: RunState::Unknown,
            },
        );
    }

    fn toggle_pin(&mut self, run_key: &str) {
        if run_key.is_empty() {
            return;
        }
        if self.pinned_run == run_key {
            // Unpin but keep selection unchanged.
            self.pinned_run.clear();
            self.metrics_grid.draw_visible();
            return;
        }
        self.pinned_run = run_key.to_string();
        self.refresh_pinned_run();
        self.metrics_grid.draw_visible();
    }

    // ---- Messages ----

    pub fn handle_msg(&mut self, msg: Msg, config: &ConfigManager) {
        match msg {
            Msg::RunDirs { keys } => self.handle_run_dirs(keys),
            Msg::RunPreloaded { run_key, run } => {
                self.handle_run_preloaded(&run_key, run.as_deref());
            }
            Msg::Batch {
                source_id, msgs, ..
            } => {
                let Some(run_key) = self.source_to_run.get(&source_id).cloned() else {
                    return;
                };
                for record in msgs {
                    self.handle_workspace_record(&run_key, record, config);
                }
                self.metrics_grid.draw_visible();
            }
            Msg::ReaderError { source_id, .. } => {
                // The affected run simply stops streaming.
                if let Some(run_key) = self.source_to_run.get(&source_id).cloned() {
                    self.drop_run(&run_key);
                }
            }
            _ => {}
        }
    }

    fn handle_workspace_record(
        &mut self,
        run_key: &str,
        record: RecordMsg,
        config: &ConfigManager,
    ) {
        match record {
            RecordMsg::Run(msg) => {
                self.get_or_create_run_overview(run_key)
                    .process_run_msg(&msg);
                self.index_run_filter_data(run_key, &msg);
                if !self.filter.query().is_empty() {
                    self.apply_run_filter();
                }
                if let Some(run) = self.runs_by_key.get_mut(run_key) {
                    run.state = RunState::Running;
                }
            }
            RecordMsg::History(msg) => {
                self.metrics_grid.process_history(&msg);
                let synced = self
                    .get_or_create_media_store(run_key)
                    .process_history(&msg);
                if synced
                    && self.current_media_run_key == run_key
                    && let Some(store) = self.media.get(run_key)
                {
                    self.media_pane.sync_state(store);
                }
                if !self.pinned_run.is_empty() {
                    self.refresh_pinned_run();
                }
            }
            RecordMsg::Stats(msg) => {
                self.get_or_create_system_metrics_grid(run_key, config)
                    .process_stats(&msg);
            }
            RecordMsg::SystemInfo { record, .. } => {
                self.get_or_create_run_overview(run_key)
                    .process_system_info(&record);
            }
            RecordMsg::Summary { summary, .. } => {
                self.get_or_create_run_overview(run_key)
                    .process_summary(&summary);
            }
            RecordMsg::ConsoleLog(msg) => {
                let ts = msg
                    .time
                    .unwrap_or_else(SystemTime::now)
                    .duration_since(UNIX_EPOCH)
                    .map(|d| d.as_secs() as i64)
                    .unwrap_or(0);
                self.get_or_create_console_logs(run_key)
                    .process_raw(&msg.text, msg.is_stderr, ts);
            }
            RecordMsg::FileComplete { exit_code } => {
                let state = if exit_code == 0 {
                    RunState::Finished
                } else {
                    RunState::Failed
                };
                if let Some(run) = self.runs_by_key.get_mut(run_key) {
                    run.state = state;
                }
                self.get_or_create_run_overview(run_key)
                    .set_run_state(state);
            }
        }
    }

    fn handle_run_dirs(&mut self, run_keys: Vec<String>) {
        if !self.run_keys_equal(&run_keys) {
            self.apply_run_keys(&run_keys);
            // Auto-select the latest run on initial workspace load.
            if !self.auto_selected_latest && !run_keys.is_empty() {
                self.auto_selected_latest = true;
                let latest = run_keys[0].clone();
                self.toggle_run_selected(&latest);
            }
        }
        // Enqueue missing run overviews (even if the run list is unchanged),
        // making new overviews eventually consistent even if the .wandb file
        // wasn't readable on the first scan.
        self.enqueue_missing_run_overviews(&run_keys);
        self.start_run_overview_preloads();
    }

    fn handle_run_preloaded(&mut self, run_key: &str, run: Option<&RunMsg>) {
        self.preloader.mark_done(run_key);

        if let Some(run) = run
            && !run.id.is_empty()
        {
            let ro = self.get_or_create_run_overview(run_key);
            ro.process_run_msg(run);
            // We don't know the final state of this run after a pre-load.
            ro.set_run_state(RunState::Unknown);
            self.index_run_filter_data(run_key, run);
            if !self.filter.query().is_empty() {
                self.apply_run_filter();
            }
        }

        // Keep draining the queue.
        self.start_run_overview_preloads();
    }

    fn enqueue_missing_run_overviews(&mut self, run_keys: &[String]) {
        for run_key in run_keys {
            if !self.run_overview.contains_key(run_key) {
                self.preloader.enqueue(run_key);
            }
        }
    }

    fn start_run_overview_preloads(&mut self) {
        let Some(tx) = self.tx.clone() else { return };
        for run_key in self.preloader.dequeue_startable() {
            let wandb_file = self.run_path_for_key(&run_key);
            if wandb_file.is_empty() {
                self.preloader.mark_done(&run_key);
                continue;
            }
            spawn_run_preload(run_key, wandb_file, tx.clone());
        }
    }

    fn run_keys_equal(&self, run_keys: &[String]) -> bool {
        run_keys.len() == self.runs.items.len()
            && run_keys
                .iter()
                .zip(&self.runs.items)
                .all(|(key, item)| *key == item.key)
    }

    fn apply_run_keys(&mut self, run_keys: &[String]) {
        // Preserve the currently highlighted run key if possible.
        let prev_cursor_key = self.current_run_key();

        let present: HashSet<String> = run_keys.iter().cloned().collect();

        // Drop queued (not in-flight) overview preloads for runs that
        // disappeared.
        self.preloader.drop_queued_not_present(&present);

        // If the pinned run disappeared, clear it.
        if !self.pinned_run.is_empty() && !present.contains(&self.pinned_run) {
            self.pinned_run.clear();
        }

        // Deselect and clean up any loaded run that no longer exists.
        let stale: Vec<String> = self
            .selected_runs
            .iter()
            .chain(self.runs_by_key.keys())
            .filter(|key| !present.contains(*key))
            .cloned()
            .collect();
        for key in stale {
            self.drop_run(&key);
        }

        self.run_overview.retain(|key, _| present.contains(key));
        self.runs_filter_index
            .retain(|key, _| present.contains(key));

        let released: Vec<String> = self
            .runs
            .items
            .iter()
            .filter(|item| !present.contains(&item.key))
            .map(|item| self.run_path_for_key(&item.key))
            .collect();
        for run_path in released {
            self.run_colors.borrow_mut().release(&run_path);
        }

        self.set_run_items(run_keys);

        if let Some(key) = prev_cursor_key {
            self.restore_run_cursor(&key);
        }
        self.sync_runs_page();
    }

    fn set_run_items(&mut self, run_keys: &[String]) {
        self.runs.items = run_keys
            .iter()
            .map(|key| KeyValuePair {
                key: key.clone(),
                value: String::new(),
                path: Vec::new(),
            })
            .collect();
        self.apply_run_filter();
    }

    fn restore_run_cursor(&mut self, run_key: &str) {
        let ipp = self.runs.items_per_page();
        if run_key.is_empty() || ipp == 0 {
            return;
        }
        if let Some(idx) = self
            .runs
            .filtered_items
            .iter()
            .position(|it| it.key == run_key)
        {
            self.runs.set_page_and_line(idx / ipp, idx % ipp);
        }
    }

    /// Clamps the runs list page/line against the current item set and
    /// returns the bounds of the visible slice `[start, end)`.
    fn sync_runs_page(&mut self) -> (usize, usize) {
        let total = self.runs.filtered_items.len();
        let ipp = self.runs.items_per_page();

        if total == 0 || ipp == 0 {
            self.runs.home();
            return (0, 0);
        }

        let total_pages = total.div_ceil(ipp).max(1);
        let page = self.runs.current_page().min(total_pages - 1);

        let start = page * ipp;
        let end = (start + ipp).min(total);

        let max_line = (end - start).saturating_sub(1);
        let line = self.runs.current_line().min(max_line);

        self.runs.set_page_and_line(page, line);
        (start, end)
    }

    // ---- Runs filter ----

    /// Caches searchable metadata derived from a RunMsg.
    fn index_run_filter_data(&mut self, run_key: &str, msg: &RunMsg) {
        let mut data = WorkspaceRunFilterData::from_run_msg(run_key, msg);
        if let Some(existing) = self.runs_filter_index.get(run_key) {
            data = data.merge_over(existing);
        }
        self.runs_filter_index.insert(run_key.to_string(), data);
    }

    /// Reevaluates the runs sidebar against the current filter query,
    /// preserving the cursor when the focused run remains visible.
    fn apply_run_filter(&mut self) {
        let prev_cursor_key = self.current_run_key();

        let query = self.filter.query().to_string();
        if query.is_empty() {
            self.runs.filtered_items = self.runs.items.clone();
        } else {
            let compiled = RunFilterQuery::compile(&query, self.filter.mode());
            self.runs.filtered_items = self
                .runs
                .items
                .iter()
                .filter(|item| match self.runs_filter_index.get(&item.key) {
                    Some(data) => compiled.matches(data),
                    None => compiled.matches(&WorkspaceRunFilterData::from_key(&item.key)),
                })
                .cloned()
                .collect();
        }

        if let Some(key) = prev_cursor_key {
            self.restore_run_cursor(&key);
        }
        self.sync_runs_page();
    }

    fn handle_run_filter_key(&mut self, fk: FilterKey) {
        if self.filter.handle_key(fk) {
            self.apply_run_filter();
        }
    }

    /// Focuses the runs sidebar and enters runs filter input mode,
    /// expanding the sidebar first if it is collapsed.
    fn enter_runs_filter(&mut self) {
        if !self.runs_anim.is_expanded() && !self.runs_anim.is_animating() {
            self.toggle_runs_sidebar();
        }
        self.runs.active = true;
        self.console_logs_pane.set_active(false);
        self.overview_sidebar.deactivate_all_sections();
        self.filter.activate();
        self.apply_run_filter();
    }

    fn clear_runs_filter(&mut self) {
        if self.filter.query().is_empty() && !self.filter.is_active() {
            return;
        }
        self.filter.clear();
        self.apply_run_filter();
    }

    // ---- Animation ----

    /// Advances all animations. Returns true while any is still animating.
    pub fn tick(&mut self, now: Instant) -> bool {
        let mut changed = false;

        if self.runs_anim.is_animating() {
            self.runs_anim.update(now);
            changed = true;
        }
        if self.overview_sidebar.is_animating() {
            self.overview_sidebar.update_animation(now);
            changed = true;
        }
        if self.metrics_grid_anim.is_animating() {
            self.metrics_grid_anim.update(now);
            changed = true;
        }
        if self.system_metrics_pane.is_animating() {
            self.system_metrics_pane.update(now);
            changed = true;
        }
        if self.media_pane.is_animating() {
            self.media_pane.update(now);
            changed = true;
        }
        if self.console_logs_pane.is_animating() {
            self.console_logs_pane.update(now);
            changed = true;
        }

        if changed {
            self.update_sidebar_dimensions(
                self.runs_anim.target_visible(),
                self.overview_sidebar.target_visible(),
            );
            self.update_bottom_pane_heights(
                self.system_metrics_pane.anim_state.target_visible(),
                self.media_pane.target_visible(),
                self.console_logs_pane.target_visible(),
            );
            self.recalculate_layout();
        }

        self.runs_anim.is_animating()
            || self.overview_sidebar.is_animating()
            || self.metrics_grid_anim.is_animating()
            || self.system_metrics_pane.is_animating()
            || self.media_pane.is_animating()
            || self.console_logs_pane.is_animating()
    }

    // ---- Layout ----

    pub fn handle_resize(&mut self, width: i32, height: i32) {
        self.set_size(width, height);
        self.update_sidebar_dimensions(
            self.runs_anim.target_visible(),
            self.overview_sidebar.target_visible(),
        );
        self.update_bottom_pane_heights(
            self.system_metrics_pane.anim_state.target_visible(),
            self.media_pane.target_visible(),
            self.console_logs_pane.target_visible(),
        );
        self.recalculate_layout();
    }

    fn set_size(&mut self, width: i32, height: i32) {
        self.width = width;
        self.height = height;

        let content_height = height
            - STATUS_BAR_HEIGHT as i32
            - WORKSPACE_HEADER_LINES
            - SIDEBAR_BOTTOM_PADDING as i32;
        self.runs.set_items_per_page(content_height.max(1) as usize);

        self.media_pane.update_expanded_height(height);
        self.console_logs_pane.update_expanded_height(height);
    }

    /// Recomputes viewports and pushes dimensions to the metrics grid. Call
    /// after any change that affects available content area.
    fn recalculate_layout(&mut self) {
        let layout = self.compute_viewports();
        self.metrics_grid
            .update_dimensions(layout.main_content_area_width, layout.height);
    }

    pub fn compute_viewports(&self) -> WorkspaceLayout {
        let left_w = self.runs_anim.value();
        let right_w = self.overview_sidebar.width();
        let content_w = (self.width - left_w - right_w).max(1);
        let total_h = (self.height - STATUS_BAR_HEIGHT as i32).max(0);

        let stack = compute_vertical_stack_layout(
            total_h,
            &[
                StackSectionSpec {
                    id: StackSection::Metrics,
                    visible: self.metrics_grid_anim.is_visible(),
                    height: 0,
                    flex: true,
                },
                StackSectionSpec {
                    id: StackSection::SystemMetrics,
                    visible: self.system_metrics_pane.is_visible(),
                    height: self.system_metrics_pane.height(),
                    flex: false,
                },
                StackSectionSpec {
                    id: StackSection::Media,
                    visible: self.media_pane.is_visible(),
                    height: self.media_pane.height(),
                    flex: false,
                },
                StackSectionSpec {
                    id: StackSection::ConsoleLogs,
                    visible: self.console_logs_pane.is_visible(),
                    height: self.console_logs_pane.height(),
                    flex: false,
                },
            ],
        );

        WorkspaceLayout {
            left_sidebar_width: left_w,
            main_content_area_width: content_w,
            right_sidebar_width: right_w,
            total_content_area_height: total_h,
            height: stack.height(StackSection::Metrics),
            system_metrics_y: stack.y(StackSection::SystemMetrics),
            system_metrics_height: stack.height(StackSection::SystemMetrics),
            media_y: stack.y(StackSection::Media),
            media_height: stack.height(StackSection::Media),
            console_logs_y: stack.y(StackSection::ConsoleLogs),
            console_logs_height: stack.height(StackSection::ConsoleLogs),
        }
    }

    /// Tells both sidebars to recalculate their expanded widths given the
    /// post-toggle visibility of each side.
    fn update_sidebar_dimensions(&mut self, left_visible: bool, right_visible: bool) {
        self.runs_anim.set_expanded(sidebar_width_for(
            self.width,
            right_visible,
            self.layout.left_sidebar,
        ));
        self.overview_sidebar
            .update_dimensions(self.width, left_visible);
    }

    fn update_bottom_pane_heights(
        &mut self,
        sys_visible: bool,
        media_visible: bool,
        logs_visible: bool,
    ) {
        let metrics_visible = self.metrics_grid_anim.target_visible();

        let section_count = [metrics_visible, sys_visible, media_visible, logs_visible]
            .iter()
            .filter(|&&v| v)
            .count() as i32;
        let sep_lines = (section_count - 1).max(0);

        let max_h = (self.height - STATUS_BAR_HEIGHT as i32 - sep_lines).max(0);
        let lower_count = [sys_visible, media_visible, logs_visible]
            .iter()
            .filter(|&&v| v)
            .count() as i32;
        if lower_count == 0 {
            return;
        }

        let lower_tier_h = if metrics_visible {
            (max_h as f64 * LOWER_TIER_RATIO) as i32
        } else {
            max_h
        };

        let each = lower_tier_h / lower_count;
        let total_height = self.height;
        let h_for = move |fraction: Option<f64>| match fraction {
            Some(f) => ((total_height as f64 * f).round() as i32).min(max_h),
            None => each,
        };
        if sys_visible {
            self.system_metrics_pane
                .set_expanded_height(h_for(self.layout.system));
        }
        if media_visible {
            self.media_pane
                .set_expanded_height(h_for(self.layout.media));
        }
        if logs_visible {
            self.console_logs_pane
                .set_expanded_height(h_for(self.layout.logs));
        }
    }

    // ---- Focus ----

    fn with_focus_mgr(&mut self, f: impl FnOnce(&mut FocusManager, &mut Self)) {
        let mut fm = std::mem::take(&mut self.focus_mgr);
        f(&mut fm, self);
        self.focus_mgr = fm;
    }

    // Note: unlike the run view, the workspace never resolves focus on data
    // availability changes; focus only moves on explicit visibility toggles.
    // This keeps the runs list focused at startup while panes stream in.
    fn resolve_focus_after_visibility_change(&mut self) {
        self.with_focus_mgr(|fm, view| fm.resolve_after_visibility_change(view));
    }

    fn adopt_chart_mouse_focus(&mut self) {
        let target = if self.metrics_grid.focus.ty == FocusType::MainChart {
            FocusTarget::MetricsGrid
        } else if self
            .active_system_metrics_grid_ref()
            .is_some_and(|g| g.focus.ty == FocusType::SystemChart)
        {
            FocusTarget::SystemMetrics
        } else {
            return;
        };
        self.with_focus_mgr(|fm, view| fm.adopt_target(view, target));
    }

    /// Clears focus from both the main metrics grid and the current run's
    /// system metrics grid.
    fn clear_chart_focus(&mut self) {
        self.metrics_grid.clear_focus();
        if let Some(grid) = self.active_system_metrics_grid() {
            grid.clear_focus();
        }
    }

    /// Tries to move within overview sections. Returns true if handled
    /// (i.e. we're not at a boundary).
    fn cycle_overview_section(&mut self, direction: i32) -> bool {
        let Some((first, last)) = self.overview_sidebar.focusable_section_bounds() else {
            return false;
        };
        if !self.overview_sidebar.is_expanded() {
            return false;
        }

        let active = self.overview_sidebar.active_section();
        let at_boundary =
            (direction == 1 && active == last) || (direction == -1 && active == first);
        if at_boundary {
            return false;
        }

        self.overview_sidebar.navigate_section(direction);
        true
    }

    // ---- Keys ----

    pub fn handle_key(&mut self, key: &KeyEvent, config: &mut ConfigManager) -> WorkspaceAction {
        // Filter modes take priority.
        if self.filter.is_active() {
            if let Some(fk) = FilterKey::from_event(key) {
                self.handle_run_filter_key(fk);
            }
            return WorkspaceAction::None;
        }
        if self.overview_sidebar.is_filter_mode() {
            if let Some(fk) = FilterKey::from_event(key) {
                let cur = self.current_run_key().unwrap_or_default();
                let overview = self.run_overview.get(&cur).unwrap_or(&self.empty_overview);
                self.overview_sidebar.handle_filter_key(fk, overview);
            }
            return WorkspaceAction::None;
        }
        if self.metrics_grid.is_filter_mode() {
            if let Some(fk) = FilterKey::from_event(key) {
                self.metrics_grid.handle_filter_key(fk);
            }
            return WorkspaceAction::None;
        }
        if self
            .active_system_metrics_grid_ref()
            .is_some_and(|g| g.is_filter_mode())
        {
            if let (Some(fk), Some(grid)) = (
                FilterKey::from_event(key),
                self.active_system_metrics_grid(),
            ) {
                grid.handle_filter_key(fk);
            }
            return WorkspaceAction::None;
        }

        // Grid config capture takes priority.
        if config.is_awaiting_grid_config() {
            self.handle_config_number_key(key, config);
            return WorkspaceAction::None;
        }

        // Focus-aware key dispatch.
        match self.focus_mgr.current() {
            FocusTarget::MetricsGrid | FocusTarget::SystemMetrics => {
                if self.handle_grid_nav(key) {
                    return WorkspaceAction::None;
                }
            }
            FocusTarget::Media => {
                let cur = self.current_run_key().unwrap_or_default();
                let store = self.media.get(&cur).unwrap_or(&self.empty_media);
                if self.media_pane.handle_key(key, store) {
                    return WorkspaceAction::None;
                }
            }
            _ => {}
        }

        let ctrl = key.modifiers.contains(KeyModifiers::CONTROL);
        match key.code {
            KeyCode::Char('q') => return WorkspaceAction::Quit,
            KeyCode::Char('c') if ctrl => return WorkspaceAction::Quit,

            KeyCode::Esc => self.handle_focus_runs(),
            KeyCode::Enter => {
                if self.run_selector_active() {
                    let run_key = self.selected_run_key();
                    let wandb_file = self.selected_run_wandb_file();
                    if !wandb_file.is_empty() {
                        return WorkspaceAction::OpenRun {
                            run_key,
                            wandb_file,
                        };
                    }
                }
            }

            KeyCode::Char('1') => self.toggle_metrics_grid(config),
            KeyCode::Char('[') => self.toggle_runs_sidebar(),
            KeyCode::Char('2') => self.toggle_system_metrics_pane(config),
            KeyCode::Char(']') => self.toggle_overview_sidebar(config),
            KeyCode::Char('3') => self.toggle_media_pane(config),
            KeyCode::Char('4') => self.toggle_console_logs_pane(config),
            KeyCode::Char('0') => self.reset_layout(config),

            KeyCode::Char('y') => self.cycle_focused_chart_mode(),

            KeyCode::Char('f') if ctrl => self.clear_runs_filter(),
            KeyCode::Char('f') => self.enter_runs_filter(),

            KeyCode::Char('/') if ctrl => self.clear_metrics_filter(),
            KeyCode::Char('l') if ctrl => self.clear_metrics_filter(),
            KeyCode::Char('\\') if ctrl => self.clear_system_metrics_filter(),
            KeyCode::Char('o') if ctrl => {
                if self.overview_sidebar.is_filtering() {
                    let cur = self.current_run_key().unwrap_or_default();
                    let overview = self.run_overview.get(&cur).unwrap_or(&self.empty_overview);
                    self.overview_sidebar.clear_filter(overview);
                }
            }
            KeyCode::Char('/') => self.metrics_grid.enter_filter_mode(),
            KeyCode::Char('\\') => self.enter_system_metrics_filter(config),
            KeyCode::Char('o') => self.overview_sidebar.enter_filter_mode(),

            KeyCode::Char('c') => self.config_focused_cols(config),
            KeyCode::Char('r') => self.config_focused_rows(config),

            KeyCode::Char(' ') => self.handle_toggle_run_selected_key(),
            KeyCode::Char('p') => self.handle_pin_run_key(),

            KeyCode::Tab => self.handle_sidebar_tab_nav(1),
            KeyCode::BackTab => self.handle_sidebar_tab_nav(-1),

            _ => match decode_nav(key) {
                NavIntent::Up => self.handle_runs_vertical_nav(true),
                NavIntent::Down => self.handle_runs_vertical_nav(false),
                NavIntent::Left => self.handle_runs_page_nav(true),
                NavIntent::Right => self.handle_runs_page_nav(false),
                NavIntent::PageUp => self.handle_prev_page(),
                NavIntent::PageDown => self.handle_next_page(),
                NavIntent::Home => self.handle_nav_home(),
                NavIntent::End => self.handle_nav_end(),
                _ => {}
            },
        }

        WorkspaceAction::None
    }

    fn handle_config_number_key(&mut self, key: &KeyEvent, config: &mut ConfigManager) {
        let digit = match key.code {
            KeyCode::Esc => Option::None,
            KeyCode::Char(c) => c.to_digit(10),
            _ => Option::None,
        };
        if let Some(num) = digit
            && config.set_grid_config(num as i32).is_some()
        {
            self.sync_grid_shapes_from_config(config);
            self.recalculate_layout();
        }
        config.set_pending_grid_config(GridConfigTarget::None);
    }

    /// Propagates configured grid shapes to the grids/panes after a change.
    fn sync_grid_shapes_from_config(&mut self, config: &ConfigManager) {
        let cfg = config.config();
        self.metrics_grid.set_grid_shape(
            cfg.workspace_metrics_grid.rows,
            cfg.workspace_metrics_grid.cols,
        );
        let settings = workspace_system_grid_settings(cfg);
        for grid in self.system_metrics.values_mut() {
            grid.set_settings(settings.clone());
        }
        self.media_pane
            .set_grid_config(cfg.workspace_media_grid.rows, cfg.workspace_media_grid.cols);
    }

    /// Handles navigation keys while a chart grid holds focus. Returns
    /// whether the key was consumed.
    fn handle_grid_nav(&mut self, key: &KeyEvent) -> bool {
        let intent = decode_nav(key);
        if intent == NavIntent::None {
            return false;
        }

        let system = self.focus_mgr.current() == FocusTarget::SystemMetrics;
        macro_rules! grid {
            ($m:ident($($a:expr),*)) => {
                if system {
                    if let Some(g) = self.active_system_metrics_grid() {
                        g.$m($($a),*);
                    }
                } else {
                    self.metrics_grid.$m($($a),*);
                }
            };
        }

        match intent {
            NavIntent::Up => grid!(navigate_focus(-1, 0)),
            NavIntent::Down => grid!(navigate_focus(1, 0)),
            NavIntent::Left => grid!(navigate_focus(0, -1)),
            NavIntent::Right => grid!(navigate_focus(0, 1)),
            NavIntent::PageUp => grid!(navigate(-1)),
            NavIntent::PageDown => grid!(navigate(1)),
            NavIntent::Home => grid!(navigate_home()),
            NavIntent::End => grid!(navigate_end()),
            NavIntent::None => return false,
        }
        true
    }

    fn handle_prev_page(&mut self) {
        match self.focus_mgr.current() {
            FocusTarget::MetricsGrid => self.metrics_grid.navigate(-1),
            FocusTarget::SystemMetrics => {
                if let Some(g) = self.active_system_metrics_grid() {
                    g.navigate(-1);
                }
            }
            FocusTarget::Media => self.media_pane_nav_page(-1),
            FocusTarget::RunsList => self.runs.page_up(),
            FocusTarget::Overview => self.overview_sidebar.navigate_page_up(),
            FocusTarget::ConsoleLogs => self.console_logs_pane.page_up(),
            _ => {}
        }
    }

    fn handle_next_page(&mut self) {
        match self.focus_mgr.current() {
            FocusTarget::MetricsGrid => self.metrics_grid.navigate(1),
            FocusTarget::SystemMetrics => {
                if let Some(g) = self.active_system_metrics_grid() {
                    g.navigate(1);
                }
            }
            FocusTarget::Media => self.media_pane_nav_page(1),
            FocusTarget::RunsList => self.runs.page_down(),
            FocusTarget::Overview => self.overview_sidebar.navigate_page_down(),
            FocusTarget::ConsoleLogs => self.console_logs_pane.page_down(),
            _ => {}
        }
    }

    fn handle_nav_home(&mut self) {
        match self.focus_mgr.current() {
            FocusTarget::MetricsGrid => self.metrics_grid.navigate_home(),
            FocusTarget::SystemMetrics => {
                if let Some(g) = self.active_system_metrics_grid() {
                    g.navigate_home();
                }
            }
            FocusTarget::Media => self.with_media_store(|pane, store| pane.scrub_to_start(store)),
            FocusTarget::RunsList => self.runs.home(),
            FocusTarget::Overview => self.overview_sidebar.navigate_home(),
            FocusTarget::ConsoleLogs => self.console_logs_pane.scroll_to_start(),
            _ => {}
        }
    }

    fn handle_nav_end(&mut self) {
        match self.focus_mgr.current() {
            FocusTarget::MetricsGrid => self.metrics_grid.navigate_end(),
            FocusTarget::SystemMetrics => {
                if let Some(g) = self.active_system_metrics_grid() {
                    g.navigate_end();
                }
            }
            FocusTarget::Media => self.with_media_store(|pane, store| pane.scrub_to_end(store)),
            FocusTarget::RunsList => self.runs.end(),
            FocusTarget::Overview => self.overview_sidebar.navigate_end(),
            FocusTarget::ConsoleLogs => self.console_logs_pane.scroll_to_end_and_follow(),
            _ => {}
        }
    }

    /// Runs a media-pane operation with the current run's store.
    fn with_media_store(&mut self, f: impl FnOnce(&mut MediaPane, &MediaStore)) {
        let cur = self.current_run_key().unwrap_or_default();
        let store = self.media.get(&cur).unwrap_or(&self.empty_media);
        f(&mut self.media_pane, store);
    }

    fn media_pane_nav_page(&mut self, direction: i32) {
        self.with_media_store(|pane, store| pane.navigate_page(store, direction));
    }

    fn cycle_focused_chart_mode(&mut self) {
        if self.metrics_grid.focus.ty == FocusType::MainChart {
            self.metrics_grid.toggle_focused_chart_log_y();
        } else if let Some(g) = self.active_system_metrics_grid()
            && g.focus.ty == FocusType::SystemChart
        {
            g.cycle_focused_chart_mode();
        }
    }

    fn clear_metrics_filter(&mut self) {
        if !self.metrics_grid.filter_query().is_empty() {
            self.metrics_grid.clear_filter();
        }
        if self.focus_mgr.current() == FocusTarget::MetricsGrid {
            self.metrics_grid.navigate_focus(0, 0);
        }
    }

    fn enter_system_metrics_filter(&mut self, config: &mut ConfigManager) {
        if !self.system_metrics_pane.is_expanded() && !self.system_metrics_pane.is_animating() {
            self.toggle_system_metrics_pane(config);
        }

        let Some(cur) = self.current_run_key() else {
            return;
        };
        if !self.selected_runs.contains(&cur) {
            return;
        }

        let grid = self.get_or_create_system_metrics_grid(&cur, config);
        grid.enter_filter_mode();
        grid.apply_filter();
    }

    fn clear_system_metrics_filter(&mut self) {
        if let Some(g) = self.active_system_metrics_grid()
            && !g.filter_query().is_empty()
        {
            g.clear_filter();
        }
        if self.focus_mgr.current() == FocusTarget::SystemMetrics
            && let Some(g) = self.active_system_metrics_grid()
        {
            g.navigate_focus(0, 0);
        }
    }

    fn config_focused_cols(&mut self, config: &mut ConfigManager) {
        let target = match self.focus_mgr.current() {
            FocusTarget::SystemMetrics => GridConfigTarget::WorkspaceSystemCols,
            FocusTarget::Media => GridConfigTarget::WorkspaceMediaCols,
            _ => GridConfigTarget::WorkspaceMetricsCols,
        };
        config.set_pending_grid_config(target);
    }

    fn config_focused_rows(&mut self, config: &mut ConfigManager) {
        let target = match self.focus_mgr.current() {
            FocusTarget::SystemMetrics => GridConfigTarget::WorkspaceSystemRows,
            FocusTarget::Media => GridConfigTarget::WorkspaceMediaRows,
            _ => GridConfigTarget::WorkspaceMetricsRows,
        };
        config.set_pending_grid_config(target);
    }

    fn handle_toggle_run_selected_key(&mut self) {
        if !self.run_selector_active() {
            return;
        }
        if let Some(key) = self.current_run_key() {
            self.toggle_run_selected(&key);
        }
    }

    /// Pinning selects the run first if needed, so its series exists and can
    /// be promoted/drawn.
    fn handle_pin_run_key(&mut self) {
        if !self.run_selector_active() {
            return;
        }
        let Some(run_key) = self.current_run_key() else {
            return;
        };

        if !self.selected_runs.contains(&run_key) {
            self.toggle_run_selected(&run_key);
            if !self.selected_runs.contains(&run_key) {
                return;
            }
            // toggle_run_selected may auto-pin when pinned_run was empty.
            if self.pinned_run != run_key {
                self.toggle_pin(&run_key);
            }
            return;
        }

        self.toggle_pin(&run_key);
    }

    /// Moves focus to the runs list if it's visible, giving Esc a natural
    /// "return home" feel in workspace mode.
    fn handle_focus_runs(&mut self) {
        if self.runs_anim.target_visible() {
            self.with_focus_mgr(|fm, view| fm.set_target(view, FocusTarget::RunsList, 1));
        }
    }

    /// Cycles focus between panes; within the overview region, Tab first
    /// cycles through sections.
    fn handle_sidebar_tab_nav(&mut self, direction: i32) {
        if self.focus_mgr.is_target(FocusTarget::Overview) && self.cycle_overview_section(direction)
        {
            return;
        }
        self.with_focus_mgr(|fm, view| fm.tab(view, direction));
    }

    fn handle_runs_vertical_nav(&mut self, up: bool) {
        match self.focus_mgr.current() {
            FocusTarget::ConsoleLogs => {
                if up {
                    self.console_logs_pane.up();
                } else {
                    self.console_logs_pane.down();
                }
            }
            FocusTarget::RunsList => {
                if up {
                    self.runs.up();
                } else {
                    self.runs.down();
                }
            }
            FocusTarget::Overview => {
                if up {
                    self.overview_sidebar.navigate_up();
                } else {
                    self.overview_sidebar.navigate_down();
                }
            }
            _ => {}
        }
    }

    fn handle_runs_page_nav(&mut self, left: bool) {
        match self.focus_mgr.current() {
            FocusTarget::ConsoleLogs => {
                if left {
                    self.console_logs_pane.page_up();
                } else {
                    self.console_logs_pane.page_down();
                }
            }
            FocusTarget::RunsList => {
                if left {
                    self.runs.page_up();
                } else {
                    self.runs.page_down();
                }
            }
            FocusTarget::Overview => {
                if left {
                    self.overview_sidebar.navigate_page_up();
                } else {
                    self.overview_sidebar.navigate_page_down();
                }
            }
            _ => {}
        }
    }

    // ---- Pane toggles ----

    fn toggle_metrics_grid(&mut self, config: &mut ConfigManager) {
        let will_be_visible = !self.metrics_grid_anim.target_visible();
        config.update(|c| c.workspace_metrics_grid_visible = will_be_visible);

        self.metrics_grid_anim.toggle();
        self.resolve_focus_after_visibility_change();

        self.update_bottom_pane_heights(
            self.system_metrics_pane.anim_state.target_visible(),
            self.media_pane.target_visible(),
            self.console_logs_pane.target_visible(),
        );
        self.recalculate_layout();
    }

    /// Whether the runs sidebar is (or is animating toward) visible.
    #[cfg(test)]
    pub(crate) fn runs_sidebar_target_visible(&self) -> bool {
        self.runs_anim.target_visible()
    }

    fn toggle_runs_sidebar(&mut self) {
        let left_will_be_visible = !self.runs_anim.target_visible();
        let right_is_visible = self.overview_sidebar.target_visible();

        self.update_sidebar_dimensions(left_will_be_visible, right_is_visible);
        self.runs_anim.toggle();
        self.resolve_focus_after_visibility_change();
        self.recalculate_layout();
    }

    fn toggle_overview_sidebar(&mut self, config: &mut ConfigManager) {
        let right_will_be_visible = !self.overview_sidebar.target_visible();
        let left_is_visible = self.runs_anim.target_visible();
        config.update(|c| c.workspace_overview_visible = right_will_be_visible);

        self.update_sidebar_dimensions(left_is_visible, right_will_be_visible);
        self.overview_sidebar.toggle();
        self.resolve_focus_after_visibility_change();
        self.recalculate_layout();
    }

    fn toggle_media_pane(&mut self, config: &mut ConfigManager) {
        let will_be_visible = !self.media_pane.target_visible();
        config.update(|c| c.workspace_media_visible = will_be_visible);

        if !will_be_visible {
            self.media_pane.exit_fullscreen();
        }
        self.update_bottom_pane_heights(
            self.system_metrics_pane.anim_state.target_visible(),
            will_be_visible,
            self.console_logs_pane.target_visible(),
        );
        self.media_pane.toggle();
        if !will_be_visible {
            self.resolve_focus_after_visibility_change();
        }
        self.recalculate_layout();
    }

    fn toggle_console_logs_pane(&mut self, config: &mut ConfigManager) {
        let will_be_visible = !self.console_logs_pane.target_visible();
        config.update(|c| c.workspace_console_logs_visible = will_be_visible);

        self.update_bottom_pane_heights(
            self.system_metrics_pane.anim_state.target_visible(),
            self.media_pane.target_visible(),
            will_be_visible,
        );
        self.console_logs_pane.toggle();
        self.resolve_focus_after_visibility_change();
        self.recalculate_layout();
    }

    fn toggle_system_metrics_pane(&mut self, config: &mut ConfigManager) {
        let sys_will_be_visible = !self.system_metrics_pane.anim_state.target_visible();
        config.update(|c| c.workspace_system_metrics_visible = sys_will_be_visible);

        self.update_bottom_pane_heights(
            sys_will_be_visible,
            self.media_pane.target_visible(),
            self.console_logs_pane.target_visible(),
        );
        self.system_metrics_pane.toggle();
        self.resolve_focus_after_visibility_change();
        self.recalculate_layout();
    }

    // ---- Layout resizing (mouse) ----

    /// Handles mouse-driven pane resizing on the sidebar borders and the
    /// separator rows. Returns whether the event was consumed.
    fn handle_layout_drag(
        &mut self,
        event: &MouseEvent,
        layout: &WorkspaceLayout,
        config: &mut ConfigManager,
    ) -> bool {
        if self.media_pane.is_fullscreen() {
            return false;
        }
        let x = event.column as i32;
        let y = event.row as i32;

        match event.kind {
            MouseEventKind::Down(MouseButton::Left) => {
                let Some(boundary) = self.boundary_at(x, y, layout) else {
                    return false;
                };
                self.drag = Some(boundary);
                true
            }
            MouseEventKind::Drag(MouseButton::Left) => {
                let Some(boundary) = self.drag else {
                    return false;
                };
                self.apply_drag(boundary, x, y);
                true
            }
            MouseEventKind::Up(MouseButton::Left) => {
                if self.drag.take().is_none() {
                    return false;
                }
                let overrides = self.layout;
                config.update(|c| c.workspace_layout = overrides);
                true
            }
            _ => false,
        }
    }

    /// The draggable boundary at (x, y), if any: a sidebar border column or
    /// a separator row between stacked panes.
    fn boundary_at(&self, x: i32, y: i32, layout: &WorkspaceLayout) -> Option<DragBoundary> {
        if y >= layout.total_content_area_height {
            return None;
        }

        if self.runs_anim.is_expanded() && x == layout.left_sidebar_width - 1 {
            return Some(DragBoundary::LeftSidebar);
        }
        if self.overview_sidebar.is_expanded() && x == self.width - layout.right_sidebar_width {
            return Some(DragBoundary::RightSidebar);
        }

        // Separator rows only exist within the central column.
        if x < layout.left_sidebar_width || x >= self.width - layout.right_sidebar_width {
            return None;
        }
        for section in [
            StackSection::SystemMetrics,
            StackSection::Media,
            StackSection::ConsoleLogs,
        ] {
            let (sec_y, sec_h, _) = Self::section_geom(layout, section);
            if sec_h > 0 && sec_y > 0 && y == sec_y - 1 {
                return Some(DragBoundary::Separator(section));
            }
        }
        None
    }

    fn apply_drag(&mut self, boundary: DragBoundary, x: i32, y: i32) {
        let width = self.width.max(1) as f64;
        match boundary {
            DragBoundary::LeftSidebar => {
                // The border column is the sidebar's last column.
                self.layout.left_sidebar = Some((x + 1) as f64 / width);
            }
            DragBoundary::RightSidebar => {
                self.layout.right_sidebar = Some((self.width - x) as f64 / width);
                self.overview_sidebar
                    .set_width_fraction(self.layout.right_sidebar);
            }
            DragBoundary::Separator(section) => self.drag_separator(section, y),
        }

        self.update_sidebar_dimensions(
            self.runs_anim.target_visible(),
            self.overview_sidebar.target_visible(),
        );
        self.update_bottom_pane_heights(
            self.system_metrics_pane.anim_state.target_visible(),
            self.media_pane.target_visible(),
            self.console_logs_pane.target_visible(),
        );
        self.recalculate_layout();
    }

    /// Moves the separator above `section` to row `y`, resizing it and, when
    /// the section above is not the flexible metrics grid, its neighbor.
    fn drag_separator(&mut self, section: StackSection, y: i32) {
        let layout = self.compute_viewports();
        let (sec_y, sec_h, sec_min) = Self::section_geom(&layout, section);
        if sec_h <= 0 {
            return;
        }
        let bottom = sec_y + sec_h;

        // The visible section directly above the dragged separator.
        let prev = [
            StackSection::Metrics,
            StackSection::SystemMetrics,
            StackSection::Media,
        ]
        .into_iter()
        .take_while(|&s| s != section)
        .filter(|&s| Self::section_geom(&layout, s).1 > 0)
        .last();
        let Some(prev) = prev else { return };
        let (prev_y, _, prev_min) = Self::section_geom(&layout, prev);

        // Keep both neighbors at or above their minimum heights.
        let (lo, hi) = (prev_y + prev_min, bottom - 1 - sec_min);
        if lo > hi {
            return;
        }
        let y = y.clamp(lo, hi);

        let height = self.height.max(1) as f64;
        self.set_section_fraction(section, (bottom - y - 1) as f64 / height);
        if prev != StackSection::Metrics {
            self.set_section_fraction(prev, (y - prev_y) as f64 / height);
        }
    }

    /// (y, height, min height) of a stack section in the current layout.
    fn section_geom(layout: &WorkspaceLayout, section: StackSection) -> (i32, i32, i32) {
        match section {
            StackSection::Metrics => (0, layout.height, MIN_FLEX_METRICS_HEIGHT),
            StackSection::SystemMetrics => (
                layout.system_metrics_y,
                layout.system_metrics_height,
                SYSTEM_METRICS_PANE_MIN_HEIGHT,
            ),
            StackSection::Media => (layout.media_y, layout.media_height, MEDIA_PANE_MIN_HEIGHT),
            StackSection::ConsoleLogs => (
                layout.console_logs_y,
                layout.console_logs_height,
                CONSOLE_LOGS_PANE_MIN_HEIGHT,
            ),
        }
    }

    fn set_section_fraction(&mut self, section: StackSection, frac: f64) {
        match section {
            StackSection::SystemMetrics => self.layout.system = Some(frac),
            StackSection::Media => self.layout.media = Some(frac),
            StackSection::ConsoleLogs => self.layout.logs = Some(frac),
            StackSection::Metrics => {}
        }
    }

    /// Resets pane proportions to the built-in defaults.
    fn reset_layout(&mut self, config: &mut ConfigManager) {
        self.layout = LayoutOverrides::default();
        self.overview_sidebar.set_width_fraction(None);
        config.update(|c| c.workspace_layout = LayoutOverrides::default());

        self.update_sidebar_dimensions(
            self.runs_anim.target_visible(),
            self.overview_sidebar.target_visible(),
        );
        self.update_bottom_pane_heights(
            self.system_metrics_pane.anim_state.target_visible(),
            self.media_pane.target_visible(),
            self.console_logs_pane.target_visible(),
        );
        self.recalculate_layout();
    }

    // ---- Mouse ----

    pub fn handle_mouse(&mut self, event: &MouseEvent, config: &mut ConfigManager) {
        let layout = self.compute_viewports();
        let x = event.column as i32;
        let y = event.row as i32;

        // Pane resizing wins over pane-local mouse handling.
        if self.handle_layout_drag(event, &layout, config) {
            return;
        }

        // Clicks in either sidebar clear all chart focus.
        if self.runs_anim.is_visible() && x < layout.left_sidebar_width {
            self.clear_chart_focus();
            return;
        }
        if self.overview_sidebar.is_visible() && x >= self.width - layout.right_sidebar_width {
            self.clear_chart_focus();
            return;
        }

        if self.media_pane.is_fullscreen() {
            return;
        }

        if layout.height > 0 && y < layout.height {
            self.handle_metrics_mouse(event, layout);
            return;
        }

        if layout.system_metrics_height > 0
            && y >= layout.system_metrics_y
            && y < layout.system_metrics_y + layout.system_metrics_height
        {
            self.handle_system_metrics_mouse(event, layout);
            return;
        }

        if layout.media_height > 0
            && y >= layout.media_y
            && y < layout.media_y + layout.media_height
        {
            self.handle_media_mouse(event, layout);
            return;
        }

        if layout.console_logs_height > 0
            && y >= layout.console_logs_y
            && y < layout.console_logs_y + layout.console_logs_height
        {
            self.clear_chart_focus();
        }
    }

    fn handle_metrics_mouse(&mut self, event: &MouseEvent, layout: WorkspaceLayout) {
        let alt = event.modifiers.contains(KeyModifiers::ALT);
        const HEADER_OFFSET: i32 = 1; // metrics header line

        let adjusted_x = event.column as i32 - layout.left_sidebar_width - CONTENT_PADDING as i32;
        let adjusted_y = event.row as i32 - HEADER_OFFSET;
        if adjusted_x < 0 || adjusted_y < 0 {
            return;
        }

        let dims = self
            .metrics_grid
            .calculate_chart_dimensions(layout.main_content_area_width, layout.height);
        if dims.cell_h_with_padding == 0 || dims.cell_w_with_padding == 0 {
            return;
        }

        let row = adjusted_y / dims.cell_h_with_padding;
        let col = adjusted_x / dims.cell_w_with_padding;

        match event.kind {
            MouseEventKind::Down(MouseButton::Left) => {
                if let Some(g) = self.active_system_metrics_grid() {
                    g.clear_focus();
                }
                self.metrics_grid.handle_click(row, col);
                self.adopt_chart_mouse_focus();
            }
            MouseEventKind::Down(MouseButton::Right) => {
                self.metrics_grid
                    .start_inspection(adjusted_x, row, col, dims, alt);
                self.adopt_chart_mouse_focus();
            }
            MouseEventKind::Drag(MouseButton::Right) => {
                self.metrics_grid
                    .update_inspection(adjusted_x, row, col, dims);
            }
            MouseEventKind::Up(MouseButton::Right) => {
                self.metrics_grid.end_inspection();
            }
            MouseEventKind::ScrollUp | MouseEventKind::ScrollDown => {
                self.metrics_grid.handle_wheel(
                    adjusted_x,
                    row,
                    col,
                    dims,
                    event.kind == MouseEventKind::ScrollUp,
                );
                self.adopt_chart_mouse_focus();
            }
            _ => {}
        }
    }

    fn handle_system_metrics_mouse(&mut self, event: &MouseEvent, layout: WorkspaceLayout) {
        let alt = event.modifiers.contains(KeyModifiers::ALT);

        let Some(cur) = self.current_run_key() else {
            return;
        };
        if !self.system_metrics.contains_key(&cur) {
            return;
        }

        let adjusted_x = event.column as i32 - layout.left_sidebar_width - CONTENT_PADDING as i32;
        let adjusted_y =
            event.row as i32 - layout.system_metrics_y - SYSTEM_METRICS_PANE_HEADER_LINES;
        if adjusted_x < 0 || adjusted_y < 0 {
            return;
        }

        let grid = self.system_metrics.get_mut(&cur).unwrap();
        let dims = grid.calculate_chart_dimensions();
        if dims.cell_h_with_padding == 0 || dims.cell_w_with_padding == 0 {
            return;
        }
        let row = adjusted_y / dims.cell_h_with_padding;
        let col = adjusted_x / dims.cell_w_with_padding;

        match event.kind {
            MouseEventKind::Down(MouseButton::Left) => {
                self.metrics_grid.clear_focus();
                let clicked = self
                    .system_metrics
                    .get_mut(&cur)
                    .unwrap()
                    .handle_mouse_click(row, col);
                if clicked {
                    self.adopt_chart_mouse_focus();
                }
            }
            MouseEventKind::Down(MouseButton::Right) => {
                self.metrics_grid.clear_focus();
                self.system_metrics
                    .get_mut(&cur)
                    .unwrap()
                    .start_inspection(adjusted_x, adjusted_y, row, col, dims, alt);
                self.adopt_chart_mouse_focus();
            }
            MouseEventKind::Drag(MouseButton::Right) => {
                self.system_metrics
                    .get_mut(&cur)
                    .unwrap()
                    .update_inspection(adjusted_x, adjusted_y, row, col, dims);
            }
            MouseEventKind::Up(MouseButton::Right) => {
                self.system_metrics.get_mut(&cur).unwrap().end_inspection();
            }
            MouseEventKind::ScrollUp | MouseEventKind::ScrollDown => {
                self.metrics_grid.clear_focus();
                self.system_metrics.get_mut(&cur).unwrap().handle_wheel(
                    adjusted_x,
                    row,
                    col,
                    dims,
                    event.kind == MouseEventKind::ScrollUp,
                );
                self.adopt_chart_mouse_focus();
            }
            _ => {}
        }
    }

    fn handle_media_mouse(&mut self, event: &MouseEvent, layout: WorkspaceLayout) {
        if event.kind != MouseEventKind::Down(MouseButton::Left) {
            return;
        }
        let local_x = event.column as i32 - layout.left_sidebar_width;
        let local_y = event.row as i32 - layout.media_y;
        if local_x < 0 || local_y < 0 {
            return;
        }

        let cur = self.current_run_key().unwrap_or_default();
        let store = self.media.get(&cur).unwrap_or(&self.empty_media);
        let clicked = self.media_pane.handle_mouse_click(
            store,
            local_x as u16,
            local_y as u16,
            layout.main_content_area_width as u16,
            layout.media_height as u16,
        );
        if clicked {
            self.media_pane.set_active(true);
            self.with_focus_mgr(|fm, view| fm.adopt_target(view, FocusTarget::Media));
        }
    }

    // ---- Rendering ----

    pub fn render(&mut self, area: Rect, buf: &mut Buffer, config: &ConfigManager) {
        self.width = area.width as i32;
        self.height = area.height as i32;

        if area.width == 0 || area.height == 0 {
            return;
        }

        let layout = self.compute_viewports();
        let ctx = self.sync_current_run_context();
        let total_h = layout.total_content_area_height.max(0) as u16;

        if self.runs_anim.is_visible() && layout.left_sidebar_width > 0 {
            self.render_runs_list(
                Rect {
                    x: area.x,
                    y: area.y,
                    width: (layout.left_sidebar_width as u16).min(area.width),
                    height: total_h,
                },
                buf,
            );
        }

        let central = Rect {
            x: area.x + layout.left_sidebar_width as u16,
            y: area.y,
            width: layout.main_content_area_width as u16,
            height: total_h,
        };
        self.render_central_column(central, buf, layout, &ctx);

        if self.overview_sidebar.is_visible() && layout.right_sidebar_width > 0 {
            self.render_run_overview(
                Rect {
                    x: area.x + (self.width - layout.right_sidebar_width) as u16,
                    y: area.y,
                    width: layout.right_sidebar_width as u16,
                    height: total_h,
                },
                buf,
            );
        }

        self.render_status_bar(area, buf, config);
    }

    fn render_central_column(
        &mut self,
        area: Rect,
        buf: &mut Buffer,
        layout: WorkspaceLayout,
        ctx: &RunContext,
    ) {
        if area.width == 0 || area.height == 0 {
            return;
        }

        if self.media_pane.is_fullscreen() {
            let store = self.media.get(&ctx.run_key).unwrap_or(&self.empty_media);
            self.media_pane
                .render(area, buf, store, &ctx.run_label, &ctx.media_hint);
            return;
        }

        let mut section_tops: Vec<u16> = Vec::new();

        if self.metrics_grid_anim.is_visible() && layout.height > 0 {
            let metrics_area = Rect {
                x: area.x,
                y: area.y,
                width: area.width,
                height: layout.height.min(area.height as i32) as u16,
            };
            if self.selected_runs.is_empty() {
                render_metrics_empty_state(metrics_area, buf, "Select a run to view charts.");
            } else if self.metrics_grid.chart_count() == 0 {
                render_metrics_empty_state(metrics_area, buf, "No scalar metrics logged.");
            } else {
                self.metrics_grid
                    .sync_dimensions(area.width as i32, layout.height);
                let dims = self
                    .metrics_grid
                    .calculate_chart_dimensions(area.width as i32, layout.height);
                self.metrics_grid.render(metrics_area, buf, dims);
            }
            section_tops.push(metrics_area.y);
        }

        if layout.system_metrics_height > 0 {
            let sys_area = Rect {
                x: area.x,
                y: area.y + layout.system_metrics_y as u16,
                width: area.width,
                height: layout.system_metrics_height as u16,
            };
            let grid = if ctx.run_key.is_empty() {
                Option::None
            } else {
                self.system_metrics.get_mut(&ctx.run_key)
            };
            self.system_metrics_pane
                .render(sys_area, buf, &ctx.run_label, grid, &ctx.system_hint);
            section_tops.push(sys_area.y);
        }

        if layout.media_height > 0 {
            let media_area = Rect {
                x: area.x,
                y: area.y + layout.media_y as u16,
                width: area.width,
                height: layout.media_height as u16,
            };
            let store = self.media.get(&ctx.run_key).unwrap_or(&self.empty_media);
            self.media_pane
                .render(media_area, buf, store, &ctx.run_label, &ctx.media_hint);
            section_tops.push(media_area.y);
        } else {
            self.media_pane.park();
        }

        if layout.console_logs_height > 0 {
            let logs_area = Rect {
                x: area.x,
                y: area.y + layout.console_logs_y as u16,
                width: area.width,
                height: layout.console_logs_height as u16,
            };
            self.console_logs_pane
                .render(logs_area, buf, &ctx.run_label, &ctx.logs_hint);
            section_tops.push(logs_area.y);
        }

        if section_tops.is_empty() {
            theme::render_logo_art(area, buf);
            return;
        }

        // Separator lines in the 1-row gaps between stacked sections.
        for &top in section_tops.iter().skip(1) {
            if top > area.y {
                theme::render_horizontal_separator(
                    Rect {
                        x: area.x,
                        y: top - 1,
                        width: area.width,
                        height: 1,
                    },
                    buf,
                );
            }
        }
    }

    /// Syncs per-run context (media store switch, console logs) and returns
    /// the labels/hints for the current run.
    fn sync_current_run_context(&mut self) -> RunContext {
        let current_run_key = self.current_run_key().unwrap_or_default();
        let run_label = current_run_key.clone();

        // Media store switching: save/restore per-run view state.
        let has_store = self.media.contains_key(&current_run_key);
        if current_run_key != self.current_media_run_key {
            if !self.current_media_run_key.is_empty() {
                let state = self.media_pane.save_view_state();
                self.media_pane_states
                    .insert(self.current_media_run_key.clone(), state);
            }

            self.current_media_run_key = current_run_key.clone();
            let store = self
                .media
                .get(&current_run_key)
                .unwrap_or(&self.empty_media);
            let state = self.media_pane_states.get(&current_run_key).cloned();
            match (has_store, state) {
                (true, Some(state)) => self.media_pane.restore_view_state(state, store),
                _ => self.media_pane.reset_view_state(store),
            }
        }

        let mut ctx = RunContext {
            run_key: current_run_key.clone(),
            run_label,
            ..RunContext::default()
        };

        if current_run_key.is_empty() {
            if !self.console_logs_synced.0.is_empty() {
                self.console_logs_pane.set_console_logs(Vec::new());
                self.console_logs_synced = (String::new(), 0);
            }
            return ctx;
        }

        // Re-sync the pane only when the run or its content changed; the
        // clone is O(log lines) and would otherwise run every frame.
        let logs = self.console_logs.get(&current_run_key);
        let revision = logs.map_or(0, |cl| cl.revision());
        if self.console_logs_synced.0 != current_run_key || self.console_logs_synced.1 != revision {
            let items = logs.map(|cl| cl.items().to_vec()).unwrap_or_default();
            self.console_logs_pane.set_console_logs(items);
            self.console_logs_synced = (current_run_key.clone(), revision);
        }

        if !self.selected_runs.contains(&current_run_key) {
            ctx.system_hint = "Select this run (Space) to load system metrics.".into();
            ctx.media_hint = "Select this run (Space) to load media.".into();
            ctx.logs_hint = "Select this run (Space) to load console logs.".into();
        }

        ctx
    }

    fn render_run_overview(&mut self, area: Rect, buf: &mut Buffer) {
        let cur = self.current_run_key().unwrap_or_default();
        let overview = self.run_overview.get(&cur).unwrap_or(&self.empty_overview);
        self.overview_sidebar.sync(overview);

        if self.run_overview_active() {
            self.overview_sidebar.activate_selection();
        } else {
            self.overview_sidebar.deactivate_all_sections();
        }

        self.overview_sidebar.render(area, buf, Some(overview));
    }

    fn render_runs_list(&mut self, area: Rect, buf: &mut Buffer) {
        let (start, end) = self.sync_runs_page();

        let total_w = area.width as i32;
        if total_w <= SIDEBAR_OVERHEAD || area.height == 0 {
            return;
        }

        // Right border column.
        let border_x = area.right() - 1;
        for y in area.top()..area.bottom() {
            buf[(border_x, y)]
                .set_char(BOX_LIGHT_VERTICAL)
                .set_style(theme::border_style());
        }

        let content_w = sidebar_content_width(total_w);
        let inner = Rect {
            x: area.x + CONTENT_PADDING,
            y: area.y,
            width: content_w.max(0) as u16,
            height: area.height.saturating_sub(SIDEBAR_BOTTOM_PADDING),
        };
        if inner.width == 0 || inner.height == 0 {
            return;
        }

        self.render_runs_list_header(inner, buf, start, end);

        let rows_area = Rect {
            y: inner.y + 1,
            height: inner.height.saturating_sub(1),
            ..inner
        };
        if rows_area.height == 0 {
            return;
        }

        if self.runs.filtered_items.is_empty() {
            buf.set_stringn(
                rows_area.x,
                rows_area.y,
                "No runs found.",
                rows_area.width as usize,
                theme::nav_info_style(),
            );
            return;
        }

        self.render_run_lines(rows_area, buf, start, end);
    }

    fn render_runs_list_header(&self, area: Rect, buf: &mut Buffer, start: usize, end: usize) {
        let filtered_count = self.runs.filtered_items.len();
        let total_count = self.runs.items.len();
        let ipp = self.runs.items_per_page();

        let info = if !self.filter.query().is_empty() && total_count > 0 {
            if filtered_count == 0 {
                format!(" [0 of {total_count} filtered]")
            } else if ipp > 0 && filtered_count > ipp {
                format!(
                    " [{}-{} of {} filtered from {} total]",
                    start + 1,
                    end,
                    filtered_count,
                    total_count
                )
            } else {
                format!(" [{filtered_count} filtered from {total_count} total]")
            }
        } else if filtered_count > 0 {
            if ipp > 0 && filtered_count > ipp {
                format!(" [{}-{} of {}]", start + 1, end, filtered_count)
            } else {
                format!(" [{filtered_count} items]")
            }
        } else {
            String::new()
        };

        let (x, _) = buf.set_stringn(
            area.x,
            area.y,
            "Runs",
            area.width as usize,
            theme::sidebar_section_header_style(),
        );
        if !info.is_empty() && x < area.right() {
            buf.set_stringn(
                x,
                area.y,
                &info,
                (area.right() - x) as usize,
                theme::nav_info_style(),
            );
        }
    }

    /// Renders the visible slice with zebra background and selection.
    fn render_run_lines(&self, area: Rect, buf: &mut Buffer, start: usize, end: usize) {
        let selected_line = self.runs.current_line();
        let content_w = area.width as i32;

        for (idx_on_page, i) in (start..end).enumerate() {
            if idx_on_page as u16 >= area.height {
                break;
            }
            let y = area.y + idx_on_page as u16;
            let item = &self.runs.filtered_items[i];
            let run_key = &item.key;

            // Determine row style.
            let row_style = if idx_on_page == selected_line {
                if self.runs.active {
                    theme::selected_run_style()
                } else {
                    theme::selected_run_inactive_style()
                }
            } else if idx_on_page % 2 == 1 {
                theme::odd_run_style()
            } else {
                ratatui::style::Style::new()
            };

            let run_color = self.run_color_for_key(run_key);
            let is_selected = self.selected_runs.contains(run_key);
            let is_pinned = self.pinned_run == *run_key;

            let mark = if is_pinned {
                PINNED_RUN_MARK
            } else if is_selected {
                SELECTED_RUN_MARK
            } else {
                RUN_MARK
            };

            // Prefix without background, colored by the run's series color.
            let prefix = format!("{mark} ");
            let (mut x, _) = buf.set_stringn(
                area.x,
                y,
                &prefix,
                content_w as usize,
                ratatui::style::Style::new().fg(run_color.color()),
            );

            // Subtle muting for unselected/unpinned runs.
            let name_fg = if !is_selected && !is_pinned {
                theme::COLOR_TEXT.color()
            } else if idx_on_page == selected_line {
                theme::COLOR_DARK
            } else {
                theme::COLOR_ITEM_VALUE.color()
            };

            let name_w = (content_w - prefix.chars().count() as i32).max(1);
            let name = truncate_value(run_key, name_w as usize);
            let (nx, _) = buf.set_stringn(x, y, &name, name_w as usize, row_style.fg(name_fg));
            x = nx;

            // Pad the rest of the row with the row background.
            while x < area.x + content_w as u16 {
                buf[(x, y)].set_char(' ').set_style(row_style);
                x += 1;
            }
        }
    }

    fn render_status_bar(&self, area: Rect, buf: &mut Buffer, config: &ConfigManager) {
        let y = area.bottom().saturating_sub(1);
        let style = theme::status_bar_style();

        for x in area.left()..area.right() {
            buf[(x, y)].set_char(' ').set_style(style);
        }

        let status = self.build_status_text(config);
        let help = self.build_help_text(config);

        let inner_w = area.width.saturating_sub(2 * STATUS_BAR_PADDING) as usize;
        let (end_x, _) = buf.set_stringn(area.x + STATUS_BAR_PADDING, y, &status, inner_w, style);

        if !help.is_empty() {
            let help_w = help.chars().count() as u16;
            let help_x = area.right().saturating_sub(STATUS_BAR_PADDING + help_w);
            if help_x > end_x {
                buf.set_stringn(help_x, y, help, help_w as usize, style);
            }
        }
    }

    fn build_status_text(&self, config: &ConfigManager) -> String {
        if self.filter.is_active() {
            return self.build_runs_filter_status();
        }
        if self.metrics_grid.is_filter_mode() {
            return self.build_metrics_filter_status();
        }
        if let Some(g) = self.active_system_metrics_grid_ref()
            && g.is_filter_mode()
        {
            return self.build_system_metrics_filter_status(g);
        }
        if self.overview_sidebar.is_filter_mode() {
            return self.build_overview_filter_status();
        }
        if config.is_awaiting_grid_config() {
            return config.grid_config_status().to_string();
        }
        self.build_active_status()
    }

    fn build_runs_filter_status(&self) -> String {
        format!(
            "Runs filter ({}): {}{} [{}/{}] (Enter to apply • Tab to toggle mode)",
            self.filter.mode(),
            self.filter.query(),
            MEDIUM_SHADE_BLOCK,
            self.runs.filtered_items.len(),
            self.runs.items.len(),
        )
    }

    fn build_metrics_filter_status(&self) -> String {
        format!(
            "Filter ({}): {}{} [{}/{}] (Enter to apply • Tab to toggle mode)",
            self.metrics_grid.filter_mode(),
            self.metrics_grid.filter_query(),
            MEDIUM_SHADE_BLOCK,
            self.metrics_grid.filtered_chart_count(),
            self.metrics_grid.chart_count(),
        )
    }

    fn build_system_metrics_filter_status(&self, grid: &SystemMetricsGrid) -> String {
        if !self.system_metrics_pane.is_visible() {
            return String::new();
        }
        format!(
            "System filter ({}): {}{} [{}/{}] (Enter to apply • Tab to toggle mode)",
            grid.filter_mode(),
            grid.filter_query(),
            MEDIUM_SHADE_BLOCK,
            grid.filtered_chart_count(),
            grid.chart_count(),
        )
    }

    fn build_overview_filter_status(&self) -> String {
        let mut filter_info = self.overview_sidebar.filter_info();
        if filter_info.is_empty() {
            filter_info = "no matches".to_string();
        }
        format!(
            "Overview filter ({}): {}{} [{}] (Enter to apply • Tab to toggle mode)",
            self.overview_sidebar.filter_mode(),
            self.overview_sidebar.filter_query(),
            MEDIUM_SHADE_BLOCK,
            filter_info,
        )
    }

    /// Summarizes the active filters and selection when no dedicated input
    /// mode (filter / grid config) is active.
    fn build_active_status(&self) -> String {
        let mut parts: Vec<String> = Vec::new();

        // Active filters.
        if !self.filter.query().is_empty() && !self.filter.is_active() {
            parts.push(format!(
                "Runs ({}): {:?} [{}/{}] (f to change, ctrl+f to clear)",
                self.filter.mode(),
                self.filter.query(),
                self.runs.filtered_items.len(),
                self.runs.items.len(),
            ));
        }

        if self.metrics_grid.is_filtering() {
            parts.push(format!(
                "Filter ({}): {:?} [{}/{}] (/ to change, ctrl+/ to clear)",
                self.metrics_grid.filter_mode(),
                self.metrics_grid.filter_query(),
                self.metrics_grid.filtered_chart_count(),
                self.metrics_grid.chart_count(),
            ));
        }

        if let Some(g) = self.active_system_metrics_grid_ref()
            && g.is_filtering()
            && self.system_metrics_pane.is_visible()
        {
            parts.push(format!(
                "System filter ({}): {:?} [{}/{}] (\\ to change, ctrl+\\ to clear)",
                g.filter_mode(),
                g.filter_query(),
                g.filtered_chart_count(),
                g.chart_count(),
            ));
        }

        if self.overview_sidebar.is_visible() && self.overview_sidebar.is_filtering() {
            parts.push(format!(
                "Overview: {:?} [{}] (o to change, ctrl+o to clear)",
                self.overview_sidebar.filter_query(),
                self.overview_sidebar.filter_info(),
            ));
        }

        // Selection status.
        if self.run_overview_active()
            && let Some((key, value)) = self.overview_sidebar.selected_item()
            && !key.is_empty()
        {
            parts.push(format!("{key}: {value}"));
        }

        if self.media_pane.active() {
            let store = self
                .current_run_key()
                .and_then(|k| self.media.get(&k))
                .unwrap_or(&self.empty_media);
            let label = self.media_pane.status_label(store);
            if !label.is_empty() {
                parts.push(label);
            }
        }

        // Focused chart status.
        parts.extend(self.active_focus_status());

        if parts.is_empty() {
            return self.wandb_dir.clone();
        }
        format!("{} • {}", self.wandb_dir, parts.join(" • "))
    }

    fn active_focus_status(&self) -> Vec<String> {
        let mut parts = Vec::new();

        if self.metrics_grid.focus.ty == FocusType::MainChart {
            parts.push(self.metrics_grid.focus.title.clone());
            let label = self.metrics_grid.focused_chart_scale_label();
            if !label.is_empty() {
                parts.push(label.to_string());
            }
        } else if let Some(g) = self.active_system_metrics_grid_ref()
            && g.focus.ty == FocusType::SystemChart
        {
            parts.push(g.focus.title.clone());
            let detail = g.focused_chart_title_detail();
            if !detail.is_empty() {
                parts.push(detail);
            }
            let view_mode = g.focused_chart_view_mode_label();
            if !view_mode.is_empty() {
                parts.push(view_mode);
            }
            let scale = g.focused_chart_scale_label();
            if !scale.is_empty() {
                parts.push(scale.to_string());
            }
        }

        parts.retain(|p| !p.is_empty());
        parts
    }

    fn build_help_text(&self, config: &ConfigManager) -> &'static str {
        if self.is_filtering() || config.is_awaiting_grid_config() {
            ""
        } else {
            "h: help"
        }
    }
}

/// Labels and hints for the currently highlighted run, computed per frame.
#[derive(Debug, Clone, Default)]
struct RunContext {
    run_key: String,
    run_label: String,
    system_hint: String,
    media_hint: String,
    logs_hint: String,
}

impl FocusContext for WorkspaceView {
    fn available(&self, target: FocusTarget) -> bool {
        match target {
            FocusTarget::RunsList => {
                self.runs_anim.is_visible() && !self.runs.filtered_items.is_empty()
            }
            FocusTarget::Overview => {
                self.overview_sidebar.is_expanded()
                    && self.overview_sidebar.focusable_section_bounds().is_some()
            }
            FocusTarget::MetricsGrid => {
                self.metrics_grid_anim.is_expanded() && self.metrics_grid.chart_count() > 0
            }
            FocusTarget::SystemMetrics => {
                self.system_metrics_pane.is_expanded()
                    && self
                        .active_system_metrics_grid_ref()
                        .is_some_and(|g| g.chart_count() > 0)
            }
            FocusTarget::Media => {
                let store = self
                    .current_run_key()
                    .and_then(|k| self.media.get(&k))
                    .unwrap_or(&self.empty_media);
                self.media_pane.is_expanded() && self.media_pane.has_data(store)
            }
            FocusTarget::ConsoleLogs => self.console_logs_pane.is_expanded(),
            _ => false,
        }
    }

    fn available_target(&self, target: FocusTarget) -> bool {
        match target {
            FocusTarget::RunsList => {
                self.runs_anim.target_visible() && !self.runs.filtered_items.is_empty()
            }
            FocusTarget::Overview => {
                self.overview_sidebar.target_visible()
                    && self.overview_sidebar.focusable_section_bounds().is_some()
            }
            FocusTarget::MetricsGrid => {
                self.metrics_grid_anim.target_visible() && self.metrics_grid.chart_count() > 0
            }
            FocusTarget::SystemMetrics => {
                self.system_metrics_pane.anim_state.target_visible()
                    && self
                        .active_system_metrics_grid_ref()
                        .is_some_and(|g| g.chart_count() > 0)
            }
            FocusTarget::Media => {
                let store = self
                    .current_run_key()
                    .and_then(|k| self.media.get(&k))
                    .unwrap_or(&self.empty_media);
                self.media_pane.target_visible() && self.media_pane.has_data(store)
            }
            FocusTarget::ConsoleLogs => self.console_logs_pane.target_visible(),
            _ => false,
        }
    }

    fn activate(&mut self, target: FocusTarget, direction: i32) {
        match target {
            FocusTarget::RunsList => self.runs.active = true,
            FocusTarget::Overview => {
                if let Some((first, last)) = self.overview_sidebar.focusable_section_bounds() {
                    self.overview_sidebar.set_active_section(if direction >= 0 {
                        first
                    } else {
                        last
                    });
                }
            }
            FocusTarget::MetricsGrid => {
                self.metrics_grid.navigate_focus(0, 0);
            }
            FocusTarget::SystemMetrics => {
                if let Some(g) = self.active_system_metrics_grid() {
                    g.navigate_focus(0, 0);
                }
            }
            FocusTarget::Media => self.media_pane.set_active(true),
            FocusTarget::ConsoleLogs => self.console_logs_pane.set_active(true),
            _ => {}
        }
    }

    fn deactivate(&mut self, target: FocusTarget) {
        match target {
            FocusTarget::RunsList => self.runs.active = false,
            FocusTarget::Overview => self.overview_sidebar.deactivate_all_sections(),
            FocusTarget::MetricsGrid => {
                if self.metrics_grid.focus.ty == FocusType::MainChart {
                    self.metrics_grid.clear_focus();
                }
            }
            FocusTarget::SystemMetrics => {
                if let Some(g) = self.active_system_metrics_grid()
                    && g.focus.ty == FocusType::SystemChart
                {
                    g.clear_focus();
                }
            }
            FocusTarget::Media => self.media_pane.set_active(false),
            FocusTarget::ConsoleLogs => self.console_logs_pane.set_active(false),
            _ => {}
        }
    }
}
#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::*;

    /// Regression test: with bottom panes enabled in the config, the initial
    /// resize used to steal focus from the (still empty) runs list and hand
    /// it to the console logs pane, breaking Enter/run selection.
    #[test]
    fn startup_focus_stays_on_runs_list() {
        let path = std::env::temp_dir().join("leet-ws-focus-test.json");
        let _ = std::fs::remove_file(&path);
        let mut config = ConfigManager::new(path);
        config.update(|c| {
            c.workspace_console_logs_visible = true;
            c.workspace_media_visible = true;
            c.workspace_system_metrics_visible = true;
        });

        let mut ws = WorkspaceView::new("wandb".to_string(), &config);
        ws.handle_resize(200, 50);
        assert_eq!(ws.focus_mgr.current(), FocusTarget::RunsList);
    }

    /// Regression test: a toggled-on pane must finish its expand animation
    /// and become Tab-focusable. A per-frame expanded-size recomputation used
    /// to restart the easing clock, leaving panes one cell short of expanded
    /// (and so unfocusable) forever.
    #[test]
    fn toggled_pane_becomes_focusable_after_settle() {
        let path = std::env::temp_dir().join("leet-ws-toggle-focus-test.json");
        let _ = std::fs::remove_file(&path);
        let mut config = ConfigManager::new(path);

        let mut ws = WorkspaceView::new("wandb".to_string(), &config);
        ws.handle_resize(200, 50);

        ws.handle_key(
            &KeyEvent::new(KeyCode::Char('4'), KeyModifiers::NONE),
            &mut config,
        );
        let deadline = Instant::now() + Duration::from_secs(1);
        while ws.tick(deadline) && Instant::now() < deadline {}

        assert!(ws.console_logs_pane.is_expanded());
        assert!(FocusContext::available(&ws, FocusTarget::ConsoleLogs));

        ws.handle_key(
            &KeyEvent::new(KeyCode::Tab, KeyModifiers::NONE),
            &mut config,
        );
        assert_eq!(ws.focus_mgr.current(), FocusTarget::ConsoleLogs);

        // Esc returns focus to the runs list.
        ws.handle_key(
            &KeyEvent::new(KeyCode::Esc, KeyModifiers::NONE),
            &mut config,
        );
        assert_eq!(ws.focus_mgr.current(), FocusTarget::RunsList);
    }

    /// Dragging the runs sidebar border resizes it, persists the fraction on
    /// release, and `0` resets to defaults.
    #[test]
    fn mouse_drag_resizes_and_persists_sidebar_width() {
        let path = std::env::temp_dir().join("leet-ws-drag-test.json");
        let _ = std::fs::remove_file(&path);
        let mut config = ConfigManager::new(path);

        let mut ws = WorkspaceView::new("wandb".to_string(), &config);
        ws.handle_resize(200, 50);

        let default_w = ws.compute_viewports().left_sidebar_width;
        let border_x = (default_w - 1) as u16;

        let mouse = |kind, column: u16, row: u16| MouseEvent {
            kind,
            column,
            row,
            modifiers: KeyModifiers::NONE,
        };
        ws.handle_mouse(
            &mouse(MouseEventKind::Down(MouseButton::Left), border_x, 10),
            &mut config,
        );
        ws.handle_mouse(
            &mouse(MouseEventKind::Drag(MouseButton::Left), 79, 10),
            &mut config,
        );
        assert_eq!(ws.compute_viewports().left_sidebar_width, 80);

        ws.handle_mouse(
            &mouse(MouseEventKind::Up(MouseButton::Left), 79, 10),
            &mut config,
        );
        let saved = config.config().workspace_layout.left_sidebar;
        assert_eq!(saved, Some(0.4));

        // Reset restores the default width and clears the override.
        ws.handle_key(
            &KeyEvent::new(KeyCode::Char('0'), KeyModifiers::NONE),
            &mut config,
        );
        assert_eq!(ws.compute_viewports().left_sidebar_width, default_w);
        assert!(config.config().workspace_layout.is_default());
    }

    /// Dragging the separator above a stacked pane resizes it against the
    /// flexible metrics grid and persists the fraction.
    #[test]
    fn mouse_drag_resizes_stacked_pane() {
        let path = std::env::temp_dir().join("leet-ws-drag-sep-test.json");
        let _ = std::fs::remove_file(&path);
        let mut config = ConfigManager::new(path);

        let mut ws = WorkspaceView::new("wandb".to_string(), &config);
        ws.handle_resize(200, 50);

        // Show the system metrics pane and finish its animation.
        ws.handle_key(
            &KeyEvent::new(KeyCode::Char('2'), KeyModifiers::NONE),
            &mut config,
        );
        let deadline = Instant::now() + Duration::from_secs(1);
        while ws.tick(deadline) && Instant::now() < deadline {}

        let before = ws.compute_viewports();
        assert!(before.system_metrics_height > 0);
        let sep_y = (before.system_metrics_y - 1) as u16;
        let x = (before.left_sidebar_width + 5) as u16;

        let mouse = |kind, column: u16, row: u16| MouseEvent {
            kind,
            column,
            row,
            modifiers: KeyModifiers::NONE,
        };
        ws.handle_mouse(
            &mouse(MouseEventKind::Down(MouseButton::Left), x, sep_y),
            &mut config,
        );
        ws.handle_mouse(
            &mouse(MouseEventKind::Drag(MouseButton::Left), x, sep_y - 5),
            &mut config,
        );
        ws.handle_mouse(
            &mouse(MouseEventKind::Up(MouseButton::Left), x, sep_y - 5),
            &mut config,
        );

        let after = ws.compute_viewports();
        assert_eq!(
            after.system_metrics_height,
            before.system_metrics_height + 5
        );
        assert!(config.config().workspace_layout.system.is_some());
    }
}
