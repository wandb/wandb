//! The single-run view: metrics grid, sidebars, media, and console logs.

use std::sync::mpsc::Sender;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use crossterm::event::{KeyCode, KeyEvent, KeyModifiers, MouseButton, MouseEvent, MouseEventKind};
use ratatui::buffer::Buffer;
use ratatui::layout::Rect;

use crate::animation::AnimatedValue;
use crate::config::{ConfigManager, GridConfigTarget, LayoutOverrides};
use crate::consolelogs::{CONSOLE_LOGS_PANE_MIN_HEIGHT, ConsoleLogsPane, RunConsoleLogs};
use crate::filter::FilterKey;
use crate::flexlayout::{StackSection, StackSectionSpec, compute_vertical_stack_layout};
use crate::focusmanager::{FocusContext, FocusManager, FocusTarget};
use crate::grid::FocusType;
use crate::media::pane::{LOWER_TIER_RATIO, MEDIA_PANE_MIN_HEIGHT, MediaPane};
use crate::media::store::MediaStore;
use crate::metricsgrid::{MetricsGrid, render_metrics_empty_state};
use crate::msg::{Msg, RecordMsg};
use crate::nav::{NavIntent, decode_nav};
use crate::rightsidebar::RightSidebar;
use crate::runoverview::{RunOverview, RunState};
use crate::sidebar::{RunOverviewSidebar, SidebarSide};
use crate::store::live::{ReaderHandle, spawn_reader};
use crate::systemgrid::SystemGridSettings;
use crate::theme::{
    self, CONTENT_PADDING, MEDIUM_SHADE_BLOCK, SIDEBAR_MIN_WIDTH, STATUS_BAR_HEIGHT,
};

const STATUS_BAR_PADDING: u16 = 1;
const MIN_RUN_MAIN_CONTENT_WIDTH: i32 = 10;

/// Minimum height kept for the flexible metrics grid while dragging the
/// separator directly below it.
const MIN_FLEX_METRICS_HEIGHT: i32 = 5;

/// An action the parent model should take after an input event.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RunAction {
    None,
    Quit,
}

/// Computed layout for the single-run view.
#[derive(Debug, Clone, Copy, Default)]
pub struct RunLayout {
    pub left_sidebar_width: i32,
    pub main_content_area_width: i32,
    pub right_sidebar_width: i32,
    pub total_content_area_height: i32,
    /// Metrics grid height.
    pub height: i32,
    pub media_y: i32,
    pub media_height: i32,
    pub console_logs_y: i32,
    pub console_logs_height: i32,
}

/// Holds data/state related to a single W&B run.
pub struct RunView {
    width: i32,
    height: i32,

    run_path: String,
    run_state: RunState,
    is_loading: bool,

    reader: Option<ReaderHandle>,

    focus_mgr: FocusManager,

    metrics_grid_anim: AnimatedValue,
    pub metrics_grid: MetricsGrid,
    pub run_overview: RunOverview,
    pub left_sidebar: RunOverviewSidebar,
    pub right_sidebar: RightSidebar,
    console_logs: RunConsoleLogs,
    pub console_logs_pane: ConsoleLogsPane,
    /// Revision last pushed into the pane, to skip re-syncing.
    console_logs_synced: u64,
    pub media_store: MediaStore,
    pub media_pane: MediaPane,

    records_loaded: usize,
    last_error: String,

    /// User-set pane proportions (mirrors `config.run_layout`).
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

fn system_grid_settings(cfg: &crate::config::Config) -> SystemGridSettings {
    SystemGridSettings {
        rows: cfg.system_grid.rows,
        cols: cfg.system_grid.cols,
        color_scheme: cfg.system_color_scheme.clone(),
        color_mode: cfg.system_color_mode.clone(),
        french_fries_scheme: cfg.french_fries_color_scheme.clone(),
        tail_window_secs: cfg.system_tail_window_secs(),
    }
}

impl RunView {
    pub fn new(run_path: String, config: &ConfigManager) -> Self {
        let cfg = config.config();

        let mut metrics_grid = MetricsGrid::new(
            cfg.metrics_grid.rows,
            cfg.metrics_grid.cols,
            &cfg.color_scheme,
            &cfg.per_plot_color_scheme,
        );
        metrics_grid.set_single_series_color_mode(&cfg.single_run_color_mode);

        let mut left_sidebar = RunOverviewSidebar::new(
            AnimatedValue::new(cfg.left_sidebar_visible, SIDEBAR_MIN_WIDTH),
            SidebarSide::Left,
        );
        left_sidebar.set_tag_color_scheme(&cfg.tag_color_scheme);

        let mut media_pane =
            MediaPane::new(AnimatedValue::new(cfg.media_visible, MEDIA_PANE_MIN_HEIGHT));
        media_pane.set_grid_config(cfg.media_grid.rows, cfg.media_grid.cols);

        let mut run = Self {
            width: 0,
            height: 0,
            run_path,
            run_state: RunState::Unknown,
            is_loading: true,
            reader: None,
            focus_mgr: FocusManager::new(vec![
                FocusTarget::Overview,
                FocusTarget::MetricsGrid,
                FocusTarget::Media,
                FocusTarget::ConsoleLogs,
                FocusTarget::SystemMetrics,
            ]),
            metrics_grid_anim: AnimatedValue::new(cfg.metrics_grid_visible, 1),
            metrics_grid,
            run_overview: RunOverview::new(),
            left_sidebar,
            right_sidebar: RightSidebar::new(cfg.right_sidebar_visible, system_grid_settings(cfg)),
            console_logs: RunConsoleLogs::new(),
            console_logs_pane: ConsoleLogsPane::new(AnimatedValue::new(
                cfg.console_logs_visible,
                CONSOLE_LOGS_PANE_MIN_HEIGHT,
            )),
            console_logs_synced: u64::MAX,
            media_store: MediaStore::new(),
            media_pane,
            records_loaded: 0,
            last_error: String::new(),
            layout: cfg.run_layout,
            drag: None,
        };
        run.left_sidebar.set_width_fraction(run.layout.left_sidebar);
        run.right_sidebar
            .set_width_fraction(run.layout.right_sidebar);
        run
    }

    /// Starts the background reader for this run's transaction log.
    pub fn start(&mut self, tx: Sender<Msg>) {
        self.reader = Some(spawn_reader(self.run_path.clone(), tx));
    }

    /// Stops the background reader.
    pub fn cleanup(&mut self) {
        self.reader = None;
    }

    pub fn run_path(&self) -> &str {
        &self.run_path
    }

    /// The reader source id for message routing, if started.
    pub fn source_id(&self) -> Option<u64> {
        self.reader.as_ref().map(|r| r.source_id)
    }

    pub fn is_loading(&self) -> bool {
        self.is_loading
    }

    pub fn media_fullscreen(&self) -> bool {
        self.media_pane.is_fullscreen()
    }

    pub fn is_filtering(&self) -> bool {
        self.metrics_grid.is_filter_mode()
            || self.left_sidebar.is_filter_mode()
            || self.right_sidebar.is_filter_mode()
    }

    /// The title of the currently focused chart, if any.
    fn focused_title(&self) -> Option<String> {
        match self.focus_mgr.current() {
            FocusTarget::MetricsGrid if self.metrics_grid.focus.ty == FocusType::MainChart => {
                Some(self.metrics_grid.focus.title.clone())
            }
            FocusTarget::SystemMetrics
                if self.right_sidebar.metrics_grid.focus.ty == FocusType::SystemChart =>
            {
                Some(self.right_sidebar.metrics_grid.focus.title.clone())
            }
            _ => None,
        }
    }

    // ---- Data ----

    /// Handles a message from the background reader.
    pub fn handle_msg(&mut self, msg: Msg) {
        match msg {
            Msg::Batch {
                source_id,
                msgs,
                progress,
                ..
            } => {
                let Some(reader) = &self.reader else { return };
                if reader.source_id != source_id {
                    return;
                }
                self.records_loaded += progress;
                let mut should_draw = false;
                for record in msgs {
                    should_draw |= self.handle_record(record);
                }
                if should_draw {
                    self.metrics_grid.draw_visible();
                }
                self.resolve_focus_after_availability_change();
            }
            Msg::ReaderError { source_id, error } => {
                if self.reader.as_ref().map(|r| r.source_id) != Some(source_id) {
                    return;
                }
                self.is_loading = false;
                self.last_error = error;
                self.run_state = RunState::Failed;
                self.run_overview.set_run_state(self.run_state);
                self.left_sidebar.sync(&self.run_overview);
            }
            _ => {}
        }
    }

    /// Processes one record. Returns whether new history data arrived.
    fn handle_record(&mut self, record: RecordMsg) -> bool {
        match record {
            RecordMsg::Run(msg) => {
                self.last_error.clear();
                self.run_overview.process_run_msg(&msg);
                self.left_sidebar.sync(&self.run_overview);
                self.run_state = RunState::Running;
                self.is_loading = false;
            }
            RecordMsg::History(msg) => {
                let should_draw = self.metrics_grid.process_history(&msg);
                if self.media_store.process_history(&msg) {
                    self.media_pane.sync_state(&self.media_store);
                }
                return should_draw;
            }
            RecordMsg::Stats(msg) => {
                self.right_sidebar.process_stats(&msg);
            }
            RecordMsg::SystemInfo { record, .. } => {
                self.run_overview.process_system_info(&record);
                self.left_sidebar.sync(&self.run_overview);
            }
            RecordMsg::Summary { summary, .. } => {
                self.run_overview.process_summary(&summary);
                self.left_sidebar.sync(&self.run_overview);
            }
            RecordMsg::ConsoleLog(msg) => {
                let ts = msg
                    .time
                    .unwrap_or_else(SystemTime::now)
                    .duration_since(UNIX_EPOCH)
                    .map(|d| d.as_secs() as i64)
                    .unwrap_or(0);
                self.console_logs.process_raw(&msg.text, msg.is_stderr, ts);
            }
            RecordMsg::FileComplete { exit_code } => {
                self.run_state = if exit_code == 0 {
                    RunState::Finished
                } else {
                    RunState::Failed
                };
                self.run_overview.set_run_state(self.run_state);
                self.left_sidebar.sync(&self.run_overview);
            }
        }
        false
    }

    // ---- Animation ----

    /// Advances all animations. Returns true while any is still animating.
    pub fn tick(&mut self, now: Instant) -> bool {
        let mut changed = false;

        if self.left_sidebar.is_animating() {
            self.left_sidebar.update_animation(now);
            changed = true;
        }
        if self.right_sidebar.is_animating() {
            self.right_sidebar.update(now);
            changed = true;
        }
        if self.metrics_grid_anim.is_animating() {
            self.metrics_grid_anim.update(now);
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
            self.left_sidebar
                .update_dimensions(self.width, self.right_sidebar.anim_state.target_visible());
            self.right_sidebar
                .update_dimensions(self.width, self.left_sidebar.target_visible());
            self.update_bottom_pane_heights(
                self.media_pane.target_visible(),
                self.console_logs_pane.target_visible(),
            );
            let layout = self.compute_viewports();
            self.metrics_grid
                .update_dimensions(layout.main_content_area_width, layout.height);
        }

        self.left_sidebar.is_animating()
            || self.right_sidebar.is_animating()
            || self.metrics_grid_anim.is_animating()
            || self.media_pane.is_animating()
            || self.console_logs_pane.is_animating()
    }

    fn is_animating(&self) -> bool {
        self.left_sidebar.is_animating()
            || self.right_sidebar.is_animating()
            || self.media_pane.is_animating()
            || self.console_logs_pane.is_animating()
    }

    // ---- Layout ----

    pub fn handle_resize(&mut self, width: i32, height: i32) {
        self.width = width;
        self.height = height;

        self.left_sidebar
            .update_dimensions(width, self.right_sidebar.anim_state.target_visible());
        self.right_sidebar
            .update_dimensions(width, self.left_sidebar.target_visible());
        self.update_bottom_pane_heights(
            self.media_pane.target_visible(),
            self.console_logs_pane.target_visible(),
        );

        let layout = self.compute_viewports();
        self.metrics_grid
            .update_dimensions(layout.main_content_area_width, layout.height);
        self.resolve_focus_after_availability_change();
    }

    /// Distributes the lower tier height between the media and console logs
    /// panes based on the visibility state being configured toward.
    fn update_bottom_pane_heights(&mut self, media_visible: bool, logs_visible: bool) {
        let metrics_visible = self.metrics_grid_anim.target_visible();

        let section_count = [metrics_visible, media_visible, logs_visible]
            .iter()
            .filter(|&&v| v)
            .count() as i32;
        let sep_lines = (section_count - 1).max(0);

        let max_h = (self.height - STATUS_BAR_HEIGHT as i32 - sep_lines).max(0);
        let lower_count = [media_visible, logs_visible].iter().filter(|&&v| v).count() as i32;
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
        if media_visible {
            self.media_pane
                .set_expanded_height(h_for(self.layout.media));
        }
        if logs_visible {
            self.console_logs_pane
                .set_expanded_height(h_for(self.layout.logs));
        }
    }

    /// Recomputes viewports and pushes dimensions to the metrics grid.
    fn recalculate_layout(&mut self) {
        let layout = self.compute_viewports();
        self.metrics_grid
            .update_dimensions(layout.main_content_area_width, layout.height);
    }

    /// The widths that can actually be rendered without starving the main
    /// content area. Only clamps this layout pass; visibility preferences
    /// remain unchanged.
    fn effective_sidebar_widths(&self) -> (i32, i32) {
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

    pub fn compute_viewports(&self) -> RunLayout {
        let (left_w, right_w) = self.effective_sidebar_widths();
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

        RunLayout {
            left_sidebar_width: left_w,
            main_content_area_width: content_w,
            right_sidebar_width: right_w,
            total_content_area_height: total_h,
            height: stack.height(StackSection::Metrics),
            media_y: stack.y(StackSection::Media),
            media_height: stack.height(StackSection::Media),
            console_logs_y: stack.y(StackSection::ConsoleLogs),
            console_logs_height: stack.height(StackSection::ConsoleLogs),
        }
    }

    // ---- Focus ----

    fn with_focus_mgr(&mut self, f: impl FnOnce(&mut FocusManager, &mut Self)) {
        let mut fm = std::mem::take(&mut self.focus_mgr);
        f(&mut fm, self);
        self.focus_mgr = fm;
    }

    fn resolve_focus_after_availability_change(&mut self) {
        self.with_focus_mgr(|fm, view| fm.resolve_after_availability_change(view));
    }

    fn resolve_focus_after_visibility_change(&mut self) {
        self.with_focus_mgr(|fm, view| fm.resolve_after_visibility_change(view));
    }

    fn adopt_chart_mouse_focus(&mut self) {
        let target = if self.metrics_grid.focus.ty == FocusType::MainChart {
            FocusTarget::MetricsGrid
        } else if self.right_sidebar.metrics_grid.focus.ty == FocusType::SystemChart {
            FocusTarget::SystemMetrics
        } else {
            return;
        };
        self.with_focus_mgr(|fm, view| fm.adopt_target(view, target));
    }

    /// Tries to move within overview sections. Returns true if handled
    /// (i.e. we're not at a boundary).
    fn cycle_run_overview_section(&mut self, direction: i32) -> bool {
        let Some((first, last)) = self.left_sidebar.focusable_section_bounds() else {
            return false;
        };
        if !self.left_sidebar.is_expanded() {
            return false;
        }

        let active = self.left_sidebar.active_section();
        let at_boundary =
            (direction == 1 && active == last) || (direction == -1 && active == first);
        if at_boundary {
            return false;
        }

        self.left_sidebar.navigate_section(direction);
        true
    }

    // ---- Keys ----

    pub fn handle_key(&mut self, key: &KeyEvent, config: &mut ConfigManager) -> RunAction {
        // Filter modes take priority.
        if self.left_sidebar.is_filter_mode() {
            if let Some(fk) = FilterKey::from_event(key) {
                self.left_sidebar.handle_filter_key(fk, &self.run_overview);
            }
            return RunAction::None;
        }
        if self.metrics_grid.is_filter_mode() {
            if let Some(fk) = FilterKey::from_event(key) {
                self.metrics_grid.handle_filter_key(fk);
            }
            return RunAction::None;
        }
        if self.right_sidebar.is_filter_mode() {
            if let Some(fk) = FilterKey::from_event(key) {
                self.right_sidebar.handle_filter_key(fk);
            }
            return RunAction::None;
        }

        // Grid config capture takes priority.
        if config.is_awaiting_grid_config() {
            self.handle_config_number_key(key, config);
            return RunAction::None;
        }

        // Focus-aware key dispatch.
        match self.focus_mgr.current() {
            FocusTarget::MetricsGrid | FocusTarget::SystemMetrics => {
                if self.handle_grid_nav(key) {
                    return RunAction::None;
                }
            }
            FocusTarget::Media => {
                if self.media_pane.handle_key(key, &self.media_store) {
                    return RunAction::None;
                }
            }
            _ => {}
        }

        let ctrl = key.modifiers.contains(KeyModifiers::CONTROL);
        match key.code {
            KeyCode::Char('q') => return RunAction::Quit,
            KeyCode::Char('c') if ctrl => return RunAction::Quit,

            KeyCode::Char('1') => self.toggle_metrics_grid(config),
            KeyCode::Char('[') => self.toggle_left_sidebar(config),
            KeyCode::Char(']') | KeyCode::Char('2') => self.toggle_right_sidebar(config),
            KeyCode::Char('3') => self.toggle_media_pane(config),
            KeyCode::Char('4') => self.toggle_console_logs_pane(config),
            KeyCode::Char('0') => self.reset_layout(config),

            KeyCode::Char('y') => self.cycle_focused_chart_mode(),

            KeyCode::Char('/') if ctrl => self.clear_metrics_filter(),
            KeyCode::Char('l') if ctrl => self.clear_metrics_filter(),
            KeyCode::Char('\\') if ctrl => self.clear_system_metrics_filter(),
            KeyCode::Char('o') if ctrl => {
                if self.left_sidebar.is_filtering() {
                    self.left_sidebar.clear_filter(&self.run_overview);
                }
            }
            KeyCode::Char('/') => self.metrics_grid.enter_filter_mode(),
            KeyCode::Char('\\') => self.enter_system_metrics_filter(config),
            KeyCode::Char('o') => self.left_sidebar.enter_filter_mode(),

            KeyCode::Char('c') => self.config_focused_cols(config),
            KeyCode::Char('r') => self.config_focused_rows(config),

            KeyCode::Tab => self.handle_sidebar_tab_nav(1),
            KeyCode::BackTab => self.handle_sidebar_tab_nav(-1),

            _ => match decode_nav(key) {
                NavIntent::Up => self.handle_sidebar_vertical_nav(true),
                NavIntent::Down => self.handle_sidebar_vertical_nav(false),
                NavIntent::Left => self.handle_sidebar_page_nav(true),
                NavIntent::Right => self.handle_sidebar_page_nav(false),
                NavIntent::PageUp => self.handle_prev_page(),
                NavIntent::PageDown => self.handle_next_page(),
                NavIntent::Home => self.handle_nav_home(),
                NavIntent::End => self.handle_nav_end(),
                _ => {}
            },
        }

        RunAction::None
    }

    fn handle_config_number_key(&mut self, key: &KeyEvent, config: &mut ConfigManager) {
        let digit = match key.code {
            KeyCode::Esc => None,
            KeyCode::Char(c) => c.to_digit(10),
            _ => None,
        };
        if let Some(num) = digit
            && config.set_grid_config(num as i32).is_some()
        {
            self.sync_grid_shapes_from_config(config);
            let layout = self.compute_viewports();
            self.metrics_grid
                .update_dimensions(layout.main_content_area_width, layout.height);
        }
        config.set_pending_grid_config(GridConfigTarget::None);
    }

    /// Propagates configured grid shapes to the grids/panes after a change.
    fn sync_grid_shapes_from_config(&mut self, config: &ConfigManager) {
        let cfg = config.config();
        self.metrics_grid
            .set_grid_shape(cfg.metrics_grid.rows, cfg.metrics_grid.cols);
        self.right_sidebar
            .metrics_grid
            .set_settings(system_grid_settings(cfg));
        self.media_pane
            .set_grid_config(cfg.media_grid.rows, cfg.media_grid.cols);
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
                    self.right_sidebar.metrics_grid.$m($($a),*);
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
            FocusTarget::SystemMetrics => self.right_sidebar.metrics_grid.navigate(-1),
            FocusTarget::Media => self.media_pane.navigate_page(&self.media_store, -1),
            FocusTarget::Overview => self.left_sidebar.navigate_page_up(),
            FocusTarget::ConsoleLogs => self.console_logs_pane.page_up(),
            _ => {}
        }
    }

    fn handle_next_page(&mut self) {
        match self.focus_mgr.current() {
            FocusTarget::MetricsGrid => self.metrics_grid.navigate(1),
            FocusTarget::SystemMetrics => self.right_sidebar.metrics_grid.navigate(1),
            FocusTarget::Media => self.media_pane.navigate_page(&self.media_store, 1),
            FocusTarget::Overview => self.left_sidebar.navigate_page_down(),
            FocusTarget::ConsoleLogs => self.console_logs_pane.page_down(),
            _ => {}
        }
    }

    fn handle_nav_home(&mut self) {
        match self.focus_mgr.current() {
            FocusTarget::MetricsGrid => self.metrics_grid.navigate_home(),
            FocusTarget::SystemMetrics => self.right_sidebar.metrics_grid.navigate_home(),
            FocusTarget::Media => self.media_pane.scrub_to_start(&self.media_store),
            FocusTarget::Overview => self.left_sidebar.navigate_home(),
            FocusTarget::ConsoleLogs => self.console_logs_pane.scroll_to_start(),
            _ => {}
        }
    }

    fn handle_nav_end(&mut self) {
        match self.focus_mgr.current() {
            FocusTarget::MetricsGrid => self.metrics_grid.navigate_end(),
            FocusTarget::SystemMetrics => self.right_sidebar.metrics_grid.navigate_end(),
            FocusTarget::Media => self.media_pane.scrub_to_end(&self.media_store),
            FocusTarget::Overview => self.left_sidebar.navigate_end(),
            FocusTarget::ConsoleLogs => self.console_logs_pane.scroll_to_end_and_follow(),
            _ => {}
        }
    }

    fn cycle_focused_chart_mode(&mut self) {
        if self.metrics_grid.focus.ty == FocusType::MainChart {
            self.metrics_grid.toggle_focused_chart_log_y();
        } else if self.right_sidebar.metrics_grid.focus.ty == FocusType::SystemChart {
            self.right_sidebar.metrics_grid.cycle_focused_chart_mode();
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
        if !config.config().right_sidebar_visible {
            self.toggle_right_sidebar(config);
        }
        self.right_sidebar.metrics_grid.enter_filter_mode();
        self.right_sidebar.metrics_grid.apply_filter();
    }

    fn clear_system_metrics_filter(&mut self) {
        if !self.right_sidebar.metrics_grid.filter_query().is_empty() {
            self.right_sidebar.metrics_grid.clear_filter();
        }
        if self.focus_mgr.current() == FocusTarget::SystemMetrics {
            self.right_sidebar.metrics_grid.navigate_focus(0, 0);
        }
    }

    fn config_focused_cols(&mut self, config: &mut ConfigManager) {
        let target = match self.focus_mgr.current() {
            FocusTarget::SystemMetrics => GridConfigTarget::SystemCols,
            FocusTarget::Media => GridConfigTarget::MediaCols,
            _ => GridConfigTarget::MetricsCols,
        };
        config.set_pending_grid_config(target);
    }

    fn config_focused_rows(&mut self, config: &mut ConfigManager) {
        let target = match self.focus_mgr.current() {
            FocusTarget::SystemMetrics => GridConfigTarget::SystemRows,
            FocusTarget::Media => GridConfigTarget::MediaRows,
            _ => GridConfigTarget::MetricsRows,
        };
        config.set_pending_grid_config(target);
    }

    /// Cycles focus between panes; within the overview region, Tab first
    /// cycles through sections.
    fn handle_sidebar_tab_nav(&mut self, direction: i32) {
        if self.focus_mgr.is_target(FocusTarget::Overview)
            && self.cycle_run_overview_section(direction)
        {
            return;
        }
        self.with_focus_mgr(|fm, view| fm.tab(view, direction));
    }

    fn handle_sidebar_vertical_nav(&mut self, up: bool) {
        match self.focus_mgr.current() {
            FocusTarget::Media => {
                // Media pane keeps arrow-vs-letter distinction: arrows scrub by 10.
                self.media_pane
                    .scrub(&self.media_store, if up { -10 } else { 10 });
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
    }

    fn handle_sidebar_page_nav(&mut self, left: bool) {
        match self.focus_mgr.current() {
            FocusTarget::Media => {
                self.media_pane
                    .scrub(&self.media_store, if left { -1 } else { 1 });
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
    }

    // ---- Pane toggles ----

    fn toggle_metrics_grid(&mut self, config: &mut ConfigManager) {
        let will_be_visible = !self.metrics_grid_anim.target_visible();
        config.update(|c| c.metrics_grid_visible = will_be_visible);

        self.metrics_grid_anim.toggle();
        self.resolve_focus_after_visibility_change();

        self.update_bottom_pane_heights(
            self.media_pane.target_visible(),
            self.console_logs_pane.target_visible(),
        );
        let layout = self.compute_viewports();
        self.metrics_grid
            .update_dimensions(layout.main_content_area_width, layout.height);
    }

    fn toggle_left_sidebar(&mut self, config: &mut ConfigManager) {
        if self.is_animating() {
            return;
        }
        let will_be_visible = !self.left_sidebar.target_visible();
        config.update(|c| c.left_sidebar_visible = will_be_visible);

        self.left_sidebar
            .update_dimensions(self.width, self.right_sidebar.anim_state.target_visible());
        self.right_sidebar
            .update_dimensions(self.width, will_be_visible);
        self.left_sidebar.toggle();
        self.resolve_focus_after_visibility_change();

        let layout = self.compute_viewports();
        self.metrics_grid
            .update_dimensions(layout.main_content_area_width, layout.height);
    }

    fn toggle_right_sidebar(&mut self, config: &mut ConfigManager) {
        if self.is_animating() {
            return;
        }
        let will_be_visible = !self.right_sidebar.anim_state.target_visible();
        config.update(|c| c.right_sidebar_visible = will_be_visible);

        self.right_sidebar
            .update_dimensions(self.width, self.left_sidebar.target_visible());
        self.left_sidebar
            .update_dimensions(self.width, will_be_visible);
        self.right_sidebar.toggle();
        self.resolve_focus_after_visibility_change();

        let layout = self.compute_viewports();
        self.metrics_grid
            .update_dimensions(layout.main_content_area_width, layout.height);
    }

    fn toggle_media_pane(&mut self, config: &mut ConfigManager) {
        if self.is_animating() {
            return;
        }
        let will_be_visible = !self.media_pane.target_visible();
        config.update(|c| c.media_visible = will_be_visible);

        if !will_be_visible {
            self.media_pane.exit_fullscreen();
        }
        self.media_pane.toggle();
        self.update_bottom_pane_heights(will_be_visible, self.console_logs_pane.target_visible());
        if !will_be_visible {
            self.resolve_focus_after_visibility_change();
        }

        let layout = self.compute_viewports();
        self.metrics_grid
            .update_dimensions(layout.main_content_area_width, layout.height);
    }

    fn toggle_console_logs_pane(&mut self, config: &mut ConfigManager) {
        if self.is_animating() {
            return;
        }
        let will_be_visible = !self.console_logs_pane.target_visible();
        config.update(|c| c.console_logs_visible = will_be_visible);

        self.console_logs_pane.toggle();
        self.update_bottom_pane_heights(self.media_pane.target_visible(), will_be_visible);
        self.resolve_focus_after_visibility_change();

        let layout = self.compute_viewports();
        self.metrics_grid
            .update_dimensions(layout.main_content_area_width, layout.height);
    }

    // ---- Mouse ----

    /// Handles mouse-driven pane resizing on the sidebar borders and the
    /// separator rows. Returns whether the event was consumed.
    fn handle_layout_drag(
        &mut self,
        event: &MouseEvent,
        layout: &RunLayout,
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
                config.update(|c| c.run_layout = overrides);
                true
            }
            _ => false,
        }
    }

    /// The draggable boundary at (x, y), if any: a sidebar border column or
    /// a separator row between stacked panes.
    fn boundary_at(&self, x: i32, y: i32, layout: &RunLayout) -> Option<DragBoundary> {
        if y >= layout.total_content_area_height {
            return None;
        }

        if layout.left_sidebar_width > 0
            && self.left_sidebar.is_expanded()
            && x == layout.left_sidebar_width - 1
        {
            return Some(DragBoundary::LeftSidebar);
        }
        if layout.right_sidebar_width > 0
            && self.right_sidebar.anim_state.is_expanded()
            && x == self.width - layout.right_sidebar_width
        {
            return Some(DragBoundary::RightSidebar);
        }

        // Separator rows only exist within the central column.
        if x < layout.left_sidebar_width || x >= self.width - layout.right_sidebar_width {
            return None;
        }
        for section in [StackSection::Media, StackSection::ConsoleLogs] {
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
                self.left_sidebar
                    .set_width_fraction(self.layout.left_sidebar);
            }
            DragBoundary::RightSidebar => {
                self.layout.right_sidebar = Some((self.width - x) as f64 / width);
                self.right_sidebar
                    .set_width_fraction(self.layout.right_sidebar);
            }
            DragBoundary::Separator(section) => self.drag_separator(section, y),
        }

        self.left_sidebar
            .update_dimensions(self.width, self.right_sidebar.anim_state.target_visible());
        self.right_sidebar
            .update_dimensions(self.width, self.left_sidebar.target_visible());
        self.update_bottom_pane_heights(
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
        let prev = [StackSection::Metrics, StackSection::Media]
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
        match section {
            StackSection::Media => self.layout.media = Some((bottom - y - 1) as f64 / height),
            StackSection::ConsoleLogs => self.layout.logs = Some((bottom - y - 1) as f64 / height),
            _ => {}
        }
        if prev == StackSection::Media {
            self.layout.media = Some((y - prev_y) as f64 / height);
        }
    }

    /// (y, height, min height) of a stack section in the current layout.
    fn section_geom(layout: &RunLayout, section: StackSection) -> (i32, i32, i32) {
        match section {
            StackSection::Metrics => (0, layout.height, MIN_FLEX_METRICS_HEIGHT),
            StackSection::Media => (layout.media_y, layout.media_height, MEDIA_PANE_MIN_HEIGHT),
            StackSection::ConsoleLogs => (
                layout.console_logs_y,
                layout.console_logs_height,
                CONSOLE_LOGS_PANE_MIN_HEIGHT,
            ),
            StackSection::SystemMetrics => (0, 0, 0),
        }
    }

    /// Resets pane proportions to the built-in defaults.
    fn reset_layout(&mut self, config: &mut ConfigManager) {
        self.layout = LayoutOverrides::default();
        self.left_sidebar.set_width_fraction(None);
        self.right_sidebar.set_width_fraction(None);
        config.update(|c| c.run_layout = LayoutOverrides::default());

        self.left_sidebar
            .update_dimensions(self.width, self.right_sidebar.anim_state.target_visible());
        self.right_sidebar
            .update_dimensions(self.width, self.left_sidebar.target_visible());
        self.update_bottom_pane_heights(
            self.media_pane.target_visible(),
            self.console_logs_pane.target_visible(),
        );
        self.recalculate_layout();
    }

    pub fn handle_mouse(&mut self, event: &MouseEvent, config: &mut ConfigManager) {
        let layout = self.compute_viewports();
        let x = event.column as i32;
        let y = event.row as i32;

        // Pane resizing wins over pane-local mouse handling.
        if self.handle_layout_drag(event, &layout, config) {
            return;
        }

        if x < layout.left_sidebar_width {
            self.metrics_grid.clear_focus();
            self.right_sidebar.clear_focus();
            return;
        }

        let right_start = self.width - layout.right_sidebar_width;
        if layout.right_sidebar_width > 0 && x >= right_start {
            self.handle_right_sidebar_mouse(event, x - right_start, y);
            return;
        }

        self.handle_main_content_mouse(event, layout);
    }

    fn handle_right_sidebar_mouse(&mut self, event: &MouseEvent, x: i32, y: i32) {
        let alt = event.modifiers.contains(KeyModifiers::ALT);
        match event.kind {
            MouseEventKind::Down(MouseButton::Left) => {
                self.metrics_grid.clear_focus();
                if self.right_sidebar.handle_mouse_click(x, y) {
                    self.adopt_chart_mouse_focus();
                }
            }
            MouseEventKind::Down(MouseButton::Right) => {
                self.metrics_grid.clear_focus();
                self.right_sidebar.start_inspection(x, y, alt);
                self.adopt_chart_mouse_focus();
            }
            MouseEventKind::Drag(MouseButton::Right) => {
                self.right_sidebar.update_inspection(x, y);
            }
            MouseEventKind::Up(MouseButton::Right) => {
                self.right_sidebar.end_inspection();
            }
            MouseEventKind::ScrollUp | MouseEventKind::ScrollDown => {
                self.metrics_grid.clear_focus();
                self.right_sidebar
                    .handle_wheel(x, y, event.kind == MouseEventKind::ScrollUp);
                self.adopt_chart_mouse_focus();
            }
            _ => {}
        }
    }

    fn handle_media_mouse(&mut self, event: &MouseEvent, layout: RunLayout) {
        if event.kind != MouseEventKind::Down(MouseButton::Left) {
            return;
        }
        let local_x = event.column as i32 - layout.left_sidebar_width;
        let local_y = event.row as i32 - layout.media_y;
        if local_x < 0 || local_y < 0 {
            return;
        }
        if self.media_pane.handle_mouse_click(
            &self.media_store,
            local_x as u16,
            local_y as u16,
            layout.main_content_area_width as u16,
            layout.media_height as u16,
        ) {
            self.media_pane.set_active(true);
            self.with_focus_mgr(|fm, view| fm.adopt_target(view, FocusTarget::Media));
        }
    }

    fn handle_main_content_mouse(&mut self, event: &MouseEvent, layout: RunLayout) {
        if self.media_pane.is_fullscreen() {
            return;
        }

        let y = event.row as i32;
        if layout.media_height > 0
            && y >= layout.media_y
            && y < layout.media_y + layout.media_height
        {
            self.handle_media_mouse(event, layout);
            return;
        }

        let alt = event.modifiers.contains(KeyModifiers::ALT);
        const HEADER_OFFSET: i32 = 1;

        let adjusted_x = event.column as i32 - layout.left_sidebar_width - CONTENT_PADDING as i32;
        let adjusted_y = y - HEADER_OFFSET;
        if adjusted_x < 0 || adjusted_y < 0 || adjusted_y >= layout.height {
            self.metrics_grid.clear_focus();
            self.right_sidebar.clear_focus();
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
                self.right_sidebar.clear_focus();
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

    // ---- Rendering ----

    pub fn render(&mut self, area: Rect, buf: &mut Buffer, config: &ConfigManager) {
        self.width = area.width as i32;
        self.height = area.height as i32;

        if area.width == 0 || area.height == 0 {
            return;
        }

        if self.is_loading {
            let logo_area = Rect {
                height: area.height.saturating_sub(STATUS_BAR_HEIGHT),
                ..area
            };
            theme::render_logo_art(logo_area, buf);
            self.render_status_bar(area, buf, config);
            return;
        }

        let layout = self.compute_viewports();
        let total_h = layout.total_content_area_height.max(0) as u16;

        if layout.left_sidebar_width > 0 {
            self.left_sidebar.render(
                Rect {
                    x: area.x,
                    y: area.y,
                    width: layout.left_sidebar_width as u16,
                    height: total_h,
                },
                buf,
                Some(&self.run_overview),
            );
        }

        let central = Rect {
            x: area.x + layout.left_sidebar_width as u16,
            y: area.y,
            width: layout.main_content_area_width as u16,
            height: total_h,
        };
        self.render_central_column(central, buf, layout);

        if layout.right_sidebar_width > 0 {
            let right_x = area.x + (self.width - layout.right_sidebar_width) as u16;
            self.right_sidebar.render(
                Rect {
                    x: right_x,
                    y: area.y,
                    width: layout.right_sidebar_width as u16,
                    height: total_h,
                },
                buf,
            );
        }

        self.render_status_bar(area, buf, config);
    }

    fn render_central_column(&mut self, area: Rect, buf: &mut Buffer, layout: RunLayout) {
        if area.width == 0 || area.height == 0 {
            return;
        }

        if self.media_pane.is_fullscreen() {
            self.media_pane.render(area, buf, &self.media_store, "", "");
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
            if self.metrics_grid.chart_count() == 0 {
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

        if layout.media_height > 0 {
            let media_area = Rect {
                x: area.x,
                y: area.y + layout.media_y as u16,
                width: area.width,
                height: layout.media_height as u16,
            };
            self.media_pane
                .render(media_area, buf, &self.media_store, "", "");
            section_tops.push(media_area.y);
        } else {
            self.media_pane.park();
        }

        if layout.console_logs_height > 0 {
            // Re-sync the pane only when the content changed; the clone is
            // O(log lines) and would otherwise run every frame.
            if self.console_logs_synced != self.console_logs.revision() {
                self.console_logs_pane
                    .set_console_logs(self.console_logs.items().to_vec());
                self.console_logs_synced = self.console_logs.revision();
            }
            let logs_area = Rect {
                x: area.x,
                y: area.y + layout.console_logs_y as u16,
                width: area.width,
                height: layout.console_logs_height as u16,
            };
            self.console_logs_pane.render(logs_area, buf, "", "");
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

    fn render_status_bar(&self, area: Rect, buf: &mut Buffer, config: &ConfigManager) {
        let y = area.bottom().saturating_sub(1);
        let style = theme::status_bar_style();

        // Fill the entire row with the status bar background.
        for x in area.left()..area.right() {
            buf[(x, y)].set_char(' ').set_style(style);
        }

        let status = self.build_status_text(config);
        let help = self.build_help_text();

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
        if self.left_sidebar.is_filter_mode() {
            return self.build_overview_filter_status();
        }
        if self.metrics_grid.is_filter_mode() {
            return self.build_metrics_filter_status();
        }
        if self.right_sidebar.is_filter_mode() {
            return self.build_system_metrics_filter_status();
        }
        if config.is_awaiting_grid_config() {
            return config.grid_config_status().to_string();
        }
        if !self.last_error.is_empty() {
            return format!("Error: {}", self.last_error);
        }
        if self.is_loading {
            return self.build_loading_status();
        }
        self.build_active_status()
    }

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

    fn build_system_metrics_filter_status(&self) -> String {
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

    fn build_active_status(&self) -> String {
        let mut parts: Vec<String> = Vec::new();

        if self.metrics_grid.is_filtering() {
            parts.push(format!(
                "Filter ({}): {:?} [{}/{}] (/ to change, Ctrl+L to clear)",
                self.metrics_grid.filter_mode(),
                self.metrics_grid.filter_query(),
                self.metrics_grid.filtered_chart_count(),
                self.metrics_grid.chart_count(),
            ));
        }

        if self.left_sidebar.is_filtering() {
            parts.push(format!(
                "Overview: {:?} [{}] (o to change, Ctrl+K to clear)",
                self.left_sidebar.filter_query(),
                self.left_sidebar.filter_info(),
            ));
        }

        if self.right_sidebar.is_filtering() {
            let grid = &self.right_sidebar.metrics_grid;
            parts.push(format!(
                "System filter ({}): {:?} [{}/{}] (\\ to change, Ctrl+\\ to clear)",
                grid.filter_mode(),
                grid.filter_query(),
                grid.filtered_chart_count(),
                grid.chart_count(),
            ));
        }

        if self.left_sidebar.is_visible()
            && let Some((key, value)) = self.left_sidebar.selected_item()
            && !key.is_empty()
        {
            parts.push(format!("{key}: {value}"));
        }

        if self.media_pane.active() {
            let label = self.media_pane.status_label(&self.media_store);
            if !label.is_empty() {
                parts.push(label);
            }
        }

        if let Some(title) = self.focused_title()
            && !title.is_empty()
        {
            parts.push(title);
            match self.focus_mgr.current() {
                FocusTarget::MetricsGrid => {
                    let label = self.metrics_grid.focused_chart_scale_label();
                    if !label.is_empty() {
                        parts.push(label.to_string());
                    }
                }
                FocusTarget::SystemMetrics => {
                    let grid = &self.right_sidebar.metrics_grid;
                    let detail = grid.focused_chart_title_detail();
                    if !detail.is_empty() {
                        parts.push(detail);
                    }
                    let view_mode = self.right_sidebar.focused_chart_view_mode_label();
                    if !view_mode.is_empty() {
                        parts.push(view_mode);
                    }
                    let scale = grid.focused_chart_scale_label();
                    if !scale.is_empty() {
                        parts.push(scale.to_string());
                    }
                }
                _ => {}
            }
        }

        parts.join(" • ")
    }

    fn build_help_text(&self) -> &'static str {
        if self.is_filtering() { "" } else { "h: help" }
    }
}

impl FocusContext for RunView {
    fn available(&self, target: FocusTarget) -> bool {
        match target {
            FocusTarget::Overview => {
                self.left_sidebar.is_expanded()
                    && self.left_sidebar.focusable_section_bounds().is_some()
            }
            FocusTarget::MetricsGrid => {
                self.metrics_grid_anim.is_expanded() && self.metrics_grid.chart_count() > 0
            }
            FocusTarget::SystemMetrics => {
                self.right_sidebar.is_visible() && self.right_sidebar.metrics_grid.chart_count() > 0
            }
            FocusTarget::Media => {
                self.media_pane.is_expanded() && self.media_pane.has_data(&self.media_store)
            }
            FocusTarget::ConsoleLogs => self.console_logs_pane.is_expanded(),
            _ => false,
        }
    }

    fn available_target(&self, target: FocusTarget) -> bool {
        match target {
            FocusTarget::Overview => {
                self.left_sidebar.target_visible()
                    && self.left_sidebar.focusable_section_bounds().is_some()
            }
            FocusTarget::MetricsGrid => {
                self.metrics_grid_anim.target_visible() && self.metrics_grid.chart_count() > 0
            }
            FocusTarget::SystemMetrics => {
                self.right_sidebar.anim_state.target_visible()
                    && self.right_sidebar.metrics_grid.chart_count() > 0
            }
            FocusTarget::Media => {
                self.media_pane.target_visible() && self.media_pane.has_data(&self.media_store)
            }
            FocusTarget::ConsoleLogs => self.console_logs_pane.target_visible(),
            _ => false,
        }
    }

    fn activate(&mut self, target: FocusTarget, direction: i32) {
        match target {
            FocusTarget::Overview => {
                if let Some((first, last)) = self.left_sidebar.focusable_section_bounds() {
                    self.left_sidebar
                        .set_active_section(if direction >= 0 { first } else { last });
                }
            }
            FocusTarget::MetricsGrid => {
                self.metrics_grid.navigate_focus(0, 0);
            }
            FocusTarget::SystemMetrics => {
                self.right_sidebar.metrics_grid.navigate_focus(0, 0);
            }
            FocusTarget::Media => self.media_pane.set_active(true),
            FocusTarget::ConsoleLogs => self.console_logs_pane.set_active(true),
            _ => {}
        }
    }

    fn deactivate(&mut self, target: FocusTarget) {
        match target {
            FocusTarget::Overview => self.left_sidebar.deactivate_all_sections(),
            FocusTarget::MetricsGrid => {
                if self.metrics_grid.focus.ty == FocusType::MainChart {
                    self.metrics_grid.clear_focus();
                }
            }
            FocusTarget::SystemMetrics => {
                if self.right_sidebar.metrics_grid.focus.ty == FocusType::SystemChart {
                    self.right_sidebar.metrics_grid.clear_focus();
                }
            }
            FocusTarget::Media => self.media_pane.set_active(false),
            FocusTarget::ConsoleLogs => self.console_logs_pane.set_active(false),
            _ => {}
        }
    }
}
