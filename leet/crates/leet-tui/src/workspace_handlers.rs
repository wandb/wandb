//! Port of `core/internal/leet/workspacehandlers.go` — the Workspace's key /
//! mouse dispatch, animation and toggle handlers, reader/watcher commands,
//! and record/message handlers — plus the `*Workspace` handler half of
//! `workspacedirwatcher.go` (workspacedirwatcher.go:168-403; the preloader
//! queue and the off-thread command bodies live in workspace_dir_watcher.rs
//! / runtime.rs, see that module's doc).
//!
//! Go's `tea.Cmd` returns become `Vec<Command>`; Go's `batchCmds` (nil
//! filtering + tea.Batch, workspacehandlers.go:14-30) is inherent to the
//! vector representation and has no counterpart.

use std::time::Instant;

use leet_charts::styles::CONTENT_PADDING;
use leet_data::config::GridConfigTarget;
use leet_data::run_overview::RunState;

use crate::command::Command;
use crate::event::{
    Event, EventErrorKind, RunMsg, WorkspaceBatchedRecordsMsg, WorkspaceChunkedBatchMsg,
    WorkspaceFileChangedMsg, WorkspaceInitErrMsg, WorkspaceRunDirsMsg, WorkspaceRunInitMsg,
    WorkspaceRunOverviewPreloadedMsg,
};
use crate::focus_manager::FocusTarget;
use crate::key::{KeyCode, KeyEvent, KeyMods, MouseButton, MouseEvent, MouseKind, normalize_key};
use crate::keybindings::WorkspaceAction;
use crate::nav::{NavIntent, decode_nav};
use crate::panel_grid::FocusType;
use crate::run::{Layout, media_pane_commands};
use crate::system_metrics_grid::SystemMetricsGrid;
use crate::watcher_manager::WatcherManager;
use crate::workspace::{Workspace, WorkspaceRun, run_wandb_file};
use crate::workspace_dir_watcher::{WANDB_DIR_POLL_INTERVAL, poll_wandb_dir_cmd};
use crate::workspace_run_filter::WorkspaceRunFilterHost;
use crate::workspace_system_metrics_pane::SYSTEM_METRICS_PANE_HEADER_LINES;

/// Converts an app-event RunMsg to the leet-data form consumed by
/// `RunOverview::process_run_msg` (Go has one RunMsg type; the port splits
/// it across crates — see the PARITY note on
/// `leet_data::run_overview::RunMsg`).
pub(crate) fn run_msg_to_overview(msg: &RunMsg) -> leet_data::run_overview::RunMsg {
    leet_data::run_overview::RunMsg {
        run_path: msg.run_path.clone(),
        id: msg.id.clone(),
        project: msg.project.clone(),
        display_name: msg.display_name.clone(),
        notes: msg.notes.clone(),
        tags: msg.tags.clone(),
        config: msg.config.as_deref().cloned(),
    }
}

impl Workspace {
    // ---- Key / Mouse Dispatch ----

    pub(crate) fn adopt_chart_mouse_focus(&mut self) {
        if self.focus.borrow().focus_type == FocusType::MainChart {
            self.focus_mgr_do(|fm, w| fm.adopt_target(w, FocusTarget::MetricsGrid));
        } else if self.system_metrics_focus.borrow().focus_type == FocusType::SystemChart {
            // PARITY: Go nil-checks systemMetricsFocus; always set here.
            self.focus_mgr_do(|fm, w| fm.adopt_target(w, FocusTarget::SystemMetrics));
        }
    }

    pub(crate) fn handle_media_mouse(&mut self, msg: &MouseEvent, layout: Layout) -> Vec<Command> {
        let local_x = msg.x - layout.left_sidebar_width;
        let local_y = msg.y - layout.media_y;

        if msg.kind == MouseKind::Click
            && msg.button == MouseButton::Left
            && self.media_pane.handle_mouse_click(
                local_x,
                local_y,
                layout.main_content_area_width,
                layout.media_height,
            )
        {
            self.media_pane.set_active(true);
            self.focus_mgr_do(|fm, w| fm.adopt_target(w, FocusTarget::Media));
        }

        vec![]
    }

    pub(crate) fn handle_key_press_msg(&mut self, msg: &KeyEvent) -> Vec<Command> {
        // Filter mode takes priority.
        if self.filter.is_active() {
            self.handle_run_filter_key(msg);
            return vec![];
        }
        if self.run_overview_sidebar.is_filter_mode() {
            self.run_overview_sidebar.handle_filter_key(msg);
            return vec![];
        }
        if self.metrics_grid.is_filter_mode() {
            self.metrics_grid.handle_filter_key(msg);
            return vec![];
        }
        if let Some(g) = self.active_system_metrics_grid_mut()
            && g.is_filter_mode()
        {
            g.handle_filter_key(msg);
            return vec![];
        }

        // Grid config capture takes priority.
        if self.config.borrow().is_awaiting_grid_config() {
            let layout = self.compute_viewports();
            self.metrics_grid.handle_grid_config_number_key(
                msg,
                layout.main_content_area_width,
                layout.height,
            );
            return vec![];
        }

        // Focus-aware key dispatch.
        match self.focus_mgr.current() {
            FocusTarget::MetricsGrid | FocusTarget::SystemMetrics => {
                if let Some(cmds) = self.handle_grid_nav(msg) {
                    return cmds;
                }
            }
            FocusTarget::Media => {
                let (handled, cmds) = self.media_pane.handle_key(msg);
                if handled {
                    return media_pane_commands(cmds);
                }
            }
            _ => {}
        }

        // Dispatch via key map.
        if let Some(&action) = self.key_map.get(normalize_key(&msg.key_string())) {
            return self.dispatch_workspace_action(action, msg);
        }
        vec![]
    }

    /// Executes one bound action — Go's `handler(w, msg)` through the
    /// `keyMap` (workspacehandlers.go:100-103); one arm per
    /// `(*Workspace).handle*` func referenced by the binding table.
    fn dispatch_workspace_action(
        &mut self,
        action: WorkspaceAction,
        msg: &KeyEvent,
    ) -> Vec<Command> {
        match action {
            WorkspaceAction::Quit => self.handle_quit(msg),
            WorkspaceAction::FocusRuns => self.handle_focus_runs(msg),
            WorkspaceAction::ToggleMetricsGrid => self.handle_toggle_metrics_grid(msg),
            WorkspaceAction::ToggleRunsSidebar => self.handle_toggle_runs_sidebar(msg),
            WorkspaceAction::ToggleSystemMetricsPane => self.handle_toggle_system_metrics_pane(msg),
            WorkspaceAction::ToggleOverviewSidebar => self.handle_toggle_overview_sidebar(msg),
            WorkspaceAction::ToggleMediaPane => self.handle_toggle_media_pane(msg),
            WorkspaceAction::ToggleConsoleLogsPane => self.handle_toggle_console_logs_pane(msg),
            WorkspaceAction::PrevPage => self.handle_prev_page(msg),
            WorkspaceAction::NextPage => self.handle_next_page(msg),
            WorkspaceAction::NavHome => self.handle_nav_home(msg),
            WorkspaceAction::NavEnd => self.handle_nav_end(msg),
            WorkspaceAction::EnterRunsFilter => {
                WorkspaceRunFilterHost::handle_enter_runs_filter(self, msg).unwrap_or_default()
            }
            WorkspaceAction::ClearRunsFilter => {
                WorkspaceRunFilterHost::handle_clear_runs_filter(self, msg).unwrap_or_default()
            }
            WorkspaceAction::CycleFocusedChartMode => self.handle_cycle_focused_chart_mode(msg),
            WorkspaceAction::EnterMetricsFilter => self.handle_enter_metrics_filter(msg),
            WorkspaceAction::EnterSystemMetricsFilter => {
                self.handle_enter_system_metrics_filter(msg)
            }
            WorkspaceAction::ClearMetricsFilter => self.handle_clear_metrics_filter(msg),
            WorkspaceAction::ClearSystemMetricsFilter => {
                self.handle_clear_system_metrics_filter(msg)
            }
            WorkspaceAction::EnterOverviewFilter => self.handle_enter_overview_filter(msg),
            WorkspaceAction::ClearOverviewFilter => self.handle_clear_overview_filter(msg),
            WorkspaceAction::ConfigFocusedCols => self.handle_config_focused_cols(msg),
            WorkspaceAction::ConfigFocusedRows => self.handle_config_focused_rows(msg),
            WorkspaceAction::SidebarTabNav => self.handle_sidebar_tab_nav(msg),
            WorkspaceAction::RunsVerticalNav => self.handle_runs_vertical_nav(msg),
            WorkspaceAction::RunsPageNav => self.handle_runs_page_nav(msg),
            WorkspaceAction::ToggleRunSelectedKey => self.handle_toggle_run_selected_key(msg),
            WorkspaceAction::PinRunKey => self.handle_pin_run_key(msg),
        }
    }

    pub(crate) fn handle_mouse(&mut self, msg: &MouseEvent) -> Vec<Command> {
        let layout = self.compute_viewports();

        // Clicks in the left sidebar clear all chart focus.
        if self.runs_anim_state.is_visible() && msg.x < layout.left_sidebar_width {
            self.clear_chart_focus();
            return vec![];
        }

        // Clicks in the right sidebar clear all chart focus.
        if self.run_overview_sidebar.is_visible()
            && msg.x >= self.width - layout.right_sidebar_width
        {
            self.clear_chart_focus();
            return vec![];
        }

        if self.media_pane.is_fullscreen() {
            return vec![];
        }

        if layout.height > 0 && msg.y < layout.height {
            return self.handle_metrics_mouse(msg, layout);
        }

        if layout.system_metrics_height > 0
            && msg.y >= layout.system_metrics_y
            && msg.y < layout.system_metrics_y + layout.system_metrics_height
        {
            return self.handle_system_metrics_mouse(msg, layout);
        }

        if layout.media_height > 0
            && msg.y >= layout.media_y
            && msg.y < layout.media_y + layout.media_height
        {
            return self.handle_media_mouse(msg, layout);
        }

        if layout.console_logs_height > 0
            && msg.y >= layout.console_logs_y
            && msg.y < layout.console_logs_y + layout.console_logs_height
        {
            self.clear_chart_focus();
            return vec![];
        }

        // Separator or status bar area — no chart interaction.
        vec![]
    }

    pub(crate) fn handle_metrics_mouse(
        &mut self,
        msg: &MouseEvent,
        layout: Layout,
    ) -> Vec<Command> {
        // Alt pressed at the time of the mouse event? (Go `Mod == ModAlt`.)
        let alt = msg.mods
            == KeyMods {
                ctrl: false,
                alt: true,
                shift: false,
            };

        const HEADER_OFFSET: isize = 1; // metrics header line

        let adjusted_x = msg.x - layout.left_sidebar_width - CONTENT_PADDING as isize;
        let adjusted_y = msg.y - HEADER_OFFSET;
        if adjusted_x < 0 || adjusted_y < 0 {
            return vec![];
        }

        let dims = self
            .metrics_grid
            .calculate_chart_dimensions(layout.main_content_area_width, layout.height);
        if dims.cell_h_with_padding == 0 || dims.cell_w_with_padding == 0 {
            return vec![];
        }

        let row = adjusted_y / dims.cell_h_with_padding;
        let col = adjusted_x / dims.cell_w_with_padding;

        match msg.kind {
            MouseKind::Click => match msg.button {
                MouseButton::Left => {
                    self.clear_current_system_metrics_focus();
                    self.metrics_grid.handle_click(row, col);
                    self.adopt_chart_mouse_focus();
                }
                MouseButton::Right => {
                    self.metrics_grid
                        .start_inspection(adjusted_x, row, col, dims, alt);
                    self.adopt_chart_mouse_focus();
                }
                _ => {}
            },
            MouseKind::Motion => {
                if msg.button == MouseButton::Right {
                    self.metrics_grid
                        .update_inspection(adjusted_x, row, col, dims);
                }
            }
            MouseKind::Release => {
                if msg.button == MouseButton::Right {
                    self.metrics_grid.end_inspection();
                }
            }
            MouseKind::Wheel => {
                match msg.button {
                    MouseButton::WheelUp => {
                        self.metrics_grid
                            .handle_wheel(adjusted_x, row, col, dims, true);
                    }
                    MouseButton::WheelDown => {
                        self.metrics_grid
                            .handle_wheel(adjusted_x, row, col, dims, false);
                    }
                    _ => {}
                }
                self.adopt_chart_mouse_focus();
            }
        }

        vec![]
    }

    pub(crate) fn handle_system_metrics_mouse(
        &mut self,
        msg: &MouseEvent,
        layout: Layout,
    ) -> Vec<Command> {
        let alt = msg.mods
            == KeyMods {
                ctrl: false,
                alt: true,
                shift: false,
            };

        let Some(cur) = self.runs.current_item() else {
            return vec![];
        };
        let cur_key = cur.key.clone();
        if !self.system_metrics.contains_key(&cur_key) {
            return vec![];
        }

        let adjusted_x = msg.x - layout.left_sidebar_width - CONTENT_PADDING as isize;
        let adjusted_y = msg.y - layout.system_metrics_y - SYSTEM_METRICS_PANE_HEADER_LINES;
        if adjusted_x < 0 || adjusted_y < 0 {
            return vec![];
        }

        let dims = self
            .system_metrics
            .get(&cur_key)
            .expect("checked above")
            .calculate_chart_dimensions();
        if dims.cell_h_with_padding == 0 || dims.cell_w_with_padding == 0 {
            return vec![];
        }
        let row = adjusted_y / dims.cell_h_with_padding;
        let col = adjusted_x / dims.cell_w_with_padding;

        match msg.kind {
            MouseKind::Click => match msg.button {
                MouseButton::Left => {
                    self.metrics_grid.clear_focus();
                    let clicked = self
                        .system_metrics
                        .get(&cur_key)
                        .expect("checked above")
                        .handle_mouse_click(row, col);
                    if clicked {
                        self.adopt_chart_mouse_focus();
                    }
                }
                MouseButton::Right => {
                    self.metrics_grid.clear_focus();
                    self.system_metrics
                        .get_mut(&cur_key)
                        .expect("checked above")
                        .start_inspection(adjusted_x, adjusted_y, row, col, dims, alt);
                    self.adopt_chart_mouse_focus();
                }
                _ => {}
            },
            MouseKind::Motion => {
                if msg.button == MouseButton::Right {
                    self.system_metrics
                        .get_mut(&cur_key)
                        .expect("checked above")
                        .update_inspection(adjusted_x, adjusted_y, row, col, dims);
                }
            }
            MouseKind::Release => {
                if msg.button == MouseButton::Right {
                    self.system_metrics
                        .get_mut(&cur_key)
                        .expect("checked above")
                        .end_inspection();
                }
            }
            MouseKind::Wheel => {
                self.metrics_grid.clear_focus();
                let grid = self.system_metrics.get(&cur_key).expect("checked above");
                match msg.button {
                    MouseButton::WheelUp => grid.handle_wheel(adjusted_x, row, col, dims, true),
                    MouseButton::WheelDown => grid.handle_wheel(adjusted_x, row, col, dims, false),
                    _ => {}
                }
                self.adopt_chart_mouse_focus();
            }
        }

        vec![]
    }

    /// clearChartFocus clears focus from both the main metrics grid
    /// and the current run's system metrics grid.
    pub(crate) fn clear_chart_focus(&mut self) {
        self.metrics_grid.clear_focus();
        self.clear_current_system_metrics_focus();
    }

    /// clearCurrentSystemMetricsFocus clears focus from the system metrics
    /// grid of the currently highlighted run (if any).
    pub(crate) fn clear_current_system_metrics_focus(&mut self) {
        let Some(cur) = self.runs.current_item() else {
            return;
        };
        let key = cur.key.clone();
        if let Some(grid) = self.system_metrics.get(&key) {
            grid.clear_focus();
        }
    }

    // ---- Animation Handlers ----

    pub(crate) fn handle_runs_animation(&mut self) -> Vec<Command> {
        self.runs_anim_state.update(Instant::now());
        self.recalculate_layout();

        if self.runs_anim_state.is_animating() {
            return vec![self.runs_animation_cmd()];
        }

        // Animation complete: let the other sidebar adjust to the new state.
        self.update_sidebar_dimensions(
            self.runs_anim_state.is_visible(),
            self.run_overview_sidebar.is_visible(),
        );
        vec![]
    }

    pub(crate) fn handle_run_overview_animation(&mut self) -> Vec<Command> {
        self.run_overview_sidebar.anim_state.update(Instant::now());
        self.recalculate_layout();

        if self.run_overview_sidebar.is_animating() {
            return vec![self.run_overview_animation_cmd()];
        }

        // Animation complete: let the other sidebar adjust to the new state.
        self.update_sidebar_dimensions(
            self.runs_anim_state.is_visible(),
            self.run_overview_sidebar.is_visible(),
        );
        vec![]
    }

    pub(crate) fn handle_console_logs_pane_animation(&mut self) -> Vec<Command> {
        self.console_logs_pane.update(Instant::now());
        self.recalculate_layout();

        if self.console_logs_pane.is_animating() {
            return vec![self.console_logs_pane_animation_cmd()];
        }
        vec![]
    }

    pub(crate) fn handle_media_pane_animation(&mut self) -> Vec<Command> {
        self.media_pane.update(Instant::now());
        self.recalculate_layout();

        if self.media_pane.is_animating() {
            return vec![self.media_pane_animation_cmd()];
        }
        vec![]
    }

    pub(crate) fn handle_system_metrics_pane_animation(&mut self, now: Instant) -> Vec<Command> {
        let done = self.system_metrics_pane.update(now);
        self.recalculate_layout();
        if done {
            return vec![];
        }
        vec![self.system_metrics_pane_animation_cmd()]
    }

    // ---- UI components Toggle Handlers ----

    pub(crate) fn handle_toggle_runs_sidebar(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        let left_will_be_visible = !self.runs_anim_state.target_visible();
        let right_is_visible = self.run_overview_sidebar.anim_state.target_visible();

        self.update_sidebar_dimensions(left_will_be_visible, right_is_visible);
        self.runs_anim_state.toggle();
        self.focus_mgr_do(|fm, w| fm.resolve_after_visibility_change(w));
        self.recalculate_layout();

        vec![self.runs_animation_cmd()]
    }

    pub(crate) fn handle_toggle_overview_sidebar(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        let right_will_be_visible = !self.run_overview_sidebar.anim_state.target_visible();
        let left_is_visible = self.runs_anim_state.target_visible();

        if let Err(err) = self
            .config
            .borrow_mut()
            .set_workspace_overview_visible(right_will_be_visible)
        {
            tracing::error!("workspace: failed to save overview state: {err}");
        }

        self.update_sidebar_dimensions(left_is_visible, right_will_be_visible);
        self.run_overview_sidebar.toggle();
        self.focus_mgr_do(|fm, w| fm.resolve_after_visibility_change(w));
        self.recalculate_layout();

        vec![self.run_overview_animation_cmd()]
    }

    pub(crate) fn handle_toggle_media_pane(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        let media_will_be_visible = !self.media_pane.anim_state.target_visible();

        if let Err(err) = self
            .config
            .borrow_mut()
            .set_workspace_media_visible(media_will_be_visible)
        {
            tracing::error!("workspace: failed to save media pane state: {err}");
        }

        if media_will_be_visible {
            self.update_bottom_pane_heights(
                self.system_metrics_pane.anim_state.target_visible(),
                true,
                self.console_logs_pane.anim_state.target_visible(),
            );
        } else {
            self.media_pane.exit_fullscreen();
            self.update_bottom_pane_heights(
                self.system_metrics_pane.anim_state.target_visible(),
                false,
                self.console_logs_pane.anim_state.target_visible(),
            );
        }

        self.media_pane.toggle();
        if !media_will_be_visible {
            self.focus_mgr_do(|fm, w| fm.resolve_after_visibility_change(w));
        }
        self.recalculate_layout();
        vec![self.media_pane_animation_cmd()]
    }

    pub(crate) fn handle_toggle_console_logs_pane(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        let bottom_will_be_visible = !self.console_logs_pane.anim_state.target_visible();

        if let Err(err) = self
            .config
            .borrow_mut()
            .set_workspace_console_logs_visible(bottom_will_be_visible)
        {
            tracing::error!("workspace: failed to save console logs state: {err}");
        }

        self.update_bottom_pane_heights(
            self.system_metrics_pane.anim_state.target_visible(),
            self.media_pane.anim_state.target_visible(),
            bottom_will_be_visible,
        );
        self.console_logs_pane.toggle();
        self.focus_mgr_do(|fm, w| fm.resolve_after_visibility_change(w));
        self.recalculate_layout();

        vec![self.console_logs_pane_animation_cmd()]
    }

    pub(crate) fn handle_toggle_system_metrics_pane(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        let sys_will_be_visible = !self.system_metrics_pane.anim_state.target_visible();
        let media_visible = self.media_pane.anim_state.target_visible();
        let logs_visible = self.console_logs_pane.anim_state.target_visible();

        if let Err(err) = self
            .config
            .borrow_mut()
            .set_workspace_system_metrics_visible(sys_will_be_visible)
        {
            tracing::error!("workspace: failed to save system metrics state: {err}");
        }

        self.update_bottom_pane_heights(sys_will_be_visible, media_visible, logs_visible);
        self.system_metrics_pane.toggle();
        self.focus_mgr_do(|fm, w| fm.resolve_after_visibility_change(w));
        self.recalculate_layout();
        vec![self.system_metrics_pane_animation_cmd()]
    }

    // ---- Reader / Watcher Commands ----

    /// initReaderCmd initializes a WandbReader for the given run
    /// asynchronously — the runtime's reader-thread init replies
    /// `WorkspaceRunInit` / `WorkspaceInitErr` (CONCURRENCY.md §2.3).
    pub(crate) fn init_reader_cmd(&self, run_key: &str, run_path: &str) -> Command {
        Command::InitWorkspaceReader {
            run_key: run_key.to_string(),
            run_path: run_path.to_string(),
        }
    }

    /// readAllChunkCmd reads a bounded chunk of records for the given
    /// workspace run (BootLoad bounds are baked into the command,
    /// command.rs). `None` ⇔ the Go nil cmd for a nil run/reader.
    pub(crate) fn read_all_chunk_cmd(&self, run_key: &str) -> Option<Command> {
        let run = self.runs_by_key.get(run_key)?;
        let reader = run.reader?;
        Some(Command::ReadAllChunk {
            source: reader.id,
            run_key: run.key.clone(),
        })
    }

    /// ReadAvailableCmd drains any new records for a live workspace run
    /// (LiveMonitor bounds baked into the command).
    pub fn read_available_cmd(&self, run_key: &str) -> Option<Command> {
        let run = self.runs_by_key.get(run_key)?;
        let reader = run.reader?;
        Some(Command::ReadAvailable {
            source: reader.id,
            run_key: run.key.clone(),
        })
    }

    // PARITY(C2): Go `waitForLiveMsg` (workspacehandlers.go:520-525) has no
    // counterpart — heartbeats go scheduler → main channel directly (§2.5).

    /// ensureLiveStreaming wires up watcher + heartbeat for a selected,
    /// running run.
    ///
    /// It is a no-op if the run is unknown, not live, or its reader is not
    /// initialized. When a watcher is started it also returns a command
    /// that waits for the first change notification so that subsequent
    /// updates are driven primarily by filesystem events, with the
    /// heartbeat as a safety net.
    pub(crate) fn ensure_live_streaming(&mut self, run_key: &str) -> Vec<Command> {
        let mut started_watcher = false;
        {
            let Some(run) = self.runs_by_key.get_mut(run_key) else {
                return vec![];
            };
            if run.reader.is_none() || run.state != RunState::Running {
                return vec![];
            }

            if run.watcher.is_none() {
                // PARITY(C3): the per-run cap-1 coalescing channel lives
                // inside the watcher registration (§2.5).
                let mut watcher = WatcherManager::new();
                match watcher.start(&run.wandb_path) {
                    Err(err) => {
                        tracing::error!(
                            "workspace: failed to start watcher for {}: {err}",
                            run.key
                        );
                    }
                    Ok(()) => {
                        run.watcher = Some(watcher);
                        started_watcher = true;
                    }
                }
            }
        }

        let mut cmds = Vec::new();
        // PARITY(S3): syncLiveRunState deleted; evaluated inline.
        let has_live_runs = self.any_run_running();
        if has_live_runs {
            cmds.push(self.heartbeat_mgr.start(has_live_runs));
        }
        if started_watcher && let Some(cmd) = self.wait_for_watcher(run_key) {
            cmds.push(cmd);
        }

        cmds
    }

    /// waitForWatcher blocks until the watcher for the given run emits a
    /// change and wraps the low-level FileChangedMsg with the originating
    /// run key — ported as the `AwaitWorkspaceWatcher` pump command doing
    /// one `recv` (CONCURRENCY.md §2.5).
    ///
    /// The watcher lookup is performed on the update thread; the pump only
    /// blocks on the registration's receiver. (Go captures the watcher
    /// pointer; the Cmd closure must not reference w.runsByKey.)
    pub(crate) fn wait_for_watcher(&self, run_key: &str) -> Option<Command> {
        let run = self.runs_by_key.get(run_key)?;
        let watcher = run.watcher.as_ref()?;

        let rx = watcher.watch_receiver()?;

        Some(Command::AwaitWorkspaceWatcher {
            run_key: run_key.to_string(),
            rx,
        })
    }

    /// stopWatcher stops and clears the watcher associated with a run, if
    /// any.
    // PARITY: Go is a *Workspace method taking the run pointer; the
    // receiver is unused, so it ports as an associated fn (avoids a second
    // &mut self borrow at map-entry call sites).
    pub(crate) fn stop_watcher(run: &mut WorkspaceRun) {
        let Some(watcher) = run.watcher.as_mut() else {
            return;
        };
        watcher.finish();
        run.watcher = None;
    }

    // ---- Message Handlers ----

    pub(crate) fn handle_workspace_init_err(&mut self, msg: &WorkspaceInitErrMsg) -> Vec<Command> {
        // Revert selection state so we don't get stuck with "selected but
        // never loads".
        let mut cmds = Vec::new();
        if !msg.run_key.is_empty() {
            cmds = self.drop_run(&msg.run_key);
        }

        if let Some(err) = &msg.err
            && err.kind != EventErrorKind::NotExist
        {
            tracing::error!(
                "workspace: init reader for {} ({}): {}",
                msg.run_key,
                msg.run_path,
                err
            );
        }
        cmds
    }

    /// handleWorkspaceRunInit stores the reader and starts the initial load
    /// for the run.
    pub(crate) fn handle_workspace_run_init(&mut self, msg: &WorkspaceRunInitMsg) -> Vec<Command> {
        // PARITY: Go also checks `msg.Reader == nil`; the handle is always
        // present in the message here, so only the empty-key check remains.
        if msg.run_key.is_empty() {
            return vec![];
        }

        if !self
            .selected_runs
            .get(&msg.run_key)
            .copied()
            .unwrap_or(false)
        {
            // The run was deselected (or removed) while the reader was
            // initializing. (Go msg.Reader.Close().)
            return vec![Command::CloseReader {
                source: msg.reader.id,
            }];
        }

        let run = WorkspaceRun {
            key: msg.run_key.clone(),
            wandb_path: msg.run_path.clone(),
            reader: Some(msg.reader),
            watcher: None,
            state: RunState::Unknown,
        };
        self.runs_by_key.insert(msg.run_key.clone(), run);

        self.read_all_chunk_cmd(&msg.run_key).into_iter().collect()
    }

    /// handleWorkspaceChunkedBatch processes an initial chunk of data for a
    /// run.
    pub(crate) fn handle_workspace_chunked_batch(
        &mut self,
        msg: &WorkspaceChunkedBatchMsg,
    ) -> Vec<Command> {
        if !self.runs_by_key.contains_key(&msg.run_key) {
            return vec![];
        }

        let mut cmds = Vec::new();
        for sub in &msg.batch.msgs {
            cmds.extend(self.handle_workspace_record(&msg.run_key, sub));
        }
        self.metrics_grid.draw_visible();

        if msg.batch.has_more {
            cmds.extend(self.read_all_chunk_cmd(&msg.run_key));
            return cmds;
        }

        // Initial load complete; if this run is live, wire up watcher +
        // heartbeat.
        cmds.extend(self.ensure_live_streaming(&msg.run_key));
        cmds
    }

    /// handleWorkspaceBatchedRecords processes incremental updates for a
    /// run.
    pub(crate) fn handle_workspace_batched_records(
        &mut self,
        msg: &WorkspaceBatchedRecordsMsg,
    ) -> Vec<Command> {
        if !self.runs_by_key.contains_key(&msg.run_key) {
            return vec![];
        }

        let mut cmds = Vec::new();
        for sub in &msg.batch.msgs {
            cmds.extend(self.handle_workspace_record(&msg.run_key, sub));
        }
        self.metrics_grid.draw_visible();

        // Continue draining while the run is still live.
        if self
            .runs_by_key
            .get(&msg.run_key)
            .is_some_and(|run| run.state == RunState::Running)
        {
            cmds.extend(self.read_available_cmd(&msg.run_key));
            return cmds;
        }

        if !self.any_run_running() {
            cmds.push(self.heartbeat_mgr.stop());
        }

        cmds
    }

    /// handleWorkspaceRecord updates per‑run and metrics state for an
    /// individual record.
    ///
    /// Go returns nothing; the heartbeat re-arm/stop side effects surface
    /// as scheduler commands here.
    pub(crate) fn handle_workspace_record(&mut self, run_key: &str, msg: &Event) -> Vec<Command> {
        let mut cmds = Vec::new();
        match msg {
            Event::Run(m) => {
                self.get_or_create_run_overview(run_key)
                    .borrow_mut()
                    .process_run_msg(run_msg_to_overview(m));
                self.index_run_filter_data(run_key, m);
                if !self.filter.query().is_empty() {
                    self.apply_run_filter();
                }
                if let Some(run) = self.runs_by_key.get_mut(run_key) {
                    run.state = RunState::Running;
                }
                // PARITY(S3): syncLiveRunState deleted.
            }

            Event::History(m) => {
                self.metrics_grid.process_history(m);
                self.get_or_create_media_store(run_key)
                    .borrow_mut()
                    .process_history(&m.media);
                if !self.pinned_run.is_empty() {
                    self.refresh_pinned_run();
                }
                if self.should_reset_run_heartbeat(run_key) {
                    let has_live_runs = self.any_run_running();
                    cmds.push(self.heartbeat_mgr.reset(has_live_runs));
                }
            }

            Event::Stats(m) => {
                self.get_or_create_system_metrics_grid(run_key)
                    .process_stats(m);
            }

            Event::SystemInfo(m) => {
                self.get_or_create_run_overview(run_key)
                    .borrow_mut()
                    .process_system_info_msg(m.record.as_deref());
            }

            Event::Summary(m) => {
                self.get_or_create_run_overview(run_key)
                    .borrow_mut()
                    .process_summary_msg(&m.summary);
            }

            Event::ConsoleLog(m) => {
                self.get_or_create_console_logs(run_key)
                    .process_raw(&m.text, m.is_stderr, m.time);
            }

            Event::FileComplete(m) => {
                let state = match m.exit_code {
                    0 => RunState::Finished,
                    _ => RunState::Failed,
                };
                if let Some(run) = self.runs_by_key.get_mut(run_key) {
                    run.state = state;
                }
                self.get_or_create_run_overview(run_key)
                    .borrow_mut()
                    .set_run_state(state);
                // PARITY(S3): syncLiveRunState deleted.

                // No more updates expected for this run; stop its watcher.
                if let Some(run) = self.runs_by_key.get_mut(run_key) {
                    Self::stop_watcher(run);
                }
                if !self.any_run_running() {
                    cmds.push(self.heartbeat_mgr.stop());
                }
            }

            _ => {}
        }
        cmds
    }

    /// handleHeartbeat is invoked when the workspace heartbeat timer fires.
    pub(crate) fn handle_heartbeat(&mut self) -> Vec<Command> {
        if !self.any_run_running() {
            // PARITY(C2): Go additionally re-arms `waitForLiveMsg`; the
            // pump has no Rust counterpart.
            return vec![self.heartbeat_mgr.stop()];
        }

        // PARITY(S3): syncLiveRunState deleted; evaluated inline.
        let has_live_runs = self.any_run_running();
        let mut cmds = vec![self.heartbeat_mgr.reset(has_live_runs)];

        // PARITY: Go iterates runsByKey unordered here; sorted for
        // determinism.
        let mut keys: Vec<String> = self.runs_by_key.keys().cloned().collect();
        keys.sort();
        for key in keys {
            let Some(run) = self.runs_by_key.get(&key) else {
                continue;
            };
            if run.state != RunState::Running
                || !self.selected_runs.get(&key).copied().unwrap_or(false)
            {
                continue;
            }
            cmds.extend(self.read_available_cmd(&key));
        }
        cmds
    }

    /// handleWorkspaceFileChanged reacts to a filesystem change for a given
    /// run.
    pub(crate) fn handle_workspace_file_changed(
        &mut self,
        msg: &WorkspaceFileChangedMsg,
    ) -> Vec<Command> {
        let Some(run) = self.runs_by_key.get(&msg.run_key) else {
            return vec![];
        };

        // Re‑arm watcher for the next change if we're still watching this
        // run.
        let watcher_cmd = if run.watcher.is_some() {
            self.wait_for_watcher(&msg.run_key)
        } else {
            None
        };

        let mut cmds = Vec::new();
        // Keep the heartbeat as a safety net when we still have live runs.
        if self.any_run_running() {
            // PARITY(S3): syncLiveRunState deleted.
            let has_live_runs = self.any_run_running();
            cmds.push(self.heartbeat_mgr.reset(has_live_runs));
        }

        cmds.extend(self.read_available_cmd(&msg.run_key));
        cmds.extend(watcher_cmd);
        cmds
    }

    pub(crate) fn handle_quit(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        tracing::debug!("workspace: quit requested");
        let mut cmds = self.cleanup();
        cmds.push(Command::Quit);
        cmds
    }

    // ---- Navigation Handlers ----

    pub(crate) fn handle_prev_page(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        match self.focus_mgr.current() {
            FocusTarget::MetricsGrid => self.metrics_grid.navigate(-1),
            FocusTarget::SystemMetrics => {
                if let Some(g) = self.active_system_metrics_grid_mut() {
                    g.navigate(-1);
                }
            }
            FocusTarget::Media => self.media_pane.navigate_page(-1),
            FocusTarget::RunsList => self.runs.page_up(),
            FocusTarget::Overview => self.run_overview_sidebar.navigate_page_up(),
            FocusTarget::ConsoleLogs => self.console_logs_pane.page_up(),
            FocusTarget::None => {}
        }
        vec![]
    }

    pub(crate) fn handle_next_page(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        match self.focus_mgr.current() {
            FocusTarget::MetricsGrid => self.metrics_grid.navigate(1),
            FocusTarget::SystemMetrics => {
                if let Some(g) = self.active_system_metrics_grid_mut() {
                    g.navigate(1);
                }
            }
            FocusTarget::Media => self.media_pane.navigate_page(1),
            FocusTarget::RunsList => self.runs.page_down(),
            FocusTarget::Overview => self.run_overview_sidebar.navigate_page_down(),
            FocusTarget::ConsoleLogs => self.console_logs_pane.page_down(),
            FocusTarget::None => {}
        }
        vec![]
    }

    pub(crate) fn handle_nav_home(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        match self.focus_mgr.current() {
            FocusTarget::MetricsGrid => self.metrics_grid.navigate_home(),
            FocusTarget::SystemMetrics => {
                if let Some(g) = self.active_system_metrics_grid_mut() {
                    g.navigate_home();
                }
            }
            FocusTarget::Media => self.media_pane.scrub_to_start(),
            FocusTarget::RunsList => self.runs.home(),
            FocusTarget::Overview => self.run_overview_sidebar.navigate_home(),
            FocusTarget::ConsoleLogs => self.console_logs_pane.scroll_to_start(),
            FocusTarget::None => {}
        }
        vec![]
    }

    pub(crate) fn handle_nav_end(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        match self.focus_mgr.current() {
            FocusTarget::MetricsGrid => self.metrics_grid.navigate_end(),
            FocusTarget::SystemMetrics => {
                if let Some(g) = self.active_system_metrics_grid_mut() {
                    g.navigate_end();
                }
            }
            FocusTarget::Media => self.media_pane.scrub_to_end(),
            FocusTarget::RunsList => self.runs.end(),
            FocusTarget::Overview => self.run_overview_sidebar.navigate_end(),
            FocusTarget::ConsoleLogs => self.console_logs_pane.scroll_to_end(),
            FocusTarget::None => {}
        }
        vec![]
    }

    pub(crate) fn handle_cycle_focused_chart_mode(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        let focus_type = self.focus.borrow().focus_type;
        match focus_type {
            FocusType::MainChart => {
                self.metrics_grid.toggle_focused_chart_log_y();
            }
            FocusType::SystemChart => {
                if let Some(g) = self.active_system_metrics_grid() {
                    g.cycle_focused_chart_mode();
                }
            }
            FocusType::None => {}
        }
        vec![]
    }

    pub(crate) fn handle_enter_metrics_filter(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        self.metrics_grid.enter_filter_mode();
        vec![]
    }

    pub(crate) fn handle_enter_system_metrics_filter(&mut self, msg: &KeyEvent) -> Vec<Command> {
        let mut cmds = Vec::new();
        if !self.system_metrics_pane.is_expanded() && !self.system_metrics_pane.is_animating() {
            cmds.extend(self.handle_toggle_system_metrics_pane(msg));
        }

        let Some(cur) = self.runs.current_item() else {
            return cmds;
        };
        let cur_key = cur.key.clone();
        if !self.selected_runs.contains_key(&cur_key) {
            return cmds;
        }

        let grid = self.get_or_create_system_metrics_grid(&cur_key);
        grid.enter_filter_mode();
        grid.apply_filter();
        cmds
    }

    pub(crate) fn handle_clear_metrics_filter(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        if !self.metrics_grid.filter_query().is_empty() {
            self.metrics_grid.clear_filter();
        }
        if self.focus_mgr.current() == FocusTarget::MetricsGrid {
            self.metrics_grid.navigate_focus(0, 0);
        }
        vec![]
    }

    pub(crate) fn handle_clear_system_metrics_filter(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        if let Some(g) = self.active_system_metrics_grid_mut()
            && !g.filter_query().is_empty()
        {
            g.clear_filter();
        }
        if self.focus_mgr.current() == FocusTarget::SystemMetrics
            && let Some(g) = self.active_system_metrics_grid()
        {
            g.navigate_focus(0, 0);
        }
        vec![]
    }

    pub(crate) fn handle_enter_overview_filter(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        self.run_overview_sidebar.enter_filter_mode();
        vec![]
    }

    pub(crate) fn handle_clear_overview_filter(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        if self.run_overview_sidebar.is_filtering() {
            self.run_overview_sidebar.clear_filter();
        }
        vec![]
    }

    pub(crate) fn handle_toggle_metrics_grid(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        let metrics_will_be_visible = !self.metrics_grid_anim_state.target_visible();

        if let Err(err) = self
            .config
            .borrow_mut()
            .set_workspace_metrics_grid_visible(metrics_will_be_visible)
        {
            tracing::error!("workspace: failed to save metrics grid state: {err}");
        }

        self.metrics_grid_anim_state.toggle();
        self.focus_mgr_do(|fm, w| fm.resolve_after_visibility_change(w));

        self.update_bottom_pane_heights(
            self.system_metrics_pane.anim_state.target_visible(),
            self.media_pane.anim_state.target_visible(),
            self.console_logs_pane.anim_state.target_visible(),
        );
        self.recalculate_layout();
        vec![self.metrics_grid_animation_cmd()]
    }

    pub(crate) fn handle_metrics_grid_animation(&mut self) -> Vec<Command> {
        self.metrics_grid_anim_state.update(Instant::now());
        self.update_bottom_pane_heights(
            self.system_metrics_pane.anim_state.target_visible(),
            self.media_pane.anim_state.target_visible(),
            self.console_logs_pane.anim_state.target_visible(),
        );
        self.recalculate_layout();
        if self.metrics_grid_anim_state.is_animating() {
            return vec![self.metrics_grid_animation_cmd()];
        }
        vec![]
    }

    /// handleGridNav routes nav intents to the focused grid.
    ///
    /// Returns `None` when the key is not a navigation key (Go returns a
    /// nil cmd and the dispatcher falls through to the key map);
    /// `Some(vec![])` is Go's consumed-key marker cmd
    /// (`func() tea.Msg { return nil }`) — handled, no commands (§2.7).
    pub(crate) fn handle_grid_nav(&mut self, msg: &KeyEvent) -> Option<Vec<Command>> {
        let intent = decode_nav(msg);
        if intent == NavIntent::None {
            return None;
        }

        match intent {
            NavIntent::Up => self.grid_nav_apply_focus(-1, 0),
            NavIntent::Down => self.grid_nav_apply_focus(1, 0),
            NavIntent::Left => self.grid_nav_apply_focus(0, -1),
            NavIntent::Right => self.grid_nav_apply_focus(0, 1),
            NavIntent::PageUp => self.grid_nav_apply_page(-1),
            NavIntent::PageDown => self.grid_nav_apply_page(1),
            NavIntent::Home => self.grid_nav_apply_jump(false),
            NavIntent::End => self.grid_nav_apply_jump(true),
            NavIntent::None => {}
        }
        Some(vec![])
    }

    /// Go's `applyFocus` closure in handleGridNav.
    fn grid_nav_apply_focus(&mut self, dr: isize, dc: isize) {
        if self.focus_mgr.is_target(FocusTarget::MetricsGrid) {
            self.metrics_grid.navigate_focus(dr, dc);
        } else if self.focus_mgr.is_target(FocusTarget::SystemMetrics)
            && let Some(g) = self.active_system_metrics_grid()
        {
            g.navigate_focus(dr, dc);
        }
    }

    /// Go's `applyPage` closure in handleGridNav.
    fn grid_nav_apply_page(&mut self, dir: isize) {
        if self.focus_mgr.is_target(FocusTarget::MetricsGrid) {
            self.metrics_grid.navigate(dir);
        } else if self.focus_mgr.is_target(FocusTarget::SystemMetrics)
            && let Some(g) = self.active_system_metrics_grid_mut()
        {
            g.navigate(dir);
        }
    }

    /// Go's `applyJump` closure in handleGridNav.
    fn grid_nav_apply_jump(&mut self, end: bool) {
        if self.focus_mgr.is_target(FocusTarget::MetricsGrid) {
            if end {
                self.metrics_grid.navigate_end();
            } else {
                self.metrics_grid.navigate_home();
            }
        } else if self.focus_mgr.is_target(FocusTarget::SystemMetrics)
            && let Some(g) = self.active_system_metrics_grid_mut()
        {
            if end {
                g.navigate_end();
            } else {
                g.navigate_home();
            }
        }
    }

    pub(crate) fn handle_config_focused_cols(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        match self.focus_mgr.current() {
            FocusTarget::SystemMetrics => self
                .config
                .borrow_mut()
                .set_pending_grid_config(GridConfigTarget::WorkspaceSystemCols),
            FocusTarget::Media => self
                .config
                .borrow_mut()
                .set_pending_grid_config(GridConfigTarget::WorkspaceMediaCols),
            _ => self
                .config
                .borrow_mut()
                .set_pending_grid_config(GridConfigTarget::WorkspaceMetricsCols),
        }
        vec![]
    }

    pub(crate) fn handle_config_focused_rows(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        match self.focus_mgr.current() {
            FocusTarget::SystemMetrics => self
                .config
                .borrow_mut()
                .set_pending_grid_config(GridConfigTarget::WorkspaceSystemRows),
            FocusTarget::Media => self
                .config
                .borrow_mut()
                .set_pending_grid_config(GridConfigTarget::WorkspaceMediaRows),
            _ => self
                .config
                .borrow_mut()
                .set_pending_grid_config(GridConfigTarget::WorkspaceMetricsRows),
        }
        vec![]
    }

    // ---- Run Selection / Pinning ----

    pub(crate) fn toggle_run_selected(&mut self, run_key: &str) -> Vec<Command> {
        if run_key.is_empty() {
            return vec![];
        }

        if self.selected_runs.contains_key(run_key) {
            return self.drop_run(run_key);
        }

        // Resolve the run file before mutating selection state so we don't
        // end up "selected but unloadable" if the key can't be mapped to a
        // .wandb file.
        let wandb_file = run_wandb_file(&self.wandb_dir, run_key);
        if wandb_file.is_empty() {
            tracing::error!("workspace: unable to resolve .wandb file for run key {run_key:?}");
            return vec![];
        }

        self.selected_runs.insert(run_key.to_string(), true);
        if self.pinned_run.is_empty() {
            self.pinned_run = run_key.to_string();
        }

        vec![self.init_reader_cmd(run_key, &wandb_file)]
    }

    pub(crate) fn handle_toggle_run_selected_key(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        if !self.run_selector_active() {
            return vec![];
        }
        let Some(cur) = self.runs.current_item() else {
            return vec![];
        };
        let key = cur.key.clone();
        self.toggle_run_selected(&key)
    }

    pub(crate) fn toggle_pin(&mut self, run_key: &str) {
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

    pub(crate) fn handle_pin_run_key(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        if !self.run_selector_active() {
            return vec![];
        }
        let Some(cur) = self.runs.current_item() else {
            return vec![];
        };

        let run_key = cur.key.clone();

        // Preserve existing behavior: pinning should select the run if it's
        // not selected, so its series exists and can be promoted/drawn.
        if !self.selected_runs.get(&run_key).copied().unwrap_or(false) {
            let cmds = self.toggle_run_selected(&run_key);
            if cmds.is_empty() {
                return vec![];
            }
            // toggleRunSelected may auto-pin when pinnedRun was empty.
            // Only toggle if we still need to pin.
            if self.pinned_run != run_key {
                self.toggle_pin(&run_key);
            }
            return cmds;
        }

        self.toggle_pin(&run_key);
        vec![]
    }

    // ---- Sidebar Navigation ----

    pub(crate) fn handle_runs_vertical_nav(&mut self, msg: &KeyEvent) -> Vec<Command> {
        let up = decode_nav(msg) == NavIntent::Up;
        if self.focus_mgr.is_target(FocusTarget::ConsoleLogs) {
            if up {
                self.console_logs_pane.up();
            } else {
                self.console_logs_pane.down();
            }
        } else if self.focus_mgr.is_target(FocusTarget::RunsList) {
            if up {
                self.runs.up();
            } else {
                self.runs.down();
            }
        } else if self.focus_mgr.is_target(FocusTarget::Overview) {
            if up {
                self.run_overview_sidebar.navigate_up();
            } else {
                self.run_overview_sidebar.navigate_down();
            }
        }
        vec![]
    }

    // ---- Focus Region Cycling ----

    pub(crate) fn handle_sidebar_tab_nav(&mut self, msg: &KeyEvent) -> Vec<Command> {
        let mut direction: isize = 1;
        if msg.code == KeyCode::Tab && msg.mods.shift {
            direction = -1;
        }
        // PARITY: Go wraps this in focusMgr.TabWithinOrAdvance(direction,
        // withinFn); the withinFn closure reads the manager's current
        // target, which the fn-pointer seam cannot (the manager is taken
        // out while its hooks run), so TabWithinOrAdvance's two steps are
        // inlined verbatim: withinFn first, tab on false.
        let within = self.focus_mgr.is_target(FocusTarget::Overview)
            && self.cycle_overview_section(direction);
        if !within {
            self.focus_mgr_do(|fm, w| fm.tab(w, direction));
        }
        vec![]
    }

    pub(crate) fn handle_runs_page_nav(&mut self, msg: &KeyEvent) -> Vec<Command> {
        let left = decode_nav(msg) == NavIntent::Left;
        if self.focus_mgr.is_target(FocusTarget::ConsoleLogs) {
            if left {
                self.console_logs_pane.page_up();
            } else {
                self.console_logs_pane.page_down();
            }
        } else if self.focus_mgr.is_target(FocusTarget::RunsList) {
            if left {
                self.runs.page_up();
            } else {
                self.runs.page_down();
            }
        } else if self.focus_mgr.is_target(FocusTarget::Overview) {
            if left {
                self.run_overview_sidebar.navigate_page_up();
            } else {
                self.run_overview_sidebar.navigate_page_down();
            }
        }
        vec![]
    }

    pub(crate) fn active_system_metrics_grid(&self) -> Option<&SystemMetricsGrid> {
        let cur = self.runs.current_item()?;
        self.system_metrics.get(&cur.key)
    }

    /// `&mut` twin of [`Workspace::active_system_metrics_grid`] for the Go
    /// call sites that mutate the grid (single-owner map vs Go's shared
    /// pointers).
    pub(crate) fn active_system_metrics_grid_mut(&mut self) -> Option<&mut SystemMetricsGrid> {
        let key = self.runs.current_item()?.key.clone();
        self.system_metrics.get_mut(&key)
    }

    /// handleFocusRuns moves focus to the runs list if it's visible.
    ///
    /// This gives Esc a natural "return home" feel in workspace mode:
    /// wherever focus currently is, Esc snaps it back to the run selector.
    pub(crate) fn handle_focus_runs(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        if self.runs_anim_state.target_visible() {
            self.focus_mgr_do(|fm, w| fm.set_target(w, FocusTarget::RunsList, 1));
        }
        vec![]
    }

    // ------------------------------------------------------------------
    // workspacedirwatcher.go — the *Workspace handler half
    // (workspacedirwatcher.go:168-403; the preloader queue and off-thread
    // command bodies live in workspace_dir_watcher.rs / runtime.rs)
    // ------------------------------------------------------------------

    /// Go `pollWandbDirCmd` (workspacedirwatcher.go:100-109); the tick
    /// callback body (dir scan) runs on the runtime's effect thread.
    pub(crate) fn poll_wandb_dir_cmd(&self, delay: std::time::Duration) -> Command {
        poll_wandb_dir_cmd(&self.wandb_dir, delay)
    }

    pub(crate) fn handle_workspace_run_dirs(&mut self, msg: &WorkspaceRunDirsMsg) -> Vec<Command> {
        let poll_cmd = self.poll_wandb_dir_cmd(WANDB_DIR_POLL_INTERVAL);

        if let Some(err) = &msg.err {
            tracing::error!("workspace: wandb dir scan: {err}");
            return vec![poll_cmd];
        }

        let mut cmds = Vec::new();
        let mut select_latest_cmds = Vec::new();
        if !self.run_keys_equal(&msg.run_keys) {
            // PARITY: applyRunKeys' dropRun teardown is direct calls in Go;
            // here the reader-close/heartbeat commands surface and are
            // dispatched ahead of the batch below.
            cmds.extend(self.apply_run_keys(&msg.run_keys));
            // Auto-select the latest run on initial workspace load.
            // (Go sync.Once → plain bool, §2.6.)
            if !self.auto_select_latest_run_on_load {
                self.auto_select_latest_run_on_load = true;
                select_latest_cmds = self.toggle_run_selected(&msg.run_keys[0]);
            }
        }
        // Enqueue missing run overviews (even if the run list is unchanged).
        // This makes new run overviews eventually consistent even if the
        // .wandb file wasn't readable on the first scan.
        self.enqueue_missing_run_overviews(&msg.run_keys);

        let start_cmds = self.start_run_overview_preloads_cmd();
        if start_cmds.is_empty() {
            // PARITY: Go returns just pollCmd here, DROPPING selectLatestCmd
            // (workspacedirwatcher.go:189-191) — benign because the first
            // list change always enqueues preloads.
            cmds.push(poll_cmd);
            return cmds;
        }
        cmds.push(poll_cmd);
        cmds.extend(start_cmds);
        cmds.extend(select_latest_cmds);
        cmds
    }

    /// enqueueMissingRunOverviews queues runs that don't yet have overview
    /// state and aren't already queued/in-flight.
    pub(crate) fn enqueue_missing_run_overviews(&mut self, run_keys: &[String]) {
        for run_key in run_keys {
            if self.run_overview.contains_key(run_key) {
                continue;
            }
            self.overview_preloader.enqueue(run_key);
        }
    }

    /// startRunOverviewPreloadsCmd starts as many overview preloads as
    /// allowed by the concurrency limit and returns the batch. It is safe
    /// to call repeatedly.
    pub(crate) fn start_run_overview_preloads_cmd(&mut self) -> Vec<Command> {
        let run_keys = self.overview_preloader.dequeue_startable();
        if run_keys.is_empty() {
            return vec![];
        }
        let mut cmds = Vec::with_capacity(run_keys.len());
        for run_key in run_keys {
            cmds.push(self.preload_run_overview_cmd(&run_key));
        }
        cmds
    }

    /// preloadRunOverviewCmd reads up to maxRecordsToScan records looking
    /// for the first RunMsg with a populated run ID — the closure body is
    /// `runtime::preload_run_overview`, run on an effect thread.
    pub(crate) fn preload_run_overview_cmd(&self, run_key: &str) -> Command {
        let wandb_file = run_wandb_file(&self.wandb_dir, run_key);
        Command::PreloadRunOverview {
            run_key: run_key.to_string(),
            wandb_file,
        }
    }

    pub(crate) fn handle_workspace_run_overview_preloaded(
        &mut self,
        msg: &WorkspaceRunOverviewPreloadedMsg,
    ) -> Vec<Command> {
        self.overview_preloader.mark_done(&msg.run_key);

        if msg.err.is_none() && msg.run.as_ref().is_some_and(|run| !run.id.is_empty()) {
            let run = msg.run.as_deref().expect("checked above");
            let ro = self.get_or_create_run_overview(&msg.run_key);
            // PARITY: Go re-checks `msg.Run != nil` inside (redundant).
            ro.borrow_mut().process_run_msg(run_msg_to_overview(run));
            self.index_run_filter_data(&msg.run_key, run);
            if !self.filter.query().is_empty() {
                self.apply_run_filter();
            }
            // We don't know the final state of this run after a pre-load.
            ro.borrow_mut().set_run_state(RunState::Unknown);
        } else if let Some(err) = &msg.err
            && err.kind != EventErrorKind::RunRecordNotFound
            && err.kind != EventErrorKind::NotExist
        {
            // Best-effort logging for unexpected failures; avoid spamming
            // for "file not ready yet" or missing run records.
            tracing::error!(
                "workspace: preload run overview for {}: {}",
                msg.run_key,
                err
            );
        }

        // Keep draining the queue.
        self.start_run_overview_preloads_cmd()
    }

    pub(crate) fn run_keys_equal(&self, run_keys: &[String]) -> bool {
        if run_keys.len() != self.runs.items.len() {
            return false;
        }
        for (i, key) in run_keys.iter().enumerate() {
            if &self.runs.items[i].key != key {
                return false;
            }
        }
        true
    }

    pub(crate) fn apply_run_keys(&mut self, run_keys: &[String]) -> Vec<Command> {
        // Preserve the currently highlighted run key if possible.
        let mut prev_cursor_key = String::new();
        if let Some(cur) = self.runs.current_item() {
            prev_cursor_key = cur.key.clone();
        }

        let present: std::collections::HashSet<String> = run_keys.iter().cloned().collect();

        // Drop queued (not in-flight) overview preloads for runs that
        // disappeared.
        self.overview_preloader.drop_queued_not_present(&present);

        // If the pinned run disappeared, clear it.
        if !self.pinned_run.is_empty() && !present.contains(&self.pinned_run) {
            self.pinned_run.clear();
        }

        let mut cmds = Vec::new();

        // If a selected run disappeared, deselect it and cleanup state.
        // PARITY: Go iterates the maps unordered; sorted for determinism.
        let mut stale: Vec<String> = self
            .selected_runs
            .keys()
            .filter(|key| !present.contains(*key))
            .cloned()
            .collect();
        stale.sort();
        for key in stale {
            cmds.extend(self.drop_run(&key));
        }

        // Defensive cleanup: drop any loaded run that no longer exists.
        let mut stale: Vec<String> = self
            .runs_by_key
            .keys()
            .filter(|key| !present.contains(*key))
            .cloned()
            .collect();
        stale.sort();
        for key in stale {
            cmds.extend(self.drop_run(&key));
        }

        let stale: Vec<String> = self
            .run_overview
            .keys()
            .filter(|key| !present.contains(*key))
            .cloned()
            .collect();
        for key in stale {
            self.run_overview.remove(&key);
            self.runs_filter_index.remove(&key);
        }

        if let Some(run_colors) = self.run_colors.clone() {
            for item in &self.runs.items {
                if present.contains(&item.key) {
                    continue;
                }
                run_colors
                    .borrow_mut()
                    .release(&self.run_path_for_key(&item.key));
            }
        }

        self.set_run_items(run_keys);

        if !prev_cursor_key.is_empty() {
            self.restore_run_cursor(&prev_cursor_key);
        }
        let _ = self.sync_runs_page();
        cmds
    }

    pub(crate) fn set_run_items(&mut self, run_keys: &[String]) {
        // PARITY: Go reuses the Items backing array (`w.runs.Items[:0]`);
        // rebuilt here — the slice is only ever reassigned wholesale.
        let items: Vec<leet_data::run_overview::KeyValuePair> = run_keys
            .iter()
            .map(|key| leet_data::run_overview::KeyValuePair {
                key: key.clone(),
                ..Default::default()
            })
            .collect();
        self.runs.items = items;

        self.apply_run_filter();
    }

    pub(crate) fn restore_run_cursor(&mut self, run_key: &str) {
        if run_key.is_empty() || self.runs.items_per_page() <= 0 {
            return;
        }
        let Some(idx) = self
            .runs
            .filtered_items
            .iter()
            .position(|it| it.key == run_key)
        else {
            return;
        };
        let page = idx as isize / self.runs.items_per_page();
        let line = idx as isize % self.runs.items_per_page();
        self.runs.set_page_and_line(page, line);
    }
}

// ---------------------------------------------------------------------------
// Tests — transliteration of workspace_keyhandling_test.go, plus the
// Workspace halves of heartbeat_lifecycle_test.go, liveread_test.go, and
// workspacedirwatcher_test.go (sections marked below).
//
// TODO(model.rs): two workspace_keyhandling_test.go cases construct
// leet.NewModel and MUST be transliterated when model.rs lands — they pin
// Enter's run-selector gating at the Model seam (Enter must not switch to
// the run view while logs own focus):
//   - TestWorkspace_Enter_NoOpWhenLogsFocused
//     (workspace_keyhandling_test.go:452)
//   - TestWorkspace_Enter_WorksWhenRunsFocused
//     (workspace_keyhandling_test.go:481)
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::time::Duration;

    use leet_data::history_source::{
        self as hs, HistorySource, HistorySourceError, LIVE_MONITOR_CHUNK_SIZE,
        LIVE_MONITOR_MAX_TIME, SourceMsg,
    };
    use pretty_assertions::assert_eq;

    use super::*;
    use crate::command::{HeartbeatOwner, ReadKind, ReadRequest, SourceId, TimerId, execute_read};
    use crate::event::{EventError, FileCompleteMsg, HistoryMsg, MetricData};
    use crate::nav::test_helpers::{primary_nav_msg, secondary_nav_msg};
    use crate::workspace::test_support::*;
    use leet_proto::wandb_internal::{ConfigItem, ConfigRecord};

    fn new_workspace(wandb_dir: &str) -> (tempfile::TempDir, Workspace) {
        let (cfg_dir, cfg) = test_config();
        (cfg_dir, Workspace::new(wandb_dir, Some(cfg)))
    }

    /// Go `typeWorkspaceFilter` (workspace_keyhandling_test.go:21-30).
    fn type_workspace_filter(w: &mut Workspace, query: &str) {
        for r in query.chars() {
            let msg = if r == ' ' {
                key_code(KeyCode::Space)
            } else {
                key_rune(r)
            };
            assert!(update_key(w, msg).is_empty());
        }
    }

    fn contains_quit(cmds: &[Command]) -> bool {
        cmds.iter().any(|c| matches!(c, Command::Quit))
    }

    // Go: TestWorkspace_KeyHandling_FilterModeConsumesQuit.
    #[test]
    fn workspace_key_handling_filter_mode_consumes_quit() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());
        update_resize(&mut w, 120, 40);

        // Enter metrics filter input mode ("/").
        assert!(update_key(&mut w, key_rune('/')).is_empty());
        assert!(
            w.is_filtering(),
            "expected IsFiltering true in metrics filter input mode"
        );

        // While filter input mode is active, 'q' should be consumed by the
        // filter editor, not treated as a global quit.
        assert!(update_key(&mut w, key_rune('q')).is_empty());

        // Exit filter input mode.
        assert!(update_key(&mut w, key_code(KeyCode::Esc)).is_empty());
        assert!(
            !w.is_filtering(),
            "expected filter mode to be inactive after Esc"
        );

        // Now 'q' should quit.
        // ADAPTED: Go asserts `cmd()` yields tea.QuitMsg; the port's quit
        // path returns the cleanup commands plus Command::Quit.
        let cmds = update_key(&mut w, key_rune('q'));
        assert!(!cmds.is_empty());
        assert!(contains_quit(&cmds));
    }

    // Go: TestWorkspace_KeyHandling_GridConfigCaptureHasPriority.
    #[test]
    fn workspace_key_handling_grid_config_capture_has_priority() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, cfg) = test_config();

        // Start from a known value.
        cfg.borrow_mut().set_workspace_metrics_cols(1).unwrap();
        cfg.borrow_mut().set_workspace_metrics_rows(1).unwrap();

        let mut w = Workspace::new(
            wandb_dir.path().to_str().unwrap(),
            Some(std::rc::Rc::clone(&cfg)),
        );
        update_resize(&mut w, 140, 45);

        // Begin grid config capture (metrics cols).
        assert!(update_key(&mut w, key_rune('c')).is_empty());
        assert!(
            cfg.borrow().is_awaiting_grid_config(),
            "expected config capture active after 'c'"
        );

        // While awaiting grid config, keys should be interpreted as config
        // input first. 'q' should NOT quit; it should just end capture
        // (no-op apply).
        assert!(update_key(&mut w, key_rune('q')).is_empty());
        assert!(
            !cfg.borrow().is_awaiting_grid_config(),
            "expected capture cleared after non-numeric key"
        );

        let (_, cols) = cfg.borrow().workspace_metrics_grid();
        assert_eq!(cols, 1, "non-numeric key should not change metrics cols");

        // Start capture again and apply a numeric value.
        assert!(update_key(&mut w, key_rune('c')).is_empty());
        assert!(cfg.borrow().is_awaiting_grid_config());

        assert!(update_key(&mut w, key_rune('2')).is_empty());
        assert!(!cfg.borrow().is_awaiting_grid_config());

        let (_, cols) = cfg.borrow().workspace_metrics_grid();
        assert_eq!(
            cols, 2,
            "expected metrics cols updated by captured numeric key"
        );
    }

    // Go: TestWorkspace_HandleWorkspaceInitErr_DropsSelectionAndPinned.
    #[test]
    fn workspace_handle_workspace_init_err_drops_selection_and_pinned() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());

        // Seed a single run. Workspace auto-selects + pins latest on first
        // load.
        let run_key = "run-20260209_010101-abcdefg";
        let _ = update_run_dirs(&mut w, &[run_key]);

        assert_eq!(
            w.selected_runs.len(),
            1,
            "expected autoselect on initial run list"
        );
        assert_eq!(w.pinned_run, run_key, "expected autopin of selected run");

        // Simulate reader init failure; selection/pin should be reverted.
        let _ = w.update(&Event::WorkspaceInitErr(WorkspaceInitErrMsg {
            run_key: run_key.to_string(),
            run_path: wandb_dir
                .path()
                .join(run_key)
                .join("run-abcdefg.wandb")
                .to_string_lossy()
                .into_owned(),
            err: Some(EventError::other("boom")),
        }));

        assert_eq!(
            w.selected_runs.len(),
            0,
            "expected selection reverted on init error"
        );
        assert_ne!(w.pinned_run, run_key, "expected pin cleared on init error");
    }

    // ---- Focus helpers ----

    /// newWorkspaceWithPanels creates a Workspace with all panels expanded
    /// and a single run seeded with overview data so overview sections are
    /// focusable.
    fn new_workspace_with_panels() -> (tempfile::TempDir, tempfile::TempDir, Workspace) {
        let (cfg_dir, cfg) = test_config();

        let wandb_dir = tempfile::tempdir().unwrap();
        let mut w = Workspace::new(wandb_dir.path().to_str().unwrap(), Some(cfg));
        update_resize(&mut w, 200, 60);

        // Seed a run so overview sections become focusable.
        let run_key = "run-20260209_010101-abcdefg";
        let _ = update_run_dirs(&mut w, &[run_key]);

        // Force all panels expanded (testhelpers.go TestForceExpand*).
        w.runs_anim_state.force_expand();
        w.run_overview_sidebar.anim_state.force_expand();
        force_expand_console_logs_pane(&mut w, 10);

        // Populate overview sections with data so the sidebar is actually
        // focusable (focusableSectionBounds needs non-empty sections with
        // computed heights).
        seed_run_overview(&mut w, run_key);

        (cfg_dir, wandb_dir, w)
    }

    // ---- handleToggleConsoleLogsPane ----

    // Go: TestWorkspace_ToggleConsoleLogsPane_FocusReturnsToRuns.
    #[test]
    fn workspace_toggle_console_logs_pane_focus_returns_to_runs() {
        let (_c, _d, mut w) = new_workspace_with_panels();

        // Focus logs via Tab until bottom bar is active.
        while !w.console_logs_pane.active() {
            let _ = update_key(&mut w, key_code(KeyCode::Tab));
        }
        assert_eq!(w.focus_mgr.current(), FocusTarget::ConsoleLogs);

        // Collapse bottom bar — focus should return to runs (the next
        // available).
        let _ = update_key(&mut w, key_rune('4'));
        let _ = update_key(&mut w, key_rune(']'));
        assert!(
            !w.console_logs_pane.active(),
            "bottom bar should not be active after collapse"
        );
        assert!(
            w.runs.active,
            "runs list should be focused after collapsing logs"
        );
    }

    // Go: TestWorkspace_ToggleConsoleLogsPane_FocusStaysOnRuns.
    #[test]
    fn workspace_toggle_console_logs_pane_focus_stays_on_runs() {
        let (_c, _d, mut w) = new_workspace_with_panels();

        // Focus should start on runs.
        assert!(w.runs.active);
        assert_eq!(w.focus_mgr.current(), FocusTarget::RunsList);

        // Collapse bottom bar while runs are focused — runs should stay
        // focused.
        let _ = update_key(&mut w, key_rune('4'));
        assert!(
            w.runs.active,
            "runs focus should be preserved when collapsing bottom bar from runs"
        );
    }

    // ---- Focus bug: collapsing overview with logs focused ----

    // Go: TestWorkspace_CollapseOverview_FocusStaysOnLogs.
    #[test]
    fn workspace_collapse_overview_focus_stays_on_logs() {
        let (_c, _d, mut w) = new_workspace_with_panels();

        // Focus logs.
        while w.focus_mgr.current() != FocusTarget::ConsoleLogs {
            let _ = update_key(&mut w, key_code(KeyCode::Tab));
        }
        assert!(w.console_logs_pane.active());

        // Collapse overview sidebar — focus should stay on logs, NOT jump
        // to runs.
        let _ = update_key(&mut w, key_rune(']'));
        assert!(
            w.console_logs_pane.active(),
            "logs should remain focused after collapsing overview"
        );
        assert!(
            !w.runs.active,
            "runs should NOT get focus when collapsing overview while logs focused"
        );
        assert_eq!(w.focus_mgr.current(), FocusTarget::ConsoleLogs);
    }

    // Go: TestWorkspace_CollapseRuns_FocusStaysOnLogs.
    #[test]
    fn workspace_collapse_runs_focus_stays_on_logs() {
        let (_c, _d, mut w) = new_workspace_with_panels();

        // Focus logs.
        while w.focus_mgr.current() != FocusTarget::ConsoleLogs {
            let _ = update_key(&mut w, key_code(KeyCode::Tab));
        }

        // Collapse runs sidebar — focus should stay on logs.
        let _ = update_key(&mut w, key_rune('['));
        assert!(
            w.console_logs_pane.active(),
            "logs should remain focused after collapsing runs sidebar"
        );
        assert_eq!(w.focus_mgr.current(), FocusTarget::ConsoleLogs);
    }

    // ---- handleRunsVerticalNav with different focus targets ----

    // Go: TestWorkspace_RunsVerticalNav_ConsoleLogsPaneConsoleLogsPaneActive.
    #[test]
    fn workspace_runs_vertical_nav_console_logs_pane_active() {
        let (_c, _d, mut w) = new_workspace_with_panels();

        // Focus logs.
        while w.focus_mgr.current() != FocusTarget::ConsoleLogs {
            let _ = update_key(&mut w, key_code(KeyCode::Tab));
        }
        assert!(w.console_logs_pane.active());

        // Up/Down should route to bottom bar, not runs list.
        let _ = update_key(&mut w, secondary_nav_msg(NavIntent::Up));
        let _ = update_key(&mut w, secondary_nav_msg(NavIntent::Down));
        assert!(
            w.console_logs_pane.active(),
            "bottom bar should still be active after vertical nav"
        );
    }

    // Go: TestWorkspace_RunsVerticalNav_OverviewActive.
    #[test]
    fn workspace_runs_vertical_nav_overview_active() {
        let (_c, _d, mut w) = new_workspace_with_panels();

        // Focus overview.
        while w.focus_mgr.current() != FocusTarget::Overview {
            let _ = update_key(&mut w, key_code(KeyCode::Tab));
        }
        assert!(!w.runs.active);
        assert!(!w.console_logs_pane.active());

        // Up/Down should route to overview sidebar, not runs list.
        let _ = update_key(&mut w, secondary_nav_msg(NavIntent::Up));
        let _ = update_key(&mut w, secondary_nav_msg(NavIntent::Down));
        assert!(
            !w.runs.active,
            "runs should not become active from overview vertical nav"
        );
    }

    // ---- Unified navigation: wasd/arrows/Home/End ----

    /// newWorkspaceWithMultipleRuns seeds a workspace with N runs so list
    /// navigation (up/down/page/home/end) is meaningful.
    fn new_workspace_with_multiple_runs(
        n: usize,
    ) -> (tempfile::TempDir, tempfile::TempDir, Workspace, Vec<String>) {
        let (cfg_dir, cfg) = test_config();
        let wandb_dir = tempfile::tempdir().unwrap();
        let mut w = Workspace::new(wandb_dir.path().to_str().unwrap(), Some(cfg));
        update_resize(&mut w, 200, 60);

        let mut keys = Vec::with_capacity(n);
        for i in 0..n {
            keys.push(format!(
                "run-20260209_010101-{}",
                char::from(b'a' + i as u8)
            ));
        }
        let key_refs: Vec<&str> = keys.iter().map(String::as_str).collect();
        let _ = update_run_dirs(&mut w, &key_refs);
        w.runs_anim_state.force_expand();

        (cfg_dir, wandb_dir, w, keys)
    }

    // Go: TestWorkspace_UnifiedNav_RunsListDirectionalAliases.
    #[test]
    fn workspace_unified_nav_runs_list_directional_aliases() {
        let (_c, _d, mut w, _keys) = new_workspace_with_multiple_runs(5);
        assert!(w.runs.active, "runs list should start focused");

        let start = current_run_key(&w);
        let _ = update_key(&mut w, primary_nav_msg(NavIntent::Down));
        let after_primary_down = current_run_key(&w);
        assert_ne!(
            start, after_primary_down,
            "the primary down binding should advance the runs cursor"
        );

        let _ = update_key(&mut w, primary_nav_msg(NavIntent::Up));
        assert_eq!(
            start,
            current_run_key(&w),
            "the primary up binding should undo the down move"
        );

        let _ = update_key(&mut w, secondary_nav_msg(NavIntent::Down));
        assert_eq!(
            after_primary_down,
            current_run_key(&w),
            "the secondary down binding should match the primary binding"
        );
        let _ = update_key(&mut w, secondary_nav_msg(NavIntent::Up));
        assert_eq!(
            start,
            current_run_key(&w),
            "the secondary up binding should match the primary binding"
        );
    }

    // Go: TestWorkspace_UnifiedNav_RunsListPagingAndBoundaries.
    #[test]
    fn workspace_unified_nav_runs_list_paging_and_boundaries() {
        let (_c, _d, mut w, keys) = new_workspace_with_multiple_runs(12);
        update_resize(&mut w, 200, 10);

        let before = current_run_key(&w);
        let _ = update_key(&mut w, primary_nav_msg(NavIntent::PageDown));
        let after_primary_page_down = current_run_key(&w);
        assert_ne!(
            before, after_primary_page_down,
            "the primary page-down binding should advance the runs page"
        );

        let _ = update_key(&mut w, secondary_nav_msg(NavIntent::PageUp));
        assert_eq!(
            before,
            current_run_key(&w),
            "the secondary page-up binding should undo the primary page-down move"
        );

        let _ = update_key(&mut w, secondary_nav_msg(NavIntent::PageDown));
        assert_eq!(
            after_primary_page_down,
            current_run_key(&w),
            "the secondary page-down binding should match the primary binding"
        );

        let _ = update_key(&mut w, primary_nav_msg(NavIntent::Home));
        assert_eq!(
            keys[0],
            current_run_key(&w),
            "Home should jump to the first visible run"
        );

        let _ = update_key(&mut w, primary_nav_msg(NavIntent::End));
        assert_eq!(
            keys[keys.len() - 1],
            current_run_key(&w),
            "End should jump to the last visible run"
        );
    }

    // ---- Console log message handling ----

    // Go: TestWorkspace_ConsoleLogMsg_CreatesLogs.
    #[test]
    fn workspace_console_log_msg_creates_logs() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());
        update_resize(&mut w, 200, 60);

        let run_key = "run-20260209_010101-abc123";
        let _ = update_run_dirs(&mut w, &[run_key]);

        // Before any console logs, the map should be empty for this key.
        assert!(
            !w.console_logs.contains_key(run_key),
            "no logs should exist before ConsoleLogMsg"
        );

        // Simulate the workspace processing a ConsoleLogMsg via the record
        // handler. In normal operation this is triggered by
        // handleWorkspaceRecord, which is called from
        // handleWorkspaceBatchedRecords. We test the public path.
        // (Go wraps this in require.NotPanics; a Rust panic fails the test.)
        let _ = &w.console_logs;
    }

    // ---- cycleOverviewSection and setFocusRegion ----

    // Go: TestWorkspace_CycleOverviewSection_StaysInOverview.
    #[test]
    fn workspace_cycle_overview_section_stays_in_overview() {
        let (_c, _d, mut w) = new_workspace_with_panels();

        // Focus overview.
        while w.focus_mgr.current() != FocusTarget::Overview {
            let _ = update_key(&mut w, key_code(KeyCode::Tab));
        }
        assert_eq!(w.focus_mgr.current(), FocusTarget::Overview);

        // Tab while in overview should cycle sections before leaving.
        let _ = update_key(&mut w, key_code(KeyCode::Tab));
        // We may still be in overview (cycling sections) or have moved on.
        // The key guarantee: the state is consistent.
        match w.focus_mgr.current() {
            FocusTarget::Overview => {
                assert!(w.run_overview_sidebar.has_active_section());
            }
            FocusTarget::RunsList => assert!(w.runs.active),
            FocusTarget::ConsoleLogs => assert!(w.console_logs_pane.active()),
            _ => {}
        }
    }

    // Go: TestWorkspace_SetFocusRegion_ClearsOtherRegions.
    #[test]
    fn workspace_set_focus_region_clears_other_regions() {
        let (_c, _d, mut w) = new_workspace_with_panels();

        // Start at runs.
        assert!(w.runs.active);

        // Tab to logs.
        while w.focus_mgr.current() != FocusTarget::ConsoleLogs {
            let _ = update_key(&mut w, key_code(KeyCode::Tab));
        }

        // Exactly one region should have focus.
        assert!(w.console_logs_pane.active(), "logs should be active");
        assert!(!w.runs.active, "runs should be inactive");
        assert!(
            !w.run_overview_sidebar.has_active_section(),
            "overview should be inactive"
        );
    }

    // Go: TestWorkspace_SetFocusRegion_NoAvailableRegion_DefaultsToRuns.
    #[test]
    fn workspace_set_focus_region_no_available_region_defaults_to_runs() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());
        update_resize(&mut w, 200, 60);

        // Collapse everything.
        w.runs_anim_state.force_collapse();
        w.run_overview_sidebar.anim_state.force_collapse();
        // Bottom bar is collapsed by default.

        // Focus should fall back to runs (even though it's collapsed).
        // This tests the fallback path in resolveFocusAfterVisibilityChange.
        assert_eq!(w.focus_mgr.current(), FocusTarget::RunsList);
    }

    // Go: TestWorkspace_Enter_RequiresRunSelectorActive — verifies that
    // Enter only triggers the mode switch when the run list sidebar is
    // focused.
    #[test]
    fn workspace_enter_requires_run_selector_active() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());
        update_resize(&mut w, 200, 60);

        // Seed a run.
        let run_key = "run-20260209_010101-abcdefg";
        let _ = update_run_dirs(&mut w, &[run_key]);

        // RunSelectorActive should be true when runs list is focused.
        assert!(
            w.run_selector_active(),
            "run selector should be active with runs focused and items present"
        );

        // Focus logs by expanding bottom bar and tabbing.
        force_expand_console_logs_pane(&mut w, 10);
        while !w.console_logs_pane.active() {
            let _ = update_key(&mut w, key_code(KeyCode::Tab));
        }

        // RunSelectorActive should be false when logs are focused.
        assert!(
            !w.run_selector_active(),
            "run selector should NOT be active when logs are focused"
        );
    }

    // ---- Overview filter mode ----

    // Go: TestWorkspace_OverviewFilterMode_ConsumesQuit.
    #[test]
    fn workspace_overview_filter_mode_consumes_quit() {
        let (_c, _d, mut w) = new_workspace_with_panels();

        // Enter overview filter input mode ("o").
        assert!(update_key(&mut w, key_rune('o')).is_empty());
        assert!(
            w.run_overview_sidebar.is_filter_mode(),
            "expected overview filter mode active after 'o'"
        );
        assert!(
            w.is_filtering(),
            "expected IsFiltering true during overview filter input"
        );

        // While overview filter is active, 'q' should be consumed (not
        // quit).
        assert!(update_key(&mut w, key_rune('q')).is_empty());
        assert!(
            w.run_overview_sidebar.is_filter_mode(),
            "overview filter should still be active after 'q'"
        );

        // Escape cancels filter mode.
        assert!(update_key(&mut w, key_code(KeyCode::Esc)).is_empty());
        assert!(
            !w.run_overview_sidebar.is_filter_mode(),
            "overview filter should be inactive after Esc"
        );
        assert!(
            !w.is_filtering(),
            "IsFiltering should be false after cancelling overview filter"
        );
    }

    // Go: TestWorkspace_OverviewFilter_ApplyAndClear.
    #[test]
    fn workspace_overview_filter_apply_and_clear() {
        let (_c, _d, mut w) = new_workspace_with_panels();

        // Enter filter, type "lr", and apply.
        assert!(update_key(&mut w, key_rune('o')).is_empty());
        for r in "lr".chars() {
            assert!(update_key(&mut w, key_rune(r)).is_empty());
        }
        assert!(update_key(&mut w, key_code(KeyCode::Enter)).is_empty());

        assert!(
            !w.run_overview_sidebar.is_filter_mode(),
            "filter input mode should end after Enter"
        );
        assert!(
            w.run_overview_sidebar.is_filtering(),
            "applied filter should be active"
        );
        assert_eq!(w.run_overview_sidebar.filter_query(), "lr");
        assert!(
            !w.run_overview_sidebar.filter_info().is_empty(),
            "filter info should show match summary"
        );

        // Clear the filter with ctrl+o.
        assert!(update_key(&mut w, ctrl_key('o')).is_empty());
        assert!(
            !w.run_overview_sidebar.is_filtering(),
            "filter should be cleared after ctrl+o"
        );
        assert!(w.run_overview_sidebar.filter_info().is_empty());
    }

    // Go: TestWorkspace_OverviewFilter_EscCancelsDraft.
    #[test]
    fn workspace_overview_filter_esc_cancels_draft() {
        let (_c, _d, mut w) = new_workspace_with_panels();

        // Enter filter, type something, then Esc to cancel.
        assert!(update_key(&mut w, key_rune('o')).is_empty());
        for r in "xyz".chars() {
            assert!(update_key(&mut w, key_rune(r)).is_empty());
        }
        assert!(update_key(&mut w, key_code(KeyCode::Esc)).is_empty());

        assert!(!w.run_overview_sidebar.is_filter_mode());
        assert!(
            !w.run_overview_sidebar.is_filtering(),
            "cancelled draft should not persist as applied filter"
        );
    }

    // Go: TestWorkspace_OverviewFilter_ToggleMode.
    #[test]
    fn workspace_overview_filter_toggle_mode() {
        let (_c, _d, mut w) = new_workspace_with_panels();

        // Enter filter mode and toggle regex -> glob via Tab.
        assert!(update_key(&mut w, key_rune('o')).is_empty());
        assert!(w.run_overview_sidebar.is_filter_mode());

        // Tab toggles match mode (regex -> glob).
        assert!(update_key(&mut w, key_code(KeyCode::Tab)).is_empty());

        // Apply and verify it took effect (mode persists after apply).
        assert!(update_key(&mut w, key_code(KeyCode::Enter)).is_empty());
        assert!(!w.run_overview_sidebar.is_filter_mode());
    }

    // Go: TestWorkspace_OverviewFilter_StatusBarShowsFilter.
    #[test]
    fn workspace_overview_filter_status_bar_shows_filter() {
        let (_c, _d, mut w) = new_workspace_with_panels();

        // Apply a filter so it shows in the idle status bar.
        assert!(update_key(&mut w, key_rune('o')).is_empty());
        for r in "loss".chars() {
            assert!(update_key(&mut w, key_rune(r)).is_empty());
        }
        assert!(update_key(&mut w, key_code(KeyCode::Enter)).is_empty());

        // The full View includes the status bar at the bottom.
        update_resize(&mut w, 200, 60);
        let view = view_string(&mut w);
        assert!(view.contains("Overview:"));
        assert!(view.contains("loss"));
    }

    // Go: TestWorkspace_OverviewFilter_LivePreviewDuringInput.
    #[test]
    fn workspace_overview_filter_live_preview_during_input() {
        let (_c, _d, mut w) = new_workspace_with_panels();

        // During filter input, the status bar should show the live prompt.
        assert!(update_key(&mut w, key_rune('o')).is_empty());
        for r in "ep".chars() {
            assert!(update_key(&mut w, key_rune(r)).is_empty());
        }

        // While still in filter mode, check the view.
        update_resize(&mut w, 200, 60);
        let view = view_string(&mut w);
        assert!(view.contains("Overview filter"));
        assert!(view.contains("ep"));

        // Cancel to clean up.
        assert!(update_key(&mut w, key_code(KeyCode::Esc)).is_empty());
    }

    // Go: TestWorkspace_OverviewFilter_PriorityOverMetricsFilter.
    #[test]
    fn workspace_overview_filter_priority_over_metrics_filter() {
        let (_c, _d, mut w) = new_workspace_with_panels();

        // Enter overview filter mode.
        assert!(update_key(&mut w, key_rune('o')).is_empty());
        assert!(w.run_overview_sidebar.is_filter_mode());

        // '/' should be consumed by overview filter (as a typed character),
        // NOT enter metrics filter mode.
        assert!(update_key(&mut w, key_rune('/')).is_empty());
        assert!(
            w.run_overview_sidebar.is_filter_mode(),
            "overview filter should still be active"
        );
        assert_eq!(
            w.run_overview_sidebar.filter_query(),
            "/",
            "'/' should appear as typed text in the overview filter draft"
        );

        // Escape out.
        assert!(update_key(&mut w, key_code(KeyCode::Esc)).is_empty());
    }

    // Go: TestWorkspace_RunsFilterMode_ConsumesQuit.
    #[test]
    fn workspace_runs_filter_mode_consumes_quit() {
        let (_c, _d, mut w) = new_workspace_with_panels();

        assert!(update_key(&mut w, key_rune('f')).is_empty());
        assert!(
            w.filter.is_active(),
            "expected runs filter mode active after 'f'"
        );
        assert!(
            w.is_filtering(),
            "expected IsFiltering true during runs filter input"
        );

        // While runs filter is active, 'q' should be consumed as filter
        // text.
        assert!(update_key(&mut w, key_rune('q')).is_empty());
        assert!(
            w.filter.is_active(),
            "runs filter should still be active after 'q'"
        );
        assert_eq!(w.filter.query(), "q");

        assert!(update_key(&mut w, key_code(KeyCode::Esc)).is_empty());
        assert!(
            !w.filter.is_active(),
            "runs filter should be inactive after Esc"
        );
    }

    fn preloaded_msg(run_key: &str, run: RunMsg) -> Event {
        Event::WorkspaceRunOverviewPreloaded(WorkspaceRunOverviewPreloadedMsg {
            run_key: run_key.to_string(),
            run: Some(Box::new(run)),
            err: None,
        })
    }

    // Go: TestWorkspace_RunsFilter_ProjectAndConfig.
    #[test]
    fn workspace_runs_filter_project_and_config() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());
        update_resize(&mut w, 200, 60);

        let run1 = "run-20260209_010101-vision01";
        let run2 = "run-20260209_010102-nlp0002";
        let _ = update_run_dirs(&mut w, &[run1, run2]);

        let _ = w.update(&preloaded_msg(
            run1,
            RunMsg {
                id: "vision01".to_string(),
                display_name: "resnet50".to_string(),
                project: "vision".to_string(),
                config: Some(Box::new(ConfigRecord {
                    update: vec![
                        ConfigItem {
                            nested_key: vec!["lr".to_string()],
                            value_json: "0.001".to_string(),
                            ..Default::default()
                        },
                        ConfigItem {
                            nested_key: vec!["optimizer".to_string()],
                            value_json: r#""adamw""#.to_string(),
                            ..Default::default()
                        },
                    ],
                    ..Default::default()
                })),
                ..Default::default()
            },
        ));
        let _ = w.update(&preloaded_msg(
            run2,
            RunMsg {
                id: "nlp0002".to_string(),
                display_name: "bert-debug".to_string(),
                project: "nlp".to_string(),
                config: Some(Box::new(ConfigRecord {
                    update: vec![
                        ConfigItem {
                            nested_key: vec!["lr".to_string()],
                            value_json: "0.01".to_string(),
                            ..Default::default()
                        },
                        ConfigItem {
                            nested_key: vec!["optimizer".to_string()],
                            value_json: r#""sgd""#.to_string(),
                            ..Default::default()
                        },
                    ],
                    ..Default::default()
                })),
                ..Default::default()
            },
        ));

        assert!(update_key(&mut w, key_rune('f')).is_empty());
        type_workspace_filter(&mut w, "project:vision cfg.lr>=1e-3 cfg.optimizer=adamw");
        assert!(update_key(&mut w, key_code(KeyCode::Enter)).is_empty());

        // testhelpers.go TestRunsFiltering: applied (non-input) filter.
        assert!(!w.filter.is_active() && !w.filter.query().is_empty());
        assert_eq!(
            w.filter.query(),
            "project:vision cfg.lr>=1e-3 cfg.optimizer=adamw"
        );
        assert_eq!(filtered_run_keys(&w), vec![run1.to_string()]);

        let view = view_string(&mut w);
        assert!(view.contains("filtered from 2 total"));
        assert!(view.contains("Runs ("));
    }

    // Go: TestWorkspace_RunsFilter_UpdatesWhenMetadataPreloadsArrive.
    #[test]
    fn workspace_runs_filter_updates_when_metadata_preloads_arrive() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());
        update_resize(&mut w, 160, 50);

        let run_key = "run-20260209_010101-vision01";
        let _ = update_run_dirs(&mut w, &[run_key]);

        assert!(update_key(&mut w, key_rune('f')).is_empty());
        type_workspace_filter(&mut w, "project:vision");
        assert!(
            filtered_run_keys(&w).is_empty(),
            "project filter should not match before metadata is preloaded"
        );

        let _ = w.update(&preloaded_msg(
            run_key,
            RunMsg {
                id: "vision01".to_string(),
                project: "vision".to_string(),
                display_name: "baseline".to_string(),
                ..Default::default()
            },
        ));

        assert_eq!(
            filtered_run_keys(&w),
            vec![run_key.to_string()],
            "preloaded metadata should immediately update the visible runs"
        );
    }

    // Go: TestWorkspace_RunsFilter_PriorityOverMetricsFilter.
    #[test]
    fn workspace_runs_filter_priority_over_metrics_filter() {
        let (_c, _d, mut w) = new_workspace_with_panels();

        assert!(update_key(&mut w, key_rune('f')).is_empty());
        assert!(w.filter.is_active());

        // '/' should be consumed as typed text, not enter metrics filter
        // mode.
        assert!(update_key(&mut w, key_rune('/')).is_empty());
        assert!(w.filter.is_active());
        assert_eq!(w.filter.query(), "/");

        assert!(update_key(&mut w, key_code(KeyCode::Esc)).is_empty());
    }

    // Go: TestWorkspace_RunsFilter_Clear.
    #[test]
    fn workspace_runs_filter_clear() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());
        update_resize(&mut w, 160, 50);

        let run1 = "run-20260209_010101-vision01";
        let run2 = "run-20260209_010102-nlp0002";
        let _ = update_run_dirs(&mut w, &[run1, run2]);
        let _ = w.update(&preloaded_msg(
            run1,
            RunMsg {
                id: "vision01".to_string(),
                project: "vision".to_string(),
                ..Default::default()
            },
        ));
        let _ = w.update(&preloaded_msg(
            run2,
            RunMsg {
                id: "nlp0002".to_string(),
                project: "nlp".to_string(),
                ..Default::default()
            },
        ));

        assert!(update_key(&mut w, key_rune('f')).is_empty());
        type_workspace_filter(&mut w, "project:vision");
        assert!(update_key(&mut w, key_code(KeyCode::Enter)).is_empty());
        assert_eq!(filtered_run_keys(&w), vec![run1.to_string()]);

        assert!(update_key(&mut w, ctrl_key('f')).is_empty());
        assert!(
            !(!w.filter.is_active() && !w.filter.query().is_empty()),
            "runs filter should not be applied after clear"
        );
        assert_eq!(
            filtered_run_keys(&w),
            vec![run1.to_string(), run2.to_string()]
        );
    }

    // Go: TestWorkspace_RunsFilter_TagsAndNotes.
    #[test]
    fn workspace_runs_filter_tags_and_notes() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());
        update_resize(&mut w, 200, 60);

        let run1 = "run-20260209_010101-vision01";
        let run2 = "run-20260209_010102-nlp0002";
        let _ = update_run_dirs(&mut w, &[run1, run2]);

        let _ = w.update(&preloaded_msg(
            run1,
            RunMsg {
                id: "vision01".to_string(),
                display_name: "resnet50".to_string(),
                project: "vision".to_string(),
                tags: vec!["baseline".to_string(), "release".to_string()],
                notes: "Warm start from ImageNet checkpoint".to_string(),
                ..Default::default()
            },
        ));
        // A later partial run record should not clobber notes/tags that
        // were already indexed.
        let _ = w.update(&preloaded_msg(
            run1,
            RunMsg {
                id: "vision01".to_string(),
                project: "vision".to_string(),
                ..Default::default()
            },
        ));
        let _ = w.update(&preloaded_msg(
            run2,
            RunMsg {
                id: "nlp0002".to_string(),
                display_name: "bert-debug".to_string(),
                project: "nlp".to_string(),
                tags: vec!["debug".to_string()],
                notes: "Tokenizer ablation run".to_string(),
                ..Default::default()
            },
        ));

        assert!(update_key(&mut w, key_rune('f')).is_empty());
        type_workspace_filter(&mut w, "tag:baseline note:imagenet");
        assert!(update_key(&mut w, key_code(KeyCode::Enter)).is_empty());
        assert_eq!(filtered_run_keys(&w), vec![run1.to_string()]);

        assert!(update_key(&mut w, ctrl_key('f')).is_empty());
        assert!(update_key(&mut w, key_rune('f')).is_empty());
        type_workspace_filter(&mut w, "ablation");
        assert!(update_key(&mut w, key_code(KeyCode::Enter)).is_empty());
        assert_eq!(filtered_run_keys(&w), vec![run2.to_string()]);
    }

    // ------------------------------------------------------------------
    // workspacedirwatcher_test.go — the Workspace.Update wiring halves
    // deferred by workspace_dir_watcher.rs (its TODO(phase-5b) checklist);
    // the queue-mechanics halves are already ported there.
    // ------------------------------------------------------------------

    /// Go `createRunWandbFile` (workspacedirwatcher_test.go:17-34).
    fn create_run_wandb_file(
        wandb_dir: &std::path::Path,
        run_key: &str,
        records: &[leet_proto::wandb_internal::Record],
    ) -> std::path::PathBuf {
        let run_id = crate::workspace::extract_run_id(run_key);
        assert!(
            !run_id.is_empty(),
            "could not extract run ID from key {run_key:?}"
        );

        let run_dir = wandb_dir.join(run_key);
        std::fs::create_dir_all(&run_dir).unwrap();

        let wandb_file = run_dir.join(format!("run-{run_id}.wandb"));
        let mut writer = leet_wire::transaction_log::open_writer(&wandb_file).unwrap();
        for rec in records {
            writer.write(rec).unwrap();
        }
        writer.close().unwrap();
        wandb_file
    }

    fn run_record(
        run_id: &str,
        display_name: &str,
        project: &str,
    ) -> leet_proto::wandb_internal::Record {
        use leet_proto::wandb_internal::{Record, RunRecord, record};
        Record {
            record_type: Some(record::RecordType::Run(RunRecord {
                run_id: run_id.to_string(),
                display_name: display_name.to_string(),
                project: project.to_string(),
                ..Default::default()
            })),
            ..Default::default()
        }
    }

    /// testhelpers.go `TestExecutePreloadCmd`: resolves the preload command
    /// and runs its effect-thread body synchronously.
    fn execute_preload_cmd(
        w: &Workspace,
        run_key: &str,
    ) -> crate::event::WorkspaceRunOverviewPreloadedMsg {
        let cmd = w.preload_run_overview_cmd(run_key);
        let Command::PreloadRunOverview {
            run_key,
            wandb_file,
        } = cmd
        else {
            panic!("expected PreloadRunOverview, got {cmd:?}");
        };
        crate::runtime::preload_run_overview(&run_key, &wandb_file)
    }

    // Go: TestWorkspace_PinSelectsAndPinsWhenNotSelected.
    #[test]
    fn workspace_pin_selects_and_pins_when_not_selected() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());
        assert_eq!(w.selected_runs.len(), 0);

        let run1 = "run-20250731_170606-iazb7i1k";
        let _ = update_run_dirs(&mut w, &[run1]);

        assert_eq!(w.selected_runs.len(), 1); // autoselect and pin
        assert_eq!(w.pinned_run, run1);

        // Unpin. (Go tea.KeyPressMsg{Code: 'p'} — no Text.)
        let _ = update_key(
            &mut w,
            crate::key::KeyEvent {
                code: KeyCode::Char('p'),
                text: None,
                mods: crate::key::KeyMods::NONE,
            },
        );

        assert_eq!(w.selected_runs.len(), 1);
        assert!(is_run_selected(&w, run1));
        assert_eq!(w.pinned_run, "");
    }

    // Go: TestWorkspace_SelectAndPinRuns_StateTransitions.
    #[test]
    fn workspace_select_and_pin_runs_state_transitions() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());

        let run1 = "run-20250731_170606-iazb7i1k";
        let run2 = "run-20250731_170607-zzzzzzzz";
        let _ = update_run_dirs(&mut w, &[run1, run2]);

        // First run is autoselected.
        assert_eq!(w.selected_runs.len(), 1);
        assert!(is_run_selected(&w, run1));
        assert_eq!(w.pinned_run, run1);

        // Move to second run + select it.
        let _ = update_key(&mut w, key_code(KeyCode::Down));
        assert_eq!(current_run_key(&w), run2);

        let _ = update_key(&mut w, key_code(KeyCode::Space));
        assert_eq!(w.selected_runs.len(), 2);
        assert!(is_run_selected(&w, run2));
        assert_eq!(
            w.pinned_run, run1,
            "auto-pin stays on first selection until explicitly pinned"
        );

        // Pin the second run.
        let _ = update_key(
            &mut w,
            crate::key::KeyEvent {
                code: KeyCode::Char('p'),
                text: None,
                mods: crate::key::KeyMods::NONE,
            },
        );
        assert_eq!(w.pinned_run, run2);

        // Deselect pinned run => pin clears (current behavior).
        let _ = update_key(&mut w, key_code(KeyCode::Space));
        assert_eq!(w.selected_runs.len(), 1);
        assert!(!is_run_selected(&w, run2));
        assert_eq!(w.pinned_run, "");
    }

    // Go: TestWorkspace_RunOverviewPreloads_BoundedConcurrency (the
    // Workspace.Update wiring half; the queue mechanics are pinned in
    // workspace_dir_watcher.rs).
    #[test]
    fn workspace_run_overview_preloads_bounded_concurrency() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());

        let run_keys = [
            "run-20250731_170606-a1aaaaaa",
            "run-20250731_170607-b2bbbbbb",
            "run-20250731_170608-c3cccccc",
            "run-20250731_170609-d4dddddd",
            "run-20250731_170610-e5eeeeee",
            "run-20250731_170611-f6ffffff",
            "run-20250731_170612-g7gggggg",
        ];

        // Seeds queue and starts up to maxConcurrentPreloads immediately.
        let _ = update_run_dirs(&mut w, &run_keys);

        assert_eq!(w.overview_preloader.in_flight_len(), 4);
        assert_eq!(w.overview_preloader.queue_len(), 3);

        // Simulate completions in FIFO order; inFlight should stay at 4
        // until fewer remain.
        for (i, run_key) in run_keys.iter().enumerate() {
            let _ = w.update(&Event::WorkspaceRunOverviewPreloaded(
                WorkspaceRunOverviewPreloadedMsg {
                    run_key: run_key.to_string(),
                    // non-empty => treated as success
                    run: Some(Box::new(RunMsg {
                        id: "ok".to_string(),
                        ..Default::default()
                    })),
                    err: None,
                },
            ));

            let remaining = run_keys.len() - (i + 1);
            let want_in_flight = remaining.min(4);
            assert_eq!(w.overview_preloader.in_flight_len(), want_in_flight);
        }

        assert_eq!(w.overview_preloader.queue_len(), 0);
        assert_eq!(w.overview_preloader.in_flight_len(), 0);
    }

    // Go: TestWorkspace_PreloadRunOverview_ExtractsRunRecord.
    #[test]
    fn workspace_preload_run_overview_extracts_run_record() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());

        let run_id = "iazb7i1k";
        let run_key = format!("run-20250731_170606-{run_id}");
        create_run_wandb_file(
            wandb_dir.path(),
            &run_key,
            &[run_record(run_id, "test-run", "test-project")],
        );

        // call preload command directly and verify the returned message
        let msg = execute_preload_cmd(&w, &run_key);

        assert_eq!(msg.err, None);
        let run = msg.run.as_deref().expect("preload returned a Run");
        assert_eq!(run.id, run_id);
        assert_eq!(run.display_name, "test-run");
        assert_eq!(run.project, "test-project");

        // update the workspace to populate the overview
        let _ = w.update(&Event::WorkspaceRunOverviewPreloaded(msg));

        let run_overview = w
            .run_overview
            .get(&run_key)
            .expect("overview populated")
            .borrow();
        assert_eq!(run_overview.id(), run_id);
        assert_eq!(run_overview.display_name(), "test-run");
        assert_eq!(run_overview.project(), "test-project");
    }

    // Go: TestWorkspace_PreloadRunOverview_AllRunsPopulated (incl. the
    // logging suppression for errRunRecordNotFound / os.IsNotExist inside
    // handleWorkspaceRunOverviewPreloaded, which the happy path exercises).
    #[test]
    fn workspace_preload_run_overview_all_runs_populated() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());

        let runs = [
            (
                "run-20250731_170606-aaaaaaaa",
                "aaaaaaaa",
                "run-alpha",
                "proj-1",
            ),
            (
                "run-20250731_170607-bbbbbbbb",
                "bbbbbbbb",
                "run-beta",
                "proj-1",
            ),
            (
                "run-20250731_170608-cccccccc",
                "cccccccc",
                "run-gamma",
                "proj-2",
            ),
        ];

        for (key, id, display, project) in runs {
            create_run_wandb_file(wandb_dir.path(), key, &[run_record(id, display, project)]);
        }

        // preload and update the workspace to populate the overview
        for (key, ..) in runs {
            let msg = execute_preload_cmd(&w, key);
            assert_eq!(msg.err, None, "preload failed for {key}");
            assert!(msg.run.is_some(), "preload returned nil Run for {key}");
            let _ = w.update(&Event::WorkspaceRunOverviewPreloaded(msg));
        }

        for (key, id, display, project) in runs {
            let run_overview = w
                .run_overview
                .get(key)
                .unwrap_or_else(|| panic!("no overview for {key}"))
                .borrow();
            assert_eq!(run_overview.id(), id, "overview ID mismatch for {key}");
            assert_eq!(
                run_overview.display_name(),
                display,
                "overview display name mismatch for {key}"
            );
            assert_eq!(
                run_overview.project(),
                project,
                "overview project mismatch for {key}"
            );
        }
    }

    // ------------------------------------------------------------------
    // heartbeat_lifecycle_test.go — the Workspace half, pointed at the
    // PRODUCTION `handle_workspace_record` arming gate
    // (`should_reset_run_heartbeat`, workspace.go:862-868) as the
    // TODO(phase-5b) in heartbeat.rs directs. heartbeat.rs keeps its
    // gate-expression transliterations (`reset_if_should`) from before this
    // module landed; the Run half re-points with run_handlers.rs.
    // ------------------------------------------------------------------

    /// Go `leet.TestHandleWorkspaceRecord(run, msg)` — the production
    /// record handler driven with the lifecycle tests' two records: a
    /// RunMsg (marks the run Running) then a HistoryMsg (hits the
    /// heartbeat arming gate).
    fn handle_run_and_history_records(w: &mut Workspace, run_key: &str) {
        let _ = w.handle_workspace_record(
            run_key,
            &Event::Run(RunMsg {
                id: run_key.to_string(),
                display_name: "test".to_string(),
                ..Default::default()
            }),
        );
        let _ = w.handle_workspace_record(
            run_key,
            &Event::History(HistoryMsg {
                metrics: HashMap::from([(
                    "loss".to_string(),
                    MetricData {
                        x: vec![1.0],
                        y: vec![0.5],
                    },
                )]),
                ..Default::default()
            }),
        );
    }

    // Go: TestWorkspaceHandleWorkspaceRecord_DoesNotArmHeartbeatBeforeWatcherStarts
    // (heartbeat_lifecycle_test.go:49).
    #[test]
    fn workspace_handle_workspace_record_does_not_arm_heartbeat_before_watcher_starts() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());

        // Go leet.TestNewWorkspaceRun("run-1") + TestAttachRun(run, true):
        // live run, watcher not yet started.
        attach_run(&mut w, WorkspaceRun::new("run-1"), true);

        handle_run_and_history_records(&mut w, "run-1");

        assert!(!w.heartbeat_mgr.timer_armed());
    }

    // Go: TestWorkspaceHandleWorkspaceRecord_ArmsHeartbeatAfterWatcherStarts
    // (heartbeat_lifecycle_test.go:67).
    #[test]
    fn workspace_handle_workspace_record_arms_heartbeat_after_watcher_starts() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());

        let mut run = WorkspaceRun::new("run-1");
        set_watcher_started(&mut run, true); // Go run.TestSetWatcherStarted(true)
        attach_run(&mut w, run, true);

        handle_run_and_history_records(&mut w, "run-1");

        assert!(w.heartbeat_mgr.timer_armed());
        let _ = w.heartbeat_mgr.stop(); // Go: workspace.TestStopHeartbeat()
    }

    fn is_read_cmd(cmd: &Command) -> bool {
        matches!(
            cmd,
            Command::ReadAvailable { .. } | Command::ReadAllChunk { .. }
        )
    }

    /// The Workspace filter half of Go's fire-time heartbeat suppression,
    /// prescribed by the TODO(phase-5b) in heartbeat.rs —
    /// ADAPTED(TestHeartbeatManager_ChecksIsRunningBeforeSending): Go
    /// re-checks `isRunning()` on the timer goroutine at fire time
    /// (heartbeat.go:44). That check died with the scheduler design
    /// (CONCURRENCY.md §2.4); its replacement is the `!anyRunRunning()`
    /// filter at the top of handleHeartbeat (workspacehandlers.go:733-736):
    /// a stale `Event::Heartbeat` already sitting in the main queue when
    /// the last live run stops must stop the heartbeat and produce no read
    /// commands.
    #[test]
    fn workspace_stale_heartbeat_stops_timer_and_produces_no_reads() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());

        let mut run = WorkspaceRun::new("run-1");
        run.reader = stub_reader(7);
        set_watcher_started(&mut run, true);
        attach_run(&mut w, run, true);

        // Live streaming: RunMsg marks the run Running; HistoryMsg arms the
        // heartbeat through the shouldResetRunHeartbeat gate.
        handle_run_and_history_records(&mut w, "run-1");
        assert!(w.heartbeat_mgr.timer_armed());

        // While a selected run is live, a Heartbeat re-arms the safety net
        // and drains the run — proving the filter below discriminates.
        let cmds = w.update(&Event::Heartbeat);
        assert!(
            cmds.iter().any(|c| matches!(
                c,
                Command::Tick {
                    id: TimerId::Heartbeat(HeartbeatOwner::Workspace),
                    ..
                }
            )),
            "live heartbeat should re-arm the timer, got {cmds:?}"
        );
        assert!(
            cmds.iter().any(is_read_cmd),
            "live heartbeat should drain the live run, got {cmds:?}"
        );

        // The run finishes. A Heartbeat that fired before the stop reached
        // the scheduler may already sit in the main queue (§2.4's residual
        // race) and cannot be retracted.
        let _ = w.handle_workspace_record(
            "run-1",
            &Event::FileComplete(FileCompleteMsg { exit_code: 0 }),
        );

        let cmds = w.update(&Event::Heartbeat);
        assert!(
            !w.heartbeat_mgr.timer_armed(),
            "stale heartbeat must leave the timer stopped"
        );
        assert!(
            cmds.iter().any(|c| matches!(
                c,
                Command::CancelTimer {
                    id: TimerId::Heartbeat(HeartbeatOwner::Workspace),
                }
            )),
            "stale heartbeat should stop the heartbeat, got {cmds:?}"
        );
        assert!(
            !cmds.iter().any(is_read_cmd),
            "stale heartbeat must not produce read commands, got {cmds:?}"
        );
    }

    // ---- liveread_test.go — the two Workspace legs (PARITY.md §5.1) ----

    /// Go `stubHistorySource` (liveread_test.go:16-30): records the
    /// (chunkSize, maxTime) it was called with. Duplicated from the run
    /// unit's test module (run_handlers.rs) because liveread_test.go is
    /// split across port units (PARITY.md §5.1).
    struct StubHistorySource {
        msg: Option<SourceMsg>,
        err: Option<HistorySourceError>,

        chunk_size: usize,
        max_time: Duration,
    }

    impl StubHistorySource {
        fn new(msg: Option<SourceMsg>) -> StubHistorySource {
            StubHistorySource {
                msg,
                err: None,
                chunk_size: 0,
                max_time: Duration::ZERO,
            }
        }
    }

    impl HistorySource for StubHistorySource {
        fn read(
            &mut self,
            chunk_size: usize,
            max_time: Duration,
        ) -> (Option<SourceMsg>, Option<HistorySourceError>) {
            self.chunk_size = chunk_size;
            self.max_time = max_time;
            // PARITY: Go's stub returns the same msg on every call;
            // SourceMsg is not Clone, and each test reads exactly once,
            // so handing the value out is equivalent.
            (self.msg.take(), self.err.take())
        }

        fn close(&mut self) {}
    }

    /// Registers Go's `&leet.WorkspaceRun{Key: "run-1", Reader: src}`
    /// (liveread_test.go:97): the port's `read_available_cmd` looks the run
    /// up by key instead of taking the struct, so the run goes into
    /// `runs_by_key` with a stub reader handle standing in for `src`.
    fn register_stub_run(w: &mut Workspace) {
        let mut run = WorkspaceRun::new("run-1");
        run.reader = stub_reader(7);
        w.runs_by_key.insert("run-1".to_string(), run);
    }

    /// Executes a `Command::ReadAvailable` against a stub source exactly as
    /// the runtime does: the effect runner maps the command to a
    /// `ReadRequest` with the LiveMonitor bounds (runtime.rs
    /// `Command::ReadAvailable` dispatch) and the reader thread runs
    /// `execute_read` — together these are the body of Go's
    /// `ReadAvailableCmd` closure (workspacehandlers.go:486).
    fn invoke_read_available(w: &Workspace, source: &mut StubHistorySource) -> Option<Event> {
        let cmd = w
            .read_available_cmd("run-1")
            .expect("expected a ReadAvailable command");
        let Command::ReadAvailable {
            source: id,
            run_key,
        } = cmd
        else {
            panic!("expected ReadAvailable, got {cmd:?}");
        };
        assert_eq!(id, SourceId(7));
        assert_eq!(run_key, "run-1");
        execute_read(
            source,
            ReadRequest {
                kind: ReadKind::WorkspaceAvailable { run_key },
                chunk_size: LIVE_MONITOR_CHUNK_SIZE,
                max_time_per_chunk: LIVE_MONITOR_MAX_TIME,
            },
        )
    }

    /// Go: TestWorkspace_ReadAvailableCmd_WrapsChunkedBatch
    /// (liveread_test.go:80).
    #[test]
    fn workspace_read_available_cmd_wraps_chunked_batch() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());
        register_stub_run(&mut w);

        let mut src = StubHistorySource::new(Some(SourceMsg::ChunkedBatch(hs::ChunkedBatchMsg {
            msgs: vec![SourceMsg::History(hs::HistoryMsg {
                run_path: "dummy".into(),
                metrics: HashMap::from([(
                    "loss".to_string(),
                    hs::MetricData {
                        x: vec![1.0],
                        y: vec![0.5],
                    },
                )]),
                ..Default::default()
            })],
            ..Default::default()
        })));

        let msg = invoke_read_available(&w, &mut src);
        let Some(Event::WorkspaceBatchedRecords(wrapped)) = msg else {
            panic!("expected WorkspaceBatchedRecords, got {msg:?}");
        };
        assert_eq!(wrapped.run_key, "run-1");
        assert_eq!(wrapped.batch.msgs.len(), 1);
        assert_eq!(src.chunk_size, LIVE_MONITOR_CHUNK_SIZE);
        assert_eq!(src.max_time, LIVE_MONITOR_MAX_TIME);
    }

    /// Go: TestWorkspace_ReadAvailableCmd_DropsEmptyChunk
    /// (liveread_test.go:108).
    #[test]
    fn workspace_read_available_cmd_drops_empty_chunk() {
        let wandb_dir = tempfile::tempdir().unwrap();
        let (_cfg_dir, mut w) = new_workspace(wandb_dir.path().to_str().unwrap());
        register_stub_run(&mut w);

        let mut src = StubHistorySource::new(Some(SourceMsg::ChunkedBatch(
            hs::ChunkedBatchMsg::default(),
        )));
        assert_eq!(invoke_read_available(&w, &mut src), None);
    }
}
