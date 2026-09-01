//! Port of `core/internal/leet/run.go` — the single-run view model.
//!
//! Concurrency mapping (docs/CONCURRENCY.md):
//!
//!   - `stateMu sync.RWMutex` (run.go:46, S1) DIES — update and draw share
//!     one thread (§2.6).
//!   - `liveRunning atomic.Bool` (run.go:70, S2) DIES — liveness is the
//!     plain `run_state` field read on the main thread (§2.4); the
//!     fire-time re-check lives in the Heartbeat handler like Go's
//!     runhandlers.go:931-934.
//!   - `animationMu sync.Mutex` + `animating bool` (run.go:96-97, S4) —
//!     a plain `bool` (already main-thread-only in Go).
//!   - the shared `make(chan tea.Msg, 4096)` (run.go:124, C1) DIES — the
//!     main event channel is the merge point; file changes arrive through
//!     the watcher registration's cap-1 channel + `Command::AwaitWatcherMsg`
//!     pump, heartbeats through the scheduler (§2.5).
//!   - `logPanic` (run.go:421-429, P1) DIES — the runtime's panic hook +
//!     per-thread `catch_unwind` provide the log-then-restore contract
//!     (§2.8); there is no recover-equivalent to install per method.
//!
//! The `(*Run).handle*` message/key handlers live in run_handlers.rs
//! (runhandlers.go); the focus-manager construction in run_focus.rs
//! (runfocus.go).

use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;
use std::time::Instant;

use leet_charts::styles::{
    COLOR_HEADING, LEET_ART, MEDIUM_SHADE_BLOCK, SIDEBAR_MIN_WIDTH, STATUS_BAR_HEIGHT,
    STATUS_BAR_PADDING, WANDB_ART,
};
use leet_data::config::{ConfigManager, leet_config_path};
use leet_data::media::MediaStore;
use leet_data::remote::RemoteRunParams;
use leet_data::run_overview::{RunOverview, RunState};
use leet_data::width::text_width;
use ratatui::text::Text;

use crate::animation::AnimatedValue;
use crate::command::{AnimTarget, Command, HeartbeatOwner};
use crate::console_logs_pane::{CONSOLE_LOGS_PANE_MIN_HEIGHT, ConsoleLogsPane};
use crate::event::{Event, HistorySourceHandle};
use crate::flex_layout::{StackSectionId, StackSectionSpec, compute_vertical_stack_layout};
use crate::focus_manager::FocusManager;
use crate::heartbeat::HeartbeatManager;
use crate::keybindings::{RunAction, build_key_map, run_key_bindings};
use crate::layout::{
    CENTER, GoStyle, LEFT, RIGHT, TOP, join_horizontal, join_vertical, join_with_separators, place,
    place_horizontal, rgb_to_color, status_bar_style, text_from_str, text_to_string,
};
use crate::media_pane::{
    LOWER_TIER_RATIO, MEDIA_PANE_MIN_HEIGHT, MediaPane, MediaPaneCmd, media_pane_header_style,
    media_tile_placeholder_style,
};
use crate::metrics_grid::MetricsGrid;
use crate::panel_grid::{Focus, FocusType};
use crate::right_sidebar::RightSidebar;
use crate::run_console_logs::RunConsoleLogs;
use crate::run_overview_sidebar::{RunOverviewSidebar, SidebarSide};
use crate::watcher_manager::WatcherManager;

/// RunParams identifies the run LEET displays.
///
/// Exactly one of RunFile or Remote is set.
#[derive(Debug, Clone, Default)]
pub struct RunParams {
    /// RunFile is the path to a local .wandb transaction log.
    pub run_file: String,

    /// Remote identifies a run stored on a W&B server.
    // PARITY: `RemoteRunParams` is declared in run.go in Go; the port hosts
    // it in leet_data::remote (see the PARITY note there).
    pub remote: Option<RemoteRunParams>,
}

/// Run holds data/state related to a single W&B run.
///
/// Implements the tea.Model surface (`init`/`update`/`view`) driven by the
/// owning `Model` (model.go / model.rs, Phase 5b).
/// It coordinates the main metrics grid, sidebars, help screen, and data
/// loading.
// PARITY: Go package-private fields are `pub(crate)` — runhandlers.go /
// runfocus.go / model.go reach into them exactly as Go's package scope
// allows, and the transliterated tests replace testhelpers.go accessors
// with direct field access (PORTING.md Testing conventions).
pub struct Run {
    // PARITY: `stateMu sync.RWMutex` (run.go:46) dies — see the module doc.

    // Configuration and key bindings.
    pub(crate) config: Rc<RefCell<ConfigManager>>,
    pub(crate) key_map: HashMap<&'static str, RunAction>,

    // Terminal dimensions.
    pub(crate) width: isize,
    pub(crate) height: isize,

    // runParams contains the information about the run.
    // PARITY: Go stores `*RunParams` but every caller passes a non-nil
    // pointer (model.go:112/:390, all tests); the value form drops the
    // unreachable nil branch of Go's `IsRemote`.
    pub(crate) run_params: RunParams,

    // Run state tracking.
    pub(crate) run_state: RunState,

    /// isLoading controls whether the loading screen is displayed.
    ///
    /// Defaults to true and is set to false once a RunRecord is
    /// successfully loaded from the transaction log.
    pub(crate) is_loading: bool,

    // PARITY: `liveRunning atomic.Bool` (run.go:70) dies — see module doc.

    // Data reader.
    // PARITY: Go stores the `HistorySource` interface value; the reader owns
    // its file on a dedicated thread here and the model holds the opaque
    // handle, reading via `Command::Read*` (CONCURRENCY.md §2.3).
    pub(crate) history_source: Option<HistorySourceHandle>,
    // PHASE-7: `initCancel context.CancelFunc` (run.go:74) — the in-flight
    // parquet-init cancellation handle lands with leet-remote; the runtime
    // will expose a cancel flag checked at chunk boundaries (§2.6).

    // Transaction log (.wandb file) watch and heartbeat management.
    pub(crate) watcher_mgr: WatcherManager,
    pub(crate) heartbeat_mgr: HeartbeatManager,

    // Focus management.
    pub(crate) focus_mgr: FocusManager<Run>,
    pub(crate) focus: Rc<RefCell<Focus>>,

    // UI components.
    pub(crate) metrics_grid_anim_state: AnimatedValue,
    pub(crate) metrics_grid: MetricsGrid,
    pub(crate) run_overview: Rc<RefCell<RunOverview>>,
    pub(crate) left_sidebar: RunOverviewSidebar,
    pub(crate) right_sidebar: RightSidebar,
    pub(crate) console_logs: RunConsoleLogs,
    pub(crate) console_logs_pane: ConsoleLogsPane,
    pub(crate) media_store: Rc<RefCell<MediaStore>>,
    pub(crate) media_pane: MediaPane,

    // Sidebar animation synchronization.
    // PARITY: `animationMu sync.Mutex` (run.go:96) dies — main-thread-only
    // one-shot token (CONCURRENCY.md §2.6 S4).
    pub(crate) animating: bool,

    // Loading progress.
    pub(crate) records_loaded: isize,
    // PARITY: written on InitMsg (runhandlers.go:871) and never read — kept
    // for the 1:1 field map (Go zero time.Time → None).
    #[allow(dead_code)]
    pub(crate) load_start_time: Option<Instant>,
    pub(crate) last_error: String,

    /// Coalesce expensive redraws during batch processing.
    pub(crate) suppress_draw: bool,
    // PARITY: `logger *observability.CoreLogger` — the port logs via
    // `tracing` at the same call sites.
}

impl Run {
    /// Port of Go `NewRun` (the logger parameter is dropped; see the
    /// struct-level PARITY note).
    pub fn new(run_params: RunParams, cfg: Option<Rc<RefCell<ConfigManager>>>) -> Run {
        let cfg =
            cfg.unwrap_or_else(|| Rc::new(RefCell::new(ConfigManager::new(leet_config_path()))));

        let heartbeat_interval = cfg.borrow().heartbeat_interval();
        tracing::info!("run: heartbeat interval set to {heartbeat_interval:?}");

        let focus = Rc::new(RefCell::new(Focus::new()));
        // PARITY: `ch := make(chan tea.Msg, 4096)` (run.go:124, C1) dies —
        // see the module doc.

        let ro = Rc::new(RefCell::new(RunOverview::new()));
        let run_overview_anim_state = AnimatedValue::new(
            cfg.borrow().left_sidebar_visible(),
            SIDEBAR_MIN_WIDTH as isize,
        );

        // The metrics grid AnimatedValue tracks a "maximum height" that the grid is allowed.
        // When collapsed (target=0), the grid renders nothing and bottom panes take all space.
        let metrics_grid_anim_state = AnimatedValue::new(cfg.borrow().metrics_grid_visible(), 1);

        let console_logs_pane_anim_state = AnimatedValue::new(
            cfg.borrow().console_logs_visible(),
            CONSOLE_LOGS_PANE_MIN_HEIGHT,
        );
        let media_pane_anim_state =
            AnimatedValue::new(cfg.borrow().media_visible(), MEDIA_PANE_MIN_HEIGHT);

        // Go passes the method value `cfg.MetricsGrid` as the grid-config
        // getter; the port passes a closure over the shared config.
        let mut metrics_grid = MetricsGrid::new(
            Rc::clone(&cfg),
            Box::new({
                let cfg = Rc::clone(&cfg);
                move || cfg.borrow().metrics_grid()
            }),
            Rc::clone(&focus),
        );
        metrics_grid.set_single_series_color_mode(cfg.borrow().single_run_color_mode());

        let media_store = Rc::new(RefCell::new(MediaStore::new()));

        // Go passes `cfg.MediaGrid` (returns Go ints); the media pane's
        // GridConfig convention is isize.
        let media_grid_config = {
            let cfg = Rc::clone(&cfg);
            move || {
                let (rows, cols) = cfg.borrow().media_grid();
                (rows as isize, cols as isize)
            }
        };

        let mut run = Run {
            config: Rc::clone(&cfg),
            key_map: build_key_map(&run_key_bindings()),
            width: 0,
            height: 0,
            run_params,
            run_state: RunState::Unknown,
            is_loading: true,
            history_source: None,
            watcher_mgr: WatcherManager::new(),
            heartbeat_mgr: HeartbeatManager::new(heartbeat_interval, HeartbeatOwner::Run),
            focus_mgr: FocusManager::default(),
            focus: Rc::clone(&focus),
            metrics_grid_anim_state,
            metrics_grid,
            run_overview: Rc::clone(&ro),
            left_sidebar: RunOverviewSidebar::new(
                Rc::clone(&cfg),
                run_overview_anim_state,
                Some(ro),
                SidebarSide::Left,
            ),
            right_sidebar: RightSidebar::new(Rc::clone(&cfg), Rc::clone(&focus)),
            console_logs: RunConsoleLogs::new(),
            console_logs_pane: ConsoleLogsPane::new(console_logs_pane_anim_state),
            media_store,
            // PARITY: like Go, the pane starts without a store; it is wired
            // in by handleHistoryMsg (runhandlers.go:99-101) or
            // SetMediaStore (run.go:167-170).
            media_pane: MediaPane::new(media_pane_anim_state, Some(Box::new(media_grid_config))),
            animating: false,
            records_loaded: 0,
            load_start_time: None,
            last_error: String::new(),
            suppress_draw: false,
        };
        run.focus_mgr = Run::build_run_focus_manager();
        run
    }

    /// SetMediaStore replaces the run's media store (e.g., to share with workspace).
    pub fn set_media_store(&mut self, store: Rc<RefCell<MediaStore>>) {
        self.media_store = Rc::clone(&store);
        self.media_pane.set_store(Some(store));
    }

    /// Init initializes the model and returns the initial command.
    ///
    /// The watcher/heartbeat message pump is not started here: it starts
    /// together with the watcher once the boot load completes for a live run.
    pub fn init(&mut self) -> Vec<Command> {
        tracing::debug!("run: Init called");

        let source = if self.is_remote() {
            // PHASE-7: `InitializeParquetHistorySource` + `initCancel`
            // (run.go:183-185) — the effect runner logs-and-drops this
            // command until leet-remote lands.
            Command::InitRemoteReader {
                remote: self
                    .run_params
                    .remote
                    .clone()
                    .expect("is_remote checked above"),
            }
        } else {
            Command::InitReader {
                run_path: self.run_params.run_file.clone(),
            }
        };

        let mut cmds = vec![source];
        cmds.extend(media_pane_commands(self.media_pane.init()));
        cmds
    }

    /// Update handles incoming events and updates the model accordingly.
    pub fn update(&mut self, msg: &Event) -> Vec<Command> {
        // PARITY: `defer r.logPanic("Update")` (run.go:200) — module doc.
        let _timing = timeit("Model.Update");
        // PARITY: stateMu.Lock (run.go:202-203) dies — module doc.

        let mut cmds: Vec<Command> = Vec::new();

        // Forward UI messages to children if not in filter mode.
        if is_ui_msg(msg)
            && !self.metrics_grid.is_filter_mode()
            && !self.left_sidebar.is_filter_mode()
            && !matches!(msg, Event::Key(_))
        {
            if let Some(ev) = self.left_sidebar.update(msg) {
                cmds.extend(anim_command(Some(ev)));
            }
            if let Some(ev) = self.right_sidebar.update(msg) {
                cmds.extend(anim_command(Some(ev)));
            }
        }

        // PARITY: run.go:219-222 — `picture.IsPictureMsg(msg)` routes
        // picture messages to the media pane and returns. The
        // `mediaPanePrepareMsg` arm (run.go:226-230) is replaced by the
        // media pane's `prepare_requested` flag drained via
        // [`Run::after_draw`] (CONCURRENCY.md §2.5 C5).
        if let Some(picture) = self.media_pane.handle_picture_msg(msg) {
            cmds.extend(media_pane_commands(picture));
            return cmds;
        }

        // Route message to appropriate handler.
        match msg {
            Event::Key(t) => {
                cmds.extend(self.handle_key_press_msg(t));
                cmds
            }
            Event::Mouse(t) => {
                cmds.extend(self.handle_mouse_msg(t));
                cmds
            }
            Event::Resize { width, height } => {
                self.handle_window_resize(*width, *height);
                cmds
            }
            _ => {
                cmds.extend(self.dispatch(msg));
                cmds
            }
        }
    }

    /// The same-thread replacement for the `mediaPanePrepareMsg` arm of
    /// Go `Update` (run.go:226-230): the render path records a prepare
    /// request on the media pane; the owning model drains it after each
    /// draw and dispatches the resulting Kitty prepare commands
    /// (CONCURRENCY.md §2.5 C5 — the cap-1 prepare pump becomes a flag).
    pub fn after_draw(&mut self) -> Vec<Command> {
        if !self.media_pane.take_prepare_request() {
            return Vec::new();
        }
        media_pane_commands(self.media_pane.handle_prepare())
    }

    /// handleWindowResize handles window resize messages.
    pub(crate) fn handle_window_resize(&mut self, width: isize, height: isize) {
        self.width = width;
        self.height = height;

        self.left_sidebar
            .update_dimensions(width, self.right_sidebar.anim_state.target_visible());
        self.right_sidebar
            .update_dimensions(width, self.left_sidebar.anim_state.target_visible());
        self.update_bottom_pane_heights(
            self.media_pane.anim_state.target_visible(),
            self.console_logs_pane.anim_state.target_visible(),
        );

        let layout = self.compute_viewports();
        self.metrics_grid
            .update_dimensions(layout.main_content_area_width, layout.height);
        self.resolve_after_availability_change();
    }

    /// dispatch routes message types to appropriate handlers.
    fn dispatch(&mut self, msg: &Event) -> Vec<Command> {
        match msg {
            Event::Init(t) => self.handle_init(t),
            Event::ChunkedBatch(t) => self.handle_chunked_batch(t),
            Event::BatchedRecords(t) => self.handle_batched(t),
            Event::Heartbeat => self.handle_heartbeat(),
            Event::FileChanged => self.handle_file_change(),
            Event::Resize { width, height } => {
                self.handle_window_resize(*width, *height);
                Vec::new()
            }
            Event::LeftSidebarAnimation | Event::RightSidebarAnimation => {
                self.handle_sidebar_animation(msg)
            }
            Event::ConsoleLogsPaneAnimation => self.handle_console_logs_pane_animation(),
            Event::MediaPaneAnimation => self.handle_media_pane_animation(),
            Event::MetricsGridAnimation => self.handle_metrics_grid_animation(),
            // History/Run/Summary/Stats/SystemInfo/FileComplete/Error
            _ => self.handle_record_msg(msg),
        }
    }

    /// FocusedTitle returns the title of the currently focused chart.
    pub fn focused_title(&self) -> String {
        let f = self.focus.borrow();
        if f.focus_type != FocusType::None {
            return f.title.clone();
        }
        String::new()
    }

    /// View renders the UI based on the data in the model.
    ///
    /// `dark` resolves adaptive colors (Go reads the `darkBackground`
    /// package global set by the Model on `tea.BackgroundColorMsg`; the
    /// port threads it explicitly, see the layout module doc).
    pub fn view(&mut self, dark: bool) -> Text<'static> {
        // PARITY: `defer r.logPanic("View")` + stateMu.RLock
        // (run.go:325-328) die — module doc.

        if self.width == 0 || self.height == 0 {
            return text_from_str("Loading...");
        }

        if self.is_loading {
            return self.render_loading_screen(dark);
        }

        self.render_main_view(dark)
    }

    /// renderMainView renders the main application view.
    fn render_main_view(&mut self, dark: bool) -> Text<'static> {
        let layout = self.compute_viewports();

        let w = layout.main_content_area_width;
        let central_column = if self.media_pane.is_fullscreen() {
            self.media_pane
                .view(w, layout.total_content_area_height, "", "", dark)
        } else {
            let mut sections: Vec<Text<'static>> = Vec::new();

            if self.metrics_grid_anim_state.is_visible() && layout.height > 0 {
                if self.metrics_grid.chart_count() == 0 {
                    sections.push(render_metrics_empty_state(
                        w,
                        layout.height,
                        "No scalar metrics logged.",
                        dark,
                    ));
                } else {
                    let dims = self
                        .metrics_grid
                        .calculate_chart_dimensions(w, layout.height);
                    sections.push(self.metrics_grid.view(dims, dark));
                }
            }

            if layout.media_height > 0 {
                sections.push(self.media_pane.view(w, layout.media_height, "", "", dark));
            } else {
                self.media_pane.park();
            }
            if layout.console_logs_height > 0 {
                self.console_logs_pane
                    .set_console_logs(self.console_logs.items().to_vec());
                sections.push(self.console_logs_pane.view(w, "", "", dark));
            }

            // PARITY: `filterNonEmptySections` (flexlayout.go:157) — the
            // flex_layout.rs helper works on plain strings; sections here
            // are styled Text blocks, and a section is empty exactly when
            // it renders to "".
            sections.retain(|s| !text_to_string(s).is_empty());
            if sections.is_empty() {
                render_logo_art(w, layout.total_content_area_height)
            } else {
                join_with_separators(sections, w as i64, dark)
            }
        };
        // PARITY: `placeMainColumn` (flexlayout.go:168) is
        // lipgloss.Place(Left, Top); the flex_layout.rs helper works on
        // plain strings, so the styled Text goes through the layout::place
        // equivalent directly.
        let central_column = place(
            w as i64,
            layout.total_content_area_height as i64,
            LEFT,
            TOP,
            central_column,
        );

        let main_view = self.build_main_view_with_sidebars(
            central_column,
            layout.total_content_area_height,
            layout.left_sidebar_width,
            layout.right_sidebar_width,
            dark,
        );
        let status_bar = self.render_status_bar(dark);

        let full_view = join_vertical(LEFT, vec![main_view, status_bar]);
        place(self.width as i64, self.height as i64, LEFT, TOP, full_view)
    }

    /// buildMainViewWithSidebars builds the main view with sidebars.
    fn build_main_view_with_sidebars(
        &mut self,
        grid_view: Text<'static>,
        content_height: isize,
        left_width: isize,
        right_width: isize,
        dark: bool,
    ) -> Text<'static> {
        if left_width == 0 && right_width == 0 {
            return grid_view;
        }

        let mut parts: Vec<Text<'static>> = Vec::new();

        if left_width > 0 {
            // PARITY: Go reads `.Content` off the sidebar's tea.View; the
            // port's view returns the content block directly.
            parts.push(self.left_sidebar.view(content_height, dark));
        }

        parts.push(grid_view);

        if right_width > 0 {
            parts.push(self.right_sidebar.view(content_height, dark));
        }

        join_horizontal(TOP, parts)
    }

    // PARITY: `logPanic` (run.go:421-429) is not ported — module doc (§2.8).

    /// isRunning reports whether the run is live.
    // PARITY: Go reads the `liveRunning` atomic so the heartbeat AfterFunc
    // goroutine could call it; single-threaded now, it reads the
    // authoritative state directly and `syncLiveRunning` (run.go:451-453)
    // has nothing left to sync (CONCURRENCY.md §2.4, S2).
    pub(crate) fn is_running(&self) -> bool {
        self.run_state == RunState::Running
    }

    /// shouldResetLiveHeartbeat reports whether incremental data should re-arm the
    /// live heartbeat safety net.
    ///
    /// During boot load we may already know the run is live, but we intentionally
    /// avoid arming heartbeats until live streaming has fully started. Watcher and
    /// heartbeat startup happen together after the initial history drain completes.
    pub(crate) fn should_reset_live_heartbeat(&self) -> bool {
        // PARITY: Go also nil-checks `r.watcherMgr` (run.go:446); NewRun
        // always constructs one, and the manager is not optional here.
        self.run_state == RunState::Running && self.watcher_mgr.is_started()
    }

    /// renderLoadingScreen shows the wandb leet ASCII art centered on screen.
    fn render_loading_screen(&mut self, dark: bool) -> Text<'static> {
        let centered_logo = render_logo_art(self.width, self.height - STATUS_BAR_HEIGHT as isize);

        let status_bar = self.render_status_bar(dark);
        join_vertical(LEFT, vec![centered_logo, status_bar])
    }

    /// renderStatusBar creates the status bar.
    fn render_status_bar(&mut self, dark: bool) -> Text<'static> {
        let status_text = self.build_status_text();
        let help_text = self.build_help_text();

        let inner_width = (self.width - 2 * STATUS_BAR_PADDING as isize).max(0);
        let space_for_help = (inner_width - text_width(&status_text) as isize).max(0);
        let right_aligned =
            place_horizontal(space_for_help as i64, RIGHT, text_from_str(help_text));

        let full_status = format!("{}{}", status_text, text_to_string(&right_aligned));

        status_bar_style(dark)
            .width(self.width as i64)
            .max_width(self.width as i64)
            .render(&full_status)
    }

    /// buildStatusText builds the main status text.
    fn build_status_text(&self) -> String {
        if self.left_sidebar.is_filter_mode() {
            return self.build_overview_filter_status();
        }
        if self.metrics_grid.is_filter_mode() {
            return self.build_metrics_filter_status();
        }
        if self.right_sidebar.is_filter_mode() {
            return self.build_system_metrics_filter_status();
        }
        if self.config.borrow().is_awaiting_grid_config() {
            return self.config.borrow().grid_config_status().to_string();
        }
        if !self.last_error.is_empty() {
            return format!("Error: {}", self.last_error);
        }
        if self.is_loading {
            return self.build_loading_status();
        }
        self.build_active_status()
    }

    /// buildOverviewFilterStatus builds status for overview filter mode.
    fn build_overview_filter_status(&self) -> String {
        let mut filter_info = self.left_sidebar.filter_info();
        if filter_info.is_empty() {
            filter_info = "no matches".to_string();
        }
        format!(
            "Overview filter ({}): {}{} [{}] (Enter to apply • Tab to toggle mode)",
            self.left_sidebar.filter_mode(),
            self.left_sidebar.filter_query(),
            MEDIUM_SHADE_BLOCK,
            filter_info,
        )
    }

    /// buildMetricsFilterStatus builds status for metrics filter mode.
    ///
    /// Should be guarded by the caller's check that filter input is active.
    fn build_metrics_filter_status(&self) -> String {
        format!(
            "Filter ({}): {}{} [{}/{}] (Enter to apply • Tab to toggle mode)",
            self.metrics_grid.filter_mode(),
            self.metrics_grid.filter_query(),
            MEDIUM_SHADE_BLOCK,
            self.metrics_grid.filtered_chart_count(),
            self.metrics_grid.chart_count()
        )
    }

    fn build_system_metrics_filter_status(&self) -> String {
        // PARITY: Go nil-checks `r.rightSidebar`/`.metricsGrid`
        // (run.go:531-533); both are always constructed here.
        let grid = &self.right_sidebar.metrics_grid;
        format!(
            "System filter ({}): {}{} [{}/{}] (Enter to apply • Tab to toggle mode)",
            grid.filter_mode(),
            grid.filter_query(),
            MEDIUM_SHADE_BLOCK,
            grid.filtered_chart_count(),
            grid.chart_count(),
        )
    }

    /// buildLoadingStatus builds status for loading mode.
    fn build_loading_status(&self) -> String {
        if self.records_loaded > 0 {
            return format!(
                "Loading data... [{} records, {} metrics]",
                self.records_loaded,
                self.metrics_grid.chart_count()
            );
        }
        "Loading data...".to_string()
    }

    /// buildActiveStatus builds status for active (non-loading, non-filter) mode.
    fn build_active_status(&self) -> String {
        let mut parts: Vec<String> = Vec::new();

        // Add filter info if active.
        if self.metrics_grid.is_filtering() {
            parts.push(format!(
                "Filter ({}): {} [{}/{}] (/ to change, Ctrl+L to clear)",
                self.metrics_grid.filter_mode(),
                go_quote(self.metrics_grid.filter_query()),
                self.metrics_grid.filtered_chart_count(),
                self.metrics_grid.chart_count()
            ));
        }

        // Add overview filter info if active.
        if self.left_sidebar.is_filtering() {
            parts.push(format!(
                "Overview: {} [{}] (o to change, Ctrl+K to clear)",
                go_quote(self.left_sidebar.filter_query()),
                self.left_sidebar.filter_info(),
            ));
        }

        if self.right_sidebar.is_filtering() {
            let grid = &self.right_sidebar.metrics_grid;
            parts.push(format!(
                "System filter ({}): {} [{}/{}] (\\ to change, Ctrl+\\ to clear)",
                grid.filter_mode(),
                go_quote(&grid.filter_query()),
                grid.filtered_chart_count(),
                grid.chart_count(),
            ));
        }

        // Add selected overview item if sidebar is visible.
        if self.left_sidebar.is_visible() {
            let (key, value) = self.left_sidebar.selected_item();
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

        // Add focused chart name if a chart is focused.
        let focused_title = self.focused_title();
        if !focused_title.is_empty() {
            parts.push(focused_title);
            match self.focus.borrow().focus_type {
                FocusType::MainChart => {
                    let scale_label = self.metrics_grid.focused_chart_scale_label();
                    if !scale_label.is_empty() {
                        parts.push(scale_label.to_string());
                    }
                }
                FocusType::SystemChart => {
                    let detail = self.right_sidebar.metrics_grid.focused_chart_title_detail();
                    if !detail.is_empty() {
                        parts.push(detail);
                    }
                    let view_mode = self.right_sidebar.focused_chart_view_mode_label();
                    if !view_mode.is_empty() {
                        parts.push(view_mode);
                    }
                    let scale_label = self.right_sidebar.metrics_grid.focused_chart_scale_label();
                    if !scale_label.is_empty() {
                        parts.push(scale_label);
                    }
                }
                FocusType::None => {}
            }
        }

        if parts.is_empty() {
            return String::new();
        }

        parts.join(" • ")
    }

    /// buildHelpText builds the help text for the status bar.
    fn build_help_text(&self) -> &'static str {
        if self.metrics_grid.is_filter_mode()
            || self.left_sidebar.is_filter_mode()
            || self.right_sidebar.is_filter_mode()
        {
            return "";
        }
        "h: help"
    }

    pub fn is_filtering(&self) -> bool {
        self.metrics_grid.is_filter_mode()
            || self.left_sidebar.is_filter_mode()
            || self.right_sidebar.is_filter_mode()
    }

    pub fn media_fullscreen(&self) -> bool {
        // PARITY: stateMu.RLock (run.go:646-647) dies; the
        // `mediaPane != nil` guard is unrepresentable (always constructed).
        self.media_pane.is_fullscreen()
    }

    pub(crate) fn update_bottom_pane_heights(&mut self, media_visible: bool, logs_visible: bool) {
        let metrics_visible = self.metrics_grid_anim_state.target_visible();

        // Compute separator count from the visibility state we're configuring toward.
        let mut section_count: isize = 0;
        if metrics_visible {
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
        let mut lower_count: isize = 0;
        if media_visible {
            lower_count += 1;
        }
        if logs_visible {
            lower_count += 1;
        }
        if lower_count == 0 {
            return;
        }

        let lower_tier_h = if metrics_visible {
            // PARITY: Go `int(float64(maxH) * LowerTierRatio)` truncates
            // toward zero; `as isize` matches.
            (max_h as f64 * LOWER_TIER_RATIO) as isize
        } else {
            max_h
        };

        let each = lower_tier_h / lower_count;
        if media_visible {
            self.media_pane.set_expanded_height(each);
        }
        if logs_visible {
            self.console_logs_pane.set_expanded_height(each);
        }
    }

    pub fn is_remote(&self) -> bool {
        self.run_params.remote.is_some()
    }

    /// effectiveSidebarWidths returns the widths that can actually be rendered
    /// without starving the main content area.
    ///
    /// The visibility preferences remain unchanged: this method only clamps the
    /// current render/layout pass and does not mutate animation state.
    fn effective_sidebar_widths(&self) -> (isize, isize) {
        const MIN_RUN_MAIN_CONTENT_WIDTH: isize = 10;

        let mut left_w = self.left_sidebar.width();
        let mut right_w = self.right_sidebar.width();

        if left_w + right_w < self.width - MIN_RUN_MAIN_CONTENT_WIDTH {
            return (left_w, right_w);
        }
        if right_w > 0 {
            right_w = 0;
        }
        if left_w + right_w < self.width - MIN_RUN_MAIN_CONTENT_WIDTH {
            return (left_w, right_w);
        }
        if left_w > 0 {
            left_w = 0;
        }
        (left_w, right_w)
    }

    /// computeViewports returns the computed layout dimensions.
    pub(crate) fn compute_viewports(&self) -> Layout {
        let (left_w, right_w) = self.effective_sidebar_widths();
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
            system_metrics_y: 0,
            system_metrics_height: 0,
            media_y: stack.y(StackSectionId::Media),
            media_height: stack.height(StackSectionId::Media),
            console_logs_y: stack.y(StackSectionId::ConsoleLogs),
            console_logs_height: stack.height(StackSectionId::ConsoleLogs),
        }
    }

    /// Cleanup releases resources held by the RunModel.
    ///
    /// Called when switching to workspace view.
    ///
    /// PARITY: Go's exported `Cleanup` (run.go:778-783) only wrapped the
    /// package-private `cleanup` in the stateMu write lock, which dies
    /// (module doc) — the pair collapses into this one method delegating to
    /// [`Run::cleanup_inner`] (runhandlers.go:333). Returns the timer /
    /// reader commands Go's managers applied as side effects; the caller
    /// dispatches them (they are moot on full-session teardown, where the
    /// scheduler and readers die with the runtime).
    pub fn cleanup(&mut self) -> Vec<Command> {
        self.cleanup_inner()
    }

    /// Moves the focus manager out while its hooks run against `self`
    /// (focus_manager.rs module doc: Go's closures captured `*Run`; the
    /// fn-pointer hooks take the Run ctx explicitly, so the manager cannot
    /// stay borrowed inside the struct during the call).
    pub(crate) fn with_focus_mgr<T>(
        &mut self,
        f: impl FnOnce(&mut FocusManager<Run>, &mut Run) -> T,
    ) -> T {
        let mut fm = std::mem::take(&mut self.focus_mgr);
        let out = f(&mut fm, self);
        self.focus_mgr = fm;
        out
    }

    pub(crate) fn resolve_after_availability_change(&mut self) {
        self.with_focus_mgr(|fm, r| fm.resolve_after_availability_change(r));
    }

    pub(crate) fn resolve_after_visibility_change(&mut self) {
        self.with_focus_mgr(|fm, r| fm.resolve_after_visibility_change(r));
    }
}

/// isUIMsg returns true for messages that should flow to child view models.
fn is_ui_msg(msg: &Event) -> bool {
    matches!(
        msg,
        Event::Key(_)
            | Event::Mouse(_)
            | Event::Resize { .. }
            | Event::LeftSidebarAnimation
            | Event::RightSidebarAnimation
            | Event::ConsoleLogsPaneAnimation
            | Event::MediaPaneAnimation
            | Event::MetricsGridAnimation
    )
}

/// Layout represents the computed layout dimensions for the main UI.
// PARITY: declared in run.go (run.go:700-712) and shared with workspace.go's
// computeViewports (workspace.go:538-548); the two `system_metrics_*` fields
// are only populated by the workspace.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub(crate) struct Layout {
    pub(crate) left_sidebar_width: isize,
    pub(crate) main_content_area_width: isize,
    pub(crate) right_sidebar_width: isize,
    pub(crate) total_content_area_height: isize,
    pub(crate) height: isize,
    // PHASE-5: read by the workspace mouse-routing port
    // (workspacehandlers.go:130-132, :219).
    #[allow(dead_code)]
    pub(crate) system_metrics_y: isize,
    #[allow(dead_code)]
    pub(crate) system_metrics_height: isize,
    pub(crate) media_y: isize,
    pub(crate) media_height: isize,
    #[allow(dead_code)]
    pub(crate) console_logs_y: isize,
    pub(crate) console_logs_height: isize,
}

/// Maps the media pane's returned commands onto runtime [`Command`]s
/// (media_pane.rs: "the app shell maps these onto `Command`s").
pub(crate) fn media_pane_commands(cmds: Vec<MediaPaneCmd>) -> Vec<Command> {
    cmds.into_iter()
        .map(|cmd| match cmd {
            MediaPaneCmd::Picture(p) => Command::Picture(p),
            MediaPaneCmd::RequestCellSize => Command::RequestCellSize,
            MediaPaneCmd::QueryKittySupport => Command::QueryKittySupport,
        })
        .collect()
}

/// Maps a pane's returned animation [`Event`] onto the scheduler arm for its
/// frame timer — every Go `tea.Tick(AnimationFrame, ..)` return value ports
/// this way (CONCURRENCY.md §2.4).
pub(crate) fn anim_command(ev: Option<Event>) -> Vec<Command> {
    match ev.as_ref().and_then(AnimTarget::for_event) {
        Some(target) => vec![Command::tick_anim(target)],
        None => Vec::new(),
    }
}

/// timeit logs a debug timing line on exit for the given scope.
// PARITY: Go returns a func for `defer timeit(..)()`; the port returns a
// Drop guard.
pub(crate) fn timeit(scope: &'static str) -> TimeitGuard {
    TimeitGuard {
        scope,
        start: Instant::now(),
    }
}

pub(crate) struct TimeitGuard {
    scope: &'static str,
    start: Instant,
}

impl Drop for TimeitGuard {
    fn drop(&mut self) {
        tracing::debug!("perf: {} took {:?}", self.scope, self.start.elapsed());
    }
}

/// Go fmt's `%q` for the status-bar filter echoes (run.go:561/569/578).
// PARITY: strconv.Quote subset — filter queries are printable key-press text
// (filter.go UpdateDraft), so the escapes below cover every reachable input.
// PORTING.md prescribes a shared `go_quote` in leet_data::go_fmt; none
// exists yet, so it is hosted here (reported for extraction — the workspace
// status bar needs the same helper, workspace.go:1213-1245).
pub(crate) fn go_quote(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\t' => out.push_str("\\t"),
            '\r' => out.push_str("\\r"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\x{:02x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

// ---------------------------------------------------------------------------
// Shared render helpers from workspace.go
// ---------------------------------------------------------------------------
// PARITY: Go declares these two functions in workspace.go (:1078, :1091);
// they are hosted here because run.go's renderMainView / renderLoadingScreen
// need them and workspace.rs is a later unit — the workspace port MUST reuse
// `crate::run::{render_metrics_empty_state, render_logo_art}` rather than
// re-porting them (two copies would drift).

/// renderMetricsEmptyState renders a styled "Metrics" header with a hint message.
pub(crate) fn render_metrics_empty_state(
    width: isize,
    height: isize,
    hint: &str,
    dark: bool,
) -> Text<'static> {
    if width <= 0 || height <= 0 {
        return text_from_str("");
    }
    let inner_w = (width - leet_charts::styles::CONTENT_PADDING_COLS as isize).max(0);
    let header = media_pane_header_style(dark).render("Metrics");
    let hint_text = media_tile_placeholder_style(dark).render(hint);
    let content = join_vertical(LEFT, vec![header, text_from_str(""), hint_text]);
    let content = place(inner_w as i64, height as i64, LEFT, TOP, content);
    GoStyle::new()
        .padding(&[0, leet_charts::styles::CONTENT_PADDING])
        .render_text(content)
}

/// renderLogoArt renders the wandb/leet ASCII art centered in the given area.
pub(crate) fn render_logo_art(width: isize, height: isize) -> Text<'static> {
    if width <= 0 || height <= 0 {
        return text_from_str("");
    }
    let art_style = GoStyle::new()
        .foreground(rgb_to_color(COLOR_HEADING))
        .bold(true);

    let logo_content = join_vertical(
        CENTER,
        vec![art_style.render(WANDB_ART), art_style.render(LEET_ART)],
    );

    place(width as i64, height as i64, CENTER, CENTER, logo_content)
}

// ---------------------------------------------------------------------------
// Tests — transliteration of core/internal/leet/run_update_test.go.
// testhelpers.go accessors are replaced by direct pub(crate) access
// (PORTING.md Testing conventions); `stripANSI(View().Content)` becomes
// `text_to_string(&view(..))`, which is style-free by construction.
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use leet_charts::styles::default_dark_background;
    use leet_proto::wandb_internal::{
        EnvironmentRecord, HistoryItem, HistoryRecord, Record, RunRecord, SummaryRecord, record,
    };
    use leet_wire::transaction_log;
    use pretty_assertions::assert_eq;

    use super::*;
    use crate::event::{
        ChunkedBatchMsg, ErrorMsg, EventError, FileCompleteMsg, HistoryMsg, InitMsg, MetricData,
        RunMsg, StatsMsg, SummaryMsg, SystemInfoMsg,
    };
    use crate::key::{KeyCode, KeyEvent, KeyMods, MouseButton, MouseEvent, MouseKind};

    fn test_config(dir: &tempfile::TempDir) -> Rc<RefCell<ConfigManager>> {
        Rc::new(RefCell::new(ConfigManager::new(
            dir.path().join("config.json"),
        )))
    }

    /// Go `keyPressMsg(r rune)` (run_update_test.go:22-24).
    fn key_press_msg(r: char) -> Event {
        Event::Key(KeyEvent {
            code: KeyCode::Char(r),
            text: Some(r.to_string()),
            mods: KeyMods::NONE,
        })
    }

    fn key(code: KeyCode, mods: KeyMods) -> Event {
        Event::Key(KeyEvent {
            code,
            text: None,
            mods,
        })
    }

    fn resize(width: isize, height: isize) -> Event {
        Event::Resize { width, height }
    }

    fn metric(x: &[f64], y: &[f64]) -> MetricData {
        MetricData {
            x: x.to_vec(),
            y: y.to_vec(),
        }
    }

    fn history(metrics: HashMap<String, MetricData>) -> Event {
        Event::History(HistoryMsg {
            metrics,
            ..Default::default()
        })
    }

    fn mouse(kind: MouseKind, button: MouseButton, x: isize, y: isize) -> Event {
        Event::Mouse(MouseEvent {
            kind,
            button,
            x,
            y,
            mods: KeyMods::NONE,
        })
    }

    /// Go: TestProcessRecordMsg_Run_Summary_System_FileComplete.
    #[test]
    fn process_record_msg_run_summary_system_file_complete() {
        let dir = tempfile::tempdir().unwrap();
        let cfg = test_config(&dir);
        let mut model = Run::new(
            RunParams {
                run_file: "dummy".into(),
                remote: None,
            },
            Some(cfg),
        );
        model.update(&resize(140, 50));

        model.handle_record_msg(&Event::Run(RunMsg {
            id: "run_123".into(),
            display_name: "cool-run".into(),
            project: "proj".into(),
            ..Default::default()
        }));
        assert_eq!(model.run_overview.borrow().id(), "run_123");
        assert_eq!(model.run_overview.borrow().display_name(), "cool-run");
        assert_eq!(model.run_overview.borrow().project(), "proj");

        model.handle_record_msg(&Event::SystemInfo(SystemInfoMsg {
            record: Some(Box::new(EnvironmentRecord::default())),
            ..Default::default()
        }));

        model.handle_record_msg(&Event::Summary(SummaryMsg {
            summary: vec![SummaryRecord::default()],
            ..Default::default()
        }));

        model.handle_record_msg(&Event::FileComplete(FileCompleteMsg { exit_code: 0 }));
        assert_eq!(model.run_state, RunState::Finished);
    }

    /// Go: TestProcessRecordMsg_ErrorStopsLoading.
    #[test]
    fn process_record_msg_error_stops_loading() {
        let dir = tempfile::tempdir().unwrap();
        let cfg = test_config(&dir);
        let mut model = Run::new(
            RunParams {
                run_file: "dummy".into(),
                remote: None,
            },
            Some(cfg),
        );
        model.update(&resize(100, 30));

        model.handle_record_msg(&Event::Error(ErrorMsg {
            err: EventError::other("remote init failed"),
        }));

        assert_eq!(model.run_state, RunState::Failed);
        let view = text_to_string(&model.view(default_dark_background()));
        assert!(!view.contains("Loading data..."));
        assert!(view.contains("Error: remote init failed"));
    }

    /// Go: TestRemoteRun_DoesNotStartLocalWatcherAfterBootLoad.
    #[test]
    fn remote_run_does_not_start_local_watcher_after_boot_load() {
        let dir = tempfile::tempdir().unwrap();
        let cfg = test_config(&dir);
        let mut model = Run::new(
            RunParams {
                run_file: String::new(),
                remote: Some(RemoteRunParams {
                    base_url: "https://api.wandb.ai".into(),
                    entity: "entity".into(),
                    project: "project".into(),
                    run_id: "run-id".into(),
                }),
            },
            Some(cfg),
        );
        model.update(&resize(100, 30));

        model.update(&Event::ChunkedBatch(ChunkedBatchMsg {
            msgs: vec![Event::Run(RunMsg {
                run_path: "entity/project/run-id".into(),
                id: "run-id".into(),
                project: "project".into(),
                display_name: "remote-run".into(),
                ..Default::default()
            })],
            has_more: false,
            progress: 0,
        }));

        assert_eq!(model.run_state, RunState::Running);
    }

    /// Go: TestFocus_Clicks_SetClear.
    #[test]
    fn focus_clicks_set_clear() {
        let dir = tempfile::tempdir().unwrap();
        let cfg = test_config(&dir);
        let mut model = Run::new(
            RunParams {
                run_file: "dummy".into(),
                remote: None,
            },
            Some(cfg),
        );

        model.update(&resize(180, 60));
        let d = HashMap::from([
            ("a".to_string(), metric(&[0.0], &[1.0])),
            ("b".to_string(), metric(&[0.0], &[2.0])),
        ]);
        model.update(&history(d));

        // Go TestSetMainChartFocus → metricsGrid.setFocus.
        model.metrics_grid.set_focus(0, 0);
        {
            let fs = model.focus.borrow();
            assert_eq!(fs.focus_type, FocusType::MainChart);
            assert_eq!(fs.row, 0);
            assert_eq!(fs.col, 0);
            assert!(!fs.title.is_empty());
        }

        // Go TestHandleChartGridClick → metricsGrid.HandleClick.
        model.metrics_grid.handle_click(0, 0);
        assert_eq!(model.focus.borrow().focus_type, FocusType::None);

        model.metrics_grid.handle_click(0, 1);
        assert_eq!(model.focus.borrow().focus_type, FocusType::MainChart);

        // Go TestClearMainChartFocus → metricsGrid.clearFocus.
        model.metrics_grid.clear_focus();
        assert_eq!(model.focus.borrow().focus_type, FocusType::None);
    }

    /// Go: TestHandleOverviewFilter_TypingSpaceBackspaceEnterEsc.
    #[test]
    fn handle_overview_filter_typing_space_backspace_enter_esc() {
        let dir = tempfile::tempdir().unwrap();
        let cfg = test_config(&dir);
        let mut model = Run::new(
            RunParams {
                run_file: "dummy".into(),
                remote: None,
            },
            Some(cfg),
        );
        model.update(&resize(180, 60));

        // Enter overview filter mode
        model.update(&key_press_msg('o'));

        // Type "acc", add space, backspace, then Enter
        model.update(&key_press_msg('a'));
        model.update(&key_press_msg('c'));
        model.update(&key_press_msg('c'));
        model.update(&key(KeyCode::Space, KeyMods::NONE));
        model.update(&key(KeyCode::Backspace, KeyMods::NONE));
        model.update(&key(KeyCode::Enter, KeyMods::NONE));

        assert!(model.left_sidebar.is_filtering());
        assert_eq!(model.left_sidebar.filter_query(), "acc");

        // Enter filter mode again, type something, then Esc
        model.update(&key_press_msg('o'));
        model.update(&key_press_msg('t'));
        model.update(&key_press_msg('m'));
        model.update(&key_press_msg('p'));
        model.update(&key(KeyCode::Esc, KeyMods::NONE));

        // Should keep the previously applied "acc" state
        assert!(model.left_sidebar.is_filtering());
        assert_eq!(model.left_sidebar.filter_query(), "acc");
    }

    /// Go: TestHandleKeyMsg_VariousPaths.
    #[test]
    fn handle_key_msg_various_paths() {
        let dir = tempfile::tempdir().unwrap();
        let cfg = test_config(&dir);
        let mut model = Run::new(
            RunParams {
                run_file: "dummy".into(),
                remote: None,
            },
            Some(cfg),
        );
        model.update(&resize(180, 50));

        // Toggle left sidebar
        model.update(&key_press_msg('['));

        // Force complete the animation (Go TestForceExpand).
        model.left_sidebar.anim_state.force_expand();

        assert!(model.left_sidebar.is_visible());

        // Page navigation (shouldn't panic)
        model.update(&key(KeyCode::PgUp, KeyMods::NONE));
        model.update(&key(KeyCode::Up, KeyMods::SHIFT));
        model.update(&key(KeyCode::PgDown, KeyMods::NONE));
        model.update(&key(KeyCode::Down, KeyMods::SHIFT));

        // Help toggle
        model.update(&key_press_msg('h'));
        model.update(&key_press_msg('?'));

        // Overview filter
        model.update(&key_press_msg('['));
        model.update(&key(KeyCode::Space, KeyMods::NONE));
        model.update(&key(KeyCode::Backspace, KeyMods::NONE));
        model.update(&key(KeyCode::Enter, KeyMods::NONE));

        // Clear overview filter
        model.update(&key(KeyCode::Char('k'), KeyMods::CTRL));
    }

    /// Go: TestHeartbeat_LiveRun.
    ///
    /// PARITY adaptations (the Go test drives real goroutines/timers):
    ///   - `InitMsg.Source` carried a live `*LevelDBHistorySource`; the port's
    ///     InitMsg carries the reader-thread handle (CONCURRENCY.md §2.3),
    ///     so a synthetic handle stands in — the model never dereferences it.
    ///   - Go counts `cmd != nil` from `Update(HeartbeatMsg{})` polled for
    ///     500ms against a background writer goroutine; a heartbeat's non-nil
    ///     cmd ⇔ the ReadLiveBatch it issues, asserted directly here (the
    ///     writer goroutine fed only the watcher, which nothing observed).
    ///   - "heartbeat continued after file completion" (Go sleeps 200ms and
    ///     compares counts) ⇔ post-completion heartbeats issue no reads and
    ///     the timer is disarmed (scheduler Cancel).
    #[test]
    fn heartbeat_live_run() {
        // Setup config with short heartbeat interval for testing
        let dir = tempfile::tempdir().unwrap();
        let cfg = test_config(&dir);
        cfg.borrow_mut().set_heartbeat_interval(1).unwrap();

        // Create a wandb file with initial data
        let path = dir.path().join("heartbeat.wandb");

        let mut w = transaction_log::open_writer(&path).unwrap();

        // Write initial records
        let run_record = Record {
            record_type: Some(record::RecordType::Run(RunRecord {
                run_id: "heartbeat-test".into(),
                display_name: "Heartbeat Test".into(),
                ..Default::default()
            })),
            ..Default::default()
        };
        w.write(&run_record).unwrap();

        // Write some history
        for i in 0..5 {
            let h = HistoryRecord {
                item: vec![
                    HistoryItem {
                        nested_key: vec!["_step".into()],
                        value_json: format!("{i}"),
                        ..Default::default()
                    },
                    HistoryItem {
                        nested_key: vec!["loss".into()],
                        value_json: format!("{:.6}", i as f64 * 0.1),
                        ..Default::default()
                    },
                ],
                ..Default::default()
            };
            w.write(&Record {
                record_type: Some(record::RecordType::History(h)),
                ..Default::default()
            })
            .unwrap();
        }
        w.close().unwrap();

        // Create model
        let mut model = Run::new(
            RunParams {
                run_file: path.to_str().unwrap().to_string(),
                remote: None,
            },
            Some(cfg),
        );

        model.update(&resize(120, 40));

        // Process initial reader (synthetic handle, see the test doc).
        model.update(&Event::Init(InitMsg {
            source: HistorySourceHandle {
                id: crate::command::SourceId(1),
            },
        }));

        // Simulate initial data load.
        let d = HashMap::from([("loss".to_string(), metric(&[0.0], &[0.1]))]);
        model.update(&Event::ChunkedBatch(ChunkedBatchMsg {
            msgs: vec![
                Event::Run(RunMsg {
                    id: "heartbeat-test".into(),
                    display_name: "Heartbeat Test".into(),
                    ..Default::default()
                }),
                Event::History(HistoryMsg {
                    metrics: d,
                    ..Default::default()
                }),
            ],
            has_more: false,
            progress: 0,
        }));

        // Verify model is in running state
        assert_eq!(model.run_state, RunState::Running);
        // Boot-load completion started watcher + heartbeat (runhandlers.go:902-909).
        assert!(model.watcher_mgr.is_started());
        assert!(model.heartbeat_mgr.timer_armed());

        // Process heartbeats and count the live reads they issue.
        let mut heartbeat_count = 0;
        for _ in 0..3 {
            let cmds = model.update(&Event::Heartbeat);
            if cmds
                .iter()
                .any(|c| matches!(c, Command::ReadLiveBatch { .. }))
            {
                heartbeat_count += 1;
            }
        }

        // Verify heartbeat was triggered at least once
        assert_ne!(
            heartbeat_count, 0,
            "no heartbeats were processed during live run"
        );

        // Send exit to stop heartbeat
        model.update(&Event::FileComplete(FileCompleteMsg { exit_code: 0 }));

        // Verify heartbeat stops after completion: no reads, timer disarmed.
        let cmds = model.update(&Event::Heartbeat);
        assert!(
            !cmds
                .iter()
                .any(|c| matches!(c, Command::ReadLiveBatch { .. })),
            "heartbeat continued after file completion"
        );
        assert!(!model.heartbeat_mgr.timer_armed());
    }

    /// Go: TestHeartbeat_ResetsOnDataReceived.
    #[test]
    fn heartbeat_resets_on_data_received() {
        // Setup config with short heartbeat
        let dir = tempfile::tempdir().unwrap();
        let cfg = test_config(&dir);
        cfg.borrow_mut().set_heartbeat_interval(1).unwrap(); // 1 second minimum

        let path = dir.path().join("reset.wandb");

        let mut w = transaction_log::open_writer(&path).unwrap();
        w.write(&Record {
            record_type: Some(record::RecordType::Run(RunRecord {
                run_id: "test".into(),
                ..Default::default()
            })),
            ..Default::default()
        })
        .unwrap();
        w.close().unwrap();

        // Create model
        let mut model = Run::new(
            RunParams {
                run_file: path.to_str().unwrap().to_string(),
                remote: None,
            },
            Some(cfg),
        );

        model.update(&resize(120, 40));

        // Initialize (synthetic reader handle, see heartbeat_live_run).
        model.update(&Event::Init(InitMsg {
            source: HistorySourceHandle {
                id: crate::command::SourceId(1),
            },
        }));

        // Load initial data to start as running
        model.update(&Event::ChunkedBatch(ChunkedBatchMsg {
            msgs: vec![Event::Run(RunMsg {
                id: "test".into(),
                ..Default::default()
            })],
            has_more: false,
            progress: 0,
        }));

        // Track heartbeat resets
        let mut heartbeat_received = false;

        // Process a heartbeat
        let cmds = model.update(&Event::Heartbeat);
        if !cmds.is_empty() {
            heartbeat_received = true;
        }

        // Now send new data (should reset heartbeat).
        let d = HashMap::from([("metric".to_string(), metric(&[1.0], &[1.0]))]);
        model.update(&history(d));

        // The heartbeat should have been reset internally
        // We can't directly test the timer reset, but we can verify
        // that receiving data doesn't break the heartbeat mechanism
        model.update(&Event::Heartbeat);

        assert!(heartbeat_received, "heartbeat not processed initially");

        // Verify model still in good state
        assert_eq!(model.run_state, RunState::Running);
    }

    /// Go: TestModel_HandleMouseMsg.
    #[test]
    fn model_handle_mouse_msg() {
        // Helper to create a fresh model with data
        fn setup_model() -> (tempfile::TempDir, Run) {
            let dir = tempfile::tempdir().unwrap();
            let cfg = test_config(&dir);
            {
                let mut cfg = cfg.borrow_mut();
                cfg.set_metrics_rows(2).unwrap();
                cfg.set_metrics_cols(2).unwrap();
                cfg.set_system_rows(2).unwrap();
                cfg.set_system_cols(1).unwrap();
                cfg.set_left_sidebar_visible(true).unwrap();
                cfg.set_right_sidebar_visible(true).unwrap();
            }

            let mut model = Run::new(
                RunParams {
                    run_file: "dummy".into(),
                    remote: None,
                },
                Some(cfg),
            );

            model.update(&resize(120, 40));

            // Add metrics data.
            let d = HashMap::from([
                ("loss".to_string(), metric(&[0.0], &[1.0])),
                ("accuracy".to_string(), metric(&[0.0], &[0.9])),
                ("val_loss".to_string(), metric(&[0.0], &[1.2])),
            ]);
            model.update(&history(d));

            // Process stats multiple times to ensure system charts are created and drawn
            model.update(&Event::Stats(StatsMsg {
                timestamp: 1234567890,
                metrics: HashMap::from([
                    ("gpu.0.temp".to_string(), 45.0),
                    ("cpu.0.cpu_percent".to_string(), 65.0),
                ]),
                ..Default::default()
            }));

            // Add more data points to ensure charts are properly initialized
            model.update(&Event::Stats(StatsMsg {
                timestamp: 1234567891,
                metrics: HashMap::from([
                    ("gpu.0.temp".to_string(), 46.0),
                    ("cpu.0.cpu_percent".to_string(), 66.0),
                ]),
                ..Default::default()
            }));

            // Force a render to ensure sidebars are drawn
            let _ = model.view(default_dark_background());

            (dir, model)
        }

        struct Case {
            name: &'static str,
            setup: Option<fn(&mut Run)>,
            events: Vec<Event>,
            verify: fn(&mut Run),
        }

        let tests = vec![
            Case {
                name: "click_in_left_sidebar_clears_all_focus",
                setup: Some(|m: &mut Run| m.metrics_grid.set_focus(0, 0)),
                events: vec![mouse(MouseKind::Click, MouseButton::Left, 10, 10)],
                verify: |m| {
                    assert_eq!(m.focus.borrow().focus_type, FocusType::None);
                },
            },
            Case {
                name: "click_in_main_grid_focuses_and_unfocuses_chart",
                setup: Some(|m: &mut Run| m.metrics_grid.clear_focus()),
                events: vec![mouse(MouseKind::Click, MouseButton::Left, 60, 15)],
                verify: |m| {
                    assert_eq!(m.focus.borrow().focus_type, FocusType::MainChart);

                    // Send second click to same position to unfocus.
                    m.update(&mouse(MouseKind::Click, MouseButton::Left, 60, 15));

                    assert_eq!(m.focus.borrow().focus_type, FocusType::None);
                },
            },
            Case {
                name: "click_in_right_sidebar_focuses_system_chart",
                setup: None,
                events: vec![mouse(MouseKind::Click, MouseButton::Left, 110, 10)],
                verify: |m| {
                    let fs = m.focus.borrow();
                    assert_eq!(fs.focus_type, FocusType::SystemChart);
                    assert!(!fs.title.is_empty());
                },
            },
            Case {
                name: "wheel_events_focus_chart_and_zoom",
                setup: None,
                events: vec![
                    mouse(MouseKind::Wheel, MouseButton::WheelUp, 60, 25),
                    mouse(MouseKind::Wheel, MouseButton::WheelDown, 60, 25),
                    mouse(MouseKind::Wheel, MouseButton::WheelUp, 60, 25),
                ],
                verify: |m| {
                    assert_eq!(m.focus.borrow().focus_type, FocusType::MainChart);
                },
            },
            Case {
                name: "mouse_release_ignored",
                setup: Some(|m: &mut Run| m.metrics_grid.set_focus(0, 0)),
                events: vec![mouse(MouseKind::Release, MouseButton::Left, 60, 15)],
                verify: |m| {
                    assert_eq!(m.focus.borrow().focus_type, FocusType::MainChart);
                },
            },
            Case {
                name: "wheel_on_unfocused_chart_focuses_it",
                // Ensure no initial focus
                setup: Some(|m: &mut Run| m.metrics_grid.clear_focus()),
                events: vec![mouse(MouseKind::Wheel, MouseButton::WheelUp, 60, 25)],
                verify: |m| {
                    assert_eq!(m.focus.borrow().focus_type, FocusType::MainChart);
                },
            },
        ];

        for tc in tests {
            // Go: t.Run(tc.name, ..) — the name is echoed for failure triage.
            eprintln!("case: {}", tc.name);
            let (_dir, mut m) = setup_model();

            // Run setup if provided
            if let Some(setup) = tc.setup {
                setup(&mut m);
            }

            // Process all events
            for event in &tc.events {
                m.update(event);
            }

            // Verify final state
            (tc.verify)(&mut m);
        }
    }
}
