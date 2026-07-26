//! Port of `core/internal/leet/workspace.go` — the multi-run workspace view:
//! runs sidebar (select/pin/filter), overlay metrics grid, system metrics /
//! media / console-logs panes, per-run streaming state, and the workspace
//! status bar.
//!
//! Update/View follow the App-trait shape (docs/CONCURRENCY.md §2.1):
//! `update(&mut self, &Event) -> Vec<Command>`, `view(&mut self, dark) ->
//! Text` — the top-level model (model.rs) delegates exactly like model.go
//! does with `tea.Model`. Go's `tea.Cmd` returns become [`Command`] vectors
//! (`tea.Batch` → `Vec`, order preserved).
//!
//! Concurrency deltas versus Go (all prescribed by CONCURRENCY.md):
//!   - `hasLiveRuns atomic.Bool` (S3) is deleted; liveness is
//!     [`Workspace::any_run_running`] evaluated on the update thread (§2.4).
//!   - `liveChan` (C2) and `waitForLiveMsg` are deleted; heartbeats travel
//!     scheduler → main channel as `Event::Heartbeat` (§2.5).
//!   - `autoSelectLatestRunOnLoad sync.Once` is a plain bool (§2.6).

use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;

use ratatui::text::{Line, Text};

use leet_charts::styles::{
    AdaptiveColor, COLOR_DARK, COLOR_ITEM_VALUE, COLOR_TEXT, MEDIUM_SHADE_BLOCK,
    MIN_METRIC_CHART_HEIGHT, MIN_METRIC_CHART_WIDTH, Rgb, SIDEBAR_BOTTOM_PADDING,
    SIDEBAR_MIN_WIDTH, SIDEBAR_OVERHEAD, STATUS_BAR_HEIGHT, STATUS_BAR_PADDING,
    WORKSPACE_HEADER_LINES, color_index, graph_colors, test_mode_terminal_bg,
};
use leet_charts::workspace_run_colors::WorkspaceRunColors;
use leet_data::config::{ConfigManager, leet_config_path};
use leet_data::media::MediaStore;
use leet_data::run_filter_query::WorkspaceRunFilterData;
use leet_data::run_overview::{RunOverview, RunState};
use leet_data::width::text_width;

use crate::animation::AnimatedValue;
use crate::command::{Command, HeartbeatOwner};
use crate::console_logs_pane::{CONSOLE_LOGS_PANE_MIN_HEIGHT, ConsoleLogsPane};
use crate::event::{Event, HistorySourceHandle};
use crate::filter::Filter;
use crate::flex_layout::{
    StackSectionId, StackSectionSpec, compute_vertical_stack_layout, expanded_sidebar_width,
    sidebar_content_width, sidebar_inner_width,
};
use crate::focus_manager::{FocusManager, FocusRegionDef, FocusTarget};
use crate::heartbeat::HeartbeatManager;
use crate::keybindings::{WorkspaceAction, build_key_map, workspace_key_bindings};
use crate::layout::{
    GoStyle, LEFT, RIGHT, TOP, adaptive_to_color, block_width, even_run_style, join_horizontal,
    join_vertical, join_with_separators, left_sidebar_border_style, left_sidebar_style,
    nav_info_style, odd_run_style, place, place_horizontal, rgb_to_color,
    run_overview_sidebar_section_header_style, selected_run_inactive_style, selected_run_style,
    status_bar_style, text_from_str, text_to_string,
};
use crate::media_pane::{LOWER_TIER_RATIO, MEDIA_PANE_MIN_HEIGHT, MediaPane, MediaPaneViewState};
use crate::metrics_grid::MetricsGrid;
// PARITY: run.rs hosts the package-shared declarations the workspace reuses
// (see the notes there): `Layout` (run.go:700), `go_quote`, and the two
// workspace.go render helpers it needs first (renderMetricsEmptyState,
// renderLogoArt — workspace.go:1078/:1091), plus the MediaPaneCmd → Command
// mapping.
use crate::paged_list::PagedList;
use crate::panel_grid::{Focus, FocusType};
use crate::run::{
    Layout, go_quote, media_pane_commands, render_logo_art, render_metrics_empty_state,
};
use crate::run_console_logs::RunConsoleLogs;
use crate::run_overview_sidebar::{RunOverviewSidebar, SidebarSide, truncate_value};
use crate::system_metrics_grid::SystemMetricsGrid;
use crate::watcher_manager::WatcherManager;
use crate::workspace_dir_watcher::{MAX_CONCURRENT_PRELOADS, RunOverviewPreloader};
use crate::workspace_run_filter::WorkspaceRunFilterHost;
use crate::workspace_system_metrics_pane::{SYSTEM_METRICS_PANE_MIN_HEIGHT, SystemMetricsPane};

pub const RUN_MARK: &str = "○";
pub const SELECTED_RUN_MARK: &str = "●";
pub const PINNED_RUN_MARK: &str = "▶"; // ✪ ◎ ▲ ▶ ◉ ▬ ◆ ▣ ■ → ○ ●

// ---------------------------------------------------------------------------
// Path resolution utilities
// ---------------------------------------------------------------------------
// PARITY: `extractRunID` / `runWandbFile` are declared in model.go:439-464;
// hosted here because this module also uses them — model.rs reuses these
// (see its import note), not re-declares them.

/// extractRunID extracts the run ID from a run directory name.
///
/// The expected formats are:
///
/// ```text
/// "run-YYYYMMDD_HHMMSS-<run_id>"
/// "offline-run-YYYYMMDD_HHMMSS-<run_id>"
/// ```
///
/// Returns "" if the folder name doesn't match.
// PARITY: Go uses `regexp.MustCompile(`run-\d{8}_\d{6}-`)` and
// FindStringIndex (leftmost match); leet-tui has no regex dependency, so the
// fixed-shape pattern is matched by hand with identical leftmost semantics.
pub(crate) fn extract_run_id(folder_name: &str) -> &str {
    let bytes = folder_name.as_bytes();
    // Pattern length: "run-" (4) + 8 digits + "_" + 6 digits + "-" = 20.
    const PAT_LEN: usize = 20;
    let mut i = 0;
    while i + PAT_LEN <= bytes.len() {
        let window = &bytes[i..i + PAT_LEN];
        let matches = window.starts_with(b"run-")
            && window[4..12].iter().all(u8::is_ascii_digit)
            && window[12] == b'_'
            && window[13..19].iter().all(u8::is_ascii_digit)
            && window[19] == b'-';
        if matches {
            let end = i + PAT_LEN;
            // Go: `loc[1] == len(folderName)` → "".
            if end == folder_name.len() {
                return "";
            }
            return &folder_name[end..];
        }
        i += 1;
    }
    ""
}

/// runWandbFile returns the full path to the .wandb file for the given run
/// folder.
pub(crate) fn run_wandb_file(wandb_dir: &str, run_dir: &str) -> String {
    let run_id = extract_run_id(run_dir);
    if run_id.is_empty() {
        return String::new();
    }
    // Go filepath.Join(wandbDir, runDir, "run-"+runID+".wandb").
    std::path::Path::new(wandb_dir)
        .join(run_dir)
        .join(format!("run-{run_id}.wandb"))
        .to_string_lossy()
        .into_owned()
}

/// Workspace is the multi‑run view.
///
/// Implements the Update/View shape model.rs delegates to (Go: tea.Model).
// PARITY: fields are pub(crate) — Go's package-private access from
// model.go/workspacehandlers.go maps to crate-module access.
pub struct Workspace {
    pub(crate) wandb_dir: String,

    /// focusMgr is the single source of truth for UI focus state.
    // PARITY: Go's FocusRegionDef closures capture `w`; the Rust manager is
    // generic over an explicit context (focus_manager.rs) and is temporarily
    // mem::take'n out for calls that re-enter `&mut Workspace`
    // (see [`Workspace::focus_mgr_do`]).
    pub(crate) focus_mgr: FocusManager<Workspace>,

    // Configuration and key bindings.
    pub(crate) config: Rc<RefCell<ConfigManager>>,
    pub(crate) key_map: HashMap<&'static str, WorkspaceAction>,

    // Runs sidebar animation state.
    pub(crate) runs_anim_state: AnimatedValue,

    /// runs is the run selector.
    pub(crate) runs: PagedList,
    /// runDirName -> selected
    pub(crate) selected_runs: HashMap<String, bool>,
    /// runDirName or ""
    pub(crate) pinned_run: String,

    // PARITY(S3): Go's `hasLiveRuns atomic.Bool` is deleted; see the module
    // doc. Liveness is `any_run_running()` on the update thread.

    // Run overview for each run keyed by run path.
    pub(crate) run_overview: HashMap<String, Rc<RefCell<RunOverview>>>,
    pub(crate) run_overview_sidebar: RunOverviewSidebar,

    // Run overview preload pipeline for unselected runs.
    pub(crate) overview_preloader: RunOverviewPreloader,

    /// autoSelectLatestRunOnLoad is triggered when at least one run
    /// appears in the workspace.
    // PARITY: Go `sync.Once` → plain bool (main-thread only, §2.6).
    pub(crate) auto_select_latest_run_on_load: bool,

    // TODO: mark live runs upon selection.
    /// filter drives the runs sidebar search box.
    pub(crate) filter: Filter,
    /// runsFilterIndex caches searchable per-run metadata (name, project,
    /// config) for the runs sidebar so metadata filtering stays fast during
    /// live preview.
    pub(crate) runs_filter_index: HashMap<String, WorkspaceRunFilterData>,

    // Multi‑run metrics state.
    pub(crate) metrics_grid_anim_state: AnimatedValue,
    pub(crate) focus: Rc<RefCell<Focus>>,
    pub(crate) metrics_grid: MetricsGrid,
    pub(crate) run_colors: Option<Rc<RefCell<WorkspaceRunColors>>>,

    // System metrics
    pub(crate) system_metrics: HashMap<String, SystemMetricsGrid>,
    pub(crate) system_metrics_pane: SystemMetricsPane,
    /// PARITY: Go aliases `systemMetricsFocus` to the same `*Focus` as
    /// `focus` (workspace.go:168-169) — same `Rc` here.
    pub(crate) system_metrics_focus: Rc<RefCell<Focus>>,
    pub(crate) system_metrics_filter: Rc<RefCell<Filter>>,

    // Run console logs keyed by run path.
    pub(crate) console_logs: HashMap<String, RunConsoleLogs>,
    pub(crate) console_logs_pane: ConsoleLogsPane,

    // Run media keyed by run path.
    pub(crate) media: HashMap<String, Rc<RefCell<MediaStore>>>,
    pub(crate) media_pane: MediaPane,
    pub(crate) media_pane_states: HashMap<String, MediaPaneViewState>,
    /// model.go:425 writes this field directly on run-view exit.
    pub(crate) current_media_run_key: String,

    // Per‑run streaming state keyed by runDirName.
    pub(crate) runs_by_key: HashMap<String, WorkspaceRun>,

    // Heartbeat for live runs.
    // PARITY(C2): Go's `liveChan` dies; the manager emits scheduler
    // commands (heartbeat.rs).
    pub(crate) heartbeat_mgr: HeartbeatManager,

    /// The detected terminal background for the runs-list zebra stripe.
    // PARITY: port of the `termBgR/G/B` + `termBgDetected` package globals
    // (styles.go:47-53). Seeded with `initTerminalBg`'s test-mode arm
    // (frozen values under the harness; `None` at runtime) and overwritten
    // with the RGB carried on `Event::BackgroundColor` (model.rs) — Go
    // instead re-queries the same OSC 11 answer via termenv on first render.
    // `None` ⇒ Go's `termBgDetected == false` ⇒ the #d0d0d0/#1c1c1c
    // fallback (`get_odd_run_style_color`).
    pub(crate) terminal_bg: Option<Rgb>,

    pub(crate) width: isize,
    pub(crate) height: isize,
}

/// WorkspaceRun holds per‑run state for the workspace multi‑run view.
pub struct WorkspaceRun {
    pub key: String,
    /// Handle to the run's reader thread (Go: the `HistorySource`
    /// interface value; nil ⇔ `None`).
    pub reader: Option<HistorySourceHandle>,
    pub(crate) wandb_path: String,
    pub(crate) watcher: Option<WatcherManager>,
    pub(crate) state: RunState,
}

impl WorkspaceRun {
    /// Go `&WorkspaceRun{Key: ..., Reader: ...}` struct-literal zero value.
    pub fn new(key: &str) -> WorkspaceRun {
        WorkspaceRun {
            key: key.to_string(),
            reader: None,
            wandb_path: String::new(),
            watcher: None,
            state: RunState::Unknown,
        }
    }
}

impl Workspace {
    /// Port of Go `NewWorkspace(wandbDir, cfg, logger)`; the logger is
    /// `tracing`.
    pub fn new(wandb_dir: &str, cfg: Option<Rc<RefCell<ConfigManager>>>) -> Workspace {
        tracing::info!("workspace: creating new workspace for wandbDir: {wandb_dir}");

        let cfg =
            cfg.unwrap_or_else(|| Rc::new(RefCell::new(ConfigManager::new(leet_config_path()))));

        // TODO: refactor to allow non-KeyValue items + make filtered ones pointers
        let mut runs = PagedList::default();
        runs.title = "Runs".to_string();
        runs.active = true;
        runs.set_items_per_page(1);

        let focus = Rc::new(RefCell::new(Focus::new()));
        let mut metrics_grid = MetricsGrid::new(
            Rc::clone(&cfg),
            Box::new({
                let cfg = Rc::clone(&cfg);
                move || cfg.borrow().workspace_metrics_grid()
            }),
            Rc::clone(&focus),
        );
        let run_colors = Rc::new(RefCell::new(WorkspaceRunColors::new(graph_colors(
            cfg.borrow().color_scheme(),
        ))));
        metrics_grid.set_series_color_provider(Box::new({
            let run_colors = Rc::clone(&run_colors);
            move |key| run_colors.borrow_mut().assign(key)
        }));

        let smf = Rc::new(RefCell::new(Filter::new()));

        // PARITY(C2): Go creates the shared 4096-cap heartbeat channel here
        // (workspace.go:135); heartbeats now go scheduler → main channel.
        let hb_interval = cfg.borrow().heartbeat_interval();
        tracing::info!("workspace: heartbeat interval set to {hb_interval:?}");

        let run_overview_anim_state = AnimatedValue::new(
            cfg.borrow().workspace_overview_visible(),
            SIDEBAR_MIN_WIDTH as isize,
        );
        let metrics_grid_anim_state =
            AnimatedValue::new(cfg.borrow().workspace_metrics_grid_visible(), 1);

        let system_metrics_pane_anim_state = AnimatedValue::new(
            cfg.borrow().workspace_system_metrics_visible(),
            SYSTEM_METRICS_PANE_MIN_HEIGHT,
        );
        let media_pane_anim_state = AnimatedValue::new(
            cfg.borrow().workspace_media_visible(),
            MEDIA_PANE_MIN_HEIGHT,
        );
        let console_logs_pane_anim_state = AnimatedValue::new(
            cfg.borrow().workspace_console_logs_visible(),
            CONSOLE_LOGS_PANE_MIN_HEIGHT,
        );

        let mut w = Workspace {
            runs_anim_state: AnimatedValue::new(true, SIDEBAR_MIN_WIDTH as isize),
            metrics_grid_anim_state,
            wandb_dir: wandb_dir.to_string(),
            config: Rc::clone(&cfg),
            key_map: build_key_map(&workspace_key_bindings()),
            runs,
            run_overview: HashMap::new(),
            run_overview_sidebar: RunOverviewSidebar::new(
                Rc::clone(&cfg),
                run_overview_anim_state,
                Some(Rc::new(RefCell::new(RunOverview::new()))),
                SidebarSide::Right,
            ),
            overview_preloader: RunOverviewPreloader::new(MAX_CONCURRENT_PRELOADS),
            auto_select_latest_run_on_load: false,
            selected_runs: HashMap::new(),
            pinned_run: String::new(),
            focus: Rc::clone(&focus),
            metrics_grid,
            run_colors: Some(run_colors),
            system_metrics: HashMap::new(),
            system_metrics_pane: SystemMetricsPane::new(system_metrics_pane_anim_state),
            system_metrics_focus: focus,
            system_metrics_filter: smf,
            console_logs: HashMap::new(),
            console_logs_pane: ConsoleLogsPane::new(console_logs_pane_anim_state),
            media: HashMap::new(),
            media_pane: MediaPane::new(
                media_pane_anim_state,
                Some(Box::new({
                    let cfg = Rc::clone(&cfg);
                    move || {
                        let (rows, cols) = cfg.borrow().workspace_media_grid();
                        (rows as isize, cols as isize)
                    }
                })),
            ),
            media_pane_states: HashMap::new(),
            current_media_run_key: String::new(),
            runs_by_key: HashMap::new(),
            heartbeat_mgr: HeartbeatManager::new(hb_interval, HeartbeatOwner::Workspace),
            filter: Filter::new(),
            runs_filter_index: HashMap::new(),
            focus_mgr: FocusManager::default(),
            terminal_bg: test_mode_terminal_bg(),
            width: 0,
            height: 0,
        };
        w.focus_mgr = build_workspace_focus_manager();
        // The runs list starts focused by default.
        w.focus_mgr_do(|fm, w| fm.set_target(w, FocusTarget::RunsList, 1));
        w
    }

    /// Runs a closure with both the focus manager and `&mut self`: the
    /// manager is taken out for the call because its hooks re-enter the
    /// workspace (Go closures capture `w`; see focus_manager.rs).
    pub(crate) fn focus_mgr_do<R>(
        &mut self,
        f: impl FnOnce(&mut FocusManager<Workspace>, &mut Workspace) -> R,
    ) -> R {
        let mut fm = std::mem::take(&mut self.focus_mgr);
        let out = f(&mut fm, self);
        self.focus_mgr = fm;
        out
    }

    /// SetSize updates the workspace dimensions and recomputes pagination
    /// capacity.
    pub fn set_size(&mut self, width: isize, height: isize) {
        self.width = width;
        self.height = height;

        // The runs list lives in the main content area (above the status bar).
        let content_height = (height - STATUS_BAR_HEIGHT as isize).max(0);
        let available =
            (content_height - WORKSPACE_HEADER_LINES as isize - SIDEBAR_BOTTOM_PADDING as isize)
                .max(1);

        self.runs.set_items_per_page(available);
    }

    /// Init wires up long‑running commands for the workspace.
    pub fn init(&mut self) -> Vec<Command> {
        let mut cmds = Vec::new();

        // Start polling immediately; subsequent polls are scheduled by the
        // handler.
        cmds.push(self.poll_wandb_dir_cmd(std::time::Duration::ZERO));

        // PARITY(C2): Go arms `waitForLiveMsg` here (workspace.go:205-207);
        // the heartbeat pump has no Rust counterpart — the scheduler delivers
        // `Event::Heartbeat` directly.
        cmds.extend(media_pane_commands(self.media_pane.init()));

        cmds
    }

    /// Port of Go `Workspace.Update` (workspace.go:214-284).
    //gocyclo:ignore
    pub fn update(&mut self, msg: &Event) -> Vec<Command> {
        // PARITY: workspace.go:215-217 — `picture.IsPictureMsg(msg)` routes
        // picture messages to the media pane and returns. The
        // `mediaPanePrepareMsg` arm (workspace.go:219-224) is replaced by
        // the pane's `prepare_requested` flag, drained via
        // [`Workspace::drain_media_prepare`] after each draw.
        if let Some(picture) = self.media_pane.handle_picture_msg(msg) {
            return media_pane_commands(picture);
        }
        match msg {
            Event::Resize { width, height } => {
                self.handle_window_resize(*width, *height);
                vec![]
            }

            Event::Key(key) => self.handle_key_press_msg(key),

            Event::Mouse(mouse) => self.handle_mouse(mouse),

            Event::WorkspaceRunsAnimation => self.handle_runs_animation(),

            Event::WorkspaceRunOverviewAnimation => self.handle_run_overview_animation(),

            Event::WorkspaceConsoleLogsPaneAnimation => self.handle_console_logs_pane_animation(),

            Event::WorkspaceMediaPaneAnimation => self.handle_media_pane_animation(),

            Event::WorkspaceMetricsGridAnimation => self.handle_metrics_grid_animation(),

            Event::WorkspaceSystemMetricsPaneAnimation => {
                self.handle_system_metrics_pane_animation(std::time::Instant::now())
            }

            Event::WorkspaceRunInit(t) => self.handle_workspace_run_init(t),

            Event::WorkspaceInitErr(t) => self.handle_workspace_init_err(t),

            Event::WorkspaceRunDirs(t) => self.handle_workspace_run_dirs(t),

            Event::WorkspaceRunOverviewPreloaded(t) => {
                self.handle_workspace_run_overview_preloaded(t)
            }

            Event::WorkspaceChunkedBatch(t) => self.handle_workspace_chunked_batch(t),

            Event::WorkspaceBatchedRecords(t) => self.handle_workspace_batched_records(t),

            Event::WorkspaceFileChanged(t) => self.handle_workspace_file_changed(t),

            Event::Heartbeat => self.handle_heartbeat(),

            Event::Error(t) => {
                // Read errors from per-run commands; the affected run simply
                // stops streaming, so surface the error in the logs.
                tracing::error!("workspace: run read failed: {}", t.err);
                vec![]
            }

            _ => vec![],
        }
    }

    /// View renders the runs section: header + paginated list with zebra rows.
    ///
    /// `dark` resolves adaptive colors (Go reads the `darkBackground`
    /// global; the port passes it explicitly, see the layout module doc).
    pub fn view(&mut self, dark: bool) -> Text<'static> {
        let layout = self.compute_viewports();
        let (run_label, current_run_key, system_hint, media_hint, logs_hint) =
            self.sync_current_run_context();

        let mut cols: Vec<Text<'static>> = Vec::new();
        if self.runs_anim_state.is_visible() {
            cols.push(self.render_runs_list(dark));
        }

        let content_width = layout.main_content_area_width;
        let central_column;
        if self.media_pane.is_fullscreen() {
            central_column = self.media_pane.view(
                content_width,
                layout.total_content_area_height,
                &run_label,
                &media_hint,
                dark,
            );
        } else {
            let mut sections: Vec<Text<'static>> = Vec::new();

            if self.metrics_grid_anim_state.is_visible() {
                sections.push(self.render_metrics(layout, dark));
            }

            if layout.system_metrics_height > 0 {
                let grid = self.system_metrics.get_mut(&current_run_key);
                sections.push(self.system_metrics_pane.view(
                    content_width,
                    &run_label,
                    grid,
                    &system_hint,
                    dark,
                ));
            }

            if layout.media_height > 0 {
                sections.push(self.media_pane.view(
                    content_width,
                    layout.media_height,
                    &run_label,
                    &media_hint,
                    dark,
                ));
            } else {
                self.media_pane.park();
            }

            if layout.console_logs_height > 0 {
                sections.push(self.console_logs_pane.view(
                    content_width,
                    &run_label,
                    &logs_hint,
                    dark,
                ));
            }

            // Go filterNonEmptySections: keep sections whose rendered string
            // is non-empty (flexlayout.go:121-129).
            let sections: Vec<Text<'static>> = sections
                .into_iter()
                .filter(|s| !text_to_string(s).is_empty())
                .collect();
            if sections.is_empty() {
                central_column = render_logo_art(content_width, layout.total_content_area_height);
            } else {
                central_column = join_with_separators(sections, content_width as i64, dark);
            }
        }
        // Go placeMainColumn = lipgloss.Place(w, h, Left, Top, content)
        // (flexlayout.go:132-137); the styled Text equivalent is
        // layout::place.
        let central_column = place(
            content_width as i64,
            layout.total_content_area_height as i64,
            LEFT,
            TOP,
            central_column,
        );
        cols.push(central_column);

        if self.run_overview_sidebar.is_visible() {
            cols.push(self.render_run_overview(dark));
        }

        let main_view = join_horizontal(TOP, cols);
        let status_bar = self.render_status_bar(dark);

        let full_view = join_vertical(LEFT, vec![main_view, status_bar]);
        place(self.width as i64, self.height as i64, LEFT, TOP, full_view)
    }

    /// Cleanup stops the workspace's heartbeat, file watchers, and open
    /// readers.
    ///
    /// Safe to call multiple times, including after the program has exited
    /// (e.g. before a full restart).
    ///
    /// Returns the teardown commands (heartbeat cancel + reader closes) —
    /// Go performs these as direct calls; here they are dispatched by the
    /// caller (quit path) or dropped with the runtime on exit (§2.9).
    pub fn cleanup(&mut self) -> Vec<Command> {
        let mut cmds = vec![self.heartbeat_mgr.stop()];
        // PARITY: Go iterates runsByKey unordered here; sorted for
        // determinism.
        let mut keys: Vec<String> = self.runs_by_key.keys().cloned().collect();
        keys.sort();
        for key in keys {
            if let Some(run) = self.runs_by_key.get_mut(&key) {
                Self::stop_watcher(run);
                if let Some(reader) = run.reader {
                    cmds.push(Command::CloseReader { source: reader.id });
                }
            }
        }
        cmds
    }

    /// IsFiltering reports whether any workspace-level filter UI is active.
    pub fn is_filtering(&self) -> bool {
        if self.metrics_grid.is_filter_mode()
            || self.run_overview_sidebar.is_filter_mode()
            || self.filter.is_active()
        {
            return true;
        }
        if let Some(g) = self.active_system_metrics_grid()
            && g.is_filter_mode()
        {
            return true;
        }
        false
    }

    /// SelectedRunWandbFile returns the full path to the .wandb file for the
    /// selected run.
    ///
    /// Returns empty string if no run is selected.
    pub fn selected_run_wandb_file(&self) -> String {
        let total = self.runs.filtered_items.len() as isize;
        if total == 0 {
            return String::new();
        }

        let start_idx = self.runs.current_page() * self.runs.items_per_page();
        let idx = start_idx + self.runs.current_line();
        if idx < 0 || idx >= total {
            return String::new();
        }

        run_wandb_file(&self.wandb_dir, &self.runs.filtered_items[idx as usize].key)
    }

    /// SelectedRunKey returns the run key (directory name) of the currently
    /// selected run.
    pub fn selected_run_key(&self) -> String {
        let total = self.runs.filtered_items.len() as isize;
        if total == 0 {
            return String::new();
        }
        let start_idx = self.runs.current_page() * self.runs.items_per_page();
        let idx = start_idx + self.runs.current_line();
        if idx < 0 || idx >= total {
            return String::new();
        }
        self.runs.filtered_items[idx as usize].key.clone()
    }

    /// MediaStoreForRun returns the workspace's MediaStore for a given run
    /// key.
    pub fn media_store_for_run(&self, run_key: &str) -> Option<Rc<RefCell<MediaStore>>> {
        self.media.get(run_key).cloned()
    }

    /// SaveMediaPaneState stores the media pane's view state for a run.
    pub fn save_media_pane_state(&mut self, run_key: &str, state: MediaPaneViewState) {
        self.media_pane_states.insert(run_key.to_string(), state);
    }

    /// LoadMediaPaneState returns saved media pane view state for a run.
    pub fn load_media_pane_state(&self, run_key: &str) -> Option<&MediaPaneViewState> {
        self.media_pane_states.get(run_key)
    }

    /// Drains the media pane's coalesced prepare request (the Go
    /// `mediaPanePrepareMsg` pump, CONCURRENCY.md §2.5): the owning model
    /// calls this after each draw and dispatches the returned commands
    /// (same shape as `Run::after_draw`).
    pub fn after_draw(&mut self) -> Vec<Command> {
        if !self.media_pane.take_prepare_request() {
            return vec![];
        }
        media_pane_commands(self.media_pane.handle_prepare())
    }

    /// Go `syncCurrentRunContext` (workspace.go:437-497).
    ///
    /// Returns `(runLabel, currentRunKey, systemHint, mediaHint, logsHint)`;
    /// Go's `systemGrid` return is replaced by the key — the caller looks
    /// the grid up at the render site (single-owner maps).
    fn sync_current_run_context(&mut self) -> (String, String, String, String, String) {
        let mut run_label = String::new();
        let mut current_run_key = String::new();
        if let Some(cur) = self.runs.current_item() {
            current_run_key = cur.key.clone();
            run_label = cur.key.clone();
        }

        let current_store = self.media.get(&current_run_key).cloned();
        if current_run_key != self.current_media_run_key {
            if !self.current_media_run_key.is_empty() {
                let state = self.media_pane.save_view_state();
                let key = self.current_media_run_key.clone();
                self.save_media_pane_state(&key, state);
            }

            self.current_media_run_key = current_run_key.clone();
            self.media_pane.set_store(current_store.clone());
            if current_store.is_some() {
                if let Some(state) = self.media_pane_states.get(&current_run_key) {
                    self.media_pane.restore_view_state(state);
                } else {
                    self.media_pane.reset_view_state();
                }
            } else {
                self.media_pane.reset_view_state();
            }
        } else {
            let previous_store = self.media_pane.store.clone();
            self.media_pane.set_store(current_store.clone());
            if previous_store.is_none()
                && current_store.is_some()
                && let Some(state) = self.media_pane_states.get(&current_run_key)
            {
                self.media_pane.restore_view_state(state);
            }
        }

        let mut system_hint = String::new();
        let mut media_hint = String::new();
        let mut logs_hint = String::new();

        if current_run_key.is_empty() {
            // Go SetConsoleLogs(nil).
            self.console_logs_pane.set_console_logs(Vec::new());
            return (
                run_label,
                current_run_key,
                system_hint,
                media_hint,
                logs_hint,
            );
        }

        if let Some(cl) = self.console_logs.get(&current_run_key) {
            let items = cl.items().to_vec();
            self.console_logs_pane.set_console_logs(items);
        } else {
            self.console_logs_pane.set_console_logs(Vec::new());
        }

        if !self.selected_runs.contains_key(&current_run_key) {
            system_hint = "Select this run (Space) to load system metrics.".to_string();
            media_hint = "Select this run (Space) to load media.".to_string();
            logs_hint = "Select this run (Space) to load console logs.".to_string();
        }

        (
            run_label,
            current_run_key,
            system_hint,
            media_hint,
            logs_hint,
        )
    }

    // ---- Layout & Sidebar Helpers ----

    /// recalculateLayout recomputes viewports and pushes dimensions to the
    /// metrics grid. Call after any change that affects available content
    /// area (sidebar toggle, window resize, animation tick).
    pub(crate) fn recalculate_layout(&mut self) {
        let layout = self.compute_viewports();
        self.metrics_grid
            .update_dimensions(layout.main_content_area_width, layout.height);
    }

    /// computeViewports returns the computed layout dimensions.
    ///
    /// Separator lines between visible sections are subtracted from available
    /// height to prevent the status bar from being pushed off screen.
    pub(crate) fn compute_viewports(&self) -> Layout {
        let (left_w, right_w) = (
            self.runs_anim_state.value(),
            self.run_overview_sidebar.width(),
        );
        let content_w = (self.width - left_w - right_w).max(1);
        let total_h = (self.height - STATUS_BAR_HEIGHT as isize).max(0);

        let stack = compute_vertical_stack_layout(
            total_h,
            &[
                StackSectionSpec {
                    id: StackSectionId::Metrics,
                    visible: self.metrics_grid_anim_state.is_visible(),
                    height: 0,
                    flex: true,
                },
                StackSectionSpec {
                    id: StackSectionId::SystemMetrics,
                    visible: self.system_metrics_pane.is_visible(),
                    height: self.system_metrics_pane.height(),
                    flex: false,
                },
                StackSectionSpec {
                    id: StackSectionId::Media,
                    visible: self.media_pane.is_visible(),
                    height: self.media_pane.height(),
                    flex: false,
                },
                StackSectionSpec {
                    id: StackSectionId::ConsoleLogs,
                    visible: self.console_logs_pane.is_visible(),
                    height: self.console_logs_pane.height(),
                    flex: false,
                },
            ],
        );

        Layout {
            left_sidebar_width: left_w,
            main_content_area_width: content_w,
            right_sidebar_width: right_w,
            total_content_area_height: total_h,
            height: stack.height(StackSectionId::Metrics),
            system_metrics_y: stack.y(StackSectionId::SystemMetrics),
            system_metrics_height: stack.height(StackSectionId::SystemMetrics),
            media_y: stack.y(StackSectionId::Media),
            media_height: stack.height(StackSectionId::Media),
            console_logs_y: stack.y(StackSectionId::ConsoleLogs),
            console_logs_height: stack.height(StackSectionId::ConsoleLogs),
        }
    }

    /// updateSidebarDimensions tells both sidebars to recalculate their
    /// expanded widths given the post-toggle visibility of each side.
    pub(crate) fn update_sidebar_dimensions(&mut self, left_visible: bool, right_visible: bool) {
        self.runs_anim_state
            .set_expanded(expanded_sidebar_width(self.width, right_visible));
        self.run_overview_sidebar
            .update_dimensions(self.width, left_visible);
    }

    pub(crate) fn update_bottom_pane_heights(
        &mut self,
        sys_visible: bool,
        media_visible: bool,
        logs_visible: bool,
    ) {
        let metrics_visible = self.metrics_grid_anim_state.target_visible();

        // Compute separator count from the visibility state we're
        // configuring toward.
        let mut section_count = 0;
        if metrics_visible {
            section_count += 1;
        }
        if sys_visible {
            section_count += 1;
        }
        if media_visible {
            section_count += 1;
        }
        if logs_visible {
            section_count += 1;
        }
        let sep_lines = (section_count - 1).max(0);

        let max_h = (self.height - STATUS_BAR_HEIGHT as isize - sep_lines).max(0);
        let mut lower_count = 0;
        if sys_visible {
            lower_count += 1;
        }
        if media_visible {
            lower_count += 1;
        }
        if logs_visible {
            lower_count += 1;
        }
        if lower_count == 0 {
            return;
        }

        let lower_tier_h: isize = if metrics_visible {
            (max_h as f64 * LOWER_TIER_RATIO) as isize
        } else {
            max_h
        };

        let each = lower_tier_h / lower_count;
        if sys_visible {
            self.system_metrics_pane.set_expanded_height(each);
        }
        if media_visible {
            self.media_pane.set_expanded_height(each);
        }
        if logs_visible {
            self.console_logs_pane.set_expanded_height(each);
        }
    }

    // ---- Focus Query Helpers ----

    /// RunSelectorActive reports whether the runs list sidebar is focused,
    /// visible, and has items. Used by the top-level Model to gate Enter
    /// (switch to single-run view) so it only fires when the run list owns
    /// focus.
    // PARITY: Go declares both `runSelectorActive` (private) and
    // `RunSelectorActive` (its exported one-line wrapper); Rust methods
    // cannot share a name, so the single method is public.
    pub fn run_selector_active(&self) -> bool {
        self.focus_mgr.is_target(FocusTarget::RunsList)
            && self.runs_anim_state.is_visible()
            && !self.runs.filtered_items.is_empty()
    }

    pub(crate) fn run_overview_active(&self) -> bool {
        self.focus_mgr.is_target(FocusTarget::Overview) && self.run_overview_sidebar.is_visible()
    }

    /// cycleOverviewSection tries to move within overview sections.
    ///
    /// Returns true if the navigation was handled (i.e. we're not at a
    /// boundary).
    pub(crate) fn cycle_overview_section(&mut self, direction: isize) -> bool {
        let (first_sec, last_sec) = self.run_overview_sidebar.focusable_section_bounds();
        if !self.run_overview_sidebar.anim_state.is_expanded() || first_sec == -1 {
            return false;
        }

        let at_boundary = (direction == 1 && self.run_overview_sidebar.active_section == last_sec)
            || (direction == -1 && self.run_overview_sidebar.active_section == first_sec);
        if at_boundary {
            return false;
        }

        self.run_overview_sidebar.navigate_section(direction);
        true
    }

    /// handleWindowResize handles window resize messages.
    pub(crate) fn handle_window_resize(&mut self, width: isize, height: isize) {
        self.set_size(width, height);
        self.update_sidebar_dimensions(
            self.runs_anim_state.target_visible(),
            self.run_overview_sidebar.anim_state.target_visible(),
        );
        self.update_bottom_pane_heights(
            self.system_metrics_pane.anim_state.target_visible(),
            self.media_pane.anim_state.target_visible(),
            self.console_logs_pane.anim_state.target_visible(),
        );
        self.recalculate_layout();
    }

    // ---- Animation command helpers (Go tea.Tick(AnimationFrame, ..)) ----

    /// runsAnimationCmd returns a command to continue the animation on
    /// section toggle.
    pub(crate) fn runs_animation_cmd(&self) -> Command {
        Command::tick_anim(crate::command::AnimTarget::WorkspaceRuns)
    }

    /// runOverviewAnimationCmd returns a command to continue the animation
    /// on section toggle.
    pub(crate) fn run_overview_animation_cmd(&self) -> Command {
        Command::tick_anim(crate::command::AnimTarget::WorkspaceRunOverview)
    }

    pub(crate) fn console_logs_pane_animation_cmd(&self) -> Command {
        Command::tick_anim(crate::command::AnimTarget::WorkspaceConsoleLogsPane)
    }

    pub(crate) fn media_pane_animation_cmd(&self) -> Command {
        Command::tick_anim(crate::command::AnimTarget::WorkspaceMediaPane)
    }

    pub(crate) fn metrics_grid_animation_cmd(&self) -> Command {
        Command::tick_anim(crate::command::AnimTarget::WorkspaceMetricsGrid)
    }

    pub(crate) fn system_metrics_pane_animation_cmd(&self) -> Command {
        Command::tick_anim(crate::command::AnimTarget::WorkspaceSystemMetricsPane)
    }

    // ---- Run State Helpers ----

    /// anyRunRunning reports whether any selected run is currently live.
    pub(crate) fn any_run_running(&self) -> bool {
        for (key, run) in &self.runs_by_key {
            if run.state == RunState::Running
                && self.selected_runs.get(key).copied().unwrap_or(false)
            {
                return true;
            }
        }
        false
    }

    /// shouldResetRunHeartbeat reports whether new data for the run should
    /// re-arm the workspace heartbeat safety net.
    ///
    /// Like the single-run view, the workspace only arms heartbeats after
    /// the initial drain has finished and live streaming is active for the
    /// run.
    pub(crate) fn should_reset_run_heartbeat(&self, run_key: &str) -> bool {
        match self.runs_by_key.get(run_key) {
            Some(run) => {
                run.state == RunState::Running
                    && run.watcher.as_ref().is_some_and(WatcherManager::is_started)
            }
            None => false,
        }
    }

    // PARITY(S3): Go `syncLiveRunState` (workspace.go:869-878) stored
    // `anyRunRunning()` into the `hasLiveRuns` atomic for the heartbeat
    // timer goroutine. The scheduler design deletes the atomic; call sites
    // evaluate `any_run_running()` inline.

    pub(crate) fn drop_run(&mut self, run_key: &str) -> Vec<Command> {
        let mut cmds = Vec::new();

        self.selected_runs.remove(run_key);

        // If we removed the pinned run, unpin it.
        if self.pinned_run == run_key {
            self.pinned_run.clear();
        }

        if let Some(mut run) = self.runs_by_key.remove(run_key) {
            if !run.wandb_path.is_empty() {
                self.metrics_grid.remove_series(&run.wandb_path);
            }
            Self::stop_watcher(&mut run);
            if let Some(reader) = run.reader {
                // Go run.Reader.Close().
                cmds.push(Command::CloseReader { source: reader.id });
            }
            self.console_logs.remove(run_key);
            self.system_metrics.remove(run_key);
            self.media.remove(run_key);
            self.media_pane_states.remove(run_key);
        }

        // PARITY(S3): syncLiveRunState deleted.

        if !self.any_run_running() {
            cmds.push(self.heartbeat_mgr.stop());
        }
        cmds
    }

    /// getOrCreateRunOverview returns the RunOverview for the given key,
    /// creating one if needed.
    pub(crate) fn get_or_create_run_overview(&mut self, run_key: &str) -> Rc<RefCell<RunOverview>> {
        if let Some(ro) = self.run_overview.get(run_key) {
            return Rc::clone(ro);
        }
        let ro = Rc::new(RefCell::new(RunOverview::new()));
        self.run_overview
            .insert(run_key.to_string(), Rc::clone(&ro));
        ro
    }

    /// getOrCreateConsoleLogs returns the RunConsoleLogs for the given key,
    /// creating one if needed.
    pub(crate) fn get_or_create_console_logs(&mut self, run_key: &str) -> &mut RunConsoleLogs {
        self.console_logs.entry(run_key.to_string()).or_default()
    }

    pub(crate) fn get_or_create_media_store(&mut self, run_key: &str) -> Rc<RefCell<MediaStore>> {
        if let Some(store) = self.media.get(run_key) {
            return Rc::clone(store);
        }
        let store = Rc::new(RefCell::new(MediaStore::new()));
        self.media.insert(run_key.to_string(), Rc::clone(&store));
        store
    }

    pub(crate) fn get_or_create_system_metrics_grid(
        &mut self,
        run_key: &str,
    ) -> &mut SystemMetricsGrid {
        if !self.system_metrics.contains_key(run_key) {
            let (rows, cols) = self.config.borrow().workspace_system_grid();
            let init_w = MIN_METRIC_CHART_WIDTH as isize * cols as isize;
            let init_h = MIN_METRIC_CHART_HEIGHT as isize * rows as isize;

            let g = SystemMetricsGrid::new(
                init_w,
                init_h,
                Rc::clone(&self.config),
                Box::new({
                    let cfg = Rc::clone(&self.config);
                    move || cfg.borrow().workspace_system_grid()
                }),
                Rc::clone(&self.system_metrics_focus),
                Rc::clone(&self.system_metrics_filter),
            );
            self.system_metrics.insert(run_key.to_string(), g);
        }
        self.system_metrics
            .get_mut(run_key)
            .expect("inserted above")
    }

    /// refreshPinnedRun ensures the pinned run (if any) is drawn on top in
    /// all charts.
    pub(crate) fn refresh_pinned_run(&mut self) {
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

    // ---- Rendering ----

    fn render_runs_list(&mut self, dark: bool) -> Text<'static> {
        let (start_idx, end_idx) = self.sync_runs_page();

        let total_w = self.runs_anim_state.value();
        let total_h = (self.height - STATUS_BAR_HEIGHT as isize).max(0);
        if total_w <= SIDEBAR_OVERHEAD as isize || total_h <= 0 {
            // PARITY: Go returns ""; empty Text is the port's "" marker.
            return Text::default();
        }

        let content_width = sidebar_content_width(total_w);
        let mut lines = self.render_run_lines(content_width, dark);

        if lines.is_empty() {
            lines = vec![nav_info_style(dark).render("No runs found.")];
        }

        let mut content_lines: Vec<Text<'static>> = Vec::with_capacity(1 + lines.len());
        content_lines.push(self.render_runs_list_header(start_idx, end_idx, dark));
        content_lines.extend(lines);
        // Go strings.Join(contentLines, "\n").
        let content = join_blocks(content_lines);

        let inner_w = sidebar_inner_width(total_w);

        let styled_content = left_sidebar_style()
            .padding_bottom(SIDEBAR_BOTTOM_PADDING)
            .width(inner_w as i64)
            .height(total_h as i64)
            .max_width(inner_w as i64)
            .max_height(total_h as i64)
            .render_text(content);

        let boxed = left_sidebar_border_style(dark)
            .height(total_h as i64)
            .max_height(total_h as i64)
            .render_text(styled_content);
        place(total_w as i64, total_h as i64, LEFT, TOP, boxed)
    }

    fn render_run_overview(&mut self, dark: bool) -> Text<'static> {
        let mut cur_key = String::new();
        if let Some(cur) = self.runs.current_item() {
            cur_key = cur.key.clone();
        }

        let ro = self.run_overview.get(&cur_key).cloned();
        self.run_overview_sidebar.set_run_overview(ro);
        self.run_overview_sidebar.sync();

        if self.run_overview_active() {
            self.run_overview_sidebar.activate_selection();
        } else {
            self.run_overview_sidebar.deactivate_all_sections();
        }

        let content_h = (self.height - STATUS_BAR_HEIGHT as isize).max(0);
        self.run_overview_sidebar.view(content_h, dark)
    }

    fn render_metrics(&self, layout: Layout, dark: bool) -> Text<'static> {
        let content_width = layout.main_content_area_width;
        let content_height = layout.height;

        if content_width <= 0 || content_height <= 0 {
            return Text::default();
        }

        // No runs selected: show empty state with hint.
        if self.selected_runs.is_empty() {
            return render_metrics_empty_state(
                content_width,
                content_height,
                "Select a run to view charts.",
                dark,
            );
        }

        // Runs selected but no charts: show empty state.
        if self.metrics_grid.chart_count() == 0 {
            return render_metrics_empty_state(
                content_width,
                content_height,
                "No scalar metrics logged.",
                dark,
            );
        }

        // When we have selected runs, render the metrics grid.
        let dims = self
            .metrics_grid
            .calculate_chart_dimensions(content_width, content_height);
        self.metrics_grid.view(dims, dark)
    }

    fn render_status_bar(&mut self, dark: bool) -> Text<'static> {
        let status_text = self.build_status_text();
        let help_text = self.build_help_text();

        let inner_width = (self.width - 2 * STATUS_BAR_PADDING as isize).max(0);
        let space_for_help = (inner_width - text_width(&status_text) as isize).max(0);
        let right_aligned =
            place_horizontal(space_for_help as i64, RIGHT, text_from_str(help_text));

        // Both fragments are raw (unstyled) strings in Go; the concatenation
        // happens at the string level before statusBarStyle renders.
        let full_status = format!("{status_text}{}", text_to_string(&right_aligned));

        status_bar_style(dark)
            .width(self.width as i64)
            .max_width(self.width as i64)
            .render(&full_status)
    }

    pub(crate) fn build_status_text(&mut self) -> String {
        // Filter input mode has top priority.
        if self.filter.is_active() {
            return self.build_runs_filter_status();
        }
        if self.metrics_grid.is_filter_mode() {
            return self.build_metrics_filter_status();
        }
        if let Some(g) = self.active_system_metrics_grid()
            && g.is_filter_mode()
        {
            return self.build_system_metrics_filter_status_for_active();
        }
        if self.run_overview_sidebar.is_filter_mode() {
            return self.build_overview_filter_status();
        }

        // Grid layout prompt (rows/cols) for metrics/system grids.
        if self.config.borrow().is_awaiting_grid_config() {
            return self.config.borrow().grid_config_status().to_string();
        }

        self.build_active_status()
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

    /// Go `buildSystemMetricsFilterStatus(grid)` with the active grid
    /// (workspace.go:1164-1176).
    fn build_system_metrics_filter_status_for_active(&self) -> String {
        let Some(grid) = self.active_system_metrics_grid() else {
            return String::new();
        };
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
        let mut filter_info = self.run_overview_sidebar.filter_info();
        if filter_info.is_empty() {
            filter_info = "no matches".to_string();
        }
        format!(
            "Overview filter ({}): {}{} [{}] (Enter to apply • Tab to toggle mode)",
            self.run_overview_sidebar.filter_mode(),
            self.run_overview_sidebar.filter_query(),
            MEDIUM_SHADE_BLOCK,
            filter_info,
        )
    }

    /// buildActiveStatus summarizes the active filters and selection when no
    /// dedicated input mode (filter / grid config) is active.
    fn build_active_status(&mut self) -> String {
        let mut parts: Vec<String> = Vec::new();

        parts.extend(self.active_filter_status());
        parts.extend(self.active_selection_status());
        parts.extend(self.active_focus_status());

        if parts.is_empty() {
            return self.wandb_dir.clone();
        }
        format!("{} • {}", self.wandb_dir, parts.join(" • "))
    }

    /// activeFilterStatus collects status fragments for all active filters.
    fn active_filter_status(&self) -> Vec<String> {
        let mut parts = Vec::new();

        if !self.filter.query().is_empty() && !self.filter.is_active() {
            parts.push(format!(
                "Runs ({}): {} [{}/{}] (f to change, ctrl+f to clear)",
                self.filter.mode(),
                go_quote(self.filter.query()),
                self.runs.filtered_items.len(),
                self.runs.items.len(),
            ));
        }

        if self.metrics_grid.is_filtering() {
            parts.push(format!(
                "Filter ({}): {} [{}/{}] (/ to change, ctrl+/ to clear)",
                self.metrics_grid.filter_mode(),
                go_quote(self.metrics_grid.filter_query()),
                self.metrics_grid.filtered_chart_count(),
                self.metrics_grid.chart_count(),
            ));
        }

        if let Some(g) = self.active_system_metrics_grid()
            && g.is_filtering()
            && self.system_metrics_pane.is_visible()
        {
            parts.push(format!(
                "System filter ({}): {} [{}/{}] (\\ to change, ctrl+\\ to clear)",
                g.filter_mode(),
                go_quote(&g.filter_query()),
                g.filtered_chart_count(),
                g.chart_count(),
            ));
        }

        if self.run_overview_sidebar.is_visible() && self.run_overview_sidebar.is_filtering() {
            parts.push(format!(
                "Overview: {} [{}] (o to change, ctrl+o to clear)",
                go_quote(self.run_overview_sidebar.filter_query()),
                self.run_overview_sidebar.filter_info(),
            ));
        }

        parts
    }

    /// activeSelectionStatus collects status fragments for sidebar selection
    /// and media.
    fn active_selection_status(&mut self) -> Vec<String> {
        let mut parts = Vec::new();

        if self.run_overview_active() {
            let (key, value) = self.run_overview_sidebar.selected_item();
            if !key.is_empty() {
                parts.push(format!("{key}: {value}"));
            }
        }

        if self.media_pane.active() {
            let label = self.media_pane.status_label();
            if !label.is_empty() {
                parts.push(label);
            }
        }

        parts
    }

    /// activeFocusStatus collects status fragments for the focused chart.
    fn active_focus_status(&self) -> Vec<String> {
        let focus = self.focus.borrow();
        if focus.focus_type == FocusType::None {
            return Vec::new();
        }

        let mut parts = vec![focus.title.clone()];

        match focus.focus_type {
            FocusType::MainChart => {
                let scale_label = self.metrics_grid.focused_chart_scale_label();
                if !scale_label.is_empty() {
                    parts.push(scale_label.to_string());
                }
            }
            FocusType::SystemChart => {
                if let Some(g) = self.active_system_metrics_grid() {
                    let detail = g.focused_chart_title_detail();
                    if !detail.is_empty() {
                        parts.push(detail);
                    }
                    let view_mode = g.focused_chart_view_mode_label();
                    if !view_mode.is_empty() {
                        parts.push(view_mode);
                    }
                    let scale_label = g.focused_chart_scale_label();
                    if !scale_label.is_empty() {
                        parts.push(scale_label);
                    }
                }
            }
            FocusType::None => {}
        }

        parts
    }

    /// buildHelpText builds the help text for the status bar.
    fn build_help_text(&self) -> &'static str {
        // Hide help hint while any workspace-level filter / grid config is
        // active.
        if self.is_filtering() || self.config.borrow().is_awaiting_grid_config() {
            return "";
        }
        "h: help"
    }

    /// syncRunsPage clamps the SectionView page/line against the current
    /// item set and returns the bounds of the visible slice
    /// `[startIdx, endIdx)`.
    pub(crate) fn sync_runs_page(&mut self) -> (isize, isize) {
        let total = self.runs.filtered_items.len() as isize;
        let items_per_page = self.runs.items_per_page();

        if total == 0 || items_per_page <= 0 {
            self.runs.home();
            return (0, 0);
        }

        let mut total_pages = (total + items_per_page - 1) / items_per_page;
        if total_pages <= 0 {
            total_pages = 1;
        }
        let mut page = self.runs.current_page().max(0);
        if page >= total_pages {
            page = total_pages - 1;
        }

        let start_idx = page * items_per_page;
        let end_idx = (start_idx + items_per_page).min(total);

        let max_line = (end_idx - start_idx - 1).max(0);
        let line = self.runs.current_line().max(0).min(max_line);

        self.runs.set_page_and_line(page, line);
        (start_idx, end_idx)
    }

    /// renderRunsListHeader renders the runs list title and counts.
    fn render_runs_list_header(
        &self,
        start_idx: isize,
        end_idx: isize,
        dark: bool,
    ) -> Text<'static> {
        let title = run_overview_sidebar_section_header_style(dark).render("Runs");

        let filtered_count = self.runs.filtered_items.len() as isize;
        let total_count = self.runs.items.len() as isize;
        let mut info = String::new();

        if !self.filter.query().is_empty() && total_count > 0 {
            let ipp = self.runs.items_per_page();
            if filtered_count == 0 {
                info = format!(" [0 of {total_count} filtered]");
            } else if ipp > 0 && filtered_count > ipp {
                info = format!(
                    " [{}-{} of {} filtered from {} total]",
                    start_idx + 1,
                    end_idx,
                    filtered_count,
                    total_count,
                );
            } else {
                info = format!(" [{filtered_count} filtered from {total_count} total]");
            }
        } else if filtered_count > 0 {
            let ipp = self.runs.items_per_page();
            if ipp > 0 && filtered_count > ipp {
                info = format!(" [{}-{} of {}]", start_idx + 1, end_idx, filtered_count);
            } else {
                info = format!(" [{filtered_count} items]");
            }
        }

        concat_single_lines(vec![title, nav_info_style(dark).render(&info)])
    }

    pub(crate) fn run_path_for_key(&self, run_key: &str) -> String {
        if run_key.is_empty() {
            return String::new();
        }
        run_wandb_file(&self.wandb_dir, run_key)
    }

    pub(crate) fn run_color_for_key(&self, run_key: &str) -> AdaptiveColor {
        let run_path = self.run_path_for_key(run_key);
        match &self.run_colors {
            None => {
                let colors = graph_colors(self.config.borrow().color_scheme());
                if colors.is_empty() {
                    // Go's zero AdaptiveColor{}.
                    return AdaptiveColor {
                        light: Rgb(0, 0, 0),
                        dark: Rgb(0, 0, 0),
                    };
                }
                colors[color_index(&run_path, colors.len())]
            }
            Some(rc) => rc.borrow_mut().assign(&run_path),
        }
    }

    /// Records the terminal background delivered on `Event::BackgroundColor`
    /// (model.rs) for the zebra stripe. Go's equivalent latch is
    /// `initTerminalBg` caching termenv's OSC 11 query in the `termBg*`
    /// package globals (styles.go:55-84).
    pub(crate) fn set_terminal_bg(&mut self, rgb: Rgb) {
        self.terminal_bg = Some(rgb);
    }

    /// renderRunLines renders the visible slice with zebra background and
    /// selection.
    fn render_run_lines(&self, content_width: isize, dark: bool) -> Vec<Text<'static>> {
        let items_per_page = self.runs.items_per_page();
        let start_idx = self.runs.current_page() * items_per_page;
        let end_idx = (start_idx + items_per_page).min(self.runs.filtered_items.len() as isize);

        let mut lines: Vec<Text<'static>> =
            Vec::with_capacity((end_idx - start_idx).max(0) as usize);
        let selected_line = self.runs.current_line();

        let mut i = start_idx;
        while i < end_idx {
            let idx_on_page = i - start_idx;
            let item = &self.runs.filtered_items[i as usize];

            // Determine row style.
            let mut style = even_run_style();
            if idx_on_page % 2 == 1 {
                // PARITY: Go's oddRunStyle blends the REAL terminal
                // background 5% toward gray (styles.go:97-109); the port's
                // detected background arrives via `set_terminal_bg`.
                style = odd_run_style(self.terminal_bg, dark);
            }
            if idx_on_page == selected_line {
                if self.runs.active {
                    style = selected_run_style(dark);
                } else {
                    style = selected_run_inactive_style(dark);
                }
            }

            let run_key = item.key.clone();
            let run_color = self.run_color_for_key(&run_key);

            let is_selected = self.selected_runs.get(&run_key).copied().unwrap_or(false);
            let is_pinned = self.pinned_run == run_key;

            let mut mark = RUN_MARK;
            if is_selected {
                mark = SELECTED_RUN_MARK;
            }
            if is_pinned {
                mark = PINNED_RUN_MARK;
            }

            // Render prefix without background.
            let prefix = GoStyle::new()
                .foreground(adaptive_to_color(run_color, dark))
                .render(&format!("{mark} "));
            let prefix_width = block_width(&prefix) as isize;

            // Apply subtle muting to unselected/unpinned runs
            let mut name_style = style.foreground(adaptive_to_color(COLOR_ITEM_VALUE, dark));
            if idx_on_page == selected_line {
                name_style = name_style.foreground(rgb_to_color(COLOR_DARK));
            }
            if !is_selected && !is_pinned {
                name_style = name_style.foreground(adaptive_to_color(COLOR_TEXT, dark));
            }

            // Render name with background and optional muting
            let name_width = (content_width - prefix_width).max(1);
            let name = name_style.render(&truncate_value(&run_key, name_width));

            // Pad the styled name to fill remaining width
            let padding_needed = content_width - prefix_width - block_width(&name) as isize;
            let padding = style.render(&" ".repeat(padding_needed.max(0) as usize));

            lines.push(concat_single_lines(vec![prefix, name, padding]));
            i += 1;
        }

        lines
    }
}

// ---- FocusManager wiring ----

/// Go `buildWorkspaceFocusManager` (workspace.go:615-660). Free function:
/// the hooks are plain fn pointers over the Workspace context
/// (focus_manager.rs).
fn build_workspace_focus_manager() -> FocusManager<Workspace> {
    FocusManager::new(vec![
        FocusRegionDef {
            target: FocusTarget::RunsList,
            available: Some(runs_focus_available),
            available_target: Some(runs_focus_target_available),
            activate: activate_runs_focus,
            deactivate: deactivate_runs_focus,
        },
        FocusRegionDef {
            target: FocusTarget::MetricsGrid,
            available: Some(metrics_grid_focus_available),
            available_target: Some(metrics_grid_focus_target_available),
            activate: activate_metrics_grid_focus,
            deactivate: deactivate_metrics_grid_focus,
        },
        FocusRegionDef {
            target: FocusTarget::SystemMetrics,
            available: Some(sys_metrics_focus_available),
            available_target: Some(sys_metrics_focus_target_available),
            activate: activate_sys_metrics_focus,
            deactivate: deactivate_sys_metrics_focus,
        },
        FocusRegionDef {
            target: FocusTarget::Media,
            available: Some(media_focus_available),
            available_target: Some(media_focus_target_available),
            activate: activate_media_focus,
            deactivate: deactivate_media_focus,
        },
        FocusRegionDef {
            target: FocusTarget::ConsoleLogs,
            available: Some(logs_focus_available),
            available_target: Some(logs_focus_target_available),
            activate: activate_logs_focus,
            deactivate: deactivate_logs_focus,
        },
        FocusRegionDef {
            target: FocusTarget::Overview,
            available: Some(overview_focus_available),
            available_target: Some(overview_focus_target_available),
            activate: activate_overview_focus,
            deactivate: deactivate_overview_focus,
        },
    ])
}

// ---- Focus availability ----

fn runs_focus_available(w: &Workspace) -> bool {
    w.runs_anim_state.is_visible() && !w.runs.filtered_items.is_empty()
}

fn runs_focus_target_available(w: &Workspace) -> bool {
    w.runs_anim_state.target_visible() && !w.runs.filtered_items.is_empty()
}

fn metrics_grid_focus_available(w: &Workspace) -> bool {
    w.metrics_grid_anim_state.is_expanded() && w.metrics_grid.chart_count() > 0
}

fn metrics_grid_focus_target_available(w: &Workspace) -> bool {
    w.metrics_grid_anim_state.target_visible() && w.metrics_grid.chart_count() > 0
}

fn sys_metrics_focus_available(w: &Workspace) -> bool {
    if !w.system_metrics_pane.is_expanded() {
        return false;
    }
    w.active_system_metrics_grid()
        .is_some_and(|g| g.chart_count() > 0)
}

fn sys_metrics_focus_target_available(w: &Workspace) -> bool {
    if !w.system_metrics_pane.anim_state.target_visible() {
        return false;
    }
    w.active_system_metrics_grid()
        .is_some_and(|g| g.chart_count() > 0)
}

fn media_focus_available(w: &Workspace) -> bool {
    w.media_pane.is_expanded() && w.media_pane.has_data()
}

fn media_focus_target_available(w: &Workspace) -> bool {
    w.media_pane.anim_state.target_visible() && w.media_pane.has_data()
}

fn logs_focus_available(w: &Workspace) -> bool {
    w.console_logs_pane.is_expanded()
}

fn logs_focus_target_available(w: &Workspace) -> bool {
    w.console_logs_pane.anim_state.target_visible()
}

fn overview_focus_available(w: &Workspace) -> bool {
    let (first_sec, _) = w.run_overview_sidebar.focusable_section_bounds();
    w.run_overview_sidebar.anim_state.is_expanded() && first_sec != -1
}

fn overview_focus_target_available(w: &Workspace) -> bool {
    let (first_sec, _) = w.run_overview_sidebar.focusable_section_bounds();
    w.run_overview_sidebar.anim_state.target_visible() && first_sec != -1
}

// ---- Focus activate ----

fn activate_runs_focus(w: &mut Workspace, _direction: isize) {
    w.runs.active = true;
}

fn activate_metrics_grid_focus(w: &mut Workspace, _direction: isize) {
    {
        let mut focus = w.focus.borrow_mut();
        focus.focus_type = FocusType::MainChart;
        if focus.row < 0 {
            focus.row = 0;
            focus.col = 0;
        }
    }
    w.metrics_grid.navigate_focus(0, 0);
}

fn activate_sys_metrics_focus(w: &mut Workspace, _direction: isize) {
    // PARITY: Go nil-checks systemMetricsFocus; always set here.
    {
        let mut focus = w.system_metrics_focus.borrow_mut();
        focus.focus_type = FocusType::SystemChart;
        if focus.row < 0 {
            focus.row = 0;
            focus.col = 0;
        }
    }
    if let Some(g) = w.active_system_metrics_grid() {
        g.navigate_focus(0, 0);
    }
}

fn activate_media_focus(w: &mut Workspace, _direction: isize) {
    w.media_pane.set_active(true);
}

fn activate_logs_focus(w: &mut Workspace, _direction: isize) {
    w.console_logs_pane.set_active(true);
}

fn activate_overview_focus(w: &mut Workspace, direction: isize) {
    let (first_sec, last_sec) = w.run_overview_sidebar.focusable_section_bounds();
    if direction >= 0 {
        w.run_overview_sidebar.set_active_section(first_sec);
    } else {
        w.run_overview_sidebar.set_active_section(last_sec);
    }
}

// ---- Focus deactivate ----

fn deactivate_runs_focus(w: &mut Workspace) {
    w.runs.active = false;
}

fn deactivate_metrics_grid_focus(w: &mut Workspace) {
    let mut focus = w.focus.borrow_mut();
    if focus.focus_type == FocusType::MainChart {
        focus.reset();
    }
}

fn deactivate_sys_metrics_focus(w: &mut Workspace) {
    // PARITY: Go nil-checks systemMetricsFocus; always set here.
    let mut focus = w.system_metrics_focus.borrow_mut();
    if focus.focus_type == FocusType::SystemChart {
        focus.reset();
    }
}

fn deactivate_media_focus(w: &mut Workspace) {
    w.media_pane.set_active(false);
}

fn deactivate_logs_focus(w: &mut Workspace) {
    w.console_logs_pane.set_active(false);
}

fn deactivate_overview_focus(w: &mut Workspace) {
    w.run_overview_sidebar.deactivate_all_sections();
}

// ---- Standalone rendering helpers ----
// PARITY: `renderMetricsEmptyState` (workspace.go:1078) and `renderLogoArt`
// (workspace.go:1091) are hosted in run.rs (run.go's renderMainView /
// renderLoadingScreen needed them first); reused via the `crate::run`
// imports above.

/// `strings.Join(blocks, "\n")` over rendered blocks: each block contributes
/// its lines in order.
pub(crate) fn join_blocks(blocks: Vec<Text<'static>>) -> Text<'static> {
    let mut lines: Vec<Line<'static>> = Vec::new();
    for block in blocks {
        lines.extend(block.lines);
    }
    Text::from(lines)
}

/// Go string concatenation of single-line rendered fragments
/// (`prefix + name + padding`).
pub(crate) fn concat_single_lines(parts: Vec<Text<'static>>) -> Text<'static> {
    let mut spans = Vec::new();
    for part in parts {
        if let Some(line) = part.lines.into_iter().next() {
            spans.extend(line.spans);
        }
    }
    Text::from(Line::from(spans))
}

// ---- WorkspaceRunFilterHost seam (workspacerunfilter.go) ----

impl WorkspaceRunFilterHost for Workspace {
    type Cmd = Vec<Command>;

    fn filter(&self) -> &Filter {
        &self.filter
    }
    fn filter_mut(&mut self) -> &mut Filter {
        &mut self.filter
    }
    fn runs(&self) -> &PagedList {
        &self.runs
    }
    fn runs_mut(&mut self) -> &mut PagedList {
        &mut self.runs
    }
    fn runs_anim_state(&self) -> &AnimatedValue {
        &self.runs_anim_state
    }
    fn runs_filter_index(&self) -> &HashMap<String, WorkspaceRunFilterData> {
        &self.runs_filter_index
    }
    fn runs_filter_index_mut(&mut self) -> &mut HashMap<String, WorkspaceRunFilterData> {
        &mut self.runs_filter_index
    }

    fn handle_toggle_runs_sidebar(&mut self, msg: &crate::key::KeyEvent) -> Option<Vec<Command>> {
        // Inherent handler (workspace_handlers.rs); Go returns the tea.Cmd.
        Some(Workspace::handle_toggle_runs_sidebar(self, msg))
    }
    fn set_console_logs_pane_active(&mut self, active: bool) {
        self.console_logs_pane.set_active(active);
    }
    fn deactivate_all_run_overview_sections(&mut self) {
        self.run_overview_sidebar.deactivate_all_sections();
    }
    fn restore_run_cursor(&mut self, run_key: &str) {
        Workspace::restore_run_cursor(self, run_key);
    }
    fn sync_runs_page(&mut self) {
        let _ = Workspace::sync_runs_page(self);
    }
}

// ---------------------------------------------------------------------------
// Tests — transliterations of workspace_test.go plus the workspace-side
// cases of workspace_runcolors_test.go.
//
// TODO(model.rs): two workspace_test.go cases construct leet.NewModel and
// MUST be transliterated when model.rs lands — they pin metrics-filter
// isolation across the workspace↔run-view mode switch (the workspace filter
// must not leak into, or be cleared from, the run view):
//   - TestModel_WorkspaceFilterDoesNotLeakIntoRunView (workspace_test.go:16)
//   - TestModel_CtrlLInRunViewDoesNotClearWorkspaceFilter
//     (workspace_test.go:61)
// ---------------------------------------------------------------------------

#[cfg(test)]
pub(crate) mod test_support {
    //! Shared scaffolding for the workspace test transliterations (Go's
    //! `package leet_test` helpers + testhelpers.go accessors used by them).

    use super::*;
    use crate::command::SourceId;
    use crate::key::{KeyCode, KeyEvent, KeyMods};
    use leet_charts::styles::default_dark_background;
    use leet_proto::wandb_internal::{
        ConfigItem, ConfigRecord, EnvironmentRecord, SummaryItem, SummaryRecord,
    };

    /// Go `leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), ..)`.
    /// The TempDir must outlive the workspace (config saves on setters).
    pub(crate) fn test_config() -> (tempfile::TempDir, Rc<RefCell<ConfigManager>>) {
        let dir = tempfile::tempdir().unwrap();
        let cfg = Rc::new(RefCell::new(ConfigManager::new(
            dir.path().join("config.json"),
        )));
        (dir, cfg)
    }

    pub(crate) fn dark() -> bool {
        default_dark_background()
    }

    /// Go `keyRune(r)` (workspace_keyhandling_test.go:17-19).
    pub(crate) fn key_rune(r: char) -> KeyEvent {
        KeyEvent {
            code: KeyCode::Char(r),
            text: Some(r.to_string()),
            mods: KeyMods::NONE,
        }
    }

    pub(crate) fn key_code(code: KeyCode) -> KeyEvent {
        KeyEvent {
            code,
            text: None,
            mods: KeyMods::NONE,
        }
    }

    pub(crate) fn ctrl_key(c: char) -> KeyEvent {
        KeyEvent {
            code: KeyCode::Char(c),
            text: None,
            mods: KeyMods {
                ctrl: true,
                alt: false,
                shift: false,
            },
        }
    }

    pub(crate) fn update_key(w: &mut Workspace, key: KeyEvent) -> Vec<Command> {
        w.update(&Event::Key(key))
    }

    pub(crate) fn update_resize(w: &mut Workspace, width: isize, height: isize) {
        let _ = w.update(&Event::Resize { width, height });
    }

    pub(crate) fn update_run_dirs(w: &mut Workspace, run_keys: &[&str]) -> Vec<Command> {
        w.update(&Event::WorkspaceRunDirs(
            crate::event::WorkspaceRunDirsMsg {
                run_keys: run_keys.iter().map(|s| s.to_string()).collect(),
                err: None,
            },
        ))
    }

    /// Go `stripANSI(w.View().Content)`: spans carry styles out-of-band, so
    /// joining span contents IS the ANSI-stripped view.
    pub(crate) fn view_string(w: &mut Workspace) -> String {
        text_to_string(&w.view(dark()))
    }

    /// testhelpers.go `TestForceExpandSystemMetricsPane`.
    pub(crate) fn force_expand_system_metrics_pane(w: &mut Workspace, h: isize) {
        w.system_metrics_pane.set_expanded_height(h);
        w.system_metrics_pane.anim_state.force_expand();
    }

    /// testhelpers.go `TestForceExpandConsoleLogsPane`.
    pub(crate) fn force_expand_console_logs_pane(w: &mut Workspace, h: isize) {
        w.console_logs_pane.set_expanded_height(h);
        w.console_logs_pane.anim_state.force_expand();
    }

    /// testhelpers.go `TestIsRunSelected`.
    pub(crate) fn is_run_selected(w: &Workspace, run_key: &str) -> bool {
        w.selected_runs.get(run_key).copied().unwrap_or(false)
    }

    /// testhelpers.go `TestCurrentRunKey`.
    pub(crate) fn current_run_key(w: &Workspace) -> String {
        match w.runs.current_item() {
            Some(cur) => cur.key.clone(),
            None => String::new(),
        }
    }

    /// testhelpers.go `TestFilteredRunKeys`.
    pub(crate) fn filtered_run_keys(w: &Workspace) -> Vec<String> {
        w.runs
            .filtered_items
            .iter()
            .map(|item| item.key.clone())
            .collect()
    }

    /// testhelpers.go `TestAttachRun`.
    pub(crate) fn attach_run(w: &mut Workspace, run: WorkspaceRun, selected: bool) {
        let key = run.key.clone();
        w.runs_by_key.insert(key.clone(), run);
        if selected {
            w.selected_runs.insert(key, true);
        } else {
            w.selected_runs.remove(&key);
        }
    }

    /// testhelpers.go `TestSetWatcherStarted` (on WorkspaceRun).
    pub(crate) fn set_watcher_started(run: &mut WorkspaceRun, started: bool) {
        if run.watcher.is_none() {
            run.watcher = Some(WatcherManager::new());
        }
        run.watcher
            .as_mut()
            .expect("set above")
            .set_started_for_test(started);
    }

    /// testhelpers.go `TestWatcherActive`.
    pub(crate) fn watcher_active(run: &WorkspaceRun) -> bool {
        run.watcher.as_ref().is_some_and(WatcherManager::is_started)
    }

    /// A reader handle standing in for Go's stubHistorySource; "closed"
    /// means a `Command::CloseReader` for the id was emitted.
    pub(crate) fn stub_reader(id: u64) -> Option<HistorySourceHandle> {
        Some(HistorySourceHandle { id: SourceId(id) })
    }

    pub(crate) fn close_reader_ids(cmds: &[Command]) -> Vec<u64> {
        cmds.iter()
            .filter_map(|c| match c {
                Command::CloseReader { source } => Some(source.0),
                _ => None,
            })
            .collect()
    }

    /// testhelpers.go `TestSeedRunOverview`: populates overview data so the
    /// sidebar becomes focusable.
    pub(crate) fn seed_run_overview(w: &mut Workspace, run_key: &str) {
        let mut ro = RunOverview::new();
        ro.process_run_msg(leet_data::run_overview::RunMsg {
            id: "test-id".to_string(),
            project: "test-project".to_string(),
            config: Some(ConfigRecord {
                update: vec![
                    ConfigItem {
                        nested_key: vec!["lr".to_string()],
                        value_json: "0.01".to_string(),
                        ..Default::default()
                    },
                    ConfigItem {
                        nested_key: vec!["epochs".to_string()],
                        value_json: "10".to_string(),
                        ..Default::default()
                    },
                ],
                ..Default::default()
            }),
            ..Default::default()
        });
        ro.process_summary_msg(&[SummaryRecord {
            update: vec![SummaryItem {
                nested_key: vec!["loss".to_string()],
                value_json: "0.42".to_string(),
                ..Default::default()
            }],
            ..Default::default()
        }]);
        ro.process_system_info_msg(Some(&EnvironmentRecord {
            writer_id: "w1".to_string(),
            os: "linux".to_string(),
            ..Default::default()
        }));

        let ro = Rc::new(RefCell::new(ro));
        w.run_overview.insert(run_key.to_string(), Rc::clone(&ro));
        w.run_overview_sidebar.set_run_overview(Some(ro));
        w.run_overview_sidebar.sync();

        // Trigger section height calculation so ItemsPerPage > 0.
        let content_h = (w.height - STATUS_BAR_HEIGHT as isize).max(0);
        let _ = w.run_overview_sidebar.view(content_h, dark());
    }
}

#[cfg(test)]
mod tests {
    use pretty_assertions::assert_eq;

    use super::test_support::*;
    use super::*;
    use crate::event::{HistoryMsg, MetricData, RunMsg as EventRunMsg};
    use crate::key::KeyCode;
    use crate::workspace_system_metrics_pane::WORKSPACE_SYSTEM_METRICS_PANE_HEADER;

    fn new_workspace(wandb_dir: &str) -> (tempfile::TempDir, Workspace) {
        let (cfg_dir, cfg) = test_config();
        (cfg_dir, Workspace::new(wandb_dir, Some(cfg)))
    }

    // Go: TestWorkspace_View_SystemMetricsPaneShowsRunLabel.
    #[test]
    fn workspace_view_system_metrics_pane_shows_run_label() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());
        update_resize(&mut w, 200, 60);

        let run_key = "run-20260209_010101-abcdefg";
        let _ = update_run_dirs(&mut w, &[run_key]);

        force_expand_system_metrics_pane(&mut w, 20);
        assert!(w.system_metrics_pane.is_visible());

        let view = view_string(&mut w);
        assert!(view.contains(WORKSPACE_SYSTEM_METRICS_PANE_HEADER));
        assert!(
            view.contains(run_key),
            "system metrics pane header should include the current run label"
        );
    }

    // Go: TestWorkspace_View_SystemMetricsPaneShowsSelectHint.
    #[test]
    fn workspace_view_system_metrics_pane_shows_select_hint() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());
        update_resize(&mut w, 200, 60);

        let run_key = "run-20260209_010101-abcdefg";
        let _ = update_run_dirs(&mut w, &[run_key]);

        // Deselect the run if auto-selected.
        if is_run_selected(&w, run_key) {
            let _ = update_key(&mut w, key_code(KeyCode::Space));
        }
        assert!(!is_run_selected(&w, run_key));

        force_expand_system_metrics_pane(&mut w, 20);

        let view = view_string(&mut w);
        assert!(
            view.contains("Select this run (Space) to load system metrics."),
            "unselected run should show select hint in system metrics pane"
        );
    }

    // Go: TestWorkspace_View_ConsoleLogsPaneRendersWhenVisible.
    #[test]
    fn workspace_view_console_logs_pane_renders_when_visible() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());
        update_resize(&mut w, 200, 60);

        let run_key = "run-20260209_010101-abcdefg";
        let _ = update_run_dirs(&mut w, &[run_key]);

        force_expand_console_logs_pane(&mut w, 10);
        assert!(w.console_logs_pane.is_expanded());

        let view = view_string(&mut w);
        assert!(
            view.contains("Console Logs"),
            "workspace view should include Console Logs header when bottom bar is visible"
        );
    }

    // Go: TestWorkspace_View_ConsoleLogsPaneShowsNoDataWithoutLogs.
    #[test]
    fn workspace_view_console_logs_pane_shows_no_data_without_logs() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());
        update_resize(&mut w, 200, 60);

        let run_key = "run-20260209_010101-abcdefg";
        let _ = update_run_dirs(&mut w, &[run_key]);

        force_expand_console_logs_pane(&mut w, 10);

        let view = view_string(&mut w);
        assert!(
            view.contains("No data."),
            "bottom bar should show 'No data.' when no console logs exist"
        );
    }

    // Go: TestWorkspace_View_HiddenPanesNotRendered.
    #[test]
    fn workspace_view_hidden_panes_not_rendered() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());
        update_resize(&mut w, 200, 60);

        assert!(!w.system_metrics_pane.is_visible());
        assert!(!w.console_logs_pane.is_expanded());

        let view = view_string(&mut w);
        assert!(
            !view.contains("Console Logs"),
            "collapsed bottom bar should not appear in view"
        );
    }

    // Go: TestWorkspace_View_BothPanesVisibleSimultaneously.
    #[test]
    fn workspace_view_both_panes_visible_simultaneously() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());
        update_resize(&mut w, 200, 80);

        let run_key = "run-20260209_010101-abcdefg";
        let _ = update_run_dirs(&mut w, &[run_key]);

        force_expand_system_metrics_pane(&mut w, 15);
        force_expand_console_logs_pane(&mut w, 10);

        let view = view_string(&mut w);
        assert!(
            view.contains(WORKSPACE_SYSTEM_METRICS_PANE_HEADER),
            "system metrics pane should be in view"
        );
        assert!(
            view.contains("Console Logs"),
            "console logs should be in view"
        );
        assert!(view.contains(run_key), "run label should appear in view");
    }

    // Go: TestWorkspace_Cleanup_ReleasesRunResources.
    // ADAPTED: Go's closeTrackingHistorySource wraps the HistorySource
    // interface; readers are opaque SourceId handles here, so "the reader
    // was closed" is asserted as the CloseReader command for its id
    // (dispatched by the caller; the runtime drops the reader's request
    // sender).
    #[test]
    fn workspace_cleanup_releases_run_resources() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());

        let mut run = WorkspaceRun::new("run-1");
        run.reader = stub_reader(7);
        set_watcher_started(&mut run, true);
        attach_run(&mut w, run, true);

        // Arm the heartbeat via a live record, as during normal streaming.
        let _ = w.handle_workspace_record(
            "run-1",
            &Event::Run(EventRunMsg {
                id: "run-1".to_string(),
                display_name: "test".to_string(),
                ..Default::default()
            }),
        );
        let _ = w.handle_workspace_record(
            "run-1",
            &Event::History(HistoryMsg {
                metrics: std::collections::HashMap::from([(
                    "loss".to_string(),
                    MetricData {
                        x: vec![1.0],
                        y: vec![0.5],
                    },
                )]),
                ..Default::default()
            }),
        );
        assert!(w.heartbeat_mgr.timer_armed());

        let cmds = w.cleanup();

        assert!(
            !w.heartbeat_mgr.timer_armed(),
            "heartbeat should be stopped"
        );
        assert!(
            !watcher_active(w.runs_by_key.get("run-1").expect("run attached")),
            "watcher should be stopped"
        );
        assert_eq!(close_reader_ids(&cmds), vec![7], "reader should be closed");

        // Cleanup is idempotent.
        let _ = w.cleanup();
    }

    // ---- workspace_runcolors_test.go (workspace-side cases; the
    // workspaceRunColors unit cases live in leet-charts) ----

    fn test_workspace_run_color_palette() -> Vec<AdaptiveColor> {
        vec![AdaptiveColor {
            light: leet_charts::styles::parse_hex_color("#3DBAC4").unwrap(),
            dark: leet_charts::styles::parse_hex_color("#58D3DB").unwrap(),
        }]
    }

    fn color_key(c: AdaptiveColor) -> String {
        leet_charts::workspace_run_colors::workspace_run_color_key(c)
    }

    // Go: TestWorkspaceApplyRunKeysAssignsUniqueColors.
    #[test]
    fn workspace_apply_run_keys_assigns_unique_colors() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());

        let mut run_keys: Vec<String> = Vec::with_capacity(24);
        for i in 0..24 {
            run_keys.push(format!("run-20260209_{:06}-{:08x}", 10100 + i, i));
        }

        let _ = w.apply_run_keys(&run_keys);

        let mut seen: HashMap<String, String> = HashMap::new();
        for run_key in &run_keys {
            let key = color_key(w.run_color_for_key(run_key));
            if let Some(previous) = seen.get(&key) {
                panic!(
                    "workspace run color collision: {previous} and {run_key} both mapped to {key}"
                );
            }
            seen.insert(key, run_key.clone());
        }
    }

    // Go: TestWorkspaceApplyRunKeysReusesReleasedColor.
    #[test]
    fn workspace_apply_run_keys_reuses_released_color() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());
        // testhelpers.go TestSetRunColors.
        w.run_colors = Some(Rc::new(RefCell::new(WorkspaceRunColors::new(
            &test_workspace_run_color_palette(),
        ))));

        const RUN_A: &str = "run-20260209_010100-aaaabbbb";
        const RUN_B: &str = "run-20260209_010101-bbbbcccc";
        const RUN_C: &str = "run-20260209_010102-ccccdddd";

        let _ = w.apply_run_keys(&[RUN_A.to_string(), RUN_B.to_string()]);
        let color_a = color_key(w.run_color_for_key(RUN_A));
        let color_b = color_key(w.run_color_for_key(RUN_B));
        assert_ne!(color_a, color_b);

        let _ = w.apply_run_keys(&[RUN_B.to_string()]);
        let _ = w.apply_run_keys(&[RUN_B.to_string(), RUN_C.to_string()]);
        let color_c = color_key(w.run_color_for_key(RUN_C));
        assert_eq!(color_a, color_c);
    }

    // ---- extractRunID / runWandbFile (model.go helpers hosted here;
    // pinned against the Go regex semantics) ----

    #[test]
    fn extract_run_id_matches_go_regex_semantics() {
        assert_eq!(extract_run_id("run-20250731_170606-iazb7i1k"), "iazb7i1k");
        assert_eq!(extract_run_id("offline-run-20250731_170606-abc"), "abc");
        // Match ending at the end of the string → "".
        assert_eq!(extract_run_id("run-20250731_170606-"), "");
        assert_eq!(extract_run_id("not-a-run-dir"), "");
        assert_eq!(extract_run_id("run-2025_170606-abc"), "");
    }

    #[test]
    fn run_wandb_file_joins_run_dir_and_id() {
        assert_eq!(
            run_wandb_file("/tmp/wandb", "run-20250731_170606-iazb7i1k"),
            "/tmp/wandb/run-20250731_170606-iazb7i1k/run-iazb7i1k.wandb"
        );
        assert_eq!(run_wandb_file("/tmp/wandb", "junk"), "");
    }
}
