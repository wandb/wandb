//! Port of `core/internal/leet/rightsidebar.go` — the collapsible right
//! sidebar displaying system metrics in the single-run view.
//!
//! Hosts the [`SystemMetricsGrid`] (grid config `[`/`]`/number toggles live
//! with the grid itself), drives the expand/collapse animation, and maps
//! sidebar-local mouse coordinates onto grid cells.
//!
//! Go guards nothing here with locks; all state is Update-thread-only, and
//! the port keeps it that way (CONCURRENCY.md §2.6). The Go
//! `*observability.CoreLogger` is dropped; logging goes through `tracing` at
//! the same call sites (metrics_grid.rs convention).

use std::cell::RefCell;
use std::rc::Rc;
use std::time::Instant;

use ratatui::text::Text;

use leet_charts::styles::{
    CONTENT_PADDING, DEFAULT_SYSTEM_METRICS_GRID_HEIGHT, MIN_METRIC_CHART_HEIGHT,
    MIN_METRIC_CHART_WIDTH, SIDEBAR_BORDER_COLS, SIDEBAR_MIN_WIDTH, SIDEBAR_OVERHEAD,
};
use leet_data::config::ConfigManager;

use crate::animation::AnimatedValue;
use crate::event::{Event, StatsMsg};
use crate::filter::Filter;
use crate::flex_layout::{expanded_sidebar_width, sidebar_content_width, sidebar_inner_width};
use crate::key::KeyEvent;
use crate::layout::{
    LEFT, TOP, join_horizontal, join_vertical, nav_info_style, place, right_sidebar_border_style,
    right_sidebar_header_style, right_sidebar_style, text_from_str,
};
use crate::metrics_grid::GridConfigFn;
use crate::panel_grid::{Focus, GridDims, items_per_page};
use crate::system_metrics_grid::SystemMetricsGrid;

const RIGHT_SIDEBAR_HEADER: &str = "System Metrics";
const RIGHT_SIDEBAR_HEADER_LINES: isize = 1;
/// rightSidebarGridXOffset is the X offset from the sidebar's left edge
/// to the start of the grid content (border + left padding).
const RIGHT_SIDEBAR_GRID_X_OFFSET: isize = (SIDEBAR_BORDER_COLS + CONTENT_PADDING) as isize;

/// RightSidebar represents a collapsible right sidebar displaying system metrics.
// PARITY: Go package-private fields are `pub(crate)` where sibling files
// reach into them (run.go reads r.rightSidebar.animState and
// r.rightSidebar.metricsGrid directly).
pub struct RightSidebar {
    // PARITY: Go stores *ConfigManager (rightsidebar.go:24) but never reads
    // it after NewRightSidebar (the grid holds its own handle); kept for the
    // 1:1 field map.
    #[allow(dead_code)]
    config: Rc<RefCell<ConfigManager>>,
    pub(crate) anim_state: AnimatedValue,
    pub(crate) metrics_grid: SystemMetricsGrid,
    // PARITY: Go stores focusState (rightsidebar.go:26) but never reads it
    // back on the sidebar; the grid shares the same Focus handle.
    #[allow(dead_code)]
    focus_state: Rc<RefCell<Focus>>,
}

impl RightSidebar {
    /// Port of Go `NewRightSidebar` (the logger parameter is dropped; see
    /// the module docs).
    pub fn new(
        config: Rc<RefCell<ConfigManager>>,
        focus_state: Rc<RefCell<Focus>>,
    ) -> RightSidebar {
        let (rows, cols) = config.borrow().system_grid();
        let init_w = MIN_METRIC_CHART_WIDTH as isize * cols as isize;
        let init_h = MIN_METRIC_CHART_HEIGHT as isize * rows as isize;

        // Go passes the method value `config.SystemGrid` as the grid-config
        // getter; the port passes a closure over the shared config
        // (metrics_grid.rs `GridConfigFn` convention).
        let grid_config: GridConfigFn = Box::new({
            let config = Rc::clone(&config);
            move || config.borrow().system_grid()
        });

        let anim_state = AnimatedValue::new(
            config.borrow().right_sidebar_visible(),
            SIDEBAR_MIN_WIDTH as isize,
        );
        let metrics_grid = SystemMetricsGrid::new(
            init_w,
            init_h,
            Rc::clone(&config),
            grid_config,
            Rc::clone(&focus_state),
            // Go `NewFilter()` — the grid takes the *Filter pointer
            // (system_metrics_grid.rs shares it as Rc<RefCell<_>> because the
            // Workspace hands ONE filter to every per-run grid).
            Rc::new(RefCell::new(Filter::new())),
        );

        RightSidebar {
            config,
            anim_state,
            metrics_grid,
            focus_state,
        }
    }

    /// UpdateDimensions updates the right sidebar dimensions based on terminal width
    /// and the visibility of the left sidebar.
    pub fn update_dimensions(&mut self, terminal_width: isize, left_sidebar_visible: bool) {
        self.anim_state
            .set_expanded(expanded_sidebar_width(terminal_width, left_sidebar_visible));

        let grid_width = sidebar_content_width(self.anim_state.value());
        if grid_width > 0 {
            self.metrics_grid
                .resize(grid_width, DEFAULT_SYSTEM_METRICS_GRID_HEIGHT as isize);
        }
    }

    /// Toggle toggles the sidebar between expanded and collapsed states.
    pub fn toggle(&mut self) {
        self.anim_state.toggle();
    }

    /// grid_mouse_target maps sidebar-local mouse coordinates onto a grid cell.
    // PARITY: Go returns `(systemGridMouseTarget, bool)`; `None` ⇔ `ok == false`.
    fn grid_mouse_target(&self, x: isize, y: isize) -> Option<SystemGridMouseTarget> {
        if !self.anim_state.is_visible() {
            return None;
        }

        let adjusted_x = x - RIGHT_SIDEBAR_GRID_X_OFFSET;
        let adjusted_y = y - RIGHT_SIDEBAR_HEADER_LINES;
        if adjusted_x < 0 || adjusted_y < 0 {
            return None;
        }

        let dims = self.metrics_grid.calculate_chart_dimensions();
        if dims.cell_h_with_padding == 0 || dims.cell_w_with_padding == 0 {
            return None;
        }
        Some(SystemGridMouseTarget {
            adjusted_x,
            adjusted_y,
            row: adjusted_y / dims.cell_h_with_padding,
            col: adjusted_x / dims.cell_w_with_padding,
            dims,
        })
    }

    /// HandleMouseClick handles mouse clicks in the sidebar and returns true if focus changed.
    pub fn handle_mouse_click(&mut self, x: isize, y: isize) -> bool {
        tracing::debug!(
            "rightsidebar: HandleMouseClick: x={}, y={}, state={:?}",
            x,
            y,
            self.anim_state
        );

        let Some(target) = self.grid_mouse_target(x, y) else {
            return false;
        };

        self.metrics_grid.handle_mouse_click(target.row, target.col)
    }

    /// HandleWheel zooms the chart under the mouse cursor.
    pub fn handle_wheel(&mut self, x: isize, y: isize, wheel_up: bool) {
        let Some(target) = self.grid_mouse_target(x, y) else {
            return;
        };
        self.metrics_grid.handle_wheel(
            target.adjusted_x,
            target.row,
            target.col,
            target.dims,
            wheel_up,
        );
    }

    /// StartInspection begins chart inspection under the mouse cursor.
    pub fn start_inspection(&mut self, x: isize, y: isize, synced: bool) {
        let Some(target) = self.grid_mouse_target(x, y) else {
            return;
        };
        self.metrics_grid.start_inspection(
            target.adjusted_x,
            target.adjusted_y,
            target.row,
            target.col,
            target.dims,
            synced,
        );
    }

    /// UpdateInspection moves the inspection cursor.
    pub fn update_inspection(&mut self, x: isize, y: isize) {
        let Some(target) = self.grid_mouse_target(x, y) else {
            return;
        };
        self.metrics_grid.update_inspection(
            target.adjusted_x,
            target.adjusted_y,
            target.row,
            target.col,
            target.dims,
        );
    }

    /// EndInspection clears inspection mode.
    pub fn end_inspection(&mut self) {
        self.metrics_grid.end_inspection();
    }

    /// FocusedChartTitle returns the title of the focused chart, or empty string if none.
    pub fn focused_chart_title(&self) -> String {
        self.metrics_grid.focused_chart_title()
    }

    /// FocusedChartViewModeLabel returns a short description of the focused chart view mode.
    pub fn focused_chart_view_mode_label(&self) -> String {
        self.metrics_grid.focused_chart_view_mode_label()
    }

    /// ClearFocus clears focus from the currently focused system chart.
    pub fn clear_focus(&mut self) {
        self.metrics_grid.clear_focus();
    }

    /// Update handles animation updates and stats processing.
    ///
    /// PARITY: Go returns `(*RightSidebar, tea.Cmd)` where the cmd is
    /// `tea.Tick(AnimationFrame, ...)` producing `RightSidebarAnimationMsg`.
    /// The port returns the [`Event`] to deliver after
    /// `leet_charts::styles::ANIMATION_FRAME`; Phase 5 maps `Some(ev)` to
    /// `TimerCmd::Arm(TimerId::Anim(..), ANIMATION_FRAME)`
    /// (CONCURRENCY.md §2.4).
    pub fn update(&mut self, msg: &Event) -> Option<Event> {
        if let Event::Stats(stats_msg) = msg {
            self.process_stats_msg(stats_msg);
        }

        if self.anim_state.is_animating() && !self.anim_state.update(Instant::now()) {
            return self.animation_cmd();
        }

        None
    }

    /// View renders the right sidebar.
    pub fn view(&mut self, height: isize, dark: bool) -> Text<'static> {
        let width = self.anim_state.value();
        if height <= 0 || width <= SIDEBAR_OVERHEAD as isize {
            return text_from_str("");
        }

        let content_w = sidebar_content_width(width);
        let inner_w = sidebar_inner_width(width);
        let grid_height = self.calculate_grid_height(height);
        if content_w <= 0 || inner_w <= 0 || grid_height <= 0 {
            return text_from_str("");
        }

        self.metrics_grid.resize(content_w, grid_height);

        let head = place(
            content_w as i64,
            RIGHT_SIDEBAR_HEADER_LINES as i64,
            LEFT,
            TOP,
            self.render_header(dark),
        );
        let body = join_vertical(LEFT, vec![head, self.metrics_grid.view(dark)]);
        let styled = right_sidebar_style()
            .width(inner_w as i64)
            .max_width(inner_w as i64)
            .height(height as i64)
            .max_height(height as i64)
            .render_text(body);
        let bordered = right_sidebar_border_style(dark)
            .height(height as i64)
            .max_height(height as i64)
            .render_text(styled);
        place(width as i64, height as i64, LEFT, TOP, bordered)
    }

    /// Width returns the current width of the sidebar.
    pub fn width(&self) -> isize {
        self.anim_state.value()
    }

    /// IsVisible returns true if the sidebar is visible.
    pub fn is_visible(&self) -> bool {
        self.anim_state.is_visible()
    }

    /// IsAnimating returns true if the sidebar is currently animating.
    pub fn is_animating(&self) -> bool {
        self.anim_state.is_animating()
    }

    /// HandleFilterKey delegates filter key handling to the inner metrics grid.
    pub fn handle_filter_key(&mut self, msg: &KeyEvent) {
        self.metrics_grid.handle_filter_key(msg);
    }

    /// IsFilterMode returns true if the metrics grid is currently in filter input mode.
    // PARITY: Go reads `rs.metricsGrid.filter.IsActive()` directly
    // (package scope); the grid's own `IsFilterMode`
    // (systemmetricsfilter.go:71-73) is the identical expression.
    pub fn is_filter_mode(&self) -> bool {
        self.metrics_grid.is_filter_mode()
    }

    /// IsFiltering returns true if the metrics grid has an applied filter.
    // PARITY: Go inlines `!filter.IsActive() && filter.Query() != ""`; same
    // expression as the grid's `IsFiltering` (systemmetricsfilter.go:76-78).
    pub fn is_filtering(&self) -> bool {
        self.metrics_grid.is_filtering()
    }

    /// ProcessStatsMsg processes a stats message and updates the metrics.
    pub fn process_stats_msg(&mut self, msg: &StatsMsg) {
        tracing::debug!(
            "rightsidebar: ProcessStatsMsg: processing {} metrics (state={:?}, width={})",
            msg.metrics.len(),
            self.anim_state,
            self.anim_state.value()
        );

        self.metrics_grid.process_stats(msg);
    }

    /// calculateGridHeight returns the available height for the metrics grid.
    fn calculate_grid_height(&self, sidebar_height: isize) -> isize {
        sidebar_height - RIGHT_SIDEBAR_HEADER_LINES
    }

    /// renderHeader renders the header line with title and navigation info.
    fn render_header(&self, dark: bool) -> Text<'static> {
        let header = right_sidebar_header_style(dark).render(RIGHT_SIDEBAR_HEADER);

        // Add navigation info if we have multiple pages.
        if let Some(nav_info) = self.build_navigation_info(dark) {
            return join_horizontal(LEFT, vec![header, nav_info]);
        }

        header
    }

    /// buildNavigationInfo builds the navigation info string for the header.
    // PARITY: Go returns `""` when there is nothing to show; `None` ⇔ `""`.
    fn build_navigation_info(&self, dark: bool) -> Option<Text<'static>> {
        let total_count = self.metrics_grid.chart_count() as isize;
        let filtered_count = self.metrics_grid.filtered_chart_count() as isize;
        let size = self.metrics_grid.effective_grid_size();
        let items_per_page = items_per_page(size);

        // Only show navigation if we have charts and pagination.
        if self.metrics_grid.nav.total_pages() == 0 || filtered_count == 0 || items_per_page == 0 {
            return None;
        }

        let (mut start_idx, end_idx) = self
            .metrics_grid
            .nav
            .page_bounds(filtered_count, items_per_page);
        start_idx += 1; // Display as 1-indexed

        if filtered_count != total_count {
            return Some(nav_info_style(dark).render(&format!(
                " [{start_idx}-{end_idx} of {filtered_count} filtered from {total_count} total]"
            )));
        }

        Some(nav_info_style(dark).render(&format!(" [{start_idx}-{end_idx} of {filtered_count}]")))
    }

    /// animationCmd returns a command to continue the animation.
    ///
    /// PARITY: Go returns `tea.Tick(AnimationFrame, ..)` yielding
    /// `RightSidebarAnimationMsg{}`; see [`RightSidebar::update`].
    // PARITY: pub(crate) — Go's runhandlers.go calls it directly
    // (runhandlers.go:422, :699), package-private access.
    pub(crate) fn animation_cmd(&self) -> Option<Event> {
        Some(Event::RightSidebarAnimation)
    }
}

/// Go `systemGridMouseTarget` (rightsidebar.go:66-72).
struct SystemGridMouseTarget {
    adjusted_x: isize,
    adjusted_y: isize,
    row: isize,
    col: isize,
    dims: GridDims,
}

// Transliteration of rightsidebar_test.go.
#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::time::{Duration, SystemTime, UNIX_EPOCH};

    use leet_charts::styles::{
        ANIMATION_DURATION, SIDEBAR_MAX_WIDTH, SIDEBAR_WIDTH_RATIO, default_dark_background,
    };

    use super::*;
    use crate::layout::text_to_string;

    /// The Go tests resolve adaptive colors through the darkBackground
    /// global; content assertions are color-independent
    /// (run_overview_sidebar.rs convention).
    fn dark() -> bool {
        default_dark_background()
    }

    /// Go `stripANSI(rs.View(h))`: spans carry styles out-of-band, so
    /// joining span contents IS the ANSI-stripped view.
    fn view_string(rs: &mut RightSidebar, height: isize) -> String {
        text_to_string(&rs.view(height, dark()))
    }

    /// Go test constructor: NewConfigManager + NewRightSidebar. Returns the
    /// TempDir too so the config path outlives the sidebar (Go's
    /// `t.TempDir()` lives for the test).
    fn test_right_sidebar(
        configure: impl FnOnce(&mut ConfigManager),
    ) -> (RightSidebar, tempfile::TempDir) {
        let dir = tempfile::tempdir().expect("tempdir");
        let cfg = Rc::new(RefCell::new(ConfigManager::new(
            dir.path().join("config.json"),
        )));
        configure(&mut cfg.borrow_mut());
        let rs = RightSidebar::new(cfg, Rc::new(RefCell::new(Focus::new())));
        (rs, dir)
    }

    /// Go `expandRightSidebar`.
    fn expand_right_sidebar(rs: &mut RightSidebar, term_width: isize, left_visible: bool) {
        rs.update_dimensions(term_width, left_visible);
        rs.toggle();
        std::thread::sleep(ANIMATION_DURATION + Duration::from_millis(20));
        rs.update(&Event::RightSidebarAnimation);
    }

    fn now_unix() -> i64 {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_secs() as i64
    }

    fn stats_msg(timestamp: i64, metrics: &[(&str, f64)]) -> StatsMsg {
        StatsMsg {
            timestamp,
            metrics: metrics
                .iter()
                .map(|(k, v)| (k.to_string(), *v))
                .collect::<HashMap<String, f64>>(),
            ..Default::default()
        }
    }

    // Go: TestRightSidebar_UpdateDimensions_ToggleAndViewHeader
    #[test]
    fn right_sidebar_update_dimensions_toggle_and_view_header() {
        let (mut rs, _dir) = test_right_sidebar(|cfg| {
            let _ = cfg.set_system_rows(1);
            let _ = cfg.set_system_cols(1);
            let _ = cfg.set_left_sidebar_visible(false);
            let _ = cfg.set_right_sidebar_visible(false);
        });

        let term_width: isize = 200;
        expand_right_sidebar(&mut rs, term_width, false);

        // Width should equal clamped int(termWidth * SidebarWidthRatio).
        let want = ((term_width as f64 * SIDEBAR_WIDTH_RATIO) as isize)
            .max(SIDEBAR_MIN_WIDTH as isize)
            .min(SIDEBAR_MAX_WIDTH as isize);
        assert_eq!(rs.width(), want);

        // Ensure View renders header text once visible and grid ensured.
        let view = view_string(&mut rs, 20);
        assert!(!view.is_empty());
        assert!(view.contains("System Metrics"));
    }

    // Go: TestRightSidebar_HandleMouseClick_FocusToggleAndClear
    #[test]
    fn right_sidebar_handle_mouse_click_focus_toggle_and_clear() {
        let (mut rs, _dir) = test_right_sidebar(|cfg| {
            let _ = cfg.set_system_rows(1);
            let _ = cfg.set_system_cols(1);
            let _ = cfg.set_left_sidebar_visible(false);
            let _ = cfg.set_right_sidebar_visible(false);
        });
        expand_right_sidebar(&mut rs, 160, false);

        // Feed stats so a chart exists on the first cell.
        let ts = now_unix();
        rs.process_stats_msg(&stats_msg(
            ts,
            &[("gpu.0.temp", 40.0), ("cpu.0.cpu_percent", 50.0)],
        ));

        // Click inside the grid content area (border + padding = SidebarOverhead cols from left).
        let click_x = (SIDEBAR_BORDER_COLS + CONTENT_PADDING) as isize;
        let ok = rs.handle_mouse_click(click_x, 1);
        assert!(ok, "expected focus to be set");
        assert!(!rs.focused_chart_title().is_empty());

        // Clicking the same location toggles focus off through the grid.
        let ok2 = rs.handle_mouse_click(click_x, 1);
        assert!(!ok2, "expected focus to be cleared");
        assert!(rs.focused_chart_title().is_empty());

        // Explicit clear also leaves no focus.
        rs.clear_focus();
        assert!(rs.focused_chart_title().is_empty());
    }

    // Go: TestRightSidebar_HeaderShowsPaginationInfo
    #[test]
    fn right_sidebar_header_shows_pagination_info() {
        // 1x1 grid -> ItemsPerPage == 1, so multiple charts produce pagination info.
        let (mut rs, _dir) = test_right_sidebar(|cfg| {
            let _ = cfg.set_system_rows(1);
            let _ = cfg.set_system_cols(1);
            let _ = cfg.set_left_sidebar_visible(false);
            let _ = cfg.set_right_sidebar_visible(false);
        });
        expand_right_sidebar(&mut rs, 140, false);

        let ts = now_unix();
        rs.process_stats_msg(&stats_msg(
            ts,
            &[
                ("gpu.0.temp", 40.0),        // base "gpu.temp"
                ("cpu.0.cpu_percent", 50.0), // base "cpu.cpu_percent"
                ("memory_percent", 65.0),    // base "memory_percent"
            ],
        ));

        let view = view_string(&mut rs, 12);
        assert!(view.contains("System Metrics"));
        // Header includes "[start-end of total]".
        assert!(view.contains("[1-1 of 3]"));
    }

    // Go: TestRightSidebar_Update_ReturnsAnimationCmdWhileAnimating
    #[test]
    fn right_sidebar_update_returns_animation_cmd_while_animating() {
        let (mut rs, _dir) = test_right_sidebar(|_cfg| {});

        // Start expansion; immediately update -> should get a continuation command.
        rs.update_dimensions(120, false);
        rs.toggle();
        let cmd = rs.update(&Event::RightSidebarAnimation);
        assert!(
            cmd.is_some(),
            "expected a continuation command while animating"
        );

        // After the animation window, update should finish and return None.
        std::thread::sleep(ANIMATION_DURATION + Duration::from_millis(10));
        let cmd = rs.update(&Event::RightSidebarAnimation);
        assert!(
            cmd.is_none(),
            "no continuation command expected after animation completes"
        );
        assert!(!rs.is_animating());
    }
}
