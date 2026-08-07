//! Port of `core/internal/leet/runoverviewsidebar.go`.
//!
//! Run metadata sidebar: header fields (state/ID/name/project), tag badges
//! with contrast-checked colors (`leet_charts::styles` tag math), notes, and
//! the Environment/Config/Summary sections backed by [`PagedList`]s.
//! Rendering goes through the `layout` style objects; Go's package-global
//! adaptive styles resolve via an explicit `dark` flag passed into `view`
//! (see `leet_charts::styles::AdaptiveColor`).
//!
//! Go shares the `*RunOverview` pointer between the owning view and this
//! sidebar (run.go:151-152, workspace.go:1041) and mutates it after handing
//! it over; the port mirrors that aliasing with `Rc<RefCell<RunOverview>>`
//! (single-threaded, CONCURRENCY.md §2.6). The `*ConfigManager` is shared
//! the same way. The `*AnimatedValue` has a single holder, so it is owned.
//!
//! Section-height allocation and navigation live in
//! [`crate::run_overview_sidebar_nav`]; filter key handling lives in
//! [`crate::run_overview_sidebar_filter`] (one Go file → one Rust module).

use std::cell::RefCell;
use std::rc::Rc;
use std::time::Instant;

use ratatui::text::Text;

use leet_charts::styles::{
    SIDEBAR_KEY_WIDTH_RATIO, SIDEBAR_OVERHEAD, color_scheme, default_dark_background,
};
use leet_data::config::{ConfigManager, DEFAULT_TAG_COLOR_SCHEME};
use leet_data::run_overview::{KeyValuePair, RUN_OVERVIEW_HEADER, RunOverview, RunState};
use leet_data::width::text_width;

use crate::animation::AnimatedValue;
use crate::event::Event;
use crate::filter::Filter;
use crate::flex_layout::{expanded_sidebar_width, sidebar_content_width, sidebar_inner_width};
use crate::key::{KeyCode, KeyMods};
use crate::layout::{
    GoStyle, LEFT, TOP, block_width, join_horizontal, join_vertical, left_sidebar_border_style,
    left_sidebar_header_style, left_sidebar_style, nav_info_style, place,
    right_sidebar_border_style, right_sidebar_header_style, right_sidebar_style,
    run_overview_sidebar_highlighted_item, run_overview_sidebar_key_style,
    run_overview_sidebar_section_header_style, run_overview_sidebar_section_style,
    run_overview_sidebar_value_style, run_overview_tag_style, text_from_str,
};
use crate::paged_list::PagedList;

/// Which edge of the terminal the sidebar is attached to.
// PARITY: Go declares `type SidebarSide int` with iota values 0..2; the
// zero value (Undefined) is `Default`.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum SidebarSide {
    #[default]
    Undefined,
    Left,
    Right,
}

/// minSidebarHeaderLines preserves the existing baseline layout when only the
/// original metadata fields are present, while still allowing the header to
/// grow for wrapped tags and notes.
const MIN_SIDEBAR_HEADER_LINES: isize = 6;

/// RunOverviewSidebar stores and displays run metadata.
///
/// It handles presentation concerns: sections, filtering, navigation, layout,
/// and rendering. All data processing is delegated to the RunOverview model.
// PARITY: Go package-private fields are `pub(crate)` — the nav/filter
// sibling modules and workspace.go/run.go (Phase 5) reach into them exactly
// as Go's package scope allows.
#[derive(Debug)]
pub struct RunOverviewSidebar {
    pub(crate) config: Rc<RefCell<ConfigManager>>,

    pub(crate) anim_state: AnimatedValue,
    pub(crate) run_overview: Option<Rc<RefCell<RunOverview>>>,

    // UI state: sections, filtering, navigation.
    // TODO: encapsulate and refactor
    pub(crate) sections: Vec<PagedList>,
    pub(crate) active_section: isize,

    // Filter state.
    pub(crate) filter: Filter,

    // Placement and dimensions.
    pub(crate) side: SidebarSide,
    pub(crate) height: isize,
}

impl RunOverviewSidebar {
    /// Port of `NewRunOverviewSidebar`.
    pub fn new(
        config: Rc<RefCell<ConfigManager>>,
        anim_state: AnimatedValue,
        run_overview: Option<Rc<RefCell<RunOverview>>>,
        side: SidebarSide,
    ) -> RunOverviewSidebar {
        // PARITY: Go uses struct literals; PagedList's cursor fields are
        // module-private in the port, so the zero value is built explicitly.
        let mut es = PagedList::default();
        es.title = "Environment".to_string();
        es.active = true;
        es.set_items_per_page(10);
        let mut cs = PagedList::default();
        cs.title = "Config".to_string();
        cs.set_items_per_page(15);
        let mut ss = PagedList::default();
        ss.title = "Summary".to_string();
        ss.set_items_per_page(20);

        RunOverviewSidebar {
            config,
            anim_state,
            run_overview,
            sections: vec![es, cs, ss],
            active_section: 0,
            filter: Filter::new(),
            side,
            height: 0,
        }
    }

    /// Toggle toggles the sidebar between expanded and collapsed states.
    pub fn toggle(&mut self) {
        self.anim_state.toggle();
    }

    /// Update handles animation and input updates for the sidebar.
    ///
    /// PARITY: Go returns `(*RunOverviewSidebar, tea.Cmd)` where the cmd is
    /// `tea.Tick(AnimationFrame, ...)` producing the side's animation msg.
    /// The port returns the [`Event`] to deliver after
    /// `leet_charts::styles::ANIMATION_FRAME`; Phase 5 maps `Some(ev)` to
    /// `TimerCmd::Arm(TimerId::Anim(..), ANIMATION_FRAME)`
    /// (CONCURRENCY.md §2.4).
    pub fn update(&mut self, msg: &Event) -> Option<Event> {
        // Handle key input only when expanded.
        // TODO: hook up with keybindings.
        if self.anim_state.is_expanded()
            && let Event::Key(key_msg) = msg
        {
            match key_msg.code {
                KeyCode::Up => self.navigate_up(),
                KeyCode::Down => self.navigate_down(),
                KeyCode::Tab => {
                    if key_msg.mods == KeyMods::SHIFT {
                        self.navigate_section(-1);
                    } else {
                        self.navigate_section(1);
                    }
                }
                KeyCode::Left => self.navigate_page_up(),
                KeyCode::Right => self.navigate_page_down(),
                _ => {}
            }
        }

        // Handle animation.
        if self.anim_state.is_animating() {
            let complete = self.anim_state.update(Instant::now());
            if !complete {
                return self.animation_cmd();
            }
        }

        None
    }

    /// style returns sidebar style depending on the its placement.
    fn style(&self) -> GoStyle {
        match self.side {
            SidebarSide::Left => left_sidebar_style(),
            SidebarSide::Right => right_sidebar_style(),
            SidebarSide::Undefined => GoStyle::new(),
        }
    }

    fn border_style(&self, dark: bool) -> GoStyle {
        match self.side {
            SidebarSide::Left => left_sidebar_border_style(dark),
            SidebarSide::Right => right_sidebar_border_style(dark),
            SidebarSide::Undefined => GoStyle::new(),
        }
    }

    fn header_style(&self, dark: bool) -> GoStyle {
        match self.side {
            SidebarSide::Left => left_sidebar_header_style(dark),
            SidebarSide::Right => right_sidebar_header_style(dark),
            SidebarSide::Undefined => GoStyle::new(),
        }
    }

    /// View renders the sidebar.
    ///
    /// PARITY: Go returns `tea.View`; callers only read `.Content`
    /// (workspace.go:1051), so the port returns the content block.
    pub fn view(&mut self, height: isize, dark: bool) -> Text<'static> {
        let width = self.anim_state.value();
        if height <= 0 || width <= SIDEBAR_OVERHEAD as isize {
            return text_from_str("");
        }

        self.height = height;

        let content_width = self.sidebar_content_width(width);
        let mut lines: Vec<Text<'static>> =
            vec![self.header_style(dark).render(RUN_OVERVIEW_HEADER)];

        if self.run_overview.is_some() {
            let header_lines = self.build_header_lines(content_width, dark);
            self.update_section_heights();
            let section_lines = self.build_section_lines(content_width, dark);

            lines.extend(header_lines);
            lines.extend(section_lines);
        } else {
            lines.push(nav_info_style(dark).render("No data."));
        }

        let content = join_vertical(TOP, lines);
        let inner_width = self.sidebar_inner_width(width);
        if inner_width <= 0 {
            return text_from_str("");
        }

        let styled_content = self
            .style()
            .width(inner_width as i64)
            .height(height as i64)
            .max_width(inner_width as i64)
            .max_height(height as i64)
            .render_text(content);

        let bordered = self
            .border_style(dark)
            .height(height as i64)
            .max_height(height as i64)
            .render_text(styled_content);

        place(width as i64, height as i64, LEFT, TOP, bordered)
    }

    // PHASE-5: called from the workspace handlers' port (workspace.go:1041).
    #[allow(dead_code)]
    pub fn set_run_overview(&mut self, ro: Option<Rc<RefCell<RunOverview>>>) {
        self.run_overview = ro;
    }

    /// Sync synchronizes section view with the s.runOverview.
    ///
    /// It pulls data from the model and updates UI sections.
    pub fn sync(&mut self) {
        let Some(ro) = self.run_overview.clone() else {
            return;
        };

        let had_active_section = self.has_active_section();
        let mut selected_key = String::new();
        if self.active_section >= 0 && (self.active_section as usize) < self.sections.len() {
            (selected_key, _) = self.selected_item();
        }

        {
            let ro = ro.borrow();
            self.sections[0].items = ro.environment_items();
            self.sections[1].items = ro.config_items();
            self.sections[2].items = ro.summary_items();
        }

        if self.is_filter_mode() || self.is_filtering() {
            self.apply_filter();
        } else {
            for section in &mut self.sections {
                // PARITY: Go aliases the Items slice into FilteredItems; the
                // port clones at the boundary (PORTING.md append aliasing) —
                // ApplyFilter always builds fresh vectors, so the alias is
                // never observed.
                section.filtered_items = section.items.clone();
            }
        }

        self.update_section_heights();

        if selected_key.is_empty() {
            self.select_first_available_item();
        } else {
            self.restore_selection(&selected_key);
        }

        if !had_active_section {
            self.deactivate_all_sections();
        }
    }

    /// UpdateDimensions updates the sidebar dimensions based on terminal
    /// width and the visibility of the sidebar on the opposite side.
    pub fn update_dimensions(&mut self, terminal_width: isize, opposite_sidebar_visible: bool) {
        self.anim_state.set_expanded(expanded_sidebar_width(
            terminal_width,
            opposite_sidebar_visible,
        ));
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

    /// IsExpanded returns true if the sidebar is currently expanded.
    pub fn is_expanded(&self) -> bool {
        self.anim_state.is_expanded()
    }

    /// SelectedItem returns the currently selected key-value pair.
    pub fn selected_item(&self) -> (String, String) {
        if self.active_section < 0 || self.active_section as usize >= self.sections.len() {
            return (String::new(), String::new());
        }

        let section = &self.sections[self.active_section as usize];
        if section.filtered_items.is_empty() {
            return (String::new(), String::new());
        }

        let start_idx = section.current_page() * section.items_per_page();
        let item_idx = start_idx + section.current_line();

        if item_idx >= 0 && item_idx < section.filtered_items.len() as isize {
            let item = &section.filtered_items[item_idx as usize];
            return (item.key.clone(), item.value.clone());
        }

        (String::new(), String::new())
    }

    /// animationCmd returns a command to continue the animation on section
    /// toggle.
    ///
    /// PARITY: Go returns `tea.Tick(AnimationFrame, ..)` whose callback
    /// yields a nil msg for `SidebarSideUndefined`; a nil msg is discarded
    /// by the runtime, so `None` is observationally equivalent.
    pub(crate) fn animation_cmd(&self) -> Option<Event> {
        match self.side {
            SidebarSide::Left => Some(Event::LeftSidebarAnimation),
            SidebarSide::Right => Some(Event::RightSidebarAnimation),
            SidebarSide::Undefined => None,
        }
    }

    /// headerLineCount returns the number of lines occupied by the fixed
    /// header area, including the top-level section title.
    // PARITY: Go resolves adaptive colors through the package-global
    // darkBackground (styles.go:17-31). Only the LINE COUNT matters here,
    // and it is invariant under light/dark (colors never change widths), so
    // the default flag is used instead of threading `dark` through the
    // height pass.
    pub(crate) fn header_line_count(&self) -> isize {
        if self.run_overview.is_none() {
            return 1;
        }

        let content_width = self.sidebar_content_width(self.anim_state.value());
        MIN_SIDEBAR_HEADER_LINES.max(
            1 + self
                .build_header_lines(content_width, default_dark_background())
                .len() as isize,
        )
    }

    /// buildHeaderLines builds the width-aware header metadata section.
    fn build_header_lines(&self, content_width: isize, dark: bool) -> Vec<Text<'static>> {
        let Some(ro) = &self.run_overview else {
            return Vec::new();
        };
        let ro = ro.borrow();

        let mut lines: Vec<Text<'static>> = Vec::with_capacity(8);

        if ro.state() != RunState::Unknown {
            lines.extend(self.render_wrapped_header_value(
                "State: ",
                ro.state_string(),
                content_width,
                dark,
            ));
        }

        lines.extend(self.render_wrapped_header_value("ID: ", ro.id(), content_width, dark));
        lines.extend(self.render_wrapped_header_value(
            "Name: ",
            ro.display_name(),
            content_width,
            dark,
        ));
        lines.extend(self.render_wrapped_header_value(
            "Project: ",
            ro.project(),
            content_width,
            dark,
        ));
        lines.extend(self.render_tag_header_value("Tags: ", &ro.tags(), content_width, dark));
        lines.extend(self.render_wrapped_header_value("Notes: ", ro.notes(), content_width, dark));

        if !lines.is_empty() {
            lines.push(text_from_str(""));
        }

        lines
    }

    /// renderWrappedHeaderValue renders a single metadata field, wrapping the
    /// value onto continuation lines when needed.
    fn render_wrapped_header_value(
        &self,
        prefix: &str,
        value: &str,
        width: isize,
        dark: bool,
    ) -> Vec<Text<'static>> {
        if value.trim().is_empty() {
            return Vec::new();
        }

        let prefix_text = run_overview_sidebar_key_style().render(prefix);
        let prefix_width = block_width(&prefix_text) as isize;
        let available = (width - prefix_width).max(1);
        let wrapped = wrap_header_text(value, available);
        let indent = " ".repeat(prefix_width.max(0) as usize);

        let mut lines = Vec::with_capacity(wrapped.len());
        for (i, line) in wrapped.iter().enumerate() {
            let rendered_value = run_overview_sidebar_value_style(dark).render(line);
            if i == 0 {
                // Go string `+` on single-line rendered blocks.
                lines.push(join_horizontal(
                    TOP,
                    vec![prefix_text.clone(), rendered_value],
                ));
                continue;
            }
            lines.push(join_horizontal(
                TOP,
                vec![text_from_str(&indent), rendered_value],
            ));
        }

        lines
    }

    /// renderTagHeaderValue renders tags using stable, palette-based colored
    /// badges that wrap across lines as needed.
    fn render_tag_header_value(
        &self,
        prefix: &str,
        tags: &[String],
        width: isize,
        dark: bool,
    ) -> Vec<Text<'static>> {
        if tags.is_empty() {
            return Vec::new();
        }

        let prefix_text = run_overview_sidebar_key_style().render(prefix);
        let prefix_width = block_width(&prefix_text) as isize;
        let indent = " ".repeat(prefix_width.max(0) as usize);
        let max_chip_text_width = (width - prefix_width - 2).max(1);

        let mut current_line = prefix_text;
        let mut current_width = prefix_width;
        let mut lines: Vec<Text<'static>> = Vec::with_capacity(2);
        let mut rendered_any = false;

        for tag in tags {
            if tag.trim().is_empty() {
                continue;
            }

            rendered_any = true;
            let chip_text = truncate_value(tag, max_chip_text_width);
            let chip =
                run_overview_tag_style(&self.tag_color_scheme(), tag, dark).render(&chip_text);
            let chip_width = block_width(&chip) as isize;

            let mut separator = "";
            let mut separator_width = 0;
            if current_width > prefix_width {
                separator = " ";
                separator_width = 1;
            }

            if current_width + separator_width + chip_width > width && current_width > prefix_width
            {
                lines.push(current_line);
                current_line = join_horizontal(TOP, vec![text_from_str(&indent), chip]);
                current_width = prefix_width + chip_width;
                continue;
            }

            current_line = join_horizontal(TOP, vec![current_line, text_from_str(separator), chip]);
            current_width += separator_width + chip_width;
        }

        if !rendered_any {
            return Vec::new();
        }

        lines.push(current_line);
        lines
    }

    /// buildSectionLines builds all section content lines.
    fn build_section_lines(&self, content_width: isize, dark: bool) -> Vec<Text<'static>> {
        let mut lines: Vec<Text<'static>> = Vec::new();

        for i in 0..self.sections.len() {
            if self.sections[i].height == 0 {
                continue;
            }

            // PARITY: Go signals "no content" with the empty string; the
            // port uses `None`.
            if let Some(section_content) = self.render_section(i, content_width, dark) {
                lines.push(section_content);

                // Add spacing between sections if there's a next section.
                if self.has_next_visible_section(i) {
                    lines.push(text_from_str(""));
                }
            }
        }

        lines
    }

    /// renderSection renders a single section.
    fn render_section(&self, idx: usize, width: isize, dark: bool) -> Option<Text<'static>> {
        let section = &self.sections[idx];

        if section.filtered_items.is_empty() || section.height == 0 {
            return None;
        }

        let mut lines = Vec::new();

        // Render section header.
        lines.push(self.render_section_header(section, dark));

        // Render section items.
        let item_lines = self.render_section_items(section, width, dark);
        lines.extend(item_lines);

        Some(join_vertical(TOP, lines))
    }

    /// renderSectionHeader renders the section title with pagination info.
    fn render_section_header(&self, section: &PagedList, dark: bool) -> Text<'static> {
        let mut title_style = run_overview_sidebar_section_style(dark);
        if section.active {
            title_style = run_overview_sidebar_section_header_style(dark);
        }

        let total_items = section.items.len() as isize;
        let filtered_items = section.filtered_items.len() as isize;

        let start_idx = section.current_page() * section.items_per_page();
        let end_idx = (start_idx + section.items_per_page()).min(filtered_items);

        let title_text = section.title.clone();
        let info_text =
            self.build_section_info(section, total_items, filtered_items, start_idx, end_idx);

        join_horizontal(
            TOP,
            vec![
                title_style.render(&title_text),
                nav_info_style(dark).render(&info_text),
            ],
        )
    }

    /// buildSectionInfo builds the pagination/count info string for a
    /// section.
    fn build_section_info(
        &self,
        section: &PagedList,
        total_items: isize,
        filtered_items: isize,
        start_idx: isize,
        end_idx: isize,
    ) -> String {
        if (self.is_filter_mode() || !self.filter.query().is_empty())
            && filtered_items != total_items
        {
            // Filtered view with pagination.
            format!(
                " [{}-{} of {} filtered from {}]",
                start_idx + 1,
                end_idx,
                filtered_items,
                total_items
            )
        } else if filtered_items > section.items_per_page() {
            // Paginated view.
            format!(" [{}-{} of {}]", start_idx + 1, end_idx, filtered_items)
        } else if filtered_items > 0 {
            // All items fit on one page.
            format!(" [{filtered_items} items]")
        } else {
            String::new()
        }
    }

    /// renderSectionItems renders the items for a section.
    fn render_section_items(
        &self,
        section: &PagedList,
        width: isize,
        dark: bool,
    ) -> Vec<Text<'static>> {
        // PARITY: Go `int(float64(width) * sidebarKeyWidthRatio)` truncates
        // toward zero; `as isize` matches.
        let max_key_width = (width as f64 * SIDEBAR_KEY_WIDTH_RATIO) as isize;
        let max_value_width = width - max_key_width - 3;

        let item_count = section.filtered_items.len() as isize;
        if item_count == 0 {
            return Vec::new();
        }

        let start_idx = section.current_page() * section.items_per_page();
        let end_idx = (start_idx + section.items_per_page()).min(item_count);

        let items_to_render = (end_idx - start_idx).min(section.items_per_page());

        let mut lines = Vec::with_capacity(items_to_render.max(0) as usize);
        for i in 0..items_to_render {
            let item_idx = start_idx + i;
            if item_idx >= item_count {
                break;
            }

            let item = &section.filtered_items[item_idx as usize];
            let line = self.render_item(item, i, section, max_key_width, max_value_width, dark);
            lines.push(line);
        }

        lines
    }

    /// renderItem renders a single key-value item.
    fn render_item(
        &self,
        item: &KeyValuePair,
        pos_in_page: isize,
        section: &PagedList,
        max_key_width: isize,
        max_value_width: isize,
        dark: bool,
    ) -> Text<'static> {
        let mut key_style = run_overview_sidebar_key_style();
        let mut value_style = run_overview_sidebar_value_style(dark);

        let is_highlighted = section.active && pos_in_page == section.current_line();
        if is_highlighted {
            key_style = run_overview_sidebar_highlighted_item(dark);
            value_style = run_overview_sidebar_highlighted_item(dark);
        }

        let key = truncate_value(&item.key, max_key_width);
        let value = truncate_value(&item.value, max_value_width);

        let rendered_key = key_style.width(max_key_width as i64).render(&key);

        if is_highlighted {
            let gap = run_overview_sidebar_highlighted_item(dark).render(" ");
            let rendered_value = value_style.width(max_value_width as i64).render(&value);
            return join_horizontal(TOP, vec![rendered_key, gap, rendered_value]);
        }
        join_horizontal(
            TOP,
            vec![
                rendered_key,
                text_from_str(" "),
                value_style.max_width(max_value_width as i64).render(&value),
            ],
        )
    }

    /// hasNextVisibleSection returns true if there's another visible section
    /// after idx.
    fn has_next_visible_section(&self, idx: usize) -> bool {
        for j in idx + 1..self.sections.len() {
            if self.sections[j].height > 0 {
                return true;
            }
        }
        false
    }

    /// activateSelection ensures that exactly one section is marked active
    /// (if possible). It is used when the sidebar gains focus after being
    /// deactivated.
    // PHASE-5: called from the workspace focus handlers (workspace.go:1045).
    #[allow(dead_code)]
    pub(crate) fn activate_selection(&mut self) {
        if self.sections.is_empty() {
            return;
        }
        if self.has_active_section() {
            return;
        }

        // Prefer the current activeSection if it is still usable.
        if self.is_valid_active_section() {
            let sec = &self.sections[self.active_section as usize];
            if sec.items_per_page() > 0 && !sec.filtered_items.is_empty() {
                self.set_active_section(self.active_section);
                return;
            }
        }

        self.select_first_available_item();
    }

    /// focusableSectionBounds returns the first and last sections that
    /// currently have visible items and can accept navigation. If none
    /// exist, it returns (-1, -1).
    // PHASE-5: called from the workspace focus handlers
    // (workspace.go:713-719, :748-752, :777-783).
    #[allow(dead_code)]
    pub(crate) fn focusable_section_bounds(&self) -> (isize, isize) {
        let (mut first, mut last) = (-1isize, -1isize);
        for (i, sec) in self.sections.iter().enumerate() {
            if sec.items_per_page() == 0 || sec.filtered_items.is_empty() {
                continue;
            }
            if first == -1 {
                first = i as isize;
            }
            last = i as isize;
        }
        (first, last)
    }

    /// sidebarContentWidth returns the width available for text content
    /// after subtracting border and padding.
    fn sidebar_content_width(&self, width: isize) -> isize {
        sidebar_content_width(width)
    }

    /// sidebarInnerWidth returns the width for the lipgloss Style
    /// (includes padding, excludes border).
    fn sidebar_inner_width(&self, width: isize) -> isize {
        sidebar_inner_width(width)
    }

    fn tag_color_scheme(&self) -> String {
        let scheme = self.config.borrow().tag_color_scheme().to_string();
        // Go: `if _, ok := colorSchemes[scheme]; ok`.
        if color_scheme(&scheme).is_some() {
            return scheme;
        }

        DEFAULT_TAG_COLOR_SCHEME.to_string()
    }
}

/// truncateValue truncates string values that do not fit into available
/// width.
// Defined here in Go (runoverviewsidebar.go:295-313); also called from
// consolelogspane.go, mediapane.go, systemmetricsview.go and workspace.go,
// hence `pub(crate)` — this is the canonical copy.
// PORT NOTE: console_logs_pane.rs still carries a private duplicate (its
// port predates this module); deleting it in favor of this copy is a
// console_logs_pane edit, flagged to that unit's owner.
pub(crate) fn truncate_value(value: &str, max_width: isize) -> String {
    if text_width(value) as isize <= max_width {
        return value.to_string();
    }
    if max_width <= 3 {
        return "...".to_string();
    }

    let available = max_width - 4;
    let mut w: isize = 0;
    let mut buf = [0u8; 4];
    for (i, r) in value.char_indices() {
        let rw = text_width(r.encode_utf8(&mut buf)) as isize;
        if w + rw > available {
            return format!("{}...", &value[..i]);
        }
        w += rw;
    }
    // PARITY: Go falls through here when the per-rune widths sum to at most
    // `available` even though the string as a whole is wider than maxWidth
    // (grapheme clusters) — the value is returned with "..." appended.
    format!("{value}...")
}

fn wrap_header_text(text: &str, max_width: isize) -> Vec<String> {
    if max_width <= 0 {
        return vec![text.to_string()];
    }

    let parts: Vec<&str> = text.split('\n').collect();
    let mut lines: Vec<String> = Vec::with_capacity(parts.len());
    for part in parts {
        if part.trim().is_empty() {
            lines.push(String::new());
            continue;
        }
        lines.extend(wrap_header_paragraph(part, max_width));
    }
    if lines.is_empty() {
        return vec![String::new()];
    }
    lines
}

fn wrap_header_paragraph(text: &str, max_width: isize) -> Vec<String> {
    // Go `strings.Fields`: split around runs of Unicode whitespace.
    let words: Vec<&str> = text.split_whitespace().collect();
    if words.is_empty() {
        return vec![String::new()];
    }

    let mut lines: Vec<String> = Vec::with_capacity(1);
    let mut current = words[0].to_string();
    if text_width(&current) as isize > max_width {
        let forced = wrap_single_line(&current, max_width);
        lines.extend_from_slice(&forced[..forced.len() - 1]);
        current = forced[forced.len() - 1].clone();
    }

    for &word in &words[1..] {
        let candidate = format!("{current} {word}");
        if text_width(&candidate) as isize <= max_width {
            current = candidate;
            continue;
        }

        lines.push(current);
        if text_width(word) as isize <= max_width {
            current = word.to_string();
            continue;
        }

        let forced = wrap_single_line(word, max_width);
        lines.extend_from_slice(&forced[..forced.len() - 1]);
        current = forced[forced.len() - 1].clone();
    }

    lines.push(current);
    lines
}

/// wrapSingleLine breaks a single line (no embedded newlines) into
/// chunks that each fit within maxWidth display columns.
// PORT NOTE: Go defines wrapSingleLine in consolelogspane.go:580;
// `console_logs_pane` has since landed the canonical copy
// (console_logs_pane.rs `wrap_single_line`, currently private). Deleting
// this duplicate in favor of it requires making that fn pub(crate) — a
// console_logs_pane edit, flagged to that unit's owner. Until then the two
// copies MUST stay behavior-identical (per-rune runewidth metric).
fn wrap_single_line(s: &str, max_width: isize) -> Vec<String> {
    // PARITY: Go measures with runewidth.StringWidth (per-rune width sum,
    // no grapheme clustering), matching the chunking loop below — NOT
    // lipgloss.Width. A lone char is a single-cluster string, so summing
    // text_width over chars reproduces the per-rune sum through the shim.
    let mut buf = [0u8; 4];
    let rune_sum: isize = s
        .chars()
        .map(|r| text_width(r.encode_utf8(&mut buf)) as isize)
        .sum();
    if rune_sum <= max_width {
        return vec![s.to_string()];
    }

    let runes: Vec<char> = s.chars().collect();
    let mut lines: Vec<String> = Vec::new();

    let mut start = 0usize;
    while start < runes.len() {
        let mut w: isize = 0;
        let mut end = start;
        while end < runes.len() {
            let rw = text_width(runes[end].encode_utf8(&mut buf)) as isize;
            if w + rw > max_width && end > start {
                break;
            }
            w += rw;
            end += 1;
            if w >= max_width {
                break;
            }
        }
        lines.push(runes[start..end].iter().collect());
        start = end;
    }

    lines
}

// Transliteration of `runoverviewsidebar_test.go`.
#[cfg(test)]
mod tests {
    use std::time::Duration;

    use leet_charts::styles::ANIMATION_DURATION;
    use leet_proto::wandb_internal::{
        ConfigItem, ConfigRecord, EnvironmentRecord, SummaryItem, SummaryRecord,
    };

    use super::*;
    use crate::key::KeyEvent;
    use crate::layout::text_to_string;

    /// Go `testRunOverviewSidebar`. Returns the TempDir too so the config
    /// path outlives the sidebar (Go's `t.TempDir()` lives for the test).
    fn test_run_overview_sidebar(
        is_expanded: bool,
    ) -> (
        Rc<RefCell<RunOverview>>,
        RunOverviewSidebar,
        tempfile::TempDir,
    ) {
        let dir = tempfile::tempdir().expect("tempdir");
        let cfg = Rc::new(RefCell::new(ConfigManager::new(
            dir.path().join("config.json"),
        )));
        let anim = AnimatedValue::new(is_expanded, 120);
        let ro = Rc::new(RefCell::new(RunOverview::new()));
        let s = RunOverviewSidebar::new(cfg, anim, Some(Rc::clone(&ro)), SidebarSide::Left);
        (ro, s, dir)
    }

    /// The Go tests resolve adaptive colors through the darkBackground
    /// global; content assertions are color-independent.
    fn dark() -> bool {
        default_dark_background()
    }

    /// Go `stripANSI(s.View(h).Content)`: spans carry styles out-of-band,
    /// so joining span contents IS the ANSI-stripped view.
    fn view_string(s: &mut RunOverviewSidebar, height: isize) -> String {
        text_to_string(&s.view(height, dark()))
    }

    /// Go `typeString` (metricsfilter_test.go:19-23) specialized to the
    /// sidebar; the shared `ComponentWithContentFilter` helper lands with
    /// the metrics-filter test transliteration.
    fn type_string(s: &mut RunOverviewSidebar, text: &str) {
        for r in text.chars() {
            s.update_filter_draft(&KeyEvent {
                code: KeyCode::Char(r),
                text: Some(r.to_string()),
                mods: KeyMods::NONE,
            });
        }
    }

    /// Go `expandSidebar`.
    fn expand_sidebar(s: &mut RunOverviewSidebar, term_width: isize, right_visible: bool) {
        s.update_dimensions(term_width, right_visible);
        s.toggle();
        std::thread::sleep(ANIMATION_DURATION + Duration::from_millis(20));
        // Drive animation to completion.
        s.update(&Event::LeftSidebarAnimation);
    }

    fn config_item(nested_key: &[&str], value_json: &str) -> ConfigItem {
        ConfigItem {
            nested_key: nested_key.iter().map(|k| k.to_string()).collect(),
            value_json: value_json.to_string(),
            ..Default::default()
        }
    }

    fn config_record(update: Vec<ConfigItem>) -> ConfigRecord {
        ConfigRecord {
            update,
            ..Default::default()
        }
    }

    fn summary_item(nested_key: &[&str], value_json: &str) -> SummaryItem {
        SummaryItem {
            nested_key: nested_key.iter().map(|k| k.to_string()).collect(),
            value_json: value_json.to_string(),
            ..Default::default()
        }
    }

    fn summary_record(update: Vec<SummaryItem>) -> SummaryRecord {
        SummaryRecord {
            update,
            ..Default::default()
        }
    }

    fn environment_record(writer_id: &str, os: &str) -> EnvironmentRecord {
        EnvironmentRecord {
            writer_id: writer_id.to_string(),
            os: os.to_string(),
            ..Default::default()
        }
    }

    fn key_msg(code: KeyCode) -> Event {
        Event::Key(KeyEvent {
            code,
            text: None,
            mods: KeyMods::NONE,
        })
    }

    fn shift_key_msg(code: KeyCode) -> Event {
        Event::Key(KeyEvent {
            code,
            text: None,
            mods: KeyMods::SHIFT,
        })
    }

    // Go: TestSidebarFilter_AppliesAndClears
    #[test]
    fn sidebar_filter_applies_and_clears() {
        let (ro, mut s, _dir) = test_run_overview_sidebar(true);

        ro.borrow_mut()
            .process_run_msg(leet_data::run_overview::RunMsg {
                config: Some(config_record(vec![config_item(
                    &["trainer", "epochs"],
                    "10",
                )])),
                ..Default::default()
            });
        ro.borrow_mut()
            .process_summary_msg(&[summary_record(vec![summary_item(&["acc"], "0.9")])]);
        ro.borrow_mut()
            .process_system_info_msg(Some(&environment_record("writer-1", "linux")));

        s.sync();

        s.enter_filter_mode();
        type_string(&mut s, "train");
        s.exit_filter_mode(true);
        assert!(!s.filter_info().is_empty());

        s.clear_filter();
        assert!(s.filter_info().is_empty());
    }

    // Go: TestSidebar_SelectsFirstNonEmptySection
    #[test]
    fn sidebar_selects_first_non_empty_section() {
        let (ro, mut s, _dir) = test_run_overview_sidebar(true);

        ro.borrow_mut()
            .process_run_msg(leet_data::run_overview::RunMsg {
                config: Some(config_record(vec![config_item(
                    &["trainer", "epochs"],
                    "10",
                )])),
                ..Default::default()
            });

        s.sync();

        let (key, val) = s.selected_item();
        assert_eq!(key, "trainer.epochs");
        assert_eq!(val, "10");
    }

    // Go: TestSidebar_ConfirmSummaryFilterSelectsSummary
    #[test]
    fn sidebar_confirm_summary_filter_selects_summary() {
        let (ro, mut s, _dir) = test_run_overview_sidebar(true);

        ro.borrow_mut()
            .process_run_msg(leet_data::run_overview::RunMsg {
                config: Some(config_record(vec![config_item(
                    &["trainer", "epochs"],
                    "10",
                )])),
                ..Default::default()
            });

        let sr = summary_record(vec![
            summary_item(&["acc"], "0.9"),
            summary_item(&["loss"], "0.5"),
        ]);
        ro.borrow_mut().process_summary_msg(&[sr]);

        s.sync();

        // Live preview on summary, then apply it.
        s.enter_filter_mode();
        type_string(&mut s, "acc");
        s.exit_filter_mode(true);
        let (key, _) = s.selected_item();
        assert_eq!(key, "acc");
    }

    // Go: TestSidebar_CalculateSectionHeights_PaginationAndAllItems
    #[test]
    fn sidebar_calculate_section_heights_pagination_and_all_items() {
        let (ro, mut s, _dir) = test_run_overview_sidebar(false);
        expand_sidebar(&mut s, 120, false);

        ro.borrow_mut()
            .process_run_msg(leet_data::run_overview::RunMsg {
                config: Some(config_record(vec![
                    config_item(&["alpha", "a"], "1"),
                    config_item(&["alpha", "b"], "2"),
                    config_item(&["alpha", "c"], "3"),
                    config_item(&["beta", "d"], "4"),
                    config_item(&["beta", "e"], "5"),
                ])),
                ..Default::default()
            });

        let sr = summary_record(vec![
            summary_item(&["acc"], "0.91"),
            summary_item(&["val", "acc"], "0.88"),
        ]);
        ro.borrow_mut().process_summary_msg(&[sr]);

        ro.borrow_mut()
            .process_system_info_msg(Some(&environment_record("writer-1", "linux")));

        s.sync();

        // Small height -> ItemsPerPage=1 -> expect "[1-1 of N]" pagination
        // per section.
        let view = view_string(&mut s, 15);
        assert!(view.contains("Config [1-2 of 5]"), "view: {view}");
        assert!(view.contains("Summary [1-1 of 2]"), "view: {view}");
        assert!(view.contains("Environment"), "view: {view}");

        // Larger height -> enough space -> expect "[N items]" (non-paginated).
        let view = view_string(&mut s, 40);
        assert!(view.contains("Config [5 items]"), "view: {view}");
        assert!(view.contains("Summary [2 items]"), "view: {view}");

        s.toggle();
    }

    // Go: TestSidebar_Navigation_SectionPageUpDown
    #[test]
    fn sidebar_navigation_section_page_up_down() {
        let (ro, mut s, _dir) = test_run_overview_sidebar(false);
        expand_sidebar(&mut s, 120, false);

        ro.borrow_mut()
            .process_system_info_msg(Some(&environment_record("writer-1", "linux")));

        ro.borrow_mut()
            .process_run_msg(leet_data::run_overview::RunMsg {
                config: Some(config_record(vec![
                    config_item(&["alpha", "a"], "1"),
                    config_item(&["alpha", "z"], "2"),
                    config_item(&["beta", "b"], "3"),
                ])),
                ..Default::default()
            });

        let sr = summary_record(vec![
            summary_item(&["acc"], "0.9"),
            summary_item(&["loss"], "0.1"),
        ]);
        ro.borrow_mut().process_summary_msg(&[sr]);

        s.sync();

        // Start in Environment; Tab to Config (navigateSection).
        s.update(&key_msg(KeyCode::Tab));
        let (key, _) = s.selected_item();
        assert!(
            key.starts_with("alpha.") || key.starts_with("beta."),
            "key: {key}"
        );

        // Height=15 -> 1 item/page; Down moves to next page/next item
        // (navigateDown + navigatePage).
        let _ = s.view(15, dark());
        s.update(&key_msg(KeyCode::Down));
        let (key2, _) = s.selected_item();
        assert_ne!(key2, key);

        // Page right, then left, then Up; remain in Config.
        s.update(&key_msg(KeyCode::Right));
        s.update(&key_msg(KeyCode::Left));
        s.update(&key_msg(KeyCode::Up));
        let (key3, _) = s.selected_item();
        assert!(
            key3.starts_with("alpha.") || key3.starts_with("beta."),
            "key3: {key3}"
        );

        // Shift-Tab back to previous section (Environment).
        s.update(&shift_key_msg(KeyCode::Tab));
        let (key4, _) = s.selected_item();
        assert!(
            !(key4.starts_with("alpha.") || key4.starts_with("beta.")),
            "key4: {key4}"
        );
    }

    // Go: TestSidebar_ClearFilter_PublicPath
    #[test]
    fn sidebar_clear_filter_public_path() {
        let (ro, mut s, _dir) = test_run_overview_sidebar(false);
        expand_sidebar(&mut s, 120, false);

        ro.borrow_mut()
            .process_run_msg(leet_data::run_overview::RunMsg {
                config: Some(config_record(vec![
                    config_item(&["alpha", "a"], "1"),
                    config_item(&["alpha", "b"], "2"),
                ])),
                ..Default::default()
            });

        let sr = summary_record(vec![summary_item(&["acc"], "0.91")]);
        ro.borrow_mut().process_summary_msg(&[sr]);

        ro.borrow_mut()
            .process_system_info_msg(Some(&environment_record("writer-1", "linux")));

        s.sync();

        // Apply a filter and verify info shows.
        s.enter_filter_mode();
        type_string(&mut s, "acc");
        s.exit_filter_mode(true);
        assert!(!s.filter_info().is_empty());

        s.clear_filter();
        assert!(s.filter_info().is_empty());
        let view = view_string(&mut s, 40);
        assert!(view.contains("Config [2 items]"), "view: {view}");
    }

    // Go: TestSidebar_TruncateValue
    #[test]
    fn sidebar_truncate_value() {
        let (ro, mut s, _dir) = test_run_overview_sidebar(false);
        expand_sidebar(&mut s, 40, false); // clamps to SidebarMinWidth

        let long = "x".repeat(200);

        ro.borrow_mut()
            .process_run_msg(leet_data::run_overview::RunMsg {
                config: Some(config_record(vec![config_item(
                    &["a", "k"],
                    &format!("\"{long}\""),
                )])),
                ..Default::default()
            });

        ro.borrow_mut()
            .process_system_info_msg(Some(&environment_record("writer-1", "linux")));

        s.sync();

        let view = view_string(&mut s, 12);
        assert!(view.contains("a.k"), "view: {view}");
        assert!(view.contains("..."), "view: {view}");
    }

    /// Port-local regression (no Go counterpart): wrapSingleLine's early
    /// exit measures with runewidth.StringWidth (per-rune sum), NOT
    /// lipgloss.Width. "👨\u{200D}👩\u{200D}👧" sums to 6 per rune
    /// (2+0+2+0+2) but measures 2 under the grapheme-aware metric; the
    /// grapheme metric would return it unchanged at max_width 4 where Go
    /// force-chunks. Keeps this copy behavior-identical to the canonical
    /// one in console_logs_pane.rs.
    #[test]
    fn wrap_single_line_uses_per_rune_width_sum() {
        let family = "👨\u{200D}👩\u{200D}👧";

        // Per-rune sum 6 > 4: force-chunked like Go, even though the
        // grapheme-aware width (2) fits.
        assert_eq!(
            wrap_single_line(family, 4),
            vec!["👨\u{200D}👩".to_string(), "\u{200D}👧".to_string()]
        );

        // Per-rune sum 6 <= 6: returned unchanged.
        assert_eq!(wrap_single_line(family, 6), vec![family.to_string()]);
    }

    // Go: TestSidebar_View_RendersTagsAndNotesBeforeSections
    #[test]
    fn sidebar_view_renders_tags_and_notes_before_sections() {
        let (ro, mut s, _dir) = test_run_overview_sidebar(false);
        expand_sidebar(&mut s, 120, false);

        ro.borrow_mut()
            .process_run_msg(leet_data::run_overview::RunMsg {
                id: "run-42".to_string(),
                display_name: "sim-run".to_string(),
                project: "vision".to_string(),
                tags: vec![
                    "wandb".to_string(),
                    "leet".to_string(),
                    "transformer".to_string(),
                ],
                notes: "Baseline note for the run overview sidebar renderer.".to_string(),
                config: Some(config_record(vec![config_item(
                    &["trainer", "epochs"],
                    "10",
                )])),
                ..Default::default()
            });

        s.sync();

        let view = view_string(&mut s, 18);
        assert!(view.contains("Tags:"), "view: {view}");
        assert!(view.contains("wandb"), "view: {view}");
        assert!(view.contains("leet"), "view: {view}");
        assert!(view.contains("transformer"), "view: {view}");
        assert!(view.contains("Notes:"), "view: {view}");
        assert!(view.contains("Baseline note"), "view: {view}");
        assert!(view.contains("Config"), "view: {view}");
    }

    // Go: TestSidebar_View_StaysWithinRequestedBounds
    #[test]
    fn sidebar_view_stays_within_requested_bounds() {
        let (ro, mut s, _dir) = test_run_overview_sidebar(false);
        expand_sidebar(&mut s, 120, false);

        ro.borrow_mut()
            .process_run_msg(leet_data::run_overview::RunMsg {
                id: "0bi7c9tc".to_string(),
                display_name: "sim-L64-1773703065".to_string(),
                project: "transformer-pretraining".to_string(),
                tags: vec!["wandb".to_string(), "leet".to_string()],
                notes: "Hominibus levibus ea quae non sunt facilius \
                        neglegentiusque verbis exprimi possunt quam ea quae sunt."
                    .to_string(),
                config: Some(config_record(vec![config_item(&["simulation"], "true")])),
                ..Default::default()
            });

        for i in 0..40 {
            ro.borrow_mut()
                .process_summary_msg(&[summary_record(vec![summary_item(
                    &["custom", &format!("metric_{i}")],
                    &format!("{i}"),
                )])]);
        }

        s.sync();

        const INNER_HEIGHT: isize = 24;
        let view = view_string(&mut s, INNER_HEIGHT);
        // Go `lipgloss.Height`: number of lines.
        assert_eq!(view.split('\n').count() as isize, INNER_HEIGHT);

        // Go `lipgloss.Width(line)` on the ANSI-stripped view.
        for line in view.split('\n') {
            assert!(
                text_width(line) as isize <= s.width(),
                "line too wide: {:?} ({} > {})",
                line,
                text_width(line),
                s.width()
            );
        }
    }

    // Go: TestSidebar_Filter_RegexAndGlob
    #[test]
    fn sidebar_filter_regex_and_glob() {
        let (ro, mut s, _dir) = test_run_overview_sidebar(true);

        ro.borrow_mut()
            .process_run_msg(leet_data::run_overview::RunMsg {
                config: Some(config_record(vec![
                    config_item(&["train", "loss"], "0.5"),
                    config_item(&["train", "acc"], "0.9"),
                    config_item(&["val", "loss"], "0.6"),
                ])),
                ..Default::default()
            });

        s.sync();

        // Default mode is regex — match keys ending with ".loss".
        s.enter_filter_mode();
        type_string(&mut s, "loss$");
        s.exit_filter_mode(true);

        // Expect both loss keys visible, acc not.
        // (We check counts via FilterInfo rather than view rendering.)
        let info = s.filter_info();
        assert!(info.contains("Config:"), "info: {info}");
        // Toggle to glob, same pattern should not match any if it's treated
        // as glob.
        s.clear_filter();
        s.enter_filter_mode();
        s.toggle_filter_match_mode(); // -> glob
        type_string(&mut s, "loss$");
        s.exit_filter_mode(true);
        let info = s.filter_info();
        assert_eq!(info, "no matches");

        // Now use glob syntax.
        s.clear_filter();
        s.enter_filter_mode();
        type_string(&mut s, "train*");
        s.exit_filter_mode(true);
        let info = s.filter_info();
        // Expect two matches under Config (train.loss, train.acc)
        assert!(info.contains("Config: 2"), "info: {info}");
    }

    // Go: TestSidebar_Pagination_ResizeFromLaterPage
    #[test]
    fn sidebar_pagination_resize_from_later_page() {
        let (ro, mut s, _dir) = test_run_overview_sidebar(false);
        expand_sidebar(&mut s, 120, false);

        // Make enough config items to have multiple pages at small height.
        let mut updates = Vec::new();
        for i in 0..10 {
            updates.push(config_item(&["k", &format!("v{i}")], "x"));
        }
        ro.borrow_mut()
            .process_run_msg(leet_data::run_overview::RunMsg {
                config: Some(config_record(updates)),
                ..Default::default()
            });

        s.sync();

        // Small height -> ItemsPerPage=1, ensure view is built.
        let _ = s.view(15, dark());

        // Navigate down a few items to force CurrentPage > 0.
        for _ in 0..5 {
            s.update(&key_msg(KeyCode::Down));
        }

        // Larger height -> ItemsPerPage increases. This used to panic.
        // (Go wraps this in require.NotPanics; a panic fails the test here.)
        let view = view_string(&mut s, 40);
        assert!(!view.is_empty());
    }
}
