//! The run overview sidebar: run metadata, config, and summary sections.

use ratatui::buffer::Buffer;
use ratatui::layout::Rect;
use unicode_width::{UnicodeWidthChar, UnicodeWidthStr};

use crate::animation::AnimatedValue;
use crate::filter::{Filter, FilterKey, FilterMatchMode};
use crate::flexlayout::{sidebar_content_width, sidebar_width_for};
use crate::pagedlist::{KeyValuePair, PagedList};
use crate::runoverview::{RunOverview, RunState};
use crate::textwrap::truncate_value;
use crate::theme::{
    self, BOX_LIGHT_VERTICAL, CONTENT_PADDING, DEFAULT_TAG_COLOR_SCHEME, SIDEBAR_KEY_WIDTH_RATIO,
    SIDEBAR_OVERHEAD, is_known_color_scheme,
};

/// Which edge of the screen the sidebar is attached to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SidebarSide {
    Left,
    Right,
}

const RUN_OVERVIEW_HEADER: &str = "Run Overview";

/// Preserves the baseline layout when only the original metadata fields are
/// present, while still allowing the header to grow for wrapped tags/notes.
const MIN_SIDEBAR_HEADER_LINES: usize = 6;

/// Maximum heights for each section type.
const SECTION_MAX_HEIGHTS: [usize; 3] = [12, 20, 25];

/// Minimum section height when visible (title + 1 item).
const SECTION_MIN_HEIGHT: usize = 2;

/// Stores and displays run metadata.
///
/// Handles presentation concerns: sections, filtering, navigation, layout,
/// and rendering. Data processing is delegated to the [`RunOverview`] model,
/// which is passed in by the owner at sync and render time.
pub struct RunOverviewSidebar {
    anim_state: AnimatedValue,

    tag_color_scheme: String,

    sections: [PagedList; 3],
    active_section: usize,

    filter: Filter,

    side: SidebarSide,
    height: usize,

    /// User-set width as a fraction of the terminal width (mouse resizing);
    /// `None` uses the golden-ratio default.
    width_fraction: Option<f64>,
}

impl RunOverviewSidebar {
    pub fn new(anim_state: AnimatedValue, side: SidebarSide) -> Self {
        let mut es = PagedList::new("Environment", true);
        es.set_items_per_page(10);
        let mut cs = PagedList::new("Config", false);
        cs.set_items_per_page(15);
        let mut ss = PagedList::new("Summary", false);
        ss.set_items_per_page(20);

        Self {
            anim_state,
            tag_color_scheme: DEFAULT_TAG_COLOR_SCHEME.to_string(),
            sections: [es, cs, ss],
            active_section: 0,
            filter: Filter::new(),
            side,
            height: 0,
            width_fraction: None,
        }
    }

    /// Sets the color scheme used for tag badges.
    pub fn set_tag_color_scheme(&mut self, scheme: &str) {
        self.tag_color_scheme = if is_known_color_scheme(scheme) {
            scheme.to_string()
        } else {
            DEFAULT_TAG_COLOR_SCHEME.to_string()
        };
    }

    /// Toggles the sidebar between expanded and collapsed states.
    pub fn toggle(&mut self) {
        self.anim_state.toggle();
    }

    /// Advances the animation. Returns true when complete.
    pub fn update_animation(&mut self, now: std::time::Instant) -> bool {
        self.anim_state.update(now)
    }

    /// Synchronizes section contents with the run overview model.
    pub fn sync(&mut self, overview: &RunOverview) {
        let had_active_section = self.has_active_section();
        let selected_key = self
            .selected_item()
            .map(|(k, _)| k.to_string())
            .unwrap_or_default();

        self.sections[0].items = overview.environment_items();
        self.sections[1].items = overview.config_items();
        self.sections[2].items = overview.summary_items();

        if self.is_filter_mode() || self.is_filtering() {
            self.apply_filter();
        } else {
            for section in &mut self.sections {
                section.filtered_items = section.items.clone();
            }
        }

        self.update_section_heights(overview);

        if selected_key.is_empty() {
            self.select_first_available_item();
        } else {
            self.restore_selection(&selected_key);
        }

        if !had_active_section {
            self.deactivate_all_sections();
        }
    }

    /// Updates the expanded width based on terminal width and the visibility
    /// of the sidebar on the opposite side.
    pub fn update_dimensions(&mut self, terminal_width: i32, opposite_visible: bool) {
        self.anim_state.set_expanded(sidebar_width_for(
            terminal_width,
            opposite_visible,
            self.width_fraction,
        ));
    }

    /// Sets the user width fraction (mouse resizing); `None` restores the
    /// default. Takes effect at the next `update_dimensions`.
    pub fn set_width_fraction(&mut self, fraction: Option<f64>) {
        self.width_fraction = fraction;
    }

    /// The current (possibly mid-animation) width of the sidebar.
    pub fn width(&self) -> i32 {
        self.anim_state.value()
    }

    pub fn is_visible(&self) -> bool {
        self.anim_state.is_visible()
    }

    pub fn is_animating(&self) -> bool {
        self.anim_state.is_animating()
    }

    pub fn is_expanded(&self) -> bool {
        self.anim_state.is_expanded()
    }

    pub fn target_visible(&self) -> bool {
        self.anim_state.target_visible()
    }

    pub fn force_collapse(&mut self) {
        self.anim_state.force_collapse();
    }

    /// The currently selected key-value pair.
    pub fn selected_item(&self) -> Option<(&str, &str)> {
        let section = self.sections.get(self.active_section)?;
        let item = section.current_item()?;
        Some((&item.key, &item.value))
    }

    // ---- Navigation ----

    pub fn navigate_up(&mut self) {
        self.sections[self.active_section].up();
    }

    pub fn navigate_down(&mut self) {
        self.sections[self.active_section].down();
    }

    pub fn navigate_page_up(&mut self) {
        self.sections[self.active_section].page_up();
    }

    pub fn navigate_page_down(&mut self) {
        self.sections[self.active_section].page_down();
    }

    pub fn navigate_home(&mut self) {
        self.sections[self.active_section].home();
    }

    pub fn navigate_end(&mut self) {
        self.sections[self.active_section].end();
    }

    /// Jumps between sections, skipping empty ones.
    pub fn navigate_section(&mut self, direction: i32) {
        let prev = self.active_section;
        let n = self.sections.len() as i32;
        let mut idx = prev as i32;

        for _ in 0..self.sections.len() {
            idx += direction;
            if idx < 0 {
                idx = n - 1;
            } else if idx >= n {
                idx = 0;
            }

            if !self.sections[idx as usize].filtered_items.is_empty() {
                self.set_active_section(idx as usize);
                return;
            }

            if idx as usize == prev {
                break;
            }
        }

        // No non-empty section found; keep current active.
        self.sections[prev].active = true;
    }

    /// Ensures that exactly one section is marked active (if possible).
    /// Used when the sidebar gains focus after being deactivated.
    pub fn activate_selection(&mut self) {
        if self.has_active_section() {
            return;
        }

        let sec = &self.sections[self.active_section];
        if sec.has_navigable_items() {
            self.set_active_section(self.active_section);
            return;
        }

        self.select_first_available_item();
    }

    /// Marks all sections as inactive, removing row highlights.
    pub fn deactivate_all_sections(&mut self) {
        for section in &mut self.sections {
            section.active = false;
        }
    }

    fn has_active_section(&self) -> bool {
        self.sections.iter().any(|s| s.active)
    }

    /// The first and last focusable (non-empty, paginated) section indices,
    /// or None when no section is focusable.
    pub fn focusable_section_bounds(&self) -> Option<(usize, usize)> {
        let mut bounds = None;
        for (i, sec) in self.sections.iter().enumerate() {
            if sec.items_per_page() == 0 || sec.filtered_items.is_empty() {
                continue;
            }
            bounds = Some((bounds.map_or(i, |(first, _)| first), i));
        }
        bounds
    }

    pub fn active_section(&self) -> usize {
        self.active_section
    }

    pub fn set_active_section(&mut self, idx: usize) {
        for section in &mut self.sections {
            section.active = false;
        }
        self.active_section = idx;
        if let Some(section) = self.sections.get_mut(idx) {
            section.active = true;
        }
    }

    fn select_first_available_item(&mut self) {
        for i in 0..self.sections.len() {
            if self.sections[i].has_navigable_items() {
                self.set_active_section(i);
                return;
            }
        }
        self.set_active_section(0);
    }

    /// Attempts to restore the previously selected item by key.
    fn restore_selection(&mut self, previous_key: &str) {
        if self.try_restore_in_section(previous_key) {
            return;
        }
        self.select_first_available_item();
    }

    fn try_restore_in_section(&mut self, key: &str) -> bool {
        let section = &mut self.sections[self.active_section];
        if section.items_per_page() == 0 {
            return false;
        }

        for i in 0..section.filtered_items.len() {
            if section.filtered_items[i].key == key {
                let page = i / section.items_per_page();
                let line = i % section.items_per_page();
                section.set_page_and_line(page, line);
                return true;
            }
        }
        false
    }

    // ---- Filtering ----

    /// Processes a key event while the overview filter is active.
    pub fn handle_filter_key(&mut self, key: FilterKey, overview: &RunOverview) {
        if self.filter.handle_key(key) {
            self.apply_filter();
            self.update_section_heights(overview);
        }
    }

    /// Activates filter mode (draft initialized from applied).
    pub fn enter_filter_mode(&mut self) {
        self.filter.activate();
    }

    /// Exits filter input mode and optionally applies the filter.
    pub fn exit_filter_mode(&mut self, apply: bool, overview: &RunOverview) {
        if apply {
            self.filter.commit();
        } else {
            self.filter.cancel();
        }
        self.apply_filter();
        self.update_section_heights(overview);
    }

    /// Removes any applied/draft filter and restores all items.
    pub fn clear_filter(&mut self, overview: &RunOverview) {
        self.filter.clear();
        self.apply_filter();
        self.update_section_heights(overview);
    }

    /// Flips regex <-> glob and reapplies the live preview.
    pub fn toggle_filter_match_mode(&mut self, overview: &RunOverview) {
        self.filter.toggle_mode();
        self.apply_filter();
        self.update_section_heights(overview);
    }

    /// Whether we are currently typing a filter.
    pub fn is_filter_mode(&self) -> bool {
        self.filter.is_active()
    }

    pub fn filter_mode(&self) -> FilterMatchMode {
        self.filter.mode()
    }

    /// The currently effective query (applied if set, else draft).
    pub fn filter_query(&self) -> &str {
        self.filter.query()
    }

    /// Whether an applied (non-empty) filter exists.
    pub fn is_filtering(&self) -> bool {
        !self.filter.is_active() && !self.filter.query().is_empty()
    }

    /// Recomputes filtered items for each section based on the current
    /// matcher, and auto-focuses the section with the most matches while the
    /// query is non-empty.
    pub fn apply_filter(&mut self) {
        let matcher = self.filter.matcher();

        for section in &mut self.sections {
            section.filtered_items = section
                .items
                .iter()
                .filter(|it| matcher.matches(&it.key) || matcher.matches(&it.value))
                .cloned()
                .collect();
            section.home();
        }

        if !self.filter.query().is_empty() {
            self.focus_best_match_section();
        }
    }

    /// Focuses the section with the most filter matches. Ties are resolved
    /// by keeping the current active section.
    fn focus_best_match_section(&mut self) {
        let mut best = self.active_section;
        let mut maximum = 0;

        for (i, section) in self.sections.iter().enumerate() {
            let m = section.filtered_items.len();
            if m > maximum {
                maximum = m;
                best = i;
            }
        }

        if maximum == 0 || best == self.active_section {
            return;
        }
        self.set_active_section(best);
    }

    /// A compact per-section match summary for the status bar.
    pub fn filter_info(&self) -> String {
        if !self.is_filter_mode() && self.filter_query().is_empty() {
            return String::new();
        }

        let mut parts = Vec::new();
        for section in &self.sections {
            let matches = section.filtered_items.len();
            if matches == 0 {
                continue;
            }
            let title = if section.title == "Environment" {
                "Env"
            } else {
                &section.title
            };
            parts.push(format!("{title}: {matches}"));
        }
        if parts.is_empty() {
            return "no matches".to_string();
        }
        parts.join(", ")
    }

    // ---- Layout ----

    /// The number of lines occupied by the fixed header area, including the
    /// top-level section title.
    fn header_line_count(&self, overview: &RunOverview) -> usize {
        let content_width = sidebar_content_width(self.anim_state.value()).max(0) as usize;
        MIN_SIDEBAR_HEADER_LINES.max(1 + self.build_header_lines(overview, content_width).len())
    }

    /// Dynamically allocates heights to sections.
    fn update_section_heights(&mut self, overview: &RunOverview) {
        if self.height == 0 {
            return;
        }

        let total_available = self.available_height(overview);
        if total_available == 0 {
            return;
        }

        let desired = self.calculate_desired_heights();
        let total_desired: usize = desired.iter().sum();

        if total_desired > total_available {
            self.scale_heights_proportionally(&desired, total_available);
        } else {
            for (section, &d) in self.sections.iter_mut().zip(&desired) {
                section.height = d;
            }
            self.distribute_extra_space(total_available, total_desired);
        }

        self.update_items_per_page();
    }

    fn available_height(&self, overview: &RunOverview) -> usize {
        let available = self.height as i32 - self.header_line_count(overview) as i32;

        let active_sections = self
            .sections
            .iter()
            .filter(|s| !s.filtered_items.is_empty())
            .count();
        if active_sections == 0 {
            return 0;
        }

        let spacing = active_sections.saturating_sub(1) as i32;
        let min_required = (active_sections * SECTION_MIN_HEIGHT) as i32;
        (available - spacing).max(min_required) as usize
    }

    fn calculate_desired_heights(&mut self) -> [usize; 3] {
        let mut desired = [0usize; 3];
        for i in 0..self.sections.len() {
            let item_count = self.sections[i].filtered_items.len();
            if item_count == 0 {
                self.sections[i].height = 0;
                continue;
            }
            // Desired height is item count + 1 (for title), capped at max.
            desired[i] = (item_count + 1)
                .min(SECTION_MAX_HEIGHTS[i])
                .max(SECTION_MIN_HEIGHT);
        }
        desired
    }

    fn scale_heights_proportionally(&mut self, desired: &[usize; 3], total_available: usize) {
        let total_desired: usize = desired.iter().sum();
        let scale = total_available as f64 / total_desired as f64;

        let mut allocated = 0;
        for (i, section) in self.sections.iter_mut().enumerate() {
            if desired[i] > 0 {
                let mut scaled = (desired[i] as f64 * scale) as usize;
                if scaled < SECTION_MIN_HEIGHT && !section.filtered_items.is_empty() {
                    scaled = SECTION_MIN_HEIGHT;
                }
                section.height = scaled;
                allocated += scaled;
            } else {
                section.height = 0;
            }
        }

        // Distribute remainder to the last section with items.
        if allocated < total_available {
            let remainder = total_available - allocated;
            for section in self.sections.iter_mut().rev() {
                if !section.filtered_items.is_empty() && section.height > 0 {
                    section.height += remainder;
                    return;
                }
            }
        }
    }

    /// Distributes unused space to sections that can use it, bottom to top.
    fn distribute_extra_space(&mut self, total_available: usize, total_desired: usize) {
        let mut extra = total_available - total_desired;

        for i in (0..self.sections.len()).rev() {
            if extra == 0 {
                break;
            }
            let section = &mut self.sections[i];
            if section.height == 0 {
                continue;
            }

            let item_count = section.filtered_items.len();
            let current_items = section.height - 1; // Subtract title line.

            // Only expand if we have more items to show.
            if current_items < item_count {
                let max_increase = (SECTION_MAX_HEIGHTS[i].saturating_sub(section.height))
                    .min((item_count + 1).saturating_sub(section.height));
                let increase = max_increase.min(extra);
                section.height += increase;
                extra -= increase;
            }
        }
    }

    fn update_items_per_page(&mut self) {
        for section in &mut self.sections {
            if section.height > 0 {
                section.set_items_per_page((section.height - 1).max(1));
            } else {
                section.set_items_per_page(0);
            }
        }
    }

    // ---- Rendering ----

    /// Renders the sidebar into `area`. The area width should be the current
    /// animated width.
    pub fn render(&mut self, area: Rect, buf: &mut Buffer, overview: Option<&RunOverview>) {
        let width = self.anim_state.value();
        if area.height == 0 || width <= SIDEBAR_OVERHEAD {
            return;
        }

        self.height = area.height as usize;

        // Border column: left side draws it at the right edge and vice versa.
        let border_x = match self.side {
            SidebarSide::Left => area.right().saturating_sub(1),
            SidebarSide::Right => area.x,
        };
        for y in area.y..area.bottom() {
            buf[(border_x, y)]
                .set_char(BOX_LIGHT_VERTICAL)
                .set_style(theme::border_style());
        }

        // Content area: inside the border, with horizontal padding.
        let content_x = match self.side {
            SidebarSide::Left => area.x + CONTENT_PADDING,
            SidebarSide::Right => area.x + 1 + CONTENT_PADDING,
        };
        let content_width = sidebar_content_width(width).max(0) as usize;
        if content_width == 0 {
            return;
        }

        let mut lines: Vec<Line> = vec![Line::styled(
            RUN_OVERVIEW_HEADER.to_string(),
            theme::header_style(),
        )];

        match overview {
            Some(overview) => {
                lines.extend(self.build_header_lines(overview, content_width));
                self.update_section_heights(overview);
                lines.extend(self.build_section_lines(content_width));
            }
            None => lines.push(Line::styled(
                "No data.".to_string(),
                theme::nav_info_style(),
            )),
        }

        for (row, line) in lines.iter().enumerate() {
            if row >= area.height as usize {
                break;
            }
            line.render(content_x, area.y + row as u16, content_width, buf);
        }
    }

    /// Builds the width-aware header metadata section.
    fn build_header_lines(&self, overview: &RunOverview, content_width: usize) -> Vec<Line> {
        let mut lines = Vec::with_capacity(8);

        if overview.state() != RunState::Unknown {
            lines.extend(wrapped_header_value(
                "State: ",
                overview.state_string(),
                content_width,
            ));
        }

        lines.extend(wrapped_header_value("ID: ", overview.id(), content_width));
        lines.extend(wrapped_header_value(
            "Name: ",
            overview.display_name(),
            content_width,
        ));
        lines.extend(wrapped_header_value(
            "Project: ",
            overview.project(),
            content_width,
        ));
        lines.extend(self.tag_header_value("Tags: ", overview.tags(), content_width));
        lines.extend(wrapped_header_value(
            "Notes: ",
            overview.notes(),
            content_width,
        ));

        if !lines.is_empty() {
            lines.push(Line::default());
        }

        lines
    }

    /// Renders tags as stable, palette-based colored badges that wrap across
    /// lines as needed.
    fn tag_header_value(&self, prefix: &str, tags: &[String], width: usize) -> Vec<Line> {
        if tags.is_empty() {
            return Vec::new();
        }

        let prefix_width = prefix.width();
        let indent = " ".repeat(prefix_width);
        let max_chip_text_width = (width as i32 - prefix_width as i32 - 2).max(1) as usize;

        let mut current = Line::default();
        current.push(prefix.to_string(), theme::sidebar_key_style());
        let mut current_width = prefix_width;
        let mut lines = Vec::with_capacity(2);
        let mut rendered_any = false;

        for tag in tags {
            if tag.trim().is_empty() {
                continue;
            }

            rendered_any = true;
            // Badges have one space of padding on each side.
            let chip_text = format!(" {} ", truncate_value(tag, max_chip_text_width));
            let chip_style = theme::tag_style(&self.tag_color_scheme, tag);
            let chip_width = chip_text.width();

            let separator_width = usize::from(current_width > prefix_width);

            if current_width + separator_width + chip_width > width && current_width > prefix_width
            {
                lines.push(std::mem::take(&mut current));
                current.push(indent.clone(), Style::default());
                current.push(chip_text, chip_style);
                current_width = prefix_width + chip_width;
                continue;
            }

            if separator_width > 0 {
                current.push(" ".to_string(), Style::default());
            }
            current.push(chip_text, chip_style);
            current_width += separator_width + chip_width;
        }

        if !rendered_any {
            return Vec::new();
        }

        lines.push(current);
        lines
    }

    /// Builds all section content lines.
    fn build_section_lines(&self, content_width: usize) -> Vec<Line> {
        let mut lines = Vec::new();

        for i in 0..self.sections.len() {
            let section = &self.sections[i];
            if section.height == 0 || section.filtered_items.is_empty() {
                continue;
            }

            lines.push(self.section_header_line(section));
            lines.extend(self.section_item_lines(section, content_width));

            // Add spacing between sections if there's a next visible one.
            if self.sections[i + 1..]
                .iter()
                .any(|s| s.height > 0 && !s.filtered_items.is_empty())
            {
                lines.push(Line::default());
            }
        }

        lines
    }

    /// The section title with pagination info.
    fn section_header_line(&self, section: &PagedList) -> Line {
        let title_style = if section.active {
            theme::sidebar_section_header_style()
        } else {
            theme::sidebar_section_style()
        };

        let total_items = section.items.len();
        let filtered_items = section.filtered_items.len();
        let start_idx = section.current_page() * section.items_per_page();
        let end_idx = (start_idx + section.items_per_page()).min(filtered_items);

        let info = if (self.is_filter_mode() || !self.filter.query().is_empty())
            && filtered_items != total_items
        {
            format!(
                " [{}-{} of {} filtered from {}]",
                start_idx + 1,
                end_idx,
                filtered_items,
                total_items
            )
        } else if filtered_items > section.items_per_page() {
            format!(" [{}-{} of {}]", start_idx + 1, end_idx, filtered_items)
        } else if filtered_items > 0 {
            format!(" [{filtered_items} items]")
        } else {
            String::new()
        };

        let mut line = Line::default();
        line.push(section.title.clone(), title_style);
        line.push(info, theme::nav_info_style());
        line
    }

    /// The visible items for a section.
    fn section_item_lines(&self, section: &PagedList, width: usize) -> Vec<Line> {
        let max_key_width = (width as f64 * SIDEBAR_KEY_WIDTH_RATIO) as usize;
        let max_value_width = (width as i32 - max_key_width as i32 - 3).max(0) as usize;

        let item_count = section.filtered_items.len();
        if item_count == 0 {
            return Vec::new();
        }

        let start_idx = section.current_page() * section.items_per_page();
        let end_idx = (start_idx + section.items_per_page()).min(item_count);

        let mut lines = Vec::with_capacity(end_idx.saturating_sub(start_idx));
        for (pos, item) in section.filtered_items[start_idx..end_idx]
            .iter()
            .enumerate()
        {
            lines.push(render_item(
                item,
                section.active && pos == section.current_line(),
                max_key_width,
                max_value_width,
            ));
        }
        lines
    }
}

/// A single styled sidebar line composed of spans.
#[derive(Default)]
struct Line {
    spans: Vec<(String, Style)>,
}

use ratatui::style::Style;

impl Line {
    fn styled(text: String, style: Style) -> Self {
        Self {
            spans: vec![(text, style)],
        }
    }

    fn push(&mut self, text: String, style: Style) {
        self.spans.push((text, style));
    }

    /// Renders the line at (x, y), clipping to `max_width` columns.
    fn render(&self, x: u16, y: u16, max_width: usize, buf: &mut Buffer) {
        let mut cx = x;
        let mut remaining = max_width;
        for (text, style) in &self.spans {
            if remaining == 0 {
                break;
            }
            let (next_x, _) = buf.set_stringn(cx, y, text, remaining, *style);
            remaining = remaining.saturating_sub((next_x - cx) as usize);
            cx = next_x;
        }
    }
}

/// Renders a single metadata field, wrapping the value onto continuation
/// lines when needed.
fn wrapped_header_value(prefix: &str, value: &str, width: usize) -> Vec<Line> {
    if value.trim().is_empty() {
        return Vec::new();
    }

    let prefix_width = prefix.width();
    let available = (width as i32 - prefix_width as i32).max(1) as usize;
    let wrapped = wrap_header_text(value, available);
    let indent = " ".repeat(prefix_width);

    wrapped
        .into_iter()
        .enumerate()
        .map(|(i, text)| {
            let mut line = Line::default();
            if i == 0 {
                line.push(prefix.to_string(), theme::sidebar_key_style());
            } else {
                line.push(indent.clone(), Style::default());
            }
            line.push(text, theme::sidebar_value_style());
            line
        })
        .collect()
}

/// Renders a single key-value item.
fn render_item(
    item: &KeyValuePair,
    highlighted: bool,
    max_key_width: usize,
    max_value_width: usize,
) -> Line {
    let (key_style, value_style) = if highlighted {
        let s = theme::sidebar_highlighted_item_style();
        (s, s)
    } else {
        (theme::sidebar_key_style(), theme::sidebar_value_style())
    };

    let key = truncate_value(&item.key, max_key_width);
    let value = truncate_value(&item.value, max_value_width);

    let mut line = Line::default();
    line.push(pad_to_width(&key, max_key_width), key_style);
    line.push(
        " ".to_string(),
        if highlighted {
            key_style
        } else {
            Style::default()
        },
    );
    if highlighted {
        line.push(pad_to_width(&value, max_value_width), value_style);
    } else {
        line.push(value, value_style);
    }
    line
}

fn pad_to_width(s: &str, width: usize) -> String {
    let mut out = s.to_string();
    let mut w = s.width();
    while w < width {
        out.push(' ');
        w += 1;
    }
    out
}

/// Wraps header text on word boundaries, force-breaking long words.
fn wrap_header_text(text: &str, max_width: usize) -> Vec<String> {
    if max_width == 0 {
        return vec![text.to_string()];
    }

    let mut lines = Vec::new();
    for part in text.split('\n') {
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

fn wrap_header_paragraph(text: &str, max_width: usize) -> Vec<String> {
    let words: Vec<&str> = text.split_whitespace().collect();
    if words.is_empty() {
        return vec![String::new()];
    }

    let mut lines = Vec::new();
    let mut current = words[0].to_string();
    if current.width() > max_width {
        let mut forced = wrap_single_line(&current, max_width);
        current = forced.pop().unwrap_or_default();
        lines.extend(forced);
    }

    for word in &words[1..] {
        let candidate = format!("{current} {word}");
        if candidate.width() <= max_width {
            current = candidate;
            continue;
        }

        lines.push(std::mem::take(&mut current));
        if word.width() <= max_width {
            current = word.to_string();
            continue;
        }

        let mut forced = wrap_single_line(word, max_width);
        current = forced.pop().unwrap_or_default();
        lines.extend(forced);
    }

    lines.push(current);
    lines
}

/// Hard-wraps a single line at display-width boundaries.
fn wrap_single_line(s: &str, max_width: usize) -> Vec<String> {
    if s.width() <= max_width {
        return vec![s.to_string()];
    }

    let chars: Vec<char> = s.chars().collect();
    let mut lines = Vec::new();
    let mut start = 0;

    while start < chars.len() {
        let mut w = 0;
        let mut end = start;
        while end < chars.len() {
            let cw = chars[end].width().unwrap_or(0);
            if w + cw > max_width && end > start {
                break;
            }
            w += cw;
            end += 1;
            if w >= max_width {
                break;
            }
        }
        lines.push(chars[start..end].iter().collect());
        start = end;
    }

    lines
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wraps_header_paragraphs() {
        assert_eq!(wrap_header_text("hello world", 5), vec!["hello", "world"]);
        assert_eq!(wrap_header_text("abcdefgh", 3), vec!["abc", "def", "gh"]);
        assert_eq!(wrap_header_text("a\n\nb", 5), vec!["a", "", "b"]);
    }

    #[test]
    fn filter_focuses_best_section() {
        let anim = AnimatedValue::new(true, 40);
        let mut sb = RunOverviewSidebar::new(anim, SidebarSide::Left);
        sb.sections[0].items = vec![KeyValuePair {
            key: "os".into(),
            value: "mac".into(),
            path: vec![],
        }];
        sb.sections[2].items = vec![
            KeyValuePair {
                key: "loss".into(),
                value: "0.5".into(),
                path: vec![],
            },
            KeyValuePair {
                key: "loss2".into(),
                value: "0.7".into(),
                path: vec![],
            },
        ];
        sb.filter.activate();
        sb.filter.update_draft(FilterKey::Char('l'));
        sb.apply_filter();
        assert_eq!(sb.active_section, 2);
        assert_eq!(sb.filter_info(), "Summary: 2");
    }
}
