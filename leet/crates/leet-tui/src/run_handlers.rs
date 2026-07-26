//! Port of `core/internal/leet/runhandlers.go` — the single-run view's
//! message and key handlers, as `impl Run` blocks (Go: `(*Run)` methods in a
//! sibling file of the same package).
//!
//! Command mapping (docs/CONCURRENCY.md):
//!
//!   - `tea.Tick(AnimationFrame, ..)` call sites (runhandlers.go:562, :752,
//!     :796) → `Command::tick_anim` (§2.4).
//!   - `readChunkCmd` / `ReadLiveBatchCmd` closures → `Command::ReadChunk` /
//!     `Command::ReadLiveBatch`; the read + result wrapping runs on the
//!     reader thread (command.rs `execute_read`, §2.3/§2.7).
//!   - `watcherMgr.WaitForMsg` pump → `Command::AwaitWatcherMsg` armed after
//!     boot load (runhandlers.go:908) and per handled file change (:950).
//!     Go's third site, :938 (`handleHeartbeat`), is deliberately NOT
//!     ported — see [`Run::handle_heartbeat`].
//!   - `heartbeatMgr.Start/Reset/Stop` side effects → returned scheduler
//!     [`Command`]s (heartbeat.rs; the Go methods armed `time.AfterFunc`
//!     directly, so Go call sites returning nil now return the command).

use std::time::{Duration, Instant};

use leet_data::history_source::{BOOT_LOAD_CHUNK_SIZE, BOOT_LOAD_MAX_TIME};
use leet_data::run_overview::{self as run_overview_data, RunState};

use crate::command::{AnimTarget, Command};
use crate::event::{
    BatchedRecordsMsg, ChunkedBatchMsg, Event, HistoryMsg, HistorySourceHandle, InitMsg,
};
use crate::focus_manager::FocusTarget;
use crate::key::{KeyCode, KeyEvent, KeyMods, MouseButton, MouseEvent, MouseKind, normalize_key};
use crate::keybindings::RunAction;
use crate::nav::{NavIntent, decode_nav};
use crate::panel_grid::FocusType;
use crate::run::{Layout, Run, anim_command, media_pane_commands, timeit};

/// Go `ContentPadding` (styles.go:120), as isize for mouse math.
const CONTENT_PADDING: isize = leet_charts::styles::CONTENT_PADDING as isize;

impl Run {
    /// handleRecordMsg handles messages that carry data from the .wandb file.
    ///
    /// PARITY: Go always returns a nil `tea.Cmd`; the returned commands here
    /// are the heartbeat manager's timer side effects (module doc).
    pub(crate) fn handle_record_msg(&mut self, msg: &Event) -> Vec<Command> {
        // PARITY: `defer r.logPanic("processRecordMsg")` — run.rs module doc.
        let start = Instant::now();
        let mut cmds: Vec<Command> = Vec::new();

        match msg {
            Event::Run(msg) => {
                tracing::debug!("model: processing RunMsg");
                self.last_error = String::new();
                self.run_overview
                    .borrow_mut()
                    .process_run_msg(run_overview_data::RunMsg {
                        run_path: msg.run_path.clone(),
                        id: msg.id.clone(),
                        project: msg.project.clone(),
                        display_name: msg.display_name.clone(),
                        notes: msg.notes.clone(),
                        tags: msg.tags.clone(),
                        config: msg.config.as_deref().cloned(),
                    });
                self.left_sidebar.sync();
                self.run_state = RunState::Running;
                // PARITY: syncLiveRunning (runhandlers.go:29) dies — S2.
                self.is_loading = false;
            }

            Event::History(msg) => {
                tracing::debug!("model: processing HistoryMsg");
                if self.should_reset_live_heartbeat() {
                    let is_running = self.is_running();
                    cmds.push(self.heartbeat_mgr.reset(is_running));
                }
                self.handle_history_msg(msg);
            }

            Event::Stats(msg) => {
                tracing::debug!(
                    "model: processing StatsMsg with timestamp {}",
                    msg.timestamp
                );
                if self.should_reset_live_heartbeat() {
                    let is_running = self.is_running();
                    cmds.push(self.heartbeat_mgr.reset(is_running));
                }
                self.right_sidebar.process_stats_msg(msg);
            }

            Event::SystemInfo(msg) => {
                tracing::debug!("model: processing SystemInfoMsg");
                self.run_overview
                    .borrow_mut()
                    .process_system_info_msg(msg.record.as_deref());
                self.left_sidebar.sync();
            }

            Event::Summary(msg) => {
                tracing::debug!("model: processing SummaryMsg");
                self.run_overview
                    .borrow_mut()
                    .process_summary_msg(&msg.summary);
                self.left_sidebar.sync();
            }

            Event::ConsoleLog(msg) => {
                tracing::debug!("model: processing ConsoleLogMsg");
                self.console_logs
                    .process_raw(&msg.text, msg.is_stderr, msg.time);
            }

            Event::FileComplete(msg) => {
                tracing::debug!("model: processing FileCompleteMsg - file is complete!");
                match msg.exit_code {
                    0 => self.run_state = RunState::Finished,
                    _ => self.run_state = RunState::Failed,
                }
                // PARITY: syncLiveRunning (runhandlers.go:68) dies — S2.
                self.run_overview.borrow_mut().set_run_state(self.run_state);
                self.left_sidebar.sync();

                tracing::debug!("model: stopping heartbeats and finishing watcher");
                cmds.push(self.heartbeat_mgr.stop());
                self.watcher_mgr.finish();
            }

            Event::Error(msg) => {
                tracing::debug!("model: processing ErrorMsg: {}", msg.err);
                self.is_loading = false;
                // PARITY: Go guards `msg.Err != nil` (runhandlers.go:79-82);
                // EventError is non-nil-able, so the fallback is
                // unconditionally overwritten, exactly like a non-nil Go err.
                self.last_error = "unknown error".to_string();
                self.last_error = msg.err.to_string();
                self.run_state = RunState::Failed;
                // PARITY: syncLiveRunning (runhandlers.go:84) dies — S2.
                self.run_overview.borrow_mut().set_run_state(self.run_state);
                tracing::debug!("model: stopping heartbeats and finishing watcher due to error");
                cmds.push(self.heartbeat_mgr.stop());
                self.watcher_mgr.finish();
            }

            _ => {}
        }

        // PARITY: Go defers these (runhandlers.go:14-20); the match above
        // has no early returns, so tail calls are equivalent.
        self.resolve_after_availability_change();
        tracing::debug!(
            "perf: processRecordMsg({}) took {:?}",
            msg.ack_name(),
            start.elapsed()
        );

        cmds
    }

    /// handleHistoryMsg processes new history data.
    pub(crate) fn handle_history_msg(&mut self, msg: &HistoryMsg) {
        let _timing = timeit("Model.handleHistoryMsg");

        let should_draw = self.metrics_grid.process_history(msg);
        if self.media_store.borrow_mut().process_history(&msg.media) {
            self.media_pane
                .set_store(Some(std::rc::Rc::clone(&self.media_store)));
        }
        if should_draw && !self.suppress_draw {
            self.metrics_grid.draw_visible();
        }
    }

    /// handleMouseMsg processes mouse events, routing by region.
    pub(crate) fn handle_mouse_msg(&mut self, msg: &MouseEvent) -> Vec<Command> {
        let _timing = timeit("Model.handleMouseMsg");

        let layout = self.compute_viewports();

        if self.is_in_left_sidebar(msg, layout) {
            return self.handle_left_sidebar_mouse();
        }

        if self.is_in_right_sidebar(msg, layout) {
            return self.handle_right_sidebar_mouse(msg, layout);
        }

        self.handle_main_content_mouse(msg, layout)
    }

    /// isInLeftSidebar checks if mouse position is in the left sidebar region.
    fn is_in_left_sidebar(&self, msg: &MouseEvent, layout: Layout) -> bool {
        msg.x < layout.left_sidebar_width
    }

    /// isInRightSidebar checks if mouse position is in the right sidebar region.
    fn is_in_right_sidebar(&self, msg: &MouseEvent, layout: Layout) -> bool {
        let right_start = self.width - layout.right_sidebar_width;
        msg.x >= right_start && layout.right_sidebar_width > 0
    }

    /// handleLeftSidebarMouse handles mouse events in the left sidebar.
    fn handle_left_sidebar_mouse(&mut self) -> Vec<Command> {
        self.metrics_grid.clear_focus();
        self.right_sidebar.clear_focus();
        Vec::new()
    }

    pub(crate) fn adopt_chart_mouse_focus(&mut self) {
        let target = match self.focus.borrow().focus_type {
            FocusType::MainChart => Some(FocusTarget::MetricsGrid),
            FocusType::SystemChart => Some(FocusTarget::SystemMetrics),
            FocusType::None => None,
        };
        if let Some(target) = target {
            self.with_focus_mgr(|fm, r| fm.adopt_target(r, target));
        }
    }

    fn handle_media_mouse(&mut self, msg: &MouseEvent, layout: Layout) -> Vec<Command> {
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
            self.with_focus_mgr(|fm, r| fm.adopt_target(r, FocusTarget::Media));
        }

        Vec::new()
    }

    /// handleRightSidebarMouse handles mouse events in the right sidebar.
    fn handle_right_sidebar_mouse(&mut self, msg: &MouseEvent, layout: Layout) -> Vec<Command> {
        let alt = msg.mods == KeyMods::ALT;

        let right_start = self.width - layout.right_sidebar_width;
        let adjusted_x = msg.x - right_start;

        match msg.kind {
            MouseKind::Click => match msg.button {
                MouseButton::Left => {
                    self.metrics_grid.clear_focus();
                    if self.right_sidebar.handle_mouse_click(adjusted_x, msg.y) {
                        self.adopt_chart_mouse_focus();
                    }
                }
                MouseButton::Right => {
                    self.metrics_grid.clear_focus();
                    self.right_sidebar.start_inspection(adjusted_x, msg.y, alt);
                    self.adopt_chart_mouse_focus();
                }
                _ => {}
            },
            MouseKind::Motion => {
                if msg.button == MouseButton::Right {
                    self.right_sidebar.update_inspection(adjusted_x, msg.y);
                }
            }
            MouseKind::Release => {
                if msg.button == MouseButton::Right {
                    self.right_sidebar.end_inspection();
                }
            }
            MouseKind::Wheel => {
                self.metrics_grid.clear_focus();
                match msg.button {
                    MouseButton::WheelUp => {
                        self.right_sidebar.handle_wheel(adjusted_x, msg.y, true);
                    }
                    MouseButton::WheelDown => {
                        self.right_sidebar.handle_wheel(adjusted_x, msg.y, false);
                    }
                    _ => {}
                }
                self.adopt_chart_mouse_focus();
            }
        }

        Vec::new()
    }

    /// handleMainContentMouse handles mouse events in the main content area.
    fn handle_main_content_mouse(&mut self, msg: &MouseEvent, layout: Layout) -> Vec<Command> {
        if self.media_pane.is_fullscreen() {
            return Vec::new();
        }

        if layout.media_height > 0
            && msg.y >= layout.media_y
            && msg.y < layout.media_y + layout.media_height
        {
            return self.handle_media_mouse(msg, layout);
        }

        let alt = msg.mods == KeyMods::ALT; // Alt pressed at the time of the mouse event?

        const HEADER_OFFSET: isize = 1;

        let adjusted_x = msg.x - layout.left_sidebar_width - CONTENT_PADDING;
        let adjusted_y = msg.y - HEADER_OFFSET;
        if adjusted_x < 0 || adjusted_y < 0 || adjusted_y >= layout.height {
            self.metrics_grid.clear_focus();
            self.right_sidebar.clear_focus();
            return Vec::new();
        }

        let dims = self
            .metrics_grid
            .calculate_chart_dimensions(layout.main_content_area_width, layout.height);

        // Grid too small to interact with (e.g. tiny terminal).
        if dims.cell_h_with_padding == 0 || dims.cell_w_with_padding == 0 {
            return Vec::new();
        }

        // Chart 2D indices on the grid.
        let row = adjusted_y / dims.cell_h_with_padding;
        let col = adjusted_x / dims.cell_w_with_padding;

        match msg.kind {
            MouseKind::Click => match msg.button {
                MouseButton::Left => {
                    self.right_sidebar.clear_focus();
                    self.metrics_grid.handle_click(row, col);
                    self.adopt_chart_mouse_focus();
                }
                MouseButton::Right => {
                    // Holding Alt activates synchronised inspection across all charts
                    // visible on the current page.
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

        Vec::new()
    }

    /// handleKeyPressMsg processes keyboard events using the centralized key bindings.
    pub(crate) fn handle_key_press_msg(&mut self, msg: &KeyEvent) -> Vec<Command> {
        // Filter modes take priority.
        if self.left_sidebar.is_filter_mode() {
            self.left_sidebar.handle_filter_key(msg);
            return Vec::new();
        }
        if self.metrics_grid.is_filter_mode() {
            self.metrics_grid.handle_filter_key(msg);
            return Vec::new();
        }
        if self.right_sidebar.is_filter_mode() {
            self.right_sidebar.handle_filter_key(msg);
            return Vec::new();
        }

        // Grid config capture takes priority.
        if self.config.borrow().is_awaiting_grid_config() {
            return self.handle_config_number_key(msg);
        }

        // Focus-aware key dispatch: route to the currently focused component.
        match self.focus_mgr.current() {
            FocusTarget::MetricsGrid | FocusTarget::SystemMetrics => {
                // PARITY: Go returns a no-op `func() tea.Msg { return nil }`
                // to signal the key was consumed (runhandlers.go:625); the
                // port signals with `true` and returns no command (§2.7).
                if self.handle_grid_nav(msg) {
                    return Vec::new();
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

        // Dispatch to key map.
        if let Some(action) = self.key_map.get(normalize_key(&msg.key_string())).copied() {
            return self.dispatch_action(action, msg);
        }
        Vec::new()
    }

    /// Executes the key-map handler for an action — Go's `handler(r, msg)`
    /// indirect call (runhandlers.go:322-324) over the [`RunAction`] table.
    fn dispatch_action(&mut self, action: RunAction, msg: &KeyEvent) -> Vec<Command> {
        match action {
            RunAction::Quit => self.handle_quit(msg),
            RunAction::ToggleMetricsGrid => self.handle_toggle_metrics_grid(msg),
            RunAction::ToggleLeftSidebar => self.handle_toggle_left_sidebar(msg),
            RunAction::ToggleRightSidebar => self.handle_toggle_right_sidebar(msg),
            RunAction::ToggleMediaPane => self.handle_toggle_media_pane(msg),
            RunAction::ToggleConsoleLogsPane => self.handle_toggle_console_logs_pane(msg),
            RunAction::PrevPage => self.handle_prev_page(msg),
            RunAction::NextPage => self.handle_next_page(msg),
            RunAction::NavHome => self.handle_nav_home(msg),
            RunAction::NavEnd => self.handle_nav_end(msg),
            RunAction::CycleFocusedChartMode => self.handle_cycle_focused_chart_mode(msg),
            RunAction::EnterMetricsFilter => self.handle_enter_metrics_filter(msg),
            RunAction::EnterSystemMetricsFilter => self.handle_enter_system_metrics_filter(msg),
            RunAction::ClearMetricsFilter => self.handle_clear_metrics_filter(msg),
            RunAction::ClearSystemMetricsFilter => self.handle_clear_system_metrics_filter(msg),
            RunAction::EnterOverviewFilter => self.handle_enter_overview_filter(msg),
            RunAction::ClearOverviewFilter => self.handle_clear_overview_filter(msg),
            RunAction::ConfigFocusedCols => self.handle_config_focused_cols(msg),
            RunAction::ConfigFocusedRows => self.handle_config_focused_rows(msg),
            RunAction::SidebarTabNav => self.handle_sidebar_tab_nav(msg),
            RunAction::SidebarVerticalNav => self.handle_sidebar_vertical_nav(msg),
            RunAction::SidebarPageNav => self.handle_sidebar_page_nav(msg),
        }
    }

    /// cleanup releases the run's data-loading resources: it stops the heartbeat
    /// and watcher first so they stop producing reads, then cancels any in-flight
    /// initialization and closes the history source.
    ///
    /// PARITY: Go's "caller must hold stateMu" contract dies with the lock.
    pub(crate) fn cleanup_inner(&mut self) -> Vec<Command> {
        let mut cmds = Vec::new();
        // PARITY: Go nil-checks heartbeatMgr/watcherMgr
        // (runhandlers.go:334-339); both are always constructed here.
        cmds.push(self.heartbeat_mgr.stop());
        self.watcher_mgr.finish();
        // PHASE-7: `initCancel` (runhandlers.go:340-343) — parquet-init
        // cancellation lands with leet-remote.
        if let Some(source) = self.history_source.take() {
            // Go `historySource.Close()`: dropping the reader's request
            // sender closes the file and ends the thread (§2.9).
            cmds.push(Command::CloseReader { source: source.id });
        }
        cmds
    }

    fn handle_quit(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        tracing::debug!("run: quit requested");
        let mut cmds = self.cleanup_inner();
        cmds.push(Command::Quit);
        cmds
    }

    /// beginAnimating tries to acquire the one-shot animation token.
    ///
    /// Returns true if the caller owns the token and may initiate an animation.
    // PARITY: animationMu (runhandlers.go:360-367) dies — main-thread-only.
    pub(crate) fn begin_animating(&mut self) -> bool {
        if self.animating {
            return false;
        }
        self.animating = true;
        true
    }

    /// endAnimating releases the animation token after an animation completes.
    pub(crate) fn end_animating(&mut self) {
        self.animating = false;
    }

    /// handleToggleLeftSidebar toggles the left overview sidebar and resolves
    /// focus so a collapsing sidebar loses focus and an expanding sidebar
    /// gains it when nothing else is focused.
    fn handle_toggle_left_sidebar(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        if !self.begin_animating() {
            return Vec::new();
        }

        let left_will_be_visible = !self.left_sidebar.anim_state.target_visible();

        if let Err(err) = self
            .config
            .borrow_mut()
            .set_left_sidebar_visible(left_will_be_visible)
        {
            tracing::error!("model: failed to save left sidebar state: {err}");
        }

        self.left_sidebar
            .update_dimensions(self.width, self.right_sidebar.anim_state.target_visible());
        self.right_sidebar
            .update_dimensions(self.width, left_will_be_visible);
        self.left_sidebar.toggle();

        self.resolve_after_visibility_change();

        let layout = self.compute_viewports();
        self.metrics_grid
            .update_dimensions(layout.main_content_area_width, layout.height);

        anim_command(self.left_sidebar.animation_cmd())
    }

    fn handle_toggle_right_sidebar(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        if !self.begin_animating() {
            return Vec::new();
        }

        let right_will_be_visible = !self.right_sidebar.anim_state.target_visible();

        if let Err(err) = self
            .config
            .borrow_mut()
            .set_right_sidebar_visible(right_will_be_visible)
        {
            tracing::error!("model: failed to save right sidebar state: {err}");
        }

        self.right_sidebar
            .update_dimensions(self.width, self.left_sidebar.anim_state.target_visible());
        self.left_sidebar
            .update_dimensions(self.width, right_will_be_visible);
        self.right_sidebar.toggle();
        self.resolve_after_visibility_change();

        let layout = self.compute_viewports();
        self.metrics_grid
            .update_dimensions(layout.main_content_area_width, layout.height);

        anim_command(self.right_sidebar.animation_cmd())
    }

    fn handle_prev_page(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        match self.focus_mgr.current() {
            FocusTarget::MetricsGrid => self.metrics_grid.navigate(-1),
            FocusTarget::SystemMetrics => self.right_sidebar.metrics_grid.navigate(-1),
            FocusTarget::Media => self.media_pane.navigate_page(-1),
            FocusTarget::Overview => self.left_sidebar.navigate_page_up(),
            FocusTarget::ConsoleLogs => self.console_logs_pane.page_up(),
            _ => {}
        }
        Vec::new()
    }

    fn handle_next_page(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        match self.focus_mgr.current() {
            FocusTarget::MetricsGrid => self.metrics_grid.navigate(1),
            FocusTarget::SystemMetrics => self.right_sidebar.metrics_grid.navigate(1),
            FocusTarget::Media => self.media_pane.navigate_page(1),
            FocusTarget::Overview => self.left_sidebar.navigate_page_down(),
            FocusTarget::ConsoleLogs => self.console_logs_pane.page_down(),
            _ => {}
        }
        Vec::new()
    }

    fn handle_nav_home(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        match self.focus_mgr.current() {
            FocusTarget::MetricsGrid => self.metrics_grid.navigate_home(),
            FocusTarget::SystemMetrics => self.right_sidebar.metrics_grid.navigate_home(),
            FocusTarget::Media => self.media_pane.scrub_to_start(),
            FocusTarget::Overview => self.left_sidebar.navigate_home(),
            FocusTarget::ConsoleLogs => self.console_logs_pane.scroll_to_start(),
            _ => {}
        }
        Vec::new()
    }

    fn handle_nav_end(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        match self.focus_mgr.current() {
            FocusTarget::MetricsGrid => self.metrics_grid.navigate_end(),
            FocusTarget::SystemMetrics => self.right_sidebar.metrics_grid.navigate_end(),
            FocusTarget::Media => self.media_pane.scrub_to_end(),
            FocusTarget::Overview => self.left_sidebar.navigate_end(),
            FocusTarget::ConsoleLogs => self.console_logs_pane.scroll_to_end(),
            _ => {}
        }
        Vec::new()
    }

    fn handle_cycle_focused_chart_mode(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        let focus_type = self.focus.borrow().focus_type;
        match focus_type {
            FocusType::MainChart => {
                self.metrics_grid.toggle_focused_chart_log_y();
            }
            FocusType::SystemChart => {
                // PARITY: Go nil-checks rightSidebar/metricsGrid
                // (runhandlers.go:494); always constructed here.
                self.right_sidebar.metrics_grid.cycle_focused_chart_mode();
            }
            FocusType::None => {}
        }
        Vec::new()
    }

    fn handle_enter_metrics_filter(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        self.metrics_grid.enter_filter_mode();
        Vec::new()
    }

    fn handle_clear_metrics_filter(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        if !self.metrics_grid.filter_query().is_empty() {
            self.metrics_grid.clear_filter();
        }
        if self.focus_mgr.current() == FocusTarget::MetricsGrid {
            self.metrics_grid.navigate_focus(0, 0);
        }
        Vec::new()
    }

    fn handle_enter_overview_filter(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        self.left_sidebar.enter_filter_mode();
        Vec::new()
    }

    fn handle_clear_overview_filter(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        if self.left_sidebar.is_filtering() {
            self.left_sidebar.clear_filter();
        }
        Vec::new()
    }

    fn handle_toggle_metrics_grid(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        let metrics_will_be_visible = !self.metrics_grid_anim_state.target_visible();

        if let Err(err) = self
            .config
            .borrow_mut()
            .set_metrics_grid_visible(metrics_will_be_visible)
        {
            tracing::error!("runhandlers: failed to save metrics grid state: {err}");
        }

        self.metrics_grid_anim_state.toggle();
        self.resolve_after_visibility_change();

        self.update_bottom_pane_heights(
            self.media_pane.anim_state.target_visible(),
            self.console_logs_pane.anim_state.target_visible(),
        );

        let layout = self.compute_viewports();
        self.metrics_grid
            .update_dimensions(layout.main_content_area_width, layout.height);

        vec![Self::metrics_grid_animation_cmd()]
    }

    pub(crate) fn handle_metrics_grid_animation(&mut self) -> Vec<Command> {
        self.metrics_grid_anim_state.update(Instant::now());

        self.update_bottom_pane_heights(
            self.media_pane.anim_state.target_visible(),
            self.console_logs_pane.anim_state.target_visible(),
        );
        let layout = self.compute_viewports();
        self.metrics_grid
            .update_dimensions(layout.main_content_area_width, layout.height);

        if self.metrics_grid_anim_state.is_animating() {
            return vec![Self::metrics_grid_animation_cmd()];
        }
        Vec::new()
    }

    fn metrics_grid_animation_cmd() -> Command {
        // Go: tea.Tick(AnimationFrame, .. MetricsGridAnimationMsg{})
        // (runhandlers.go:561-565).
        Command::tick_anim(AnimTarget::MetricsGrid)
    }

    /// Returns whether the key was consumed (see the PARITY note at the
    /// call site in [`Run::handle_key_press_msg`]).
    fn handle_grid_nav(&mut self, msg: &KeyEvent) -> bool {
        let intent = decode_nav(msg);
        if intent == NavIntent::None {
            return false;
        }

        // PARITY: Go's applyFocus/applyPage/applyJump closures each re-read
        // r.focusMgr.Current() (runhandlers.go:573-604); the target cannot
        // change between reads, so it is hoisted.
        let current = self.focus_mgr.current();

        let apply_focus = |r: &mut Run, dr: isize, dc: isize| match current {
            FocusTarget::MetricsGrid => {
                r.metrics_grid.navigate_focus(dr, dc);
            }
            FocusTarget::SystemMetrics => {
                r.right_sidebar.metrics_grid.navigate_focus(dr, dc);
            }
            _ => {}
        };
        let apply_page = |r: &mut Run, dir: isize| match current {
            FocusTarget::MetricsGrid => r.metrics_grid.navigate(dir),
            FocusTarget::SystemMetrics => r.right_sidebar.metrics_grid.navigate(dir),
            _ => {}
        };
        let apply_jump = |r: &mut Run, end: bool| match current {
            FocusTarget::MetricsGrid => {
                if end {
                    r.metrics_grid.navigate_end();
                } else {
                    r.metrics_grid.navigate_home();
                }
            }
            FocusTarget::SystemMetrics => {
                if end {
                    r.right_sidebar.metrics_grid.navigate_end();
                } else {
                    r.right_sidebar.metrics_grid.navigate_home();
                }
            }
            _ => {}
        };

        match intent {
            NavIntent::Up => apply_focus(self, -1, 0),
            NavIntent::Down => apply_focus(self, 1, 0),
            NavIntent::Left => apply_focus(self, 0, -1),
            NavIntent::Right => apply_focus(self, 0, 1),
            NavIntent::PageUp => apply_page(self, -1),
            NavIntent::PageDown => apply_page(self, 1),
            NavIntent::Home => apply_jump(self, false),
            NavIntent::End => apply_jump(self, true),
            NavIntent::None => unreachable!("checked above"),
        }
        // PARITY: Go returns a no-op command to signal the key was consumed
        // (runhandlers.go:625); ports as `true` with no command (§2.7).
        true
    }

    fn handle_config_focused_cols(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        let target = match self.focus_mgr.current() {
            FocusTarget::SystemMetrics => leet_data::config::GridConfigTarget::SystemCols,
            FocusTarget::Media => leet_data::config::GridConfigTarget::MediaCols,
            _ => leet_data::config::GridConfigTarget::MetricsCols,
        };
        self.config.borrow_mut().set_pending_grid_config(target);
        Vec::new()
    }

    fn handle_config_focused_rows(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        let target = match self.focus_mgr.current() {
            FocusTarget::SystemMetrics => leet_data::config::GridConfigTarget::SystemRows,
            FocusTarget::Media => leet_data::config::GridConfigTarget::MediaRows,
            _ => leet_data::config::GridConfigTarget::MetricsRows,
        };
        self.config.borrow_mut().set_pending_grid_config(target);
        Vec::new()
    }

    fn handle_enter_system_metrics_filter(&mut self, msg: &KeyEvent) -> Vec<Command> {
        let mut cmds = Vec::new();
        if !self.config.borrow().right_sidebar_visible() {
            cmds = self.handle_toggle_right_sidebar(msg);
        }
        self.right_sidebar.metrics_grid.enter_filter_mode();
        self.right_sidebar.metrics_grid.apply_filter();

        cmds
    }

    fn handle_clear_system_metrics_filter(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        if !self.right_sidebar.metrics_grid.filter_query().is_empty() {
            self.right_sidebar.metrics_grid.clear_filter();
        }
        if self.focus_mgr.current() == FocusTarget::SystemMetrics {
            self.right_sidebar.metrics_grid.navigate_focus(0, 0);
        }
        Vec::new()
    }

    /// handleConfigNumberKey handles number input for configuration.
    fn handle_config_number_key(&mut self, msg: &KeyEvent) -> Vec<Command> {
        let layout = self.compute_viewports();
        // PARITY: Go passes the whole Layout (runhandlers.go:675); the grid
        // reads mainContentAreaWidth/height only (metrics_grid.rs note).
        self.metrics_grid.handle_grid_config_number_key(
            msg,
            layout.main_content_area_width,
            layout.height,
        );

        Vec::new()
    }

    /// handleSidebarAnimation handles sidebar animation.
    pub(crate) fn handle_sidebar_animation(&mut self, msg: &Event) -> Vec<Command> {
        match msg {
            Event::LeftSidebarAnimation => {
                let layout = self.compute_viewports();
                self.metrics_grid
                    .update_dimensions(layout.main_content_area_width, layout.height);

                if self.left_sidebar.is_animating() {
                    return anim_command(self.left_sidebar.animation_cmd());
                }

                self.end_animating();
                self.right_sidebar
                    .update_dimensions(self.width, self.left_sidebar.anim_state.target_visible());
            }

            Event::RightSidebarAnimation => {
                let layout = self.compute_viewports();
                self.metrics_grid
                    .update_dimensions(layout.main_content_area_width, layout.height);

                if self.right_sidebar.is_animating() {
                    return anim_command(self.right_sidebar.animation_cmd());
                }

                self.end_animating();
                self.left_sidebar
                    .update_dimensions(self.width, self.right_sidebar.anim_state.target_visible());
            }

            _ => {}
        }

        Vec::new()
    }

    fn handle_toggle_media_pane(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        if !self.begin_animating() {
            return Vec::new();
        }

        let media_will_be_visible = !self.media_pane.anim_state.target_visible();

        if let Err(err) = self
            .config
            .borrow_mut()
            .set_media_visible(media_will_be_visible)
        {
            tracing::error!("runhandlers: failed to save media pane state: {err}");
        }

        if !media_will_be_visible {
            self.media_pane.exit_fullscreen();
        }

        self.media_pane.toggle();
        self.update_bottom_pane_heights(
            media_will_be_visible,
            self.console_logs_pane.anim_state.target_visible(),
        );

        if !media_will_be_visible {
            self.resolve_after_visibility_change();
        }

        let layout = self.compute_viewports();
        self.metrics_grid
            .update_dimensions(layout.main_content_area_width, layout.height);

        vec![Self::media_pane_animation_cmd()]
    }

    pub(crate) fn handle_media_pane_animation(&mut self) -> Vec<Command> {
        self.media_pane.update(Instant::now());

        let layout = self.compute_viewports();
        self.metrics_grid
            .update_dimensions(layout.main_content_area_width, layout.height);

        if self.media_pane.is_animating() {
            return vec![Self::media_pane_animation_cmd()];
        }

        self.end_animating();
        Vec::new()
    }

    fn media_pane_animation_cmd() -> Command {
        // Go: tea.Tick(AnimationFrame, .. MediaPaneAnimationMsg{})
        // (runhandlers.go:751-755).
        Command::tick_anim(AnimTarget::MediaPane)
    }

    /// handleToggleConsoleLogsPane toggles the console logs bottom bar and resolves
    /// focus so a collapsing bar loses focus and an expanding bar gains it
    /// when nothing else is focused.
    fn handle_toggle_console_logs_pane(&mut self, _msg: &KeyEvent) -> Vec<Command> {
        if !self.begin_animating() {
            return Vec::new();
        }

        let bottom_will_be_visible = !self.console_logs_pane.anim_state.target_visible();

        if let Err(err) = self
            .config
            .borrow_mut()
            .set_console_logs_visible(bottom_will_be_visible)
        {
            tracing::error!("runhandlers: failed to save console logs state: {err}");
        }

        self.console_logs_pane.toggle();
        self.update_bottom_pane_heights(
            self.media_pane.anim_state.target_visible(),
            bottom_will_be_visible,
        );
        self.resolve_after_visibility_change();

        let layout = self.compute_viewports();
        self.metrics_grid
            .update_dimensions(layout.main_content_area_width, layout.height);

        vec![Self::console_logs_pane_animation_cmd()]
    }

    pub(crate) fn handle_console_logs_pane_animation(&mut self) -> Vec<Command> {
        self.console_logs_pane.update(Instant::now());

        let layout = self.compute_viewports();
        self.metrics_grid
            .update_dimensions(layout.main_content_area_width, layout.height);

        if self.console_logs_pane.is_animating() {
            return vec![Self::console_logs_pane_animation_cmd()];
        }

        self.end_animating();
        Vec::new()
    }

    fn console_logs_pane_animation_cmd() -> Command {
        // Go: tea.Tick(AnimationFrame, .. ConsoleLogsPaneAnimationMsg{})
        // (runhandlers.go:795-799).
        Command::tick_anim(AnimTarget::ConsoleLogsPane)
    }

    /// readChunkCmd — Go builds a closure over (source, chunkSize, maxTime)
    /// (runhandlers.go:801-818); the port names the shape as
    /// [`Command::ReadChunk`], executed on the reader thread
    /// (command.rs `execute_read`, `ReadKind::Chunk`).
    fn read_chunk_cmd(
        &self,
        source: Option<HistorySourceHandle>,
        chunk_size: usize,
        max_time_per_chunk: Duration,
    ) -> Vec<Command> {
        // PARITY: Go's closure no-ops on a nil source (runhandlers.go:807);
        // no source ⇒ no command (the effect runner also drops reads on
        // unknown/closed ids the same way).
        let Some(source) = source else {
            return Vec::new();
        };
        vec![Command::ReadChunk {
            source: source.id,
            chunk_size,
            max_time_per_chunk,
        }]
    }

    /// ReadLiveBatchCmd — Go builds a closure baking in the LiveMonitor
    /// bounds and wrapping a non-empty ChunkedBatchMsg into
    /// BatchedRecordsMsg (runhandlers.go:820-844); the port names the shape
    /// as [`Command::ReadLiveBatch`] — the bounds are applied by the effect
    /// runner (runtime.rs `Command::ReadLiveBatch` dispatch) and the
    /// wrapping by `execute_read` (`ReadKind::LiveBatch`).
    pub fn read_live_batch_cmd(&self, source: Option<HistorySourceHandle>) -> Vec<Command> {
        // PARITY: nil-source no-op (runhandlers.go:822-824), as above.
        let Some(source) = source else {
            return Vec::new();
        };
        vec![Command::ReadLiveBatch { source: source.id }]
    }

    /// handleRecordsBatch processes a batch of sub-messages and manages redraw + loading flags.
    fn handle_records_batch(&mut self, sub_msgs: &[Event], suppress_redraw: bool) -> Vec<Command> {
        let _timing = timeit("Model.handleRecordsBatch");

        let mut cmds: Vec<Command> = Vec::new();

        let prev = self.suppress_draw;
        self.suppress_draw = suppress_redraw;
        for sub_msg in sub_msgs {
            cmds.extend(self.handle_record_msg(sub_msg));
        }
        self.suppress_draw = prev;
        if !self.suppress_draw {
            self.metrics_grid.draw_visible();
        }

        cmds
    }

    /// handleInit handles InitMsg (reader ready).
    pub(crate) fn handle_init(&mut self, msg: &InitMsg) -> Vec<Command> {
        tracing::debug!("model: InitMsg received, reader initialized");
        self.history_source = Some(msg.source);
        self.load_start_time = Some(Instant::now());

        self.read_chunk_cmd(
            self.history_source,
            BOOT_LOAD_CHUNK_SIZE,
            BOOT_LOAD_MAX_TIME,
        )
    }

    /// handleChunkedBatch handles boot-load chunked batches.
    pub(crate) fn handle_chunked_batch(&mut self, msg: &ChunkedBatchMsg) -> Vec<Command> {
        let _timing = timeit("Model.onChunkedBatch");

        tracing::debug!(
            "model: ChunkedBatchMsg received with {} messages, hasMore={}",
            msg.msgs.len(),
            msg.has_more
        );

        self.records_loaded += msg.progress;

        // Draw once per boot chunk instead of once per history record.
        let mut cmds = self.handle_records_batch(&msg.msgs, true);

        if msg.has_more {
            cmds.extend(self.read_chunk_cmd(
                self.history_source,
                BOOT_LOAD_CHUNK_SIZE,
                BOOT_LOAD_MAX_TIME,
            ));
            return cmds;
        }

        // Boot load complete -> begin live mode once. The WaitForMsg pump is
        // started alongside the watcher so it only runs while the watcher and
        // heartbeat can produce messages; WatcherManager.Finish unblocks it.
        if !self.is_remote()
            && self.run_state == RunState::Running
            && !self.watcher_mgr.is_started()
        {
            match self.watcher_mgr.start(&self.run_params.run_file) {
                Err(err) => {
                    // Go: logger.CaptureError (runhandlers.go:904).
                    tracing::error!("model: error starting watcher: {err}");
                }
                Ok(()) => {
                    tracing::info!("model: watcher started successfully");
                    let is_running = self.is_running();
                    cmds.push(self.heartbeat_mgr.start(is_running));
                    if let Some(rx) = self.watcher_mgr.watch_receiver() {
                        cmds.push(Command::AwaitWatcherMsg { rx });
                    }
                }
            }
        }
        cmds
    }

    /// handleBatched handles live drain batches.
    pub(crate) fn handle_batched(&mut self, msg: &BatchedRecordsMsg) -> Vec<Command> {
        tracing::debug!(
            "model: BatchedRecordsMsg received with {} messages",
            msg.msgs.len()
        );
        let mut cmds = self.handle_records_batch(&msg.msgs, true);
        if self.run_state != RunState::Running {
            return cmds;
        }
        cmds.extend(self.read_live_batch_cmd(self.history_source));
        cmds
    }

    /// handleHeartbeat triggers a live read and re-arms the heartbeat.
    pub(crate) fn handle_heartbeat(&mut self) -> Vec<Command> {
        tracing::debug!("model: processing HeartbeatMsg");
        if self.run_state != RunState::Running {
            return vec![self.heartbeat_mgr.stop()];
        }
        let is_running = self.is_running();
        let mut cmds = vec![self.heartbeat_mgr.reset(is_running)];
        cmds.extend(self.read_live_batch_cmd(self.history_source));
        // PARITY: Go re-arms `watcherMgr.WaitForMsg` here
        // (runhandlers.go:938) — valid there only because the shared C1
        // chan carried this HeartbeatMsg, so the pump had just returned.
        // Heartbeats bypass the pump here (scheduler → main channel); the
        // in-flight pump is still blocked on the watcher receiver, and
        // re-issuing `Command::AwaitWatcherMsg` would stack one extra pump
        // thread per heartbeat fire. NOT ported (see the caveats on
        // `Command::AwaitWatcherMsg` and `WatcherManager::watch_receiver`).
        cmds
    }

    /// handleFileChange coalesces change notifications into a read.
    pub(crate) fn handle_file_change(&mut self) -> Vec<Command> {
        if self.run_state != RunState::Running {
            return Vec::new();
        }
        let is_running = self.is_running();
        let mut cmds = vec![self.heartbeat_mgr.reset(is_running)];
        cmds.extend(self.read_live_batch_cmd(self.history_source));
        // Go: watcherMgr.WaitForMsg re-arm (runhandlers.go:950).
        if let Some(rx) = self.watcher_mgr.watch_receiver() {
            cmds.push(Command::AwaitWatcherMsg { rx });
        }
        cmds
    }

    /// handleSidebarTabNav cycles focus between overview sections and the
    /// console logs bar, mirroring the workspace's Tab cycling pattern.
    ///
    /// Within the overview region, Tab first cycles through sections. At the
    /// boundary, it moves to the next available region.
    fn handle_sidebar_tab_nav(&mut self, msg: &KeyEvent) -> Vec<Command> {
        let mut direction: isize = 1;
        if msg.code == KeyCode::Tab && msg.mods == KeyMods::SHIFT {
            direction = -1;
        }

        // PARITY: Go's withinFn checks `r.focusMgr.IsTarget(..)` inside the
        // closure (runhandlers.go:965-970); `tabWithinOrAdvance` calls it
        // before any focus mutation, so hoisting the check out is
        // equivalent (the manager is moved out during the call — run.rs
        // `with_focus_mgr`).
        let within_fn: Option<fn(&mut Run, isize) -> bool> =
            if self.focus_mgr.is_target(FocusTarget::Overview) {
                Some(|r, dir| r.cycle_run_overview_section(dir))
            } else {
                None
            };

        self.with_focus_mgr(|fm, r| fm.tab_within_or_advance(r, direction, within_fn));
        Vec::new()
    }

    fn handle_sidebar_vertical_nav(&mut self, msg: &KeyEvent) -> Vec<Command> {
        let up = decode_nav(msg) == NavIntent::Up;
        match self.focus_mgr.current() {
            FocusTarget::Media => {
                // Media pane keeps arrow-vs-letter distinction: arrows scrub by 10.
                if up {
                    self.media_pane.scrub(-10);
                } else {
                    self.media_pane.scrub(10);
                }
            }
            FocusTarget::ConsoleLogs => {
                if up {
                    self.console_logs_pane.up();
                } else {
                    self.console_logs_pane.down();
                }
            }
            FocusTarget::Overview => {
                if self.left_sidebar.is_visible() {
                    if up {
                        self.left_sidebar.navigate_up();
                    } else {
                        self.left_sidebar.navigate_down();
                    }
                }
            }
            _ => {}
        }
        Vec::new()
    }

    fn handle_sidebar_page_nav(&mut self, msg: &KeyEvent) -> Vec<Command> {
        let left = decode_nav(msg) == NavIntent::Left;
        match self.focus_mgr.current() {
            FocusTarget::Media => {
                // Media pane keeps arrow-vs-letter distinction: arrows scrub by 1.
                if left {
                    self.media_pane.scrub(-1);
                } else {
                    self.media_pane.scrub(1);
                }
            }
            FocusTarget::ConsoleLogs => {
                if left {
                    self.console_logs_pane.page_up();
                } else {
                    self.console_logs_pane.page_down();
                }
            }
            FocusTarget::Overview => {
                if self.left_sidebar.is_visible() {
                    if left {
                        self.left_sidebar.navigate_page_up();
                    } else {
                        self.left_sidebar.navigate_page_down();
                    }
                }
            }
            _ => {}
        }
        Vec::new()
    }
}

// ---------------------------------------------------------------------------
// Tests — transliteration of core/internal/leet/runhandlers_test.go plus the
// two Run legs of liveread_test.go deferred from leet-wire (PARITY.md §5.1).
// testhelpers.go accessors are replaced by direct pub(crate) access
// (PORTING.md Testing conventions).
//
// liveread_test.go's two Workspace legs,
// TestWorkspace_ReadAvailableCmd_WrapsChunkedBatch (:80) and
// TestWorkspace_ReadAvailableCmd_DropsEmptyChunk (:108), need the workspace
// unit's `Workspace`/`WorkspaceRun` types and are transliterated in
// workspace_handlers.rs's test module (PARITY.md §5.1).
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use std::cell::RefCell;
    use std::collections::HashMap;
    use std::rc::Rc;

    use leet_charts::styles::default_dark_background;
    use leet_data::config::ConfigManager;
    use leet_data::history_source::{
        self as hs, HistorySource, HistorySourceError, LIVE_MONITOR_CHUNK_SIZE,
        LIVE_MONITOR_MAX_TIME, SourceMsg,
    };
    use leet_proto::wandb_internal::{
        ConfigItem, ConfigRecord, EnvironmentRecord, SummaryItem, SummaryRecord,
    };
    use pretty_assertions::assert_eq;

    use super::*;
    use crate::command::{ReadKind, ReadRequest, SourceId, execute_read};
    use crate::event::{RunMsg, SummaryMsg, SystemInfoMsg};
    use crate::nav::test_helpers::{primary_nav_msg, secondary_nav_msg};
    use crate::run::RunParams;
    use crate::run_overview_sidebar::RunOverviewSidebar;

    fn test_config(dir: &tempfile::TempDir) -> Rc<RefCell<ConfigManager>> {
        Rc::new(RefCell::new(ConfigManager::new(
            dir.path().join("config.json"),
        )))
    }

    fn tab() -> Event {
        Event::Key(KeyEvent {
            code: KeyCode::Tab,
            text: None,
            mods: KeyMods::NONE,
        })
    }

    /// newRunForHandlerTest creates a Run model with sidebars expanded and
    /// seeded with enough data to exercise section navigation.
    fn new_run_for_handler_test(dir: &tempfile::TempDir) -> Run {
        let cfg = test_config(dir);
        cfg.borrow_mut().set_left_sidebar_visible(true).unwrap();
        cfg.borrow_mut().set_right_sidebar_visible(true).unwrap();

        let mut r = Run::new(
            RunParams {
                run_file: "testdata/fake.wandb".into(),
                remote: None,
            },
            Some(cfg),
        );
        r.update(&Event::Resize {
            width: 200,
            height: 60,
        });

        // Force left sidebar expanded so section navigation is testable
        // (Go TestForceExpandLeftSidebar).
        r.left_sidebar.anim_state.force_expand();

        // Seed overview data to create focusable sections.
        r.handle_record_msg(&Event::Run(RunMsg {
            id: "abc123".into(),
            project: "test-project".into(),
            config: Some(Box::new(ConfigRecord {
                update: vec![
                    ConfigItem {
                        nested_key: vec!["lr".into()],
                        value_json: "0.01".into(),
                        ..Default::default()
                    },
                    ConfigItem {
                        nested_key: vec!["epochs".into()],
                        value_json: "10".into(),
                        ..Default::default()
                    },
                ],
                ..Default::default()
            })),
            ..Default::default()
        }));
        r.handle_record_msg(&Event::Summary(SummaryMsg {
            summary: vec![SummaryRecord {
                update: vec![SummaryItem {
                    nested_key: vec!["loss".into()],
                    value_json: "0.42".into(),
                    ..Default::default()
                }],
                ..Default::default()
            }],
            ..Default::default()
        }));
        r.handle_record_msg(&Event::SystemInfo(SystemInfoMsg {
            record: Some(Box::new(EnvironmentRecord {
                writer_id: "w1".into(),
                os: "linux".into(),
                ..Default::default()
            })),
            ..Default::default()
        }));

        // Ensure sidebar syncs the data.
        r.left_sidebar.sync();
        let _ = r.left_sidebar.view(50, default_dark_background());

        r
    }

    /// Go `TestForceExpandConsoleLogsPane` (testhelpers.go:462-465).
    fn force_expand_console_logs_pane(r: &mut Run, h: isize) {
        r.console_logs_pane.set_expanded_height(h);
        r.console_logs_pane.anim_state.force_expand();
    }

    // ---- handleSidebarTabNav ----

    /// Go: TestRun_SidebarTabNav_BothPanelsVisible_CyclesOverviewThenLogs.
    #[test]
    fn run_sidebar_tab_nav_both_panels_visible_cycles_overview_then_logs() {
        let dir = tempfile::tempdir().unwrap();
        let mut r = new_run_for_handler_test(&dir);
        force_expand_console_logs_pane(&mut r, 10);

        // Initial state: overview section 0 should be active.
        assert!(
            r.left_sidebar.has_active_section(),
            "overview should start with an active section"
        );
        assert!(
            !r.console_logs_pane.active(),
            "bottom bar should not be active initially"
        );

        // Tab through overview sections until we reach the last one, then
        // Tab one more should jump to logs.
        let (_, last_sec) = r.left_sidebar.focusable_section_bounds();
        while r.left_sidebar.active_section < last_sec {
            r.update(&tab());
        }
        assert_eq!(
            r.left_sidebar.active_section, last_sec,
            "should have reached last overview section"
        );

        // One more Tab → logs.
        r.update(&tab());
        assert!(
            r.console_logs_pane.active(),
            "Tab past last section should focus logs"
        );
        assert!(
            !r.left_sidebar.has_active_section(),
            "overview sections should be deactivated when logs focused"
        );

        // Tab from logs → overview first section.
        r.update(&tab());
        assert!(
            !r.console_logs_pane.active(),
            "Tab from logs should leave logs"
        );
        assert!(
            r.left_sidebar.has_active_section(),
            "should re-enter overview"
        );
    }

    /// Go: TestRun_SidebarTabNav_OnlyLogsVisible.
    #[test]
    fn run_sidebar_tab_nav_only_logs_visible() {
        let dir = tempfile::tempdir().unwrap();
        let mut r = new_run_for_handler_test(&dir);
        force_expand_console_logs_pane(&mut r, 10);
        // Go TestForceCollapseLeftSidebar.
        r.left_sidebar.anim_state.force_collapse();

        // With overview collapsed, Tab should activate logs.
        r.update(&tab());
        assert!(
            r.console_logs_pane.active(),
            "Tab with collapsed overview should still reach logs"
        );
    }

    /// Go: TestRun_SidebarTabNav_OnlyOverviewVisible.
    #[test]
    fn run_sidebar_tab_nav_only_overview_visible() {
        let dir = tempfile::tempdir().unwrap();
        let mut r = new_run_for_handler_test(&dir);
        // Bottom bar collapsed (default).
        assert!(
            !r.console_logs_pane.is_expanded(),
            "bottom bar should start collapsed"
        );

        // Tab should cycle through overview sections without reaching logs.
        let initial_section = r.left_sidebar.active_section;
        r.update(&tab());
        let next_section = r.left_sidebar.active_section;
        assert_ne!(
            initial_section, next_section,
            "Tab should cycle overview sections"
        );
        assert!(
            !r.console_logs_pane.active(),
            "logs should never get focus when collapsed"
        );
    }

    /// Go: TestRun_InitialFocus_PicksFirstAvailablePane.
    #[test]
    fn run_initial_focus_picks_first_available_pane() {
        let dir = tempfile::tempdir().unwrap();
        let cfg = test_config(&dir);
        cfg.borrow_mut().set_left_sidebar_visible(false).unwrap();
        cfg.borrow_mut().set_console_logs_visible(true).unwrap();

        let mut r = Run::new(
            RunParams {
                run_file: "testdata/fake.wandb".into(),
                remote: None,
            },
            Some(cfg),
        );
        r.update(&Event::Resize {
            width: 200,
            height: 60,
        });

        assert!(
            r.console_logs_pane.active(),
            "the first available pane should receive focus on load"
        );
        assert!(
            !r.left_sidebar.has_active_section(),
            "collapsed overview should not appear focused"
        );
    }

    /// Go: TestRun_OverviewUpdatesPreserveTabContext.
    #[test]
    fn run_overview_updates_preserve_tab_context() {
        let dir = tempfile::tempdir().unwrap();
        let cfg = test_config(&dir);
        cfg.borrow_mut().set_left_sidebar_visible(true).unwrap();

        let mut r = Run::new(
            RunParams {
                run_file: "testdata/fake.wandb".into(),
                remote: None,
            },
            Some(cfg),
        );
        r.update(&Event::Resize {
            width: 200,
            height: 60,
        });

        r.handle_record_msg(&Event::Run(RunMsg {
            id: "abc123".into(),
            project: "test-project".into(),
            config: Some(Box::new(ConfigRecord {
                update: vec![ConfigItem {
                    nested_key: vec!["lr".into()],
                    value_json: "0.01".into(),
                    ..Default::default()
                }],
                ..Default::default()
            })),
            ..Default::default()
        }));
        assert_eq!(
            r.left_sidebar.active_section, 1,
            "initial single-run focus should land on the first populated overview section"
        );

        r.handle_record_msg(&Event::SystemInfo(SystemInfoMsg {
            record: Some(Box::new(EnvironmentRecord {
                writer_id: "w1".into(),
                os: "linux".into(),
                ..Default::default()
            })),
            ..Default::default()
        }));
        r.handle_record_msg(&Event::Summary(SummaryMsg {
            summary: vec![SummaryRecord {
                update: vec![SummaryItem {
                    nested_key: vec!["loss".into()],
                    value_json: "0.42".into(),
                    ..Default::default()
                }],
                ..Default::default()
            }],
            ..Default::default()
        }));

        r.update(&tab());
        assert_eq!(
            r.left_sidebar.active_section, 2,
            "Tab should continue from Config to Summary after overview updates arrive"
        );
    }

    // ---- Unified navigation: wasd/arrows aliasing + Home/End ----

    /// Go: TestRun_UnifiedNav_OverviewUsesCanonicalKeys.
    #[test]
    fn run_unified_nav_overview_uses_canonical_keys() {
        let dir = tempfile::tempdir().unwrap();
        let mut r = new_run_for_handler_test(&dir);
        let (before, _) = r.left_sidebar.selected_item();

        r.update(&Event::Key(primary_nav_msg(NavIntent::Down)));
        let (after_primary_down, _) = r.left_sidebar.selected_item();
        assert!(!before.is_empty());
        assert_ne!(
            before, after_primary_down,
            "the primary down binding should move the overview selection"
        );

        r.update(&Event::Key(primary_nav_msg(NavIntent::Up)));
        assert_eq!(
            before,
            must_selected_item(&r.left_sidebar),
            "the primary up binding should undo the down move"
        );

        r.update(&Event::Key(secondary_nav_msg(NavIntent::Down)));
        assert_eq!(
            after_primary_down,
            must_selected_item(&r.left_sidebar),
            "the secondary down binding should match the primary binding"
        );

        r.update(&Event::Key(primary_nav_msg(NavIntent::Home)));
        let (after_home, _) = r.left_sidebar.selected_item();
        assert_eq!(before, after_home, "Home should return to the first item");

        r.update(&Event::Key(primary_nav_msg(NavIntent::End)));
        let (after_end, _) = r.left_sidebar.selected_item();
        assert_ne!(
            after_home, after_end,
            "End should move the cursor away from the Home position"
        );
    }

    /// Go: TestRun_UnifiedNav_GridUsesCanonicalDirectionalKeys.
    #[test]
    fn run_unified_nav_grid_uses_canonical_directional_keys() {
        let dir = tempfile::tempdir().unwrap();
        let mut r = new_run_for_handler_test(&dir);

        // Seed enough metrics to form a 2x2 grid.
        r.handle_record_msg(&Event::History(HistoryMsg {
            metrics: HashMap::from([
                (
                    "a".to_string(),
                    crate::event::MetricData {
                        x: vec![1.0],
                        y: vec![1.0],
                    },
                ),
                (
                    "b".to_string(),
                    crate::event::MetricData {
                        x: vec![1.0],
                        y: vec![2.0],
                    },
                ),
                (
                    "c".to_string(),
                    crate::event::MetricData {
                        x: vec![1.0],
                        y: vec![3.0],
                    },
                ),
                (
                    "d".to_string(),
                    crate::event::MetricData {
                        x: vec![1.0],
                        y: vec![4.0],
                    },
                ),
            ]),
            ..Default::default()
        }));

        // Focus the metrics grid (Go TestSetFocusTarget +
        // TestSetMainChartFocus).
        r.with_focus_mgr(|fm, r| fm.set_target(r, FocusTarget::MetricsGrid, 1));
        r.metrics_grid.set_focus(0, 0);

        {
            let focus = r.focus.borrow();
            assert_eq!(focus.focus_type, FocusType::MainChart);
            assert_eq!(focus.row, 0);
            assert_eq!(focus.col, 0);
        }

        r.update(&Event::Key(primary_nav_msg(NavIntent::Right)));
        assert_eq!(
            r.focus.borrow().col,
            1,
            "the primary right binding should advance chart focus"
        );

        r.metrics_grid.set_focus(0, 0);
        r.update(&Event::Key(secondary_nav_msg(NavIntent::Right)));
        assert_eq!(
            r.focus.borrow().col,
            1,
            "the secondary right binding should match the primary binding"
        );

        r.metrics_grid.set_focus(0, 0);
        r.update(&Event::Key(secondary_nav_msg(NavIntent::Down)));
        assert_eq!(
            r.focus.borrow().row,
            1,
            "the secondary down binding should advance chart focus vertically"
        );
    }

    fn must_selected_item(sidebar: &RunOverviewSidebar) -> String {
        let (key, _) = sidebar.selected_item();
        assert!(!key.is_empty());
        key
    }

    // ---- liveread_test.go — the two Run legs (PARITY.md §5.1) ----

    /// Go `stubHistorySource` (liveread_test.go:16-30): records the
    /// (chunkSize, maxTime) it was called with.
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

    /// Executes a `Command::ReadLiveBatch` against a stub source exactly as
    /// the runtime does: the effect runner maps the command to a
    /// `ReadRequest` with the LiveMonitor bounds (runtime.rs
    /// `Command::ReadLiveBatch` dispatch) and the reader thread runs
    /// `execute_read` — together these are the body of Go's
    /// `ReadLiveBatchCmd` closure.
    fn invoke_read_live_batch(r: &Run, source: &mut StubHistorySource) -> Option<Event> {
        let cmds =
            r.read_live_batch_cmd(Some(crate::event::HistorySourceHandle { id: SourceId(7) }));
        let [Command::ReadLiveBatch { source: id }] = cmds[..] else {
            panic!("expected a single ReadLiveBatch, got {cmds:?}");
        };
        assert_eq!(id, SourceId(7));
        execute_read(
            source,
            ReadRequest {
                kind: ReadKind::LiveBatch,
                chunk_size: LIVE_MONITOR_CHUNK_SIZE,
                max_time_per_chunk: LIVE_MONITOR_MAX_TIME,
            },
        )
    }

    /// Go: TestRun_ReadLiveBatchCmd_WrapsChunkedBatchAndUsesLiveLimits
    /// (liveread_test.go:41).
    #[test]
    fn run_read_live_batch_cmd_wraps_chunked_batch_and_uses_live_limits() {
        let dir = tempfile::tempdir().unwrap();
        let cfg = test_config(&dir);
        let r = Run::new(
            RunParams {
                run_file: "dummy".into(),
                remote: None,
            },
            Some(cfg),
        );

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

        let msg = invoke_read_live_batch(&r, &mut src);
        let Some(Event::BatchedRecords(batch)) = msg else {
            panic!("expected BatchedRecords, got {msg:?}");
        };
        assert_eq!(batch.msgs.len(), 1);
        assert_eq!(src.chunk_size, LIVE_MONITOR_CHUNK_SIZE);
        assert_eq!(src.max_time, LIVE_MONITOR_MAX_TIME);
    }

    /// Go: TestRun_ReadLiveBatchCmd_DropsEmptyChunk (liveread_test.go:69).
    #[test]
    fn run_read_live_batch_cmd_drops_empty_chunk() {
        let dir = tempfile::tempdir().unwrap();
        let cfg = test_config(&dir);
        let r = Run::new(
            RunParams {
                run_file: "dummy".into(),
                remote: None,
            },
            Some(cfg),
        );

        let mut src = StubHistorySource::new(Some(SourceMsg::ChunkedBatch(
            hs::ChunkedBatchMsg::default(),
        )));
        assert_eq!(invoke_read_live_batch(&r, &mut src), None);
    }
}
