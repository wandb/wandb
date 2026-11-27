//! A collapsible, animated pane that renders wandb.Image media.

use std::collections::HashMap;
use std::time::Instant;

use crossterm::event::{KeyCode, KeyEvent};
use ratatui::buffer::Buffer;
use ratatui::layout::Rect;
use ratatui::style::{Modifier, Style};
use unicode_width::UnicodeWidthStr;

use super::renderer::{MediaImageRenderer, MediaRenderKey, PictureMode, render_placeholder};
use super::store::MediaStore;
use crate::animation::AnimatedValue;
use crate::grid::GridNavigator;
use crate::msg::MediaPoint;
use crate::textwrap::truncate_value;
use crate::theme::SIDEBAR_WIDTH_RATIO;
use crate::theme::{
    self, COLOR_LAYOUT, COLOR_LAYOUT_HIGHLIGHT, COLOR_SUBHEADING, COLOR_SUBTLE, COLOR_TEXT,
    CONTENT_PADDING, CONTENT_PADDING_COLS,
};

/// Golden ratio constants for visually pleasing layout proportions.
pub const GOLDEN_RATIO: f64 = 1.618033988749895;
pub const UPPER_TIER_RATIO: f64 = GOLDEN_RATIO / (1.0 + GOLDEN_RATIO); // ≈ 0.618
pub const LOWER_TIER_RATIO: f64 = 1.0 / (1.0 + GOLDEN_RATIO); // ≈ 0.382

/// Fraction of total terminal height used when the media pane is the only
/// bottom pane visible.
pub const MEDIA_PANE_HEIGHT_RATIO: f64 = SIDEBAR_WIDTH_RATIO;

/// Per-pane fraction used when three stacked bottom panes are visible.
pub const BOTTOM_PANE_HEIGHT_RATIO_THREE: f64 = 0.146;

const MEDIA_PANE_HEADER: &str = "Media";
const MEDIA_PANE_HEADER_LINES: u16 = 2;
const MEDIA_TILE_MIN_WIDTH: u16 = 18;
const MEDIA_TILE_MIN_HEIGHT: u16 = 8;
const MEDIA_TILE_BORDER_LINES: u16 = 2;
const MEDIA_TILE_TITLE_LINES: u16 = 1;
const MEDIA_TILE_FOOTER_LINES: u16 = 1;
pub const MEDIA_PANE_MIN_HEIGHT: i32 = (MEDIA_PANE_HEADER_LINES + MEDIA_TILE_MIN_HEIGHT) as i32;

fn header_style(active: bool) -> Style {
    if active {
        Style::new()
            .fg(COLOR_LAYOUT_HIGHLIGHT.color())
            .add_modifier(Modifier::BOLD)
    } else {
        Style::new()
            .fg(COLOR_SUBHEADING.color())
            .add_modifier(Modifier::BOLD)
    }
}

fn slider_style() -> Style {
    Style::new().fg(COLOR_SUBTLE.color())
}

fn tile_title_style(selected: bool) -> Style {
    if selected {
        Style::new()
            .fg(COLOR_SUBHEADING.color())
            .add_modifier(Modifier::BOLD)
    } else {
        Style::new()
            .fg(COLOR_TEXT.color())
            .add_modifier(Modifier::BOLD)
    }
}

fn tile_border_style(selected: bool) -> Style {
    if selected {
        Style::new().fg(COLOR_LAYOUT_HIGHLIGHT.color())
    } else {
        Style::new().fg(COLOR_LAYOUT.color())
    }
}

/// Captures the navigable state of a [`MediaPane`] so it can be saved and
/// restored across Run view transitions.
#[derive(Debug, Clone, Default)]
pub struct MediaPaneViewState {
    pub selected_index: usize,
    pub x_indices: HashMap<String, usize>,
    pub auto_follows: HashMap<String, bool>,
    pub linked_scrub: bool,
    pub linked_x_index: usize,
}

/// A collapsible, animated pane that renders logged image media in a
/// scrubbable grid of tiles.
pub struct MediaPane {
    anim_state: AnimatedValue,
    /// The requested media grid shape (rows, cols), set by the owner from
    /// its config.
    grid_rows: u16,
    grid_cols: u16,
    /// Owns image decoding plus ANSI/Kitty rendering caches.
    pub renderer: MediaImageRenderer,

    active: bool,
    /// Expands the selected image inside the pane and keeps keys local.
    fullscreen: bool,
    /// Makes the scrub keys move all media series in sync by driving a
    /// single shared cursor over the union X timeline.
    linked_scrub: bool,
    /// The shared cursor's index into the union timeline.
    linked_x_index: usize,
    /// Keeps the shared cursor pinned to the latest X value.
    linked_auto_follow: bool,

    /// Selected series index within the store's series keys.
    selected_index: usize,
    /// Effective grid dimensions for the last viewport.
    page_rows: u16,
    page_cols: u16,

    /// The selected X-value index for each media series.
    x_indices: HashMap<String, usize>,
    /// Which series should stay pinned to their latest X value.
    auto_follows: HashMap<String, bool>,

    nav: GridNavigator,

    /// The currently visible media placements, recorded at render time.
    render_keys: Vec<MediaRenderKey>,
}

impl MediaPane {
    pub fn new(anim_state: AnimatedValue) -> Self {
        Self {
            anim_state,
            grid_rows: 1,
            grid_cols: 2,
            renderer: MediaImageRenderer::new(),
            active: false,
            fullscreen: false,
            linked_scrub: false,
            linked_x_index: 0,
            linked_auto_follow: false,
            selected_index: 0,
            page_rows: 1,
            page_cols: 1,
            x_indices: HashMap::new(),
            auto_follows: HashMap::new(),
            nav: GridNavigator::default(),
            render_keys: Vec::new(),
        }
    }

    pub fn height(&self) -> i32 {
        self.anim_state.value()
    }
    pub fn is_expanded(&self) -> bool {
        self.anim_state.is_expanded()
    }
    pub fn is_visible(&self) -> bool {
        self.anim_state.is_visible()
    }
    pub fn is_animating(&self) -> bool {
        self.anim_state.is_animating()
    }
    pub fn target_visible(&self) -> bool {
        self.anim_state.target_visible()
    }
    pub fn active(&self) -> bool {
        self.active
    }
    pub fn is_fullscreen(&self) -> bool {
        self.fullscreen
    }
    pub fn set_active(&mut self, active: bool) {
        self.active = active;
    }
    pub fn toggle(&mut self) {
        self.anim_state.toggle();
    }
    pub fn force_collapse(&mut self) {
        self.anim_state.force_collapse();
    }
    pub fn update(&mut self, now: Instant) -> bool {
        self.anim_state.update(now)
    }

    pub fn set_expanded_height(&mut self, height: i32) {
        self.anim_state
            .set_expanded(height.max(MEDIA_PANE_MIN_HEIGHT));
    }

    pub fn update_expanded_height(&mut self, max_terminal_height: i32) {
        let max_height = (max_terminal_height as f64 * MEDIA_PANE_HEIGHT_RATIO) as i32;
        self.set_expanded_height(max_height);
    }

    /// Sets the requested grid shape from config.
    pub fn set_grid_config(&mut self, rows: i32, cols: i32) {
        self.grid_rows = rows.max(1) as u16;
        self.grid_cols = cols.max(1) as u16;
    }

    pub fn toggle_fullscreen(&mut self) {
        self.fullscreen = !self.fullscreen;
        if self.fullscreen {
            self.active = true;
        }
    }

    pub fn exit_fullscreen(&mut self) {
        self.fullscreen = false;
    }

    /// Releases rendered media for images that are not currently visible.
    pub fn park(&mut self) {
        self.set_rendered_media(Vec::new());
    }

    fn set_rendered_media(&mut self, keys: Vec<MediaRenderKey>) {
        self.renderer.park(&keys);
        if self.render_keys == keys {
            return;
        }
        self.render_keys = keys;
        self.renderer.prepare_visible(&self.render_keys);
    }

    pub fn save_view_state(&self) -> MediaPaneViewState {
        MediaPaneViewState {
            selected_index: self.selected_index,
            x_indices: self.x_indices.clone(),
            auto_follows: self.auto_follows.clone(),
            linked_scrub: self.linked_scrub,
            linked_x_index: self.linked_x_index,
        }
    }

    pub fn restore_view_state(&mut self, s: MediaPaneViewState, store: &MediaStore) {
        self.selected_index = s.selected_index;
        self.x_indices = s.x_indices;
        self.auto_follows = s.auto_follows;
        self.linked_scrub = s.linked_scrub;
        self.linked_x_index = s.linked_x_index;
        let n = store.x_values().len();
        self.linked_auto_follow = n > 0 && s.linked_x_index >= n - 1;
        self.fullscreen = false;
        self.sync_state(store);
    }

    pub fn reset_view_state(&mut self, store: &MediaStore) {
        self.selected_index = 0;
        self.x_indices.clear();
        self.auto_follows.clear();
        self.linked_scrub = false;
        self.linked_x_index = 0;
        self.linked_auto_follow = false;
        self.nav.set_current_page(0);
        self.fullscreen = false;
        self.sync_state(store);
    }

    /// Reconciles selection/scrub state with the store contents.
    pub fn sync_state(&mut self, store: &MediaStore) {
        let keys: Vec<String> = store.series_keys().to_vec();

        if keys.is_empty() {
            self.selected_index = 0;
            self.nav.update_total_pages(0, 1);
            self.fullscreen = false;
            return;
        }

        self.selected_index = self.selected_index.min(keys.len() - 1);

        // Ensure per-series indices exist and are clamped.
        for key in &keys {
            let xs = store.series_x_values(key);
            let follow = *self.auto_follows.entry(key.clone()).or_insert(true);
            let entry = self.x_indices.entry(key.clone()).or_insert(0);
            if xs.is_empty() {
                *entry = 0;
            } else if follow {
                *entry = xs.len() - 1;
            } else {
                *entry = (*entry).min(xs.len() - 1);
            }
        }

        // Maintain the shared linked cursor against the union timeline.
        let union_len = store.x_values().len();
        if union_len == 0 {
            self.linked_x_index = 0;
        } else if self.linked_auto_follow {
            self.linked_x_index = union_len - 1;
        } else {
            self.linked_x_index = self.linked_x_index.min(union_len - 1);
        }

        let items_per_page = self.items_per_page();
        self.nav.update_total_pages(keys.len(), items_per_page);
        if items_per_page > 0 {
            let page = self.selected_index / items_per_page;
            if page < self.nav.total_pages() {
                self.nav.set_current_page(page);
            }
        }
    }

    fn pagination_grid(&self) -> (u16, u16) {
        (self.page_rows.max(1), self.page_cols.max(1))
    }

    fn items_per_page(&self) -> usize {
        let (rows, cols) = self.pagination_grid();
        (rows as usize * cols as usize).max(1)
    }

    fn current_x_for_series(&self, store: &MediaStore, key: &str) -> Option<f64> {
        let xs = store.series_x_values(key);
        if xs.is_empty() {
            return None;
        }
        let idx = self
            .x_indices
            .get(key)
            .copied()
            .unwrap_or(0)
            .min(xs.len() - 1);
        Some(xs[idx])
    }

    fn current_selection<'a>(
        &self,
        store: &'a MediaStore,
    ) -> Option<(String, Option<&'a MediaPoint>)> {
        let keys = store.series_keys();
        if keys.is_empty() {
            return None;
        }
        let key = keys[self.selected_index.min(keys.len() - 1)].clone();
        let point = self
            .scrub_x(store, &key)
            .and_then(|x| store.resolve_at(&key, x));
        Some((key, point))
    }

    pub fn has_data(&self, store: &MediaStore) -> bool {
        !store.is_empty()
    }

    /// The status bar label describing the current selection.
    pub fn status_label(&self, store: &MediaStore) -> String {
        let Some((key, point)) = self.current_selection(store) else {
            return String::new();
        };

        // Show the resolved sample's step; fall back to the scrub position
        // when the series has no sample there yet.
        let x = point.map(|p| p.x).or_else(|| self.scrub_x(store, &key));

        let mut parts = vec![format!("Media: {key}")];
        if let Some(x) = x {
            parts.push(format!("X=_step {}", format_media_axis_value(x)));
        }
        if let Some(point) = point
            && !point.caption.is_empty()
        {
            parts.push(truncate_value(&point.caption, 48));
        }
        if self.linked_scrub {
            parts.push("sync".to_string());
        }
        if self.fullscreen {
            parts.push("fullscreen".to_string());
        }
        parts.join(" • ")
    }

    /// Handles media-pane-local navigation. Returns whether the key was
    /// consumed.
    pub fn handle_key(&mut self, key: &KeyEvent, store: &MediaStore) -> bool {
        if !self.active && !self.fullscreen {
            return false;
        }

        match key.code {
            KeyCode::Enter => {
                if self.has_data(store) {
                    self.toggle_fullscreen();
                }
                true
            }
            KeyCode::Esc => {
                if self.fullscreen {
                    self.exit_fullscreen();
                    return true;
                }
                false
            }
            KeyCode::Char('k') => {
                if self.has_data(store) && self.renderer.toggle_mode() {
                    self.renderer.prepare_visible(&self.render_keys.clone());
                }
                true
            }
            KeyCode::Char('l') => {
                if self.has_data(store) {
                    self.toggle_linked_scrub(store);
                }
                true
            }
            KeyCode::Left => {
                self.scrub(store, -1);
                true
            }
            KeyCode::Right => {
                self.scrub(store, 1);
                true
            }
            KeyCode::Up => {
                self.scrub(store, -10);
                true
            }
            KeyCode::Down => {
                self.scrub(store, 10);
                true
            }
            KeyCode::Home => {
                self.scrub_to_start(store);
                true
            }
            KeyCode::End => {
                self.scrub_to_end(store);
                true
            }
            KeyCode::Char('a') => {
                self.move_selection(store, -1, 0);
                true
            }
            KeyCode::Char('d') => {
                self.move_selection(store, 1, 0);
                true
            }
            KeyCode::Char('w') => {
                self.move_selection(store, 0, -1);
                true
            }
            KeyCode::Char('s') => {
                self.move_selection(store, 0, 1);
                true
            }
            KeyCode::PageUp => {
                self.navigate_page(store, -1);
                true
            }
            KeyCode::PageDown => {
                self.navigate_page(store, 1);
                true
            }
            _ => false,
        }
    }

    pub fn move_selection(&mut self, store: &MediaStore, dx: i32, dy: i32) {
        let n = store.series_keys().len();
        if n == 0 {
            return;
        }

        let (rows, cols) = self.pagination_grid();
        let (rows, cols) = (rows as i32, cols as i32);
        let items_per_page = self.items_per_page();
        self.nav.update_total_pages(n, items_per_page);

        let (mut start, mut end) = self.nav.page_bounds(n, items_per_page);
        if self.selected_index < start || self.selected_index >= end {
            self.nav
                .set_current_page(self.selected_index / items_per_page);
            (start, end) = self.nav.page_bounds(n, items_per_page);
        }

        let local = (self.selected_index.saturating_sub(start))
            .min(end.saturating_sub(start).saturating_sub(1)) as i32;
        let row = (local / cols + dy).clamp(0, rows - 1);
        let col = (local % cols + dx).clamp(0, cols - 1);

        let mut candidate = start + (row * cols + col) as usize;
        if candidate >= end {
            candidate = end - 1;
        }
        if candidate >= start {
            self.selected_index = candidate;
        }
    }

    pub fn navigate_page(&mut self, store: &MediaStore, direction: i32) {
        let n = store.series_keys().len();
        if n == 0 {
            return;
        }

        let items_per_page = self.items_per_page();
        self.nav.update_total_pages(n, items_per_page);
        if !self.nav.navigate(direction) {
            return;
        }

        let (start, end) = self.nav.page_bounds(n, items_per_page);
        if self.selected_index < start || self.selected_index >= end {
            self.selected_index = start;
        }
    }

    fn selected_key(&self, store: &MediaStore) -> Option<String> {
        let keys = store.series_keys();
        if keys.is_empty() {
            return None;
        }
        Some(keys[self.selected_index.min(keys.len() - 1)].clone())
    }

    /// Moves the scrub position by `delta` samples: the shared cursor over
    /// the union timeline when scrubbing is linked, the selected series
    /// otherwise.
    pub fn scrub(&mut self, store: &MediaStore, delta: i32) {
        if self.linked_scrub {
            let n = store.x_values().len();
            if n == 0 {
                return;
            }
            self.linked_x_index =
                (self.linked_x_index as i64 + delta as i64).clamp(0, n as i64 - 1) as usize;
            self.linked_auto_follow = self.linked_x_index == n - 1;
            return;
        }

        let Some(key) = self.selected_key(store) else {
            return;
        };
        let xs = store.series_x_values(&key);
        if xs.is_empty() {
            return;
        }
        let cur = self.x_indices.get(&key).copied().unwrap_or(0);
        let idx = (cur as i64 + delta as i64).clamp(0, xs.len() as i64 - 1) as usize;
        self.auto_follows.insert(key.clone(), idx == xs.len() - 1);
        self.x_indices.insert(key, idx);
    }

    pub fn scrub_to_start(&mut self, store: &MediaStore) {
        if self.linked_scrub {
            self.linked_x_index = 0;
            self.linked_auto_follow = false;
            return;
        }
        let Some(key) = self.selected_key(store) else {
            return;
        };
        self.x_indices.insert(key.clone(), 0);
        self.auto_follows.insert(key, false);
    }

    pub fn scrub_to_end(&mut self, store: &MediaStore) {
        if self.linked_scrub {
            let n = store.x_values().len();
            if n > 0 {
                self.linked_x_index = n - 1;
            }
            self.linked_auto_follow = true;
            return;
        }
        let Some(key) = self.selected_key(store) else {
            return;
        };
        let xs = store.series_x_values(&key);
        if xs.is_empty() {
            return;
        }
        self.x_indices.insert(key.clone(), xs.len() - 1);
        self.auto_follows.insert(key, true);
    }

    /// Switches between linked and per-series scrubbing.
    ///
    /// Linking starts the shared cursor at the most advanced series position
    /// so the view doesn't jump; unlinking writes the cursor back into each
    /// series' own scrub position so tiles keep showing the same samples.
    fn toggle_linked_scrub(&mut self, store: &MediaStore) {
        if self.linked_scrub {
            if let Some(x) = self.linked_x(store) {
                for key in store.series_keys().to_vec() {
                    self.align_series_to(store, &key, x);
                }
            }
            self.linked_scrub = false;
            return;
        }

        let union = store.x_values();
        let mut cursor = 0;
        for key in store.series_keys() {
            if let Some(x) = self.current_x_for_series(store, key)
                && let Ok(idx) = union.binary_search_by(|v| v.partial_cmp(&x).unwrap())
            {
                cursor = cursor.max(idx);
            }
        }
        self.linked_x_index = cursor;
        self.linked_auto_follow = !union.is_empty() && cursor == union.len() - 1;
        self.linked_scrub = true;
    }

    /// Moves a series' scrub position to its latest sample at or before x,
    /// or to its first sample when none exists yet.
    fn align_series_to(&mut self, store: &MediaStore, key: &str, x: f64) {
        let xs = store.series_x_values(key);
        if xs.is_empty() {
            return;
        }
        let idx = match xs.binary_search_by(|v| v.partial_cmp(&x).unwrap()) {
            Ok(idx) => idx,
            Err(ins) => ins.saturating_sub(1),
        };
        self.x_indices.insert(key.to_string(), idx);
        self.auto_follows
            .insert(key.to_string(), idx == xs.len() - 1);
    }

    /// The shared cursor's X value on the union timeline.
    fn linked_x(&self, store: &MediaStore) -> Option<f64> {
        let xs = store.x_values();
        if xs.is_empty() {
            return None;
        }
        Some(xs[self.linked_x_index.min(xs.len() - 1)])
    }

    /// The X position a series' tile resolves against: the shared cursor
    /// when scrubbing is linked, the series' own position otherwise.
    fn scrub_x(&self, store: &MediaStore, key: &str) -> Option<f64> {
        if self.linked_scrub {
            self.linked_x(store)
        } else {
            self.current_x_for_series(store, key)
        }
    }

    fn sync_grid_layout_for_viewport(&mut self, store: &MediaStore, width: u16, height: u16) {
        if self.fullscreen {
            return;
        }

        let inner_w = width.saturating_sub(CONTENT_PADDING_COLS);
        if inner_w == 0 || height == 0 {
            return;
        }

        let (rows, cols, _, _) = self.effective_grid(
            inner_w,
            height.saturating_sub(MEDIA_PANE_HEADER_LINES).max(1),
        );
        if rows != self.page_rows || cols != self.page_cols {
            self.page_rows = rows;
            self.page_cols = cols;
            self.sync_state(store);
        }
    }

    fn tile_index_at(
        &mut self,
        store: &MediaStore,
        x: u16,
        y: u16,
        width: u16,
        height: u16,
    ) -> Option<usize> {
        if width == 0 || (height as i32) < MEDIA_PANE_MIN_HEIGHT || self.fullscreen {
            return None;
        }

        self.sync_grid_layout_for_viewport(store, width, height);
        let n = store.series_keys().len();
        if n == 0 {
            return None;
        }

        let inner_w = width.saturating_sub(CONTENT_PADDING_COLS);
        let grid_h = height.saturating_sub(MEDIA_PANE_HEADER_LINES);
        let grid_x = x as i32 - CONTENT_PADDING as i32;
        let grid_y = y as i32 - MEDIA_PANE_HEADER_LINES as i32;
        if grid_x < 0 || grid_y < 0 || grid_x >= inner_w as i32 || grid_y >= grid_h as i32 {
            return None;
        }

        let (rows, cols, slot_w, slot_h) = self.effective_grid(inner_w, grid_h.max(1));
        let row = grid_y as u16 / slot_h;
        let col = grid_x as u16 / slot_w;
        if row >= rows || col >= cols {
            return None;
        }

        let items_per_page = (rows as usize * cols as usize).max(1);
        self.nav.update_total_pages(n, items_per_page);
        let (start, end) = self.nav.page_bounds(n, items_per_page);
        let idx = start + (row as usize) * cols as usize + col as usize;
        if idx < start || idx >= end || idx >= n {
            return None;
        }
        Some(idx)
    }

    /// Selects the clicked media tile. Returns true if a tile was hit.
    pub fn handle_mouse_click(
        &mut self,
        store: &MediaStore,
        x: u16,
        y: u16,
        width: u16,
        height: u16,
    ) -> bool {
        match self.tile_index_at(store, x, y, width, height) {
            Some(idx) => {
                self.selected_index = idx;
                true
            }
            None => false,
        }
    }

    // ---- Rendering ----

    /// Renders the media pane into `area`.
    pub fn render(
        &mut self,
        area: Rect,
        buf: &mut Buffer,
        store: &MediaStore,
        run_label: &str,
        hint: &str,
    ) {
        if area.width == 0 || (area.height as i32) < MEDIA_PANE_MIN_HEIGHT {
            self.set_rendered_media(Vec::new());
            return;
        }

        let inner = Rect {
            x: area.x + CONTENT_PADDING,
            y: area.y,
            width: area.width.saturating_sub(CONTENT_PADDING_COLS),
            height: area.height,
        };
        if inner.width == 0 || inner.height == 0 {
            self.set_rendered_media(Vec::new());
            return;
        }
        self.sync_grid_layout_for_viewport(store, area.width, area.height);

        if self.fullscreen {
            self.render_fullscreen_body(inner, buf, store, run_label, hint);
        } else {
            self.render_grid_body(inner, buf, store, run_label, hint);
        }
    }

    fn render_grid_body(
        &mut self,
        area: Rect,
        buf: &mut Buffer,
        store: &MediaStore,
        run_label: &str,
        hint: &str,
    ) {
        self.render_header(area, buf, store, run_label, false);
        self.render_slider(area, buf, store);
        let grid_area = Rect {
            x: area.x,
            y: area.y + MEDIA_PANE_HEADER_LINES,
            width: area.width,
            height: area.height.saturating_sub(MEDIA_PANE_HEADER_LINES),
        };
        self.render_grid(grid_area, buf, store, hint);
    }

    fn render_fullscreen_body(
        &mut self,
        area: Rect,
        buf: &mut Buffer,
        store: &MediaStore,
        run_label: &str,
        hint: &str,
    ) {
        let selection = self
            .current_selection(store)
            .and_then(|(key, point)| point.cloned().map(|p| (key, p)));

        self.render_header(area, buf, store, run_label, true);
        self.render_slider(area, buf, store);

        let body = Rect {
            x: area.x,
            y: area.y + MEDIA_PANE_HEADER_LINES,
            width: area.width,
            height: area.height.saturating_sub(MEDIA_PANE_HEADER_LINES),
        };

        let Some((key, point)) = selection else {
            self.set_rendered_media(Vec::new());
            render_placeholder(body, buf, hint_or_default(hint, "No media."));
            return;
        };

        self.render_title(&key, Rect { height: 1, ..body }, buf, true);
        let image_h = body.height.saturating_sub(2).max(1);
        let image_area = Rect {
            x: body.x,
            y: body.y + 1,
            width: body.width,
            height: image_h,
        };
        self.set_rendered_media(vec![MediaRenderKey {
            path: point.file_path.clone(),
            width: body.width,
            height: image_h,
        }]);
        self.renderer.render(&point.file_path, image_area, buf);

        if body.height > 2 {
            let footer = fullscreen_footer(&point, body.width as usize);
            buf.set_stringn(
                body.x,
                body.y + 1 + image_h,
                &footer,
                body.width as usize,
                slider_style(),
            );
        }
    }

    fn render_header(
        &mut self,
        area: Rect,
        buf: &mut Buffer,
        store: &MediaStore,
        run_label: &str,
        fullscreen: bool,
    ) {
        let mut title = MEDIA_PANE_HEADER.to_string();
        if fullscreen {
            title += " [fullscreen]";
        }
        let style = header_style(self.active || self.fullscreen);

        let n = store.series_keys().len();
        let items_per_page = self.items_per_page();
        self.nav.update_total_pages(n, items_per_page);
        let nav_info = if n > 0 {
            let (start, end) = self.nav.page_bounds(n, items_per_page);
            format!(" [{}-{} of {}]", start + 1, end, n)
        } else {
            String::new()
        };

        let (mut x, _) = buf.set_stringn(area.x, area.y, &title, area.width as usize, style);

        if !run_label.is_empty() {
            let sep = " • ";
            let max_run_width = area.width as i32
                - title.width() as i32
                - nav_info.width() as i32
                - sep.width() as i32;
            if max_run_width > 0 {
                let label = format!("{sep}{}", truncate_value(run_label, max_run_width as usize));
                (x, _) = buf.set_stringn(
                    x,
                    area.y,
                    &label,
                    (area.right().saturating_sub(x)) as usize,
                    slider_style(),
                );
            }
        }
        let _ = x;

        if !nav_info.is_empty() {
            let nav_x = (area.x + area.width).saturating_sub(nav_info.width() as u16);
            buf.set_stringn(nav_x, area.y, &nav_info, nav_info.width(), slider_style());
        }
    }

    fn render_slider(&self, area: Rect, buf: &mut Buffer, store: &MediaStore) {
        let y = area.y + 1;
        let (xs, idx) = self.slider_position(store);
        if xs.is_empty() {
            buf.set_stringn(area.x, y, "X: _step —", area.width as usize, slider_style());
            return;
        }

        let bar_width = (area.width as i32 - 24).clamp(8, 48) as usize;
        let pos = if xs.len() > 1 {
            idx * (bar_width - 1) / (xs.len() - 1)
        } else {
            0
        };

        let bar: String = (0..bar_width)
            .map(|i| {
                if i < pos {
                    '━'
                } else if i == pos {
                    '●'
                } else {
                    '─'
                }
            })
            .collect();

        let mut text = format!(
            "X: _step {}  {}  {}/{}",
            format_media_axis_value(xs[idx]),
            bar,
            idx + 1,
            xs.len()
        );
        if self.linked_scrub {
            text += "  [sync]";
        }
        let text = truncate_value(&text, area.width as usize);
        buf.set_stringn(area.x, y, &text, area.width as usize, slider_style());
    }

    /// The timeline and cursor index the slider displays: the union timeline
    /// when scrubbing is linked, the selected series otherwise.
    fn slider_position(&self, store: &MediaStore) -> (Vec<f64>, usize) {
        if self.linked_scrub {
            let xs = store.x_values().to_vec();
            let idx = self.linked_x_index.min(xs.len().saturating_sub(1));
            return (xs, idx);
        }
        let Some(key) = self.selected_key(store) else {
            return (Vec::new(), 0);
        };
        let xs = store.series_x_values(&key);
        let idx = self
            .x_indices
            .get(&key)
            .copied()
            .unwrap_or(0)
            .min(xs.len().saturating_sub(1));
        (xs, idx)
    }

    fn render_grid(&mut self, area: Rect, buf: &mut Buffer, store: &MediaStore, hint: &str) {
        let keys: Vec<String> = store.series_keys().to_vec();
        if keys.is_empty() {
            self.set_rendered_media(Vec::new());
            render_placeholder(area, buf, hint_or_default(hint, "No media."));
            return;
        }

        let (rows, cols, slot_w, slot_h) = self.effective_grid(area.width, area.height);
        let items_per_page = (rows as usize * cols as usize).max(1);
        self.nav.update_total_pages(keys.len(), items_per_page);
        let (start, end) = self.nav.page_bounds(keys.len(), items_per_page);
        if self.selected_index < start || self.selected_index >= end {
            self.selected_index = start;
        }

        let show_selection = self.active || self.fullscreen;
        let (inner_w, _, image_h, _) = media_tile_layout(slot_w, slot_h);
        let mut render_keys = Vec::with_capacity(end - start);

        #[allow(clippy::needless_range_loop)]
        for idx in start..end {
            let key = &keys[idx];
            let point = self
                .scrub_x(store, key)
                .and_then(|x| store.resolve_at(key, x))
                .cloned();
            if let Some(point) = &point {
                render_keys.push(MediaRenderKey {
                    path: point.file_path.clone(),
                    width: inner_w,
                    height: image_h,
                });
            }

            let local = idx - start;
            let row = (local / cols as usize) as u16;
            let col = (local % cols as usize) as u16;
            let slot = Rect {
                x: area.x + col * slot_w,
                y: area.y + row * slot_h,
                width: slot_w.min(area.width.saturating_sub(col * slot_w)),
                height: slot_h.min(area.height.saturating_sub(row * slot_h)),
            };
            if slot.width == 0 || slot.height == 0 {
                continue;
            }
            self.render_tile(
                key,
                point.as_ref(),
                show_selection && idx == self.selected_index,
                slot,
                buf,
                store,
            );
        }
        self.set_rendered_media(render_keys);
    }

    fn render_tile(
        &mut self,
        key: &str,
        point: Option<&MediaPoint>,
        selected: bool,
        slot: Rect,
        buf: &mut Buffer,
        store: &MediaStore,
    ) {
        use ratatui::widgets::{Block, BorderType, Borders, Widget};

        let (inner_w, _, image_h, footer_lines) = media_tile_layout(slot.width, slot.height);

        Block::new()
            .borders(Borders::ALL)
            .border_type(BorderType::Plain)
            .border_style(tile_border_style(selected))
            .render(slot, buf);

        let inner = Rect {
            x: slot.x + 1,
            y: slot.y + 1,
            width: inner_w.min(slot.width.saturating_sub(2)),
            height: slot.height.saturating_sub(2),
        };
        if inner.width == 0 || inner.height == 0 {
            return;
        }

        self.render_title(key, Rect { height: 1, ..inner }, buf, selected);

        let image_area = Rect {
            x: inner.x,
            y: inner.y + MEDIA_TILE_TITLE_LINES,
            width: inner.width,
            height: image_h.min(inner.height.saturating_sub(MEDIA_TILE_TITLE_LINES)),
        };
        match point {
            Some(point) => self.renderer.render(&point.file_path, image_area, buf),
            None => render_placeholder(image_area, buf, "No image at X"),
        }

        if footer_lines > 0 && inner.height > MEDIA_TILE_TITLE_LINES + image_h {
            let footer = self.tile_footer(key, point, inner.width as usize, store);
            buf.set_stringn(
                inner.x,
                inner.y + MEDIA_TILE_TITLE_LINES + image_h,
                &footer,
                inner.width as usize,
                slider_style(),
            );
        }
    }

    fn render_title(&self, key: &str, area: Rect, buf: &mut Buffer, selected: bool) {
        if area.width == 0 {
            return;
        }
        let style = tile_title_style(selected);
        let suffix = self.renderer_mode_title_suffix();
        let suffix_width = suffix.width();

        if area.width as usize <= suffix_width + 1 {
            buf.set_stringn(
                area.x,
                area.y,
                truncate_value(key, area.width as usize),
                area.width as usize,
                style,
            );
            return;
        }

        let label = truncate_value(key, area.width as usize - suffix_width);
        let (x, _) = buf.set_stringn(area.x, area.y, &label, area.width as usize, style);
        buf.set_stringn(
            x,
            area.y,
            suffix,
            (area.right().saturating_sub(x)) as usize,
            theme::nav_info_style(),
        );
    }

    fn renderer_mode_title_suffix(&self) -> &'static str {
        if self.renderer.mode() == PictureMode::Kitty {
            " [full-res]"
        } else {
            " [ansi]"
        }
    }

    fn tile_footer(
        &self,
        key: &str,
        point: Option<&MediaPoint>,
        width: usize,
        store: &MediaStore,
    ) -> String {
        // Show the resolved sample's step; fall back to the scrub position
        // when the series has no sample there yet.
        let x = point.map(|p| p.x).or_else(|| self.scrub_x(store, key));
        let step_label = x
            .map(|x| format!("X=_step {}", format_media_axis_value(x)))
            .unwrap_or_default();

        let Some(point) = point else {
            return truncate_value(&step_label, width);
        };

        let mut parts = Vec::new();
        if !point.caption.is_empty() {
            parts.push(point.caption.clone());
        }
        if !step_label.is_empty() {
            parts.push(step_label);
        }
        if parts.is_empty() {
            return truncate_value(
                &format!(
                    "{}x{} {}",
                    point.width,
                    point.height,
                    point.format.to_uppercase()
                ),
                width,
            );
        }
        truncate_value(&parts.join(" • "), width)
    }

    fn effective_grid(&self, width: u16, height: u16) -> (u16, u16, u16, u16) {
        let cfg_rows = self.grid_rows.max(1);
        let cfg_cols = self.grid_cols.max(1);

        let cols = cfg_cols.min((width / MEDIA_TILE_MIN_WIDTH).max(1)).max(1);
        let rows = cfg_rows.min((height / MEDIA_TILE_MIN_HEIGHT).max(1)).max(1);
        let slot_w = if width > 0 { (width / cols).max(1) } else { 1 };
        let slot_h = if height > 0 {
            (height / rows).max(1)
        } else {
            1
        };
        (rows, cols, slot_w, slot_h)
    }
}

fn media_tile_layout(slot_w: u16, slot_h: u16) -> (u16, u16, u16, u16) {
    let inner_w = slot_w.saturating_sub(MEDIA_TILE_BORDER_LINES).max(1);
    let inner_h = slot_h.saturating_sub(MEDIA_TILE_BORDER_LINES).max(1);
    let footer_lines = if inner_h >= MEDIA_TILE_TITLE_LINES + MEDIA_TILE_FOOTER_LINES + 2 {
        MEDIA_TILE_FOOTER_LINES
    } else {
        0
    };
    let image_h = inner_h
        .saturating_sub(MEDIA_TILE_TITLE_LINES + footer_lines)
        .max(1);
    (inner_w, inner_h, image_h, footer_lines)
}

fn fullscreen_footer(point: &MediaPoint, width: usize) -> String {
    let mut parts = Vec::new();
    if !point.caption.is_empty() {
        parts.push(point.caption.clone());
    }
    if point.width > 0 && point.height > 0 {
        parts.push(format!("{}x{}", point.width, point.height));
    }
    if !point.format.is_empty() {
        parts.push(point.format.to_uppercase());
    }
    parts.push(format!("X=_step {}", format_media_axis_value(point.x)));
    truncate_value(&parts.join(" • "), width)
}

fn hint_or_default<'a>(hint: &'a str, fallback: &'a str) -> &'a str {
    if hint.is_empty() { fallback } else { hint }
}

fn format_media_axis_value(x: f64) -> String {
    if x.trunc() == x {
        format!("{x:.0}")
    } else {
        format!("{x:.3}")
    }
}
