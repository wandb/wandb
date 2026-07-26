//! Port of `core/internal/leet/mediapane.go` — a collapsible, animated pane
//! that renders `wandb.Image` media as a tile grid with scrubbing, linked
//! scrubbing, fullscreen, paging and an ANSI(glyph)/Kitty renderer switch.
//!
//! Rendering goes through the [`crate::layout`] lipgloss subset; block
//! values are `ratatui::text::Text` instead of ANSI strings. Go's `""`
//! return ports as an empty `Text` (no lines). Image decoding + the
//! glyph/Kitty pipelines live in [`crate::picture`].
//!
//! PARITY (prepare loop, CONCURRENCY.md C5/§2.5): Go wakes a Kitty prepare
//! pass through a cap-1 self-notify channel — `prepareCh`
//! (mediapane.go:141, :153), try-send in `requestRenderedMediaPrepare`
//! (mediapane.go:219-227), a blocking `waitForPrepare` pump armed in `Init`
//! and re-armed by `handlePrepareMsg` (mediapane.go:212-217, :229-231),
//! delivering `mediaPanePrepareMsg` (mediapane.go:248-251). In the Rust
//! design the request originates on the main thread (render path), so the
//! channel + pump collapse to the [`MediaPane::prepare_requested`] dirty
//! flag: the render path sets it (same cap-1 coalescing — setting a set
//! flag is the dropped try-send), and the event loop drains it after draw
//! via [`MediaPane::take_prepare_request`] + [`MediaPane::handle_prepare`]
//! (the `handlePrepareMsg` body minus the pump re-arm). Per the event.rs
//! header note, no `Event` variant is added: in test mode the renderer can
//! never enter Kitty mode (capability queries are suppressed and the
//! capability stays Unknown, testmode.go:20-21), so the Go oracle never
//! acks a `mediaPanePrepareMsg` either — ack parity holds without one. If
//! a future harness scenario forces Kitty in the oracle, an ack-visible
//! `Event` variant ("leet.mediaPanePrepareMsg") must be added to event.rs
//! (flagged for that unit's owner; not added here).
//!
//! Picture-message wiring: [`MediaPane::handle_picture_msg`] is Go's
//! `handlePictureMsg` forwarding loop (mediapane.go:208-210,
//! mediapane.go:1256-1273) behind the `picture.IsPictureMsg` gate
//! (run.go:219-222, workspace.go:215-217). [`CellSizeEvent`] mirrors
//! ultraviolet's `uv.CellSizeEvent` (the CSI 16 t reply);
//! [`MediaPaneCmd::RequestCellSize`] / [`MediaPaneCmd::QueryKittySupport`]
//! map to `picture.RequestCellSize()` / `picture.QueryKittySupport()`
//! (both suppressed in test mode; the runtime captures the replies at
//! startup and replays them as events — see runtime.rs
//! `detect_terminal_capabilities`).

use std::cell::RefCell;
use std::collections::{BTreeMap, HashMap};
use std::fmt;
use std::rc::Rc;
use std::sync::Arc;
use std::time::{Duration, Instant};

use leet_charts::styles::{
    COLOR_LAYOUT, COLOR_LAYOUT_HIGHLIGHT, COLOR_SUBHEADING, COLOR_SUBTLE, COLOR_TEXT,
};
use leet_data::go_fmt::format_float_f;
use leet_data::media::{MediaPoint, MediaStore};
use leet_data::width::text_width;
use ratatui::text::{Line, Span, Text};

use crate::animation::AnimatedValue;
use crate::console_logs_pane::CONSOLE_LOGS_PANE_HEIGHT_RATIO;
use crate::event::{Event, KittyGraphicsMsg};
use crate::key::{KeyEvent, normalize_key};
use crate::layout::{
    CENTER, GoStyle, LEFT, TOP, adaptive_to_color, block_width, join_horizontal, join_vertical,
    line_width, nav_info_style, normal_border, place, text_from_str,
};
use crate::panel_grid::GridNavigator;
use crate::picture::{
    ApplyKittyGridMsg, Config as PictureConfig, KittyCapability, KittyFrameMsg,
    Model as PictureModel, PictureCmd, PictureMode, SourceImage, force_kitty_capability,
    kitty_supported, next_media_kitty_id,
};
use crate::run_overview_sidebar::truncate_value;

// PARITY: ContentPadding/ContentPaddingCols live in styles.go in Go; the
// Rust styles module hosts them as i64 — cast once so the pane math stays
// isize (console_logs_pane.rs does the same).
const CONTENT_PADDING: isize = leet_charts::styles::CONTENT_PADDING as isize;
const CONTENT_PADDING_COLS: isize = leet_charts::styles::CONTENT_PADDING_COLS as isize;

// Golden ratio constants for visually pleasing layout proportions.
pub const GOLDEN_RATIO: f64 = 1.618033988749895;
pub const UPPER_TIER_RATIO: f64 = GOLDEN_RATIO / (1.0 + GOLDEN_RATIO); // ≈ 0.618
pub const LOWER_TIER_RATIO: f64 = 1.0 / (1.0 + GOLDEN_RATIO); // ≈ 0.382

/// MediaPaneHeightRatio controls the fraction of total terminal height used
/// when the media pane is the only bottom pane visible.
pub const MEDIA_PANE_HEIGHT_RATIO: f64 = CONSOLE_LOGS_PANE_HEIGHT_RATIO;

/// BottomPaneHeightRatioThree is the per-pane fraction used when three
/// stacked bottom panes are visible at once.
pub const BOTTOM_PANE_HEIGHT_RATIO_THREE: f64 = 0.146;

const MEDIA_PANE_HEADER: &str = "Media";
const MEDIA_PANE_HEADER_LINES: isize = 2;
const MEDIA_TILE_MIN_WIDTH: isize = 18;
const MEDIA_TILE_MIN_HEIGHT: isize = 8;
const MEDIA_TILE_BORDER_LINES: isize = 2;
const MEDIA_TILE_TITLE_LINES: isize = 1;
const MEDIA_TILE_FOOTER_LINES: isize = 1;
pub const MEDIA_PANE_MIN_HEIGHT: isize = MEDIA_PANE_HEADER_LINES + MEDIA_TILE_MIN_HEIGHT;

// PARITY: the Kitty image ID namespace (mediaKittyIDBase,
// mediaKittyIDCounter, nextMediaKittyID — mediapane.go:44-59) is hosted by
// crate::picture (`MEDIA_KITTY_ID_BASE` / `next_media_kitty_id`,
// CONCURRENCY.md S14: static AtomicI64) — not re-declared here.

// The mediapane.go style objects (mediapane.go:61-97). Adaptive colors are
// resolved eagerly via `dark` (Go reads the darkBackground global; see the
// layout module doc / CONCURRENCY.md S13).

fn media_pane_style() -> GoStyle {
    GoStyle::new().padding(&[0, leet_charts::styles::CONTENT_PADDING])
}

// PARITY: pub(crate) — workspace.go's renderMetricsEmptyState (hosted in
// run.rs, see the note there) reads this style directly, Go package-private
// access.
pub(crate) fn media_pane_header_style(dark: bool) -> GoStyle {
    GoStyle::new()
        .foreground(adaptive_to_color(COLOR_SUBHEADING, dark))
        .bold(true)
}

fn media_pane_active_header_style(dark: bool) -> GoStyle {
    GoStyle::new()
        .foreground(adaptive_to_color(COLOR_LAYOUT_HIGHLIGHT, dark))
        .bold(true)
}

fn media_pane_slider_style(dark: bool) -> GoStyle {
    GoStyle::new().foreground(adaptive_to_color(COLOR_SUBTLE, dark))
}

fn media_tile_border_style(dark: bool) -> GoStyle {
    GoStyle::new()
        .border(normal_border())
        .border_foreground(adaptive_to_color(COLOR_LAYOUT, dark))
}

fn media_tile_selected_border_style(dark: bool) -> GoStyle {
    GoStyle::new()
        .border(normal_border())
        .border_foreground(adaptive_to_color(COLOR_LAYOUT_HIGHLIGHT, dark))
}

fn media_tile_title_style(dark: bool) -> GoStyle {
    GoStyle::new()
        .foreground(adaptive_to_color(COLOR_TEXT, dark))
        .bold(true)
}

fn media_tile_selected_title_style(dark: bool) -> GoStyle {
    GoStyle::new()
        .foreground(adaptive_to_color(COLOR_SUBHEADING, dark))
        .bold(true)
}

fn media_tile_footer_style(dark: bool) -> GoStyle {
    GoStyle::new().foreground(adaptive_to_color(COLOR_SUBTLE, dark))
}

// PARITY: pub(crate) — see media_pane_header_style.
pub(crate) fn media_tile_placeholder_style(dark: bool) -> GoStyle {
    GoStyle::new().foreground(adaptive_to_color(COLOR_SUBTLE, dark))
}

/// The requested media grid shape from the surrounding UI
/// (Go `gridConfig func() (rows, cols int)`).
pub type GridConfig = Box<dyn Fn() -> (isize, isize)>;

/// Ultraviolet's `uv.CellSizeEvent` — the terminal's reply to the CSI 16 t
/// cell-size query, captured by the runtime and routed here as
/// `Event::CellSize` → [`MediaPane::handle_picture_msg`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CellSizeEvent {
    pub width: isize,
    pub height: isize,
}

/// The `tea.Cmd`s the media pane's Go methods return, as data
/// (CONCURRENCY.md §2.7 — the app shell maps these onto `Command`s).
#[derive(Debug, Clone)]
pub enum MediaPaneCmd {
    /// A picture-model command: raw Kitty delete bytes or a deferred Kitty
    /// render (see [`PictureCmd`]).
    Picture(PictureCmd),
    /// `picture.RequestCellSize()` — the CSI 16 t query (mediapane.go:187).
    /// Suppressed in test mode.
    RequestCellSize,
    /// `picture.QueryKittySupport()` — the Kitty `a=q` probe
    /// (mediapane.go:188). Suppressed in test mode.
    QueryKittySupport,
}

fn picture_cmds(cmds: Vec<PictureCmd>) -> Vec<MediaPaneCmd> {
    cmds.into_iter().map(MediaPaneCmd::Picture).collect()
}

/// MediaPane is a collapsible, animated pane that renders wandb.Image media.
pub struct MediaPane {
    /// animState controls the pane's animated height and visibility.
    // PARITY: Go holds a `*AnimatedValue` built by the caller; run.go
    // reaches through it, so the single-threaded port owns it as a
    // pub(crate) field (console_logs_pane.rs precedent, CONCURRENCY.md S7).
    pub(crate) anim_state: AnimatedValue,
    /// gridConfig returns the requested media grid shape from the
    /// surrounding UI.
    grid_config: Option<GridConfig>,
    /// renderer owns image decoding plus ANSI/Kitty rendering caches.
    renderer: MediaImageRenderer,

    /// store provides the media series and points rendered by this pane.
    // PARITY: Go shares the `*MediaStore` pointer between the workspace and
    // run views (run.go:167-170) → `Rc<RefCell<_>>` (CONCURRENCY.md S10).
    // pub(crate): workspace.go reads `w.mediaPane.store` directly
    // (syncCurrentRunContext, workspace.go:470), Go package-private access.
    pub(crate) store: Option<Rc<RefCell<MediaStore>>>,

    /// active allows the pane to consume media navigation keys.
    active: bool,
    /// fullscreen expands the selected image inside the pane and keeps keys
    /// local.
    fullscreen: bool,
    /// linkedScrub makes the scrub keys move all media series in sync by
    /// driving a single shared cursor over the union X timeline.
    linked_scrub: bool,
    /// linkedXIndex is the shared cursor's index into store.XValues().
    linked_x_index: isize,
    /// linkedAutoFollow keeps the shared cursor pinned to the latest X
    /// value.
    linked_auto_follow: bool,

    /// selectedIndex is the selected series index within
    /// store.SeriesKeys().
    selected_index: isize,
    /// pageRows/pageCols are the effective grid dimensions for the last
    /// viewport.
    page_rows: isize,
    page_cols: isize,

    /// xIndices stores the selected X-value index for each media series.
    x_indices: HashMap<String, isize>,
    /// autoFollows records which series should stay pinned to their latest
    /// X value.
    auto_follows: HashMap<String, bool>,

    /// nav tracks paged movement through the media grid.
    nav: GridNavigator,

    /// renderKeys are the currently visible media placements, recorded at
    /// render time and consumed by the Kitty prepare loop.
    render_keys: Vec<MediaRenderKey>,
    /// prepareCh replacement: the render path sets this dirty flag and the
    /// event loop drains it (see the module doc; CONCURRENCY.md §2.5).
    prepare_requested: bool,
}

impl fmt::Debug for MediaPane {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("MediaPane")
            .field("active", &self.active)
            .field("fullscreen", &self.fullscreen)
            .field("linked_scrub", &self.linked_scrub)
            .field("linked_x_index", &self.linked_x_index)
            .field("selected_index", &self.selected_index)
            .field("page_rows", &self.page_rows)
            .field("page_cols", &self.page_cols)
            .finish_non_exhaustive()
    }
}

impl MediaPane {
    pub fn new(anim_state: AnimatedValue, grid_config: Option<GridConfig>) -> MediaPane {
        MediaPane {
            anim_state,
            grid_config,
            renderer: MediaImageRenderer::new(),
            store: None,
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
            prepare_requested: false,
        }
    }

    pub fn height(&self) -> isize {
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

    pub fn update(&mut self, now: Instant) -> bool {
        self.anim_state.update(now)
    }

    pub fn set_expanded_height(&mut self, height: isize) {
        self.anim_state
            .set_expanded(height.max(MEDIA_PANE_MIN_HEIGHT));
    }

    pub fn update_expanded_height(&mut self, max_terminal_height: isize) {
        let max_height = (max_terminal_height as f64 * MEDIA_PANE_HEIGHT_RATIO) as isize;
        self.set_expanded_height(max_height);
    }

    /// Init asks the terminal for what Kitty rendering needs: its cell pixel
    /// size (so images are encoded at the display's true resolution) and
    /// Kitty graphics support.
    // PARITY: Go additionally arms the internal prepare pump
    // (`waitForPrepare`) here; the pump is replaced by the
    // `prepare_requested` flag (module doc), so only the capability queries
    // remain.
    pub fn init(&self) -> Vec<MediaPaneCmd> {
        if leet_data::test_mode::enabled() {
            // No capability queries under the test harness: frames must not
            // depend on terminal replies, and the renderer stays in glyph
            // mode.
            return Vec::new();
        }
        vec![
            MediaPaneCmd::RequestCellSize,
            MediaPaneCmd::QueryKittySupport,
        ]
    }

    pub fn set_store(&mut self, store: Option<Rc<RefCell<MediaStore>>>) {
        // PARITY: Go compares the raw store pointer (mediapane.go:193).
        let same = match (&self.store, &store) {
            (Some(a), Some(b)) => Rc::ptr_eq(a, b),
            (None, None) => true,
            _ => false,
        };
        if same {
            self.sync_state();
            return;
        }
        self.store = store;
        self.sync_state();
    }

    pub fn toggle_fullscreen(&mut self) {
        self.fullscreen = !self.fullscreen;
        if self.fullscreen {
            self.active = true;
        }
    }

    /// Go `handlePictureMsg` (mediapane.go:208-210) behind the
    /// `picture.IsPictureMsg` gate (run.go:219-222, workspace.go:215-217):
    /// `None` = not a picture message, fall through to normal routing;
    /// `Some(cmds)` = consumed (the caller returns, like Go).
    pub fn handle_picture_msg(&mut self, msg: &Event) -> Option<Vec<MediaPaneCmd>> {
        match msg {
            Event::CellSize { width, height } => Some(self.handle_cell_size(CellSizeEvent {
                width: *width,
                height: *height,
            })),
            // The uv.KittyGraphicsEvent / kittyProbeTickMsg arms of
            // picture.Model.Update (picture.go:474-480) mutate only the
            // process-wide capability; the per-model forwarding is a no-op.
            Event::KittyGraphics(g) => {
                record_kitty_response(g);
                Some(Vec::new())
            }
            Event::KittyProbeTick => {
                record_kitty_timeout();
                Some(Vec::new())
            }
            Event::KittyFrame(frame) => {
                let mut cmds = Vec::new();
                if let Some((apc, apply)) = self.on_kitty_frame(frame) {
                    // PARITY: Go returns tea.Sequence(tea.Raw(apc),
                    // applyKittyGridCmd) so the APC bytes hit the wire
                    // before the placeholder grid renders. Here the Raw
                    // command is dispatched (written) after Update returns
                    // but before the next draw, so applying the grid
                    // synchronously preserves the on-wire order without an
                    // applyKittyGridMsg round-trip (see the event.rs module
                    // doc).
                    self.on_apply_kitty_grid(&apply);
                    cmds.push(MediaPaneCmd::Picture(PictureCmd::Raw(apc)));
                }
                Some(cmds)
            }
            _ => None,
        }
    }

    /// The `uv.CellSizeEvent` arm of Go `handlePictureMsg` →
    /// `renderer.Update` (mediapane.go:208-210, :1256-1273).
    pub fn handle_cell_size(&mut self, ev: CellSizeEvent) -> Vec<MediaPaneCmd> {
        picture_cmds(self.renderer.handle_cell_size(ev))
    }

    /// The `picture.KittyFrameMsg` arm of Go `handlePictureMsg`. The caller
    /// MUST write the returned APC bytes before feeding the grid message
    /// back through [`MediaPane::on_apply_kitty_grid`] (Go sequences them
    /// with `tea.Sequence`; see `picture::Model::on_kitty_frame`).
    pub fn on_kitty_frame(&mut self, msg: &KittyFrameMsg) -> Option<(String, ApplyKittyGridMsg)> {
        self.renderer.on_kitty_frame(msg)
    }

    /// The `applyKittyGridMsg` arm of Go `handlePictureMsg`.
    pub fn on_apply_kitty_grid(&mut self, msg: &ApplyKittyGridMsg) {
        self.renderer.on_apply_kitty_grid(msg);
    }

    /// Drains the prepare request recorded by the render path. The event
    /// loop calls this after drawing; when it returns true the loop runs
    /// [`MediaPane::handle_prepare`] — the same-thread replacement for the
    /// `waitForPrepare` pump delivering `mediaPanePrepareMsg` (module doc).
    pub fn take_prepare_request(&mut self) -> bool {
        std::mem::take(&mut self.prepare_requested)
    }

    fn request_rendered_media_prepare(&mut self) {
        if self.renderer.mode() != PictureMode::Kitty {
            return;
        }
        // PARITY: Go try-sends into the cap-1 prepareCh and drops when full
        // (mediapane.go:223-226); setting an already-set flag is the same
        // coalescing (CONCURRENCY.md §2.5).
        self.prepare_requested = true;
    }

    /// Go `handlePrepareMsg` (mediapane.go:229-231) minus the pump re-arm:
    /// runs the Kitty prepare pass over the placements recorded at render
    /// time.
    pub fn handle_prepare(&mut self) -> Vec<MediaPaneCmd> {
        let keys = self.render_keys.clone();
        picture_cmds(self.renderer.prepare_visible(&keys))
    }

    /// Park releases rendered media for images that are not currently
    /// visible.
    pub fn park(&mut self) {
        self.set_rendered_media(&[]);
    }

    fn set_rendered_media(&mut self, keys: &[MediaRenderKey]) {
        self.renderer.park(keys);

        if self.render_keys == keys {
            return;
        }
        self.render_keys.clear();
        self.render_keys.extend_from_slice(keys);
        self.request_rendered_media_prepare();
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

    pub fn restore_view_state(&mut self, s: &MediaPaneViewState) {
        self.selected_index = s.selected_index;
        self.x_indices.clear();
        self.x_indices
            .extend(s.x_indices.iter().map(|(k, v)| (k.clone(), *v)));
        self.auto_follows.clear();
        self.auto_follows
            .extend(s.auto_follows.iter().map(|(k, v)| (k.clone(), *v)));
        self.linked_scrub = s.linked_scrub;
        self.linked_x_index = s.linked_x_index;
        let xs = self.union_x_values();
        self.linked_auto_follow = !xs.is_empty() && s.linked_x_index >= xs.len() as isize - 1;
        self.fullscreen = false;
        self.sync_state();
    }

    pub fn reset_view_state(&mut self) {
        self.selected_index = 0;
        self.x_indices.clear();
        self.auto_follows.clear();
        self.linked_scrub = false;
        self.linked_x_index = 0;
        self.linked_auto_follow = false;
        set_nav_page(&mut self.nav, 0);
        self.fullscreen = false;
        self.sync_state();
    }

    pub fn exit_fullscreen(&mut self) {
        self.fullscreen = false;
    }

    fn sync_state(&mut self) {
        let keys = self.series_keys();

        if keys.is_empty() {
            self.selected_index = 0;
            self.nav.update_total_pages(0, 1);
            self.fullscreen = false;
            return;
        }

        self.selected_index = clamp(self.selected_index, 0, keys.len() as isize - 1);

        // Ensure per-series indices exist and are clamped.
        for key in &keys {
            let xs = self.series_x_values(key);
            if !self.auto_follows.contains_key(key) {
                self.auto_follows.insert(key.clone(), true);
            }
            if xs.is_empty() {
                self.x_indices.insert(key.clone(), 0);
            } else if self.auto_follows[key] {
                self.x_indices.insert(key.clone(), xs.len() as isize - 1);
            } else {
                let cur = self.x_indices.get(key).copied().unwrap_or(0);
                self.x_indices
                    .insert(key.clone(), clamp(cur, 0, xs.len() as isize - 1));
            }
        }

        // Maintain the shared linked cursor against the union timeline.
        let xs = self.union_x_values();
        if xs.is_empty() {
            self.linked_x_index = 0;
        } else if self.linked_auto_follow {
            self.linked_x_index = xs.len() as isize - 1;
        } else {
            self.linked_x_index = clamp(self.linked_x_index, 0, xs.len() as isize - 1);
        }

        let items_per_page = self.items_per_page();
        self.nav
            .update_total_pages(keys.len() as isize, items_per_page);
        if items_per_page > 0 {
            let page = self.selected_index / items_per_page;
            if page >= 0 && page < self.nav.total_pages() {
                set_nav_page(&mut self.nav, page);
            }
        }
    }

    fn series_keys(&self) -> Vec<String> {
        match &self.store {
            None => Vec::new(),
            Some(store) => store.borrow().series_keys(),
        }
    }

    fn pagination_grid(&self) -> (isize, isize) {
        let rows = self.page_rows.max(1);
        let cols = self.page_cols.max(1);
        (rows, cols)
    }

    fn items_per_page(&self) -> isize {
        let (rows, cols) = self.pagination_grid();
        (rows * cols).max(1)
    }

    fn series_x_values(&self, key: &str) -> Vec<f64> {
        match &self.store {
            None => Vec::new(),
            Some(store) => store.borrow().series_x_values(key),
        }
    }

    fn current_x_for_series(&self, key: &str) -> Option<f64> {
        let xs = self.series_x_values(key);
        if xs.is_empty() {
            return None;
        }
        let idx = clamp(
            self.x_indices.get(key).copied().unwrap_or(0),
            0,
            xs.len() as isize - 1,
        );
        Some(xs[idx as usize])
    }

    // PARITY: Go returns `(key, point, ok)` — the key is meaningful even
    // when ok is false (StatusLabel falls back to the scrub position).
    fn current_selection(&self) -> (String, MediaPoint, bool) {
        let keys = self.series_keys();
        if keys.is_empty() {
            return (String::new(), MediaPoint::default(), false);
        }
        let idx = clamp(self.selected_index, 0, keys.len() as isize - 1);
        let key = keys[idx as usize].clone();
        let (x, store) = (self.scrub_x(&key), self.store.as_ref());
        let (Some(x), Some(store)) = (x, store) else {
            return (key, MediaPoint::default(), false);
        };
        match store.borrow().resolve_at(&key, x) {
            Some(point) => (key, point, true),
            None => (key, MediaPoint::default(), false),
        }
    }

    pub fn has_data(&self) -> bool {
        self.store.as_ref().is_some_and(|s| !s.borrow().empty())
    }

    pub fn status_label(&self) -> String {
        let (key, point, ok) = self.current_selection();
        if key.is_empty() {
            return String::new();
        }

        // Show the resolved sample's step; fall back to the scrub position
        // when the series has no sample there yet.
        let (mut x, mut has_x) = match self.scrub_x(&key) {
            Some(x) => (x, true),
            None => (0.0, false),
        };
        if ok {
            (x, has_x) = (point.x, true);
        }
        let mut parts = vec![format!("Media: {key}")];
        if has_x {
            parts.push(format!("X=_step {}", format_media_axis_value(x)));
        }
        if ok && !point.caption.is_empty() {
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

    /// HandleKey handles media-pane-local navigation. It returns whether
    /// the key was consumed and any commands needed to render media.
    //
    // Go carries a gocyclo:ignore for the same switch.
    pub fn handle_key(&mut self, msg: &KeyEvent) -> (bool, Vec<MediaPaneCmd>) {
        if !self.active && !self.fullscreen {
            return (false, Vec::new());
        }

        match normalize_key(&msg.key_string()) {
            "enter" => {
                if self.has_data() {
                    self.toggle_fullscreen();
                }
                (true, Vec::new())
            }
            "esc" => {
                if self.fullscreen {
                    self.exit_fullscreen();
                    return (true, Vec::new());
                }
                (false, Vec::new())
            }
            "k" => {
                let mut cmd = Vec::new();
                if self.has_data() {
                    cmd = picture_cmds(self.renderer.toggle_mode());
                    self.request_rendered_media_prepare();
                }
                (true, cmd)
            }
            "l" => {
                if self.has_data() {
                    self.toggle_linked_scrub();
                }
                (true, Vec::new())
            }
            "left" => {
                self.scrub(-1);
                (true, Vec::new())
            }
            "right" => {
                self.scrub(1);
                (true, Vec::new())
            }
            "up" => {
                self.scrub(-10);
                (true, Vec::new())
            }
            "down" => {
                self.scrub(10);
                (true, Vec::new())
            }
            "home" => {
                self.scrub_to_start();
                (true, Vec::new())
            }
            "end" => {
                self.scrub_to_end();
                (true, Vec::new())
            }
            "a" => {
                self.move_selection(-1, 0);
                (true, Vec::new())
            }
            "d" => {
                self.move_selection(1, 0);
                (true, Vec::new())
            }
            "w" => {
                self.move_selection(0, -1);
                (true, Vec::new())
            }
            "s" => {
                self.move_selection(0, 1);
                (true, Vec::new())
            }
            "pgup" => {
                self.navigate_page(-1);
                (true, Vec::new())
            }
            "pgdown" => {
                self.navigate_page(1);
                (true, Vec::new())
            }
            _ => (false, Vec::new()),
        }
    }

    pub fn move_selection(&mut self, dx: isize, dy: isize) {
        let keys = self.series_keys();
        if keys.is_empty() {
            return;
        }

        let (rows, cols) = self.pagination_grid();
        let items_per_page = self.items_per_page();
        self.nav
            .update_total_pages(keys.len() as isize, items_per_page);

        let (mut start_idx, mut end_idx) =
            self.nav.page_bounds(keys.len() as isize, items_per_page);
        if self.selected_index < start_idx || self.selected_index >= end_idx {
            set_nav_page(&mut self.nav, self.selected_index / items_per_page);
            (start_idx, end_idx) = self.nav.page_bounds(keys.len() as isize, items_per_page);
        }

        let local = clamp(
            self.selected_index - start_idx,
            0,
            (end_idx - start_idx - 1).max(0),
        );
        let mut row = local / cols;
        let mut col = local % cols;
        row = clamp(row + dy, 0, rows - 1);
        col = clamp(col + dx, 0, cols - 1);

        let mut candidate = start_idx + row * cols + col;
        if candidate >= end_idx {
            candidate = end_idx - 1;
        }
        if candidate >= start_idx {
            self.selected_index = candidate;
        }
    }

    pub fn navigate_page(&mut self, direction: isize) {
        let keys = self.series_keys();
        if keys.is_empty() {
            return;
        }

        let items_per_page = self.items_per_page();
        self.nav
            .update_total_pages(keys.len() as isize, items_per_page);
        if !self.nav.navigate(direction) {
            return;
        }

        let (start_idx, end_idx) = self.nav.page_bounds(keys.len() as isize, items_per_page);
        if self.selected_index < start_idx || self.selected_index >= end_idx {
            self.selected_index = start_idx;
        }
    }

    /// selectedKey returns the currently selected series key.
    fn selected_key(&self) -> String {
        let keys = self.series_keys();
        if keys.is_empty() {
            return String::new();
        }
        keys[clamp(self.selected_index, 0, keys.len() as isize - 1) as usize].clone()
    }

    /// Scrub moves the scrub position by delta samples: the shared cursor
    /// over the union timeline when scrubbing is linked, the selected
    /// series otherwise.
    pub fn scrub(&mut self, delta: isize) {
        if self.linked_scrub {
            let xs = self.union_x_values();
            if xs.is_empty() {
                return;
            }
            self.linked_x_index = clamp(self.linked_x_index + delta, 0, xs.len() as isize - 1);
            self.linked_auto_follow = self.linked_x_index == xs.len() as isize - 1;
            return;
        }

        let key = self.selected_key();
        if key.is_empty() {
            return;
        }
        let xs = self.series_x_values(&key);
        if xs.is_empty() {
            return;
        }
        let cur = self.x_indices.get(&key).copied().unwrap_or(0);
        let idx = clamp(cur + delta, 0, xs.len() as isize - 1);
        self.x_indices.insert(key.clone(), idx);
        self.auto_follows.insert(key, idx == xs.len() as isize - 1);
    }

    pub fn scrub_to_start(&mut self) {
        if self.linked_scrub {
            self.linked_x_index = 0;
            self.linked_auto_follow = false;
            return;
        }

        let key = self.selected_key();
        if key.is_empty() {
            return;
        }
        self.x_indices.insert(key.clone(), 0);
        self.auto_follows.insert(key, false);
    }

    pub fn scrub_to_end(&mut self) {
        if self.linked_scrub {
            let xs = self.union_x_values();
            if !xs.is_empty() {
                self.linked_x_index = xs.len() as isize - 1;
            }
            self.linked_auto_follow = true;
            return;
        }

        let key = self.selected_key();
        if key.is_empty() {
            return;
        }
        let xs = self.series_x_values(&key);
        if xs.is_empty() {
            return;
        }
        self.x_indices.insert(key.clone(), xs.len() as isize - 1);
        self.auto_follows.insert(key, true);
    }

    /// toggleLinkedScrub switches between linked and per-series scrubbing.
    ///
    /// Linking starts the shared cursor at the most advanced series
    /// position so the view doesn't jump; unlinking writes the cursor back
    /// into each series' own scrub position so tiles keep showing the same
    /// samples.
    fn toggle_linked_scrub(&mut self) {
        if self.linked_scrub {
            if let Some(x) = self.linked_x() {
                for key in self.series_keys() {
                    self.align_series_to(&key, x);
                }
            }
            self.linked_scrub = false;
            return;
        }

        let union = self.union_x_values();
        let mut cursor: isize = 0;
        for key in self.series_keys() {
            if let Some(x) = self.current_x_for_series(&key) {
                let (idx, found) = slices_binary_search_f64(&union, x);
                if found {
                    cursor = cursor.max(idx as isize);
                }
            }
        }
        self.linked_x_index = cursor;
        self.linked_auto_follow = cursor == union.len() as isize - 1;
        self.linked_scrub = true;
    }

    /// alignSeriesTo moves a series' scrub position to its latest sample at
    /// or before x, or to its first sample when none exists yet.
    fn align_series_to(&mut self, key: &str, x: f64) {
        let xs = self.series_x_values(key);
        if xs.is_empty() {
            return;
        }
        let (found_idx, found) = slices_binary_search_f64(&xs, x);
        let mut idx = found_idx as isize;
        if !found {
            idx = (idx - 1).max(0);
        }
        self.x_indices.insert(key.to_string(), idx);
        self.auto_follows
            .insert(key.to_string(), idx == xs.len() as isize - 1);
    }

    fn union_x_values(&self) -> Vec<f64> {
        match &self.store {
            None => Vec::new(),
            Some(store) => store.borrow().x_values(),
        }
    }

    /// linkedX returns the shared cursor's X value on the union timeline.
    fn linked_x(&self) -> Option<f64> {
        let xs = self.union_x_values();
        if xs.is_empty() {
            return None;
        }
        Some(xs[clamp(self.linked_x_index, 0, xs.len() as isize - 1) as usize])
    }

    /// scrubX returns the X position a series' tile resolves against: the
    /// shared cursor when scrubbing is linked, the series' own position
    /// otherwise.
    fn scrub_x(&self, key: &str) -> Option<f64> {
        if self.linked_scrub {
            return self.linked_x();
        }
        self.current_x_for_series(key)
    }

    fn sync_grid_layout_for_viewport(&mut self, width: isize, height: isize) {
        if self.fullscreen {
            return;
        }

        let inner_w = (width - CONTENT_PADDING_COLS).max(0);
        let inner_h = height.max(0);
        if inner_w == 0 || inner_h == 0 {
            return;
        }

        let (rows, cols, _, _) =
            self.effective_grid(inner_w, (inner_h - MEDIA_PANE_HEADER_LINES).max(1));
        if rows != self.page_rows || cols != self.page_cols {
            self.page_rows = rows;
            self.page_cols = cols;
            self.sync_state();
        }
    }

    fn tile_index_at(&mut self, x: isize, y: isize, width: isize, height: isize) -> Option<isize> {
        if width <= 0 || height < MEDIA_PANE_MIN_HEIGHT || self.fullscreen {
            return None;
        }

        self.sync_grid_layout_for_viewport(width, height);
        let keys = self.series_keys();
        if keys.is_empty() {
            return None;
        }

        let inner_w = (width - CONTENT_PADDING_COLS).max(0);
        let grid_h = (height - MEDIA_PANE_HEADER_LINES).max(0);
        let grid_x = x - CONTENT_PADDING;
        let grid_y = y - MEDIA_PANE_HEADER_LINES;
        if grid_x < 0 || grid_y < 0 || grid_x >= inner_w || grid_y >= grid_h {
            return None;
        }

        let (rows, cols, slot_w, slot_h) = self.effective_grid(inner_w, grid_h.max(1));
        let row = grid_y / slot_h;
        let col = grid_x / slot_w;
        if row < 0 || row >= rows || col < 0 || col >= cols {
            return None;
        }

        let items_per_page = (rows * cols).max(1);
        self.nav
            .update_total_pages(keys.len() as isize, items_per_page);
        let (start_idx, end_idx) = self.nav.page_bounds(keys.len() as isize, items_per_page);
        let idx = start_idx + row * cols + col;
        if idx < start_idx || idx >= end_idx || idx >= keys.len() as isize {
            return None;
        }

        Some(idx)
    }

    /// HandleMouseClick selects the clicked media tile.
    pub fn handle_mouse_click(&mut self, x: isize, y: isize, width: isize, height: isize) -> bool {
        let Some(idx) = self.tile_index_at(x, y, width, height) else {
            return false;
        };
        self.selected_index = idx;
        true
    }

    /// `dark` resolves adaptive colors (Go reads the `darkBackground`
    /// global; the port passes it explicitly, see the layout module doc).
    pub fn view(
        &mut self,
        width: isize,
        height: isize,
        run_label: &str,
        hint: &str,
        dark: bool,
    ) -> Text<'static> {
        if width <= 0 || height < MEDIA_PANE_MIN_HEIGHT {
            self.set_rendered_media(&[]);
            return Text::default();
        }

        let inner_w = (width - CONTENT_PADDING_COLS).max(0);
        let inner_h = height.max(0);
        if inner_w == 0 || inner_h == 0 {
            self.set_rendered_media(&[]);
            return Text::default();
        }
        self.sync_grid_layout_for_viewport(width, height);

        let body = if self.fullscreen {
            self.render_fullscreen_body(inner_w, inner_h, run_label, hint, dark)
        } else {
            self.render_grid_body(inner_w, inner_h, run_label, hint, dark)
        };

        let body = place(inner_w as i64, inner_h as i64, LEFT, TOP, body);
        let padded = media_pane_style().render_text(body);
        place(width as i64, height as i64, LEFT, TOP, padded)
    }

    fn render_grid_body(
        &mut self,
        width: isize,
        height: isize,
        run_label: &str,
        hint: &str,
        dark: bool,
    ) -> Text<'static> {
        let grid_height = (height - MEDIA_PANE_HEADER_LINES).max(0);
        let head = self.render_header(width, run_label, false, dark);
        let slider = self.render_slider(width, dark);
        let grid = self.render_grid(width, grid_height, hint, dark);
        join_vertical(LEFT, vec![head, slider, grid])
    }

    fn render_fullscreen_body(
        &mut self,
        width: isize,
        height: isize,
        run_label: &str,
        hint: &str,
        dark: bool,
    ) -> Text<'static> {
        let (key, point, ok) = self.current_selection();
        let head = self.render_header(width, run_label, true, dark);
        let slider = self.render_slider(width, dark);
        let body_height = (height - MEDIA_PANE_HEADER_LINES).max(0);
        if !ok {
            self.set_rendered_media(&[]);
            let placeholder = render_media_placeholder(
                width,
                body_height,
                hint_or_default(hint, "No media."),
                dark,
            );
            return join_vertical(LEFT, vec![head, slider, placeholder]);
        }

        let title = self.render_title(&key, width, true, dark);
        let footer = media_tile_footer_style(dark)
            .width(width as i64)
            .render(&self.fullscreen_footer(&point, width));
        let image_height = (body_height - 2).max(1);
        self.set_rendered_media(&[MediaRenderKey {
            path: point.file_path.clone(),
            width,
            height: image_height,
        }]);
        let img = self
            .renderer
            .render(&point.file_path, width, image_height, dark);
        let content = join_vertical(LEFT, vec![title, img, footer]);
        let content = place(width as i64, body_height as i64, LEFT, TOP, content);
        join_vertical(LEFT, vec![head, slider, content])
    }

    fn render_header(
        &mut self,
        width: isize,
        run_label: &str,
        fullscreen: bool,
        dark: bool,
    ) -> Text<'static> {
        let mut title = MEDIA_PANE_HEADER.to_string();
        if fullscreen {
            title += " [fullscreen]";
        }
        let header_style = if self.active || self.fullscreen {
            media_pane_active_header_style(dark)
        } else {
            media_pane_header_style(dark)
        };

        let keys = self.series_keys();
        let items_per_page = self.items_per_page();
        self.nav
            .update_total_pages(keys.len() as isize, items_per_page);
        let mut nav_info = text_from_str("");
        if !keys.is_empty() {
            let (start_idx, end_idx) = self.nav.page_bounds(keys.len() as isize, items_per_page);
            nav_info = media_pane_slider_style(dark).render(&format!(
                " [{}-{} of {}]",
                start_idx + 1,
                end_idx,
                keys.len()
            ));
        }

        let title_label = header_style.render(&title);
        let mut left = title_label.clone();
        if !run_label.is_empty() {
            let sep = " • ";
            let max_run_width = width as i64
                - block_width(&title_label) as i64
                - block_width(&nav_info) as i64
                - text_width(sep) as i64;
            if max_run_width > 0 {
                left = join_horizontal(
                    LEFT,
                    vec![
                        title_label,
                        media_pane_slider_style(dark).render(&format!(
                            "{sep}{}",
                            truncate_value(run_label, max_run_width as isize)
                        )),
                    ],
                );
            }
        }

        let filler_width = width - block_width(&left) as isize - block_width(&nav_info) as isize;
        let filler = " ".repeat(filler_width.max(0) as usize);
        join_horizontal(LEFT, vec![left, text_from_str(&filler), nav_info])
    }

    fn render_slider(&self, width: isize, dark: bool) -> Text<'static> {
        let (xs, idx) = self.slider_position();
        if xs.is_empty() {
            return media_pane_slider_style(dark)
                .width(width as i64)
                .render("X: _step —");
        }

        let bar_width = clamp(width - 24, 8, 48);
        let mut pos = 0;
        if xs.len() > 1 {
            pos = idx * (bar_width - 1) / (xs.len() as isize - 1);
        }

        let mut b = String::new();
        for i in 0..bar_width {
            if i < pos {
                b.push('━');
            } else if i == pos {
                b.push('●');
            } else {
                b.push('─');
            }
        }

        let mut text = format!(
            "X: _step {}  {}  {}/{}",
            format_media_axis_value(xs[idx as usize]),
            b,
            idx + 1,
            xs.len()
        );
        if self.linked_scrub {
            text += "  [sync]";
        }
        media_pane_slider_style(dark)
            .width(width as i64)
            .render(&truncate_value(&text, width))
    }

    /// sliderPosition returns the timeline and cursor index the slider
    /// displays: the union timeline when scrubbing is linked, the selected
    /// series otherwise.
    fn slider_position(&self) -> (Vec<f64>, isize) {
        if self.linked_scrub {
            let xs = self.union_x_values();
            let idx = clamp(self.linked_x_index, 0, (xs.len() as isize - 1).max(0));
            return (xs, idx);
        }
        let key = self.selected_key();
        if key.is_empty() {
            return (Vec::new(), 0);
        }
        let xs = self.series_x_values(&key);
        let idx = clamp(
            self.x_indices.get(&key).copied().unwrap_or(0),
            0,
            (xs.len() as isize - 1).max(0),
        );
        (xs, idx)
    }

    fn render_grid(
        &mut self,
        width: isize,
        height: isize,
        hint: &str,
        dark: bool,
    ) -> Text<'static> {
        let keys = self.series_keys();
        if keys.is_empty() {
            self.set_rendered_media(&[]);
            return render_media_placeholder(
                width,
                height,
                hint_or_default(hint, "No media."),
                dark,
            );
        }

        let (rows, cols, slot_w, slot_h) = self.effective_grid(width, height);
        let items_per_page = (rows * cols).max(1);
        self.nav
            .update_total_pages(keys.len() as isize, items_per_page);
        let (start_idx, end_idx) = self.nav.page_bounds(keys.len() as isize, items_per_page);
        if self.selected_index < start_idx || self.selected_index >= end_idx {
            self.selected_index = start_idx;
        }

        let show_selection = self.active || self.fullscreen;
        let mut cells: Vec<Text<'static>> = Vec::with_capacity(items_per_page as usize);
        let (inner_w, _, image_h, _) = media_tile_layout(slot_w, slot_h);
        let mut render_keys: Vec<MediaRenderKey> =
            Vec::with_capacity((end_idx - start_idx).max(0) as usize);
        for idx in start_idx..end_idx {
            let key = keys[idx as usize].clone();
            let x = self.scrub_x(&key);
            let (mut point, mut ok) = (MediaPoint::default(), false);
            if let (Some(x), Some(store)) = (x, self.store.as_ref())
                && let Some(p) = store.borrow().resolve_at(&key, x)
            {
                (point, ok) = (p, true);
            }
            if ok {
                render_keys.push(MediaRenderKey {
                    path: point.file_path.clone(),
                    width: inner_w,
                    height: image_h,
                });
            }
            cells.push(self.render_tile(
                &key,
                &point,
                ok,
                show_selection && idx == self.selected_index,
                slot_w,
                slot_h,
                dark,
            ));
        }
        self.set_rendered_media(&render_keys);
        while (cells.len() as isize) < items_per_page {
            cells.push(
                GoStyle::new()
                    .width(slot_w as i64)
                    .height(slot_h as i64)
                    .render(""),
            );
        }

        let mut row_views: Vec<Text<'static>> = Vec::new();
        for row in 0..rows {
            let start = (row * cols) as usize;
            let end = (start + cols as usize).min(cells.len());
            if start >= end {
                break;
            }
            row_views.push(join_horizontal(TOP, cells[start..end].to_vec()));
        }

        let grid = join_vertical(LEFT, row_views);
        place(width as i64, height as i64, LEFT, TOP, grid)
    }

    #[allow(clippy::too_many_arguments)] // Go signature (mediapane.go:975-982).
    fn render_tile(
        &mut self,
        key: &str,
        point: &MediaPoint,
        ok: bool,
        selected: bool,
        slot_w: isize,
        slot_h: isize,
        dark: bool,
    ) -> Text<'static> {
        let (inner_w, inner_h, image_h, footer_lines) = media_tile_layout(slot_w, slot_h);

        let border_style = if selected {
            media_tile_selected_border_style(dark)
        } else {
            media_tile_border_style(dark)
        };

        let title = self.render_title(key, inner_w, selected, dark);

        let image_view = if ok {
            self.renderer
                .render(&point.file_path, inner_w, image_h, dark)
        } else {
            render_media_placeholder(inner_w, image_h, "No image at X", dark)
        };

        let mut parts = vec![title, image_view];
        if footer_lines > 0 {
            parts.push(
                media_tile_footer_style(dark)
                    .width(inner_w as i64)
                    .render(&self.tile_footer(key, point, ok, inner_w)),
            );
        }

        let content = join_vertical(LEFT, parts);
        let content = place(inner_w as i64, inner_h as i64, LEFT, TOP, content);
        border_style
            .width(slot_w as i64)
            .height(slot_h as i64)
            .render_text(content)
    }

    fn render_title(&self, key: &str, width: isize, selected: bool, dark: bool) -> Text<'static> {
        if width <= 0 {
            return text_from_str("");
        }

        let title_style = if selected {
            media_tile_selected_title_style(dark)
        } else {
            media_tile_title_style(dark)
        };

        let suffix = self.renderer_mode_title_suffix();
        let suffix_width = text_width(suffix) as isize;
        if width <= suffix_width + 1 {
            return title_style
                .width(width as i64)
                .render(&truncate_value(key, width));
        }

        let label = title_style.render(&truncate_value(key, width - suffix_width));
        let suffix_label = nav_info_style(dark).render(suffix);
        // PARITY: Go concatenates the two styled strings and pads with bare
        // spaces (mediapane.go:1026-1032); the span-model equivalent is one
        // line holding both span runs plus an unstyled pad span.
        let mut spans: Vec<Span<'static>> = Vec::new();
        for block in [label, suffix_label] {
            for l in block.lines {
                spans.extend(l.spans);
            }
        }
        let line = Line::from(spans);
        let padding = width - line_width(&line) as isize;
        let mut spans = line.spans;
        if padding > 0 {
            spans.push(Span::raw(" ".repeat(padding as usize)));
        }
        Text::from(Line::from(spans))
    }

    fn renderer_mode_title_suffix(&self) -> &'static str {
        if self.renderer.mode() == PictureMode::Kitty {
            return " [full-res]";
        }
        " [ansi]"
    }

    fn tile_footer(&self, key: &str, point: &MediaPoint, ok: bool, width: isize) -> String {
        // Show the resolved sample's step; fall back to the scrub position
        // when the series has no sample there yet.
        let (mut x, mut has_x) = match self.scrub_x(key) {
            Some(x) => (x, true),
            None => (0.0, false),
        };
        if ok {
            (x, has_x) = (point.x, true);
        }
        let mut step_label = String::new();
        if has_x {
            step_label = format!("X=_step {}", format_media_axis_value(x));
        }
        if !ok {
            return truncate_value(&step_label, width);
        }
        let mut parts: Vec<String> = Vec::new();
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

    fn fullscreen_footer(&self, point: &MediaPoint, width: isize) -> String {
        let mut parts: Vec<String> = Vec::new();
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
        if parts.is_empty() {
            return String::new();
        }
        truncate_value(&parts.join(" • "), width)
    }

    fn effective_grid(&self, width: isize, height: isize) -> (isize, isize, isize, isize) {
        let (mut cfg_rows, mut cfg_cols) = (1, 1);
        if let Some(grid_config) = &self.grid_config {
            (cfg_rows, cfg_cols) = grid_config();
        }
        cfg_rows = cfg_rows.max(1);
        cfg_cols = cfg_cols.max(1);

        let mut cols = cfg_cols.min((width / MEDIA_TILE_MIN_WIDTH).max(1));
        let mut rows = cfg_rows.min((height / MEDIA_TILE_MIN_HEIGHT).max(1));
        cols = cols.max(1);
        rows = rows.max(1);
        let slot_w = if width > 0 { (width / cols).max(1) } else { 1 };
        let slot_h = if height > 0 {
            (height / rows).max(1)
        } else {
            1
        };
        (rows, cols, slot_w, slot_h)
    }
}

fn hint_or_default<'a>(hint: &'a str, fallback: &'a str) -> &'a str {
    if !hint.is_empty() {
        return hint;
    }
    fallback
}

fn format_media_axis_value(x: f64) -> String {
    // PARITY: Go fmt %.0f / %.3f == strconv.FormatFloat 'f' — routed
    // through the go_fmt compat module (PORTING.md).
    if x.trunc() == x {
        return format_float_f(x, 0);
    }
    format_float_f(x, 3)
}

fn render_media_placeholder(width: isize, height: isize, msg: &str, dark: bool) -> Text<'static> {
    if width <= 0 || height <= 0 {
        return Text::default();
    }
    let msg = truncate_value(msg, width);
    place(
        width as i64,
        height as i64,
        CENTER,
        CENTER,
        media_tile_placeholder_style(dark).render(&msg),
    )
}

fn media_tile_layout(slot_w: isize, slot_h: isize) -> (isize, isize, isize, isize) {
    let inner_w = (slot_w - MEDIA_TILE_BORDER_LINES).max(1);
    let inner_h = (slot_h - MEDIA_TILE_BORDER_LINES).max(1);
    let mut footer_lines = 0;
    if inner_h >= MEDIA_TILE_TITLE_LINES + MEDIA_TILE_FOOTER_LINES + 2 {
        footer_lines = MEDIA_TILE_FOOTER_LINES;
    }
    let image_h = (inner_h - MEDIA_TILE_TITLE_LINES - footer_lines).max(1);
    (inner_w, inner_h, image_h, footer_lines)
}

/// MediaPaneViewState captures the navigable state of a MediaPane so it can
/// be saved and restored across Run view transitions.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct MediaPaneViewState {
    pub selected_index: isize,
    pub x_indices: HashMap<String, isize>,
    pub auto_follows: HashMap<String, bool>,
    pub linked_scrub: bool,
    pub linked_x_index: isize,
}

/// Go writes `p.nav.currentPage = page` directly (same-package field
/// access, mediapane.go:300, :352, :524); the field is private to
/// panel_grid here, so the write is emulated through the public API: jump
/// to page 0 (`go_home`) then one forward `navigate`, which for an
/// in-range target is a plain add from 0 — never a wrap — so the result
/// and `totalPages` match Go's field write exactly. Every Go write site
/// passes a page in `[0, totalPages)`: syncState guards it explicitly
/// (mediapane.go:351), MoveSelection derives it from a selectedIndex
/// already clamped below len(keys) right after UpdateTotalPages
/// (mediapane.go:520-524), and ResetViewState writes 0 (mediapane.go:300).
///
/// PARITY: for an out-of-range page Go stores the raw value (PageBounds
/// then yields an empty range) until the next UpdateTotalPages clamps it
/// back into `[0, totalPages)`; that raw transient is not expressible
/// through the public GridNavigator API — exact emulation needs a
/// pub(crate) page setter on panel_grid::GridNavigator (that module's
/// owner) — so this helper clamps immediately (the state Go converges to)
/// and debug-asserts so any future caller hitting the difference fails
/// loudly instead of silently diverging from the oracle. No current caller
/// can reach it.
fn set_nav_page(nav: &mut GridNavigator, page: isize) {
    debug_assert!(
        (page == 0 && nav.total_pages() <= 0) || (0..nav.total_pages()).contains(&page),
        "set_nav_page: page {page} outside [0, {}) — Go stores the raw page; \
         exact parity needs a panel_grid::GridNavigator page setter",
        nav.total_pages(),
    );
    if nav.total_pages() <= 0 {
        // Reachable only with page == 0 (ResetViewState while the store is
        // empty): current_page may be stale because UpdateTotalPages skips
        // its clamp when totalPages == 0 (panelgrid.go:174). Go's raw write
        // yields {currentPage: 0, totalPages: 0}, which Default reproduces.
        *nav = GridNavigator::default();
        return;
    }
    let page = clamp(page, 0, nav.total_pages() - 1);
    if page == nav.current_page() {
        return;
    }
    nav.go_home();
    if page != 0 {
        nav.navigate(page);
    }
}

// PORT NOTE: duplicate of the private `slices_binary_search_f64` in
// `leet_data::media` (Go `slices.BinarySearch` on []float64, NaN-first
// ordering) — leet-data does not export it and this unit must not edit
// other modules. The inputs here are MediaStore timelines (finite, sorted).
fn slices_binary_search_f64(xs: &[f64], target: f64) -> (usize, bool) {
    fn cmp_less(x: f64, y: f64) -> bool {
        x < y || (x.is_nan() && !y.is_nan())
    }

    let n = xs.len();
    let (mut i, mut j) = (0, n);
    while i < j {
        let h = (i + j) >> 1;
        if cmp_less(xs[h], target) {
            i = h + 1;
        } else {
            j = h;
        }
    }
    let found = i < n && (xs[i] == target || (xs[i].is_nan() && target.is_nan()));
    (i, found)
}

// PORT NOTE: Go's package-wide clamp helper; console_logs_pane.rs and
// metrics_grid.rs carry the same private copy.
fn clamp(val: isize, minimum: isize, maximum: isize) -> isize {
    if val < minimum {
        return minimum;
    }
    if val > maximum {
        return maximum;
    }
    val
}

// ---------------------------------------------------------------------------
// mediaImageRenderer (mediapane.go:1148-1481).
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
struct MediaRenderKey {
    path: String,
    width: isize,
    height: isize,
}

const MEDIA_ERROR_RETRY_AFTER: Duration = Duration::from_secs(1);

#[derive(Debug, Clone, Default)]
struct MediaRenderError {
    text: String,
    /// `None` ≙ Go's zero time (the "no error" zero value).
    at: Option<Instant>,
}

#[derive(Debug, Clone)]
struct MediaPicture {
    model: PictureModel,
    img: Option<Arc<SourceImage>>,
}

// PARITY: Go guards this with a sync.RWMutex (S11) because PrepareVisible
// ran on a tea.Cmd goroutine; in the Rust design the prepare pass runs on
// the main thread (the deferred Kitty render is what goes off-thread, as
// `PictureCmd::Render`), so the lock dies (CONCURRENCY.md §2.6).
#[derive(Debug)]
struct MediaImageRenderer {
    mode: PictureMode,
    /// cellPixelW/H are the terminal's cell pixel dimensions (its reply to
    /// picture.RequestCellSize), used so Kitty images are encoded at the
    /// display's true resolution. Zero until the reply arrives; the picture
    /// module's defaults apply then.
    cell_pixel_w: isize,
    cell_pixel_h: isize,
    decoded: HashMap<String, Arc<SourceImage>>,
    errors: HashMap<String, MediaRenderError>,
    rendered: HashMap<MediaRenderKey, Text<'static>>,
    // PARITY: Go iterates this map unordered in ToggleMode/Update/
    // PrepareVisible and the emitted Kitty sequences reach the terminal in
    // that order; sorted (BTreeMap) for determinism (PORTING.md map rule).
    pictures: BTreeMap<MediaRenderKey, MediaPicture>,
}

impl MediaImageRenderer {
    fn new() -> MediaImageRenderer {
        MediaImageRenderer {
            mode: PictureMode::Glyph,
            cell_pixel_w: 0,
            cell_pixel_h: 0,
            decoded: HashMap::new(),
            errors: HashMap::new(),
            rendered: HashMap::new(),
            pictures: BTreeMap::new(),
        }
    }

    fn mode(&self) -> PictureMode {
        self.mode
    }

    fn toggle_mode(&mut self) -> Vec<PictureCmd> {
        if self.mode == PictureMode::Glyph {
            if !ensure_kitty_graphics_enabled() {
                return Vec::new();
            }
            // Pictures are created lazily by PrepareVisible once the mode is
            // Kitty; in Glyph mode there are none to update.
            self.mode = PictureMode::Kitty;
            return Vec::new();
        }

        self.mode = PictureMode::Glyph;
        let mut cmds = Vec::with_capacity(self.pictures.len());
        for pic in self.pictures.values_mut() {
            // Every model in pictures is in Kitty mode; Toggle emits the
            // Kitty delete sequence that frees the on-terminal image.
            if let Some(cmd) = pic.model.toggle() {
                cmds.push(cmd);
            }
        }
        self.pictures.clear();
        cmds
    }

    /// The `uv.CellSizeEvent` arm of Go `Update` (mediapane.go:1256-1273):
    /// remember the terminal's cell pixel size for pictures created later;
    /// existing pictures pick it up through the forwarding loop.
    fn handle_cell_size(&mut self, ev: CellSizeEvent) -> Vec<PictureCmd> {
        (self.cell_pixel_w, self.cell_pixel_h) = (ev.width, ev.height);

        let mut cmds = Vec::with_capacity(1);
        for pic in self.pictures.values_mut() {
            if let Some(cmd) = pic
                .model
                .set_cell_pixel_size(ev.width as i64, ev.height as i64)
            {
                cmds.push(cmd);
            }
        }
        cmds
    }

    /// The `KittyFrameMsg` arm of Go `Update`: forwarded to every picture
    /// model; model IDs are unique, so at most one accepts it.
    fn on_kitty_frame(&mut self, msg: &KittyFrameMsg) -> Option<(String, ApplyKittyGridMsg)> {
        for pic in self.pictures.values_mut() {
            if let Some(res) = pic.model.on_kitty_frame(msg) {
                return Some(res);
            }
        }
        None
    }

    /// The `applyKittyGridMsg` arm of Go `Update`: forwarded to every
    /// picture model (each checks its own model ID).
    fn on_apply_kitty_grid(&mut self, msg: &ApplyKittyGridMsg) {
        for pic in self.pictures.values_mut() {
            pic.model.on_apply_kitty_grid(msg.clone());
        }
    }

    fn prepare_visible(&mut self, keys: &[MediaRenderKey]) -> Vec<PictureCmd> {
        if self.mode != PictureMode::Kitty {
            return Vec::new();
        }

        let mut visible: HashMap<MediaRenderKey, bool> = HashMap::with_capacity(keys.len());
        let mut cmds: Vec<PictureCmd> = Vec::with_capacity(keys.len());
        for key in keys {
            if key.path.is_empty() || key.width <= 0 || key.height <= 0 {
                continue;
            }
            visible.insert(key.clone(), true);

            let (img, _) = self.image(&key.path);
            let Some(img) = img else {
                continue;
            };

            cmds.extend(self.prepare_picture_locked(key, img));
        }

        let stale: Vec<MediaRenderKey> = self
            .pictures
            .keys()
            .filter(|key| !visible.contains_key(*key))
            .cloned()
            .collect();
        for key in stale {
            let mut pic = self.pictures.remove(&key).expect("key collected above");
            if let Some(cmd) = pic.model.set_image(None) {
                cmds.push(cmd);
            }
        }

        cmds
    }

    fn park(&mut self, keys: &[MediaRenderKey]) {
        let mut visible_keys: HashMap<&MediaRenderKey, ()> = HashMap::with_capacity(keys.len());
        let mut visible_paths: HashMap<&str, ()> = HashMap::with_capacity(keys.len());
        for key in keys {
            if key.path.is_empty() || key.width <= 0 || key.height <= 0 {
                continue;
            }
            visible_keys.insert(key, ());
            visible_paths.insert(&key.path, ());
        }

        self.decoded
            .retain(|path, _| visible_paths.contains_key(path.as_str()));
        self.errors
            .retain(|path, _| visible_paths.contains_key(path.as_str()));
        self.rendered
            .retain(|key, _| visible_keys.contains_key(key));
    }

    fn render(&mut self, path: &str, width: isize, height: isize, dark: bool) -> Text<'static> {
        if width <= 0 || height <= 0 {
            return Text::default();
        }
        if path.is_empty() {
            return render_media_placeholder(width, height, "Missing image path", dark);
        }

        let key = MediaRenderKey {
            path: path.to_string(),
            width,
            height,
        };
        if self.mode == PictureMode::Kitty {
            // PARITY: Go calls View outside the renderer lock because it
            // mutates the model's render cache; the lock is gone here.
            if let Some(pic) = self.pictures.get_mut(&key) {
                let view = pic.model.view();
                if !view.lines.is_empty() {
                    return view;
                }
            }
            return self.render_glyph(path, width, height, dark);
        }

        if let Some(rendered) = self.rendered.get(&key) {
            return rendered.clone();
        }

        self.render_glyph(path, width, height, dark)
    }

    fn image(&mut self, path: &str) -> (Option<Arc<SourceImage>>, MediaRenderError) {
        if let Some(img) = self.decoded.get(path) {
            return (Some(img.clone()), MediaRenderError::default());
        }
        if let Some(err_entry) = self.errors.get(path)
            && err_entry
                .at
                .is_some_and(|at| at.elapsed() < MEDIA_ERROR_RETRY_AFTER)
        {
            return (None, err_entry.clone());
        }

        match load_media_image(path) {
            Err(text) => {
                let err_entry = MediaRenderError {
                    text,
                    at: Some(Instant::now()),
                };
                self.errors.insert(path.to_string(), err_entry.clone());
                (None, err_entry)
            }
            Ok(loaded) => {
                self.decoded.insert(path.to_string(), loaded.clone());
                self.errors.remove(path);
                (Some(loaded), MediaRenderError::default())
            }
        }
    }

    fn render_glyph(
        &mut self,
        path: &str,
        width: isize,
        height: isize,
        dark: bool,
    ) -> Text<'static> {
        let (img, err_entry) = self.image(path);
        let Some(img) = img else {
            return render_media_placeholder(
                width,
                height,
                &truncate_value(&err_entry.text, width),
                dark,
            );
        };

        let key = MediaRenderKey {
            path: path.to_string(),
            width,
            height,
        };
        let rendered = render_picture_glyph(&img, width, height, dark);
        self.rendered.insert(key, rendered.clone());
        rendered
    }

    fn prepare_picture_locked(
        &mut self,
        key: &MediaRenderKey,
        img: Arc<SourceImage>,
    ) -> Vec<PictureCmd> {
        let mut cmds: Vec<PictureCmd> = Vec::new();

        if !self.pictures.contains_key(key) {
            let model = PictureModel::new_with_config(PictureConfig {
                kitty_id: next_media_kitty_id(),
                cell_pixel_width: self.cell_pixel_w as i64,
                cell_pixel_height: self.cell_pixel_h as i64,
                ..PictureConfig::default()
            });
            let mut pic = MediaPicture { model, img: None };
            // New models start in Glyph mode and this only runs in Kitty
            // mode, so switch them over.
            if let Some(cmd) = pic.model.toggle() {
                cmds.push(cmd);
            }
            self.pictures.insert(key.clone(), pic);
        }
        let pic = self.pictures.get_mut(key).expect("inserted above");

        if let Some(cmd) = pic.model.set_size(key.width as i64, key.height as i64) {
            cmds.push(cmd);
        }
        // PARITY: Go compares the image interface pointers
        // (mediapane.go:1442).
        let same = pic.img.as_ref().is_some_and(|prev| Arc::ptr_eq(prev, &img));
        if !same {
            pic.img = Some(img.clone());
            if let Some(cmd) = pic.model.set_image(Some(img)) {
                cmds.push(cmd);
            }
        }
        cmds
    }
}

fn ensure_kitty_graphics_enabled() -> bool {
    if media_kitty_supported() == KittyCapability::Supported {
        return true;
    }
    if !terminal_signals_kitty_graphics() {
        return false;
    }
    media_force_kitty_capability(KittyCapability::Supported);
    true
}

/// picture/kitty_capability.go:190-204 `recordKittyResponse`: any response
/// carrying the probe's image ID proves the terminal speaks the protocol —
/// even an error response. A real response is authoritative and overrides
/// the timeout's pessimistic Unsupported conclusion.
fn record_kitty_response(msg: &KittyGraphicsMsg) {
    if msg.id != crate::runtime::KITTY_PROBE_ID {
        return;
    }
    // PARITY: Go covers Unknown→Supported and Unsupported→Supported with
    // two CASes to avoid clobbering concurrent writers; on the port's
    // single update thread an unconditional store of Supported is the same
    // state machine (Supported over Supported is a no-op).
    media_force_kitty_capability(KittyCapability::Supported);
}

/// picture/kitty_capability.go:206-211 `recordKittyTimeout`: marks the
/// capability Unsupported iff the probe window elapsed while still Unknown.
/// Idempotent; never overrides an earlier response or ForceKittyCapability.
fn record_kitty_timeout() {
    // PARITY: Go's CompareAndSwap(Unknown, Unsupported) — read +
    // conditional store on the single update thread.
    if media_kitty_supported() == KittyCapability::Unknown {
        media_force_kitty_capability(KittyCapability::Unsupported);
    }
}

/// Go reads/writes the picture package's process-wide capability directly
/// (`picture.KittySupported` / `picture.ForceKittyCapability`,
/// mediapane.go:1224-1231). These wrappers add a test-only override:
/// Go's package tests run serially (`t.Setenv` forbids `t.Parallel`), so
/// mediapane_test.go can mutate the global safely, but Rust unit tests run
/// on parallel threads and picture.rs owns its own capability test — the
/// media tests override through [`test_kitty_cap`] instead of racing the
/// global. Outside `cfg(test)` both are direct calls.
fn media_kitty_supported() -> KittyCapability {
    #[cfg(test)]
    {
        if let Some(c) = test_kitty_cap::get() {
            return c;
        }
    }
    kitty_supported()
}

/// See [`media_kitty_supported`].
fn media_force_kitty_capability(c: KittyCapability) {
    #[cfg(test)]
    {
        if test_kitty_cap::get().is_some() {
            test_kitty_cap::set(c);
            return;
        }
    }
    force_kitty_capability(c);
}

/// Test-only capability override consulted by [`media_kitty_supported`] /
/// [`media_force_kitty_capability`] — the port's
/// `picture.ForceKittyCapability` sandbox (see [`media_kitty_supported`]).
#[cfg(test)]
mod test_kitty_cap {
    use std::sync::Mutex;

    use crate::picture::KittyCapability;

    static OVERRIDE: Mutex<Option<KittyCapability>> = Mutex::new(None);

    pub(super) fn get() -> Option<KittyCapability> {
        *OVERRIDE.lock().unwrap_or_else(|e| e.into_inner())
    }

    pub(super) fn set(c: KittyCapability) {
        *OVERRIDE.lock().unwrap_or_else(|e| e.into_inner()) = Some(c);
    }

    pub(super) fn clear() {
        *OVERRIDE.lock().unwrap_or_else(|e| e.into_inner()) = None;
    }
}

fn terminal_signals_kitty_graphics() -> bool {
    if !getenv("KITTY_WINDOW_ID").is_empty()
        || !getenv("KITTY_INSTALLATION_DIR").is_empty()
        || !getenv("WEZTERM_EXECUTABLE").is_empty()
        || !getenv("WEZTERM_PANE").is_empty()
        || !getenv("GHOSTTY_BIN_DIR").is_empty()
        || !getenv("GHOSTTY_RESOURCES_DIR").is_empty()
    {
        return true;
    }

    match getenv("TERM_PROGRAM").to_lowercase().as_str() {
        "ghostty" | "iterm.app" | "kitty" | "wezterm" => return true,
        _ => {}
    }

    matches!(
        getenv("TERM").to_lowercase().as_str(),
        "xterm-ghostty" | "xterm-kitty"
    )
}

/// Go `os.Getenv` (returns `""` for unset). Tests inject through the
/// [`test_env`] seam instead of the process environment: Go's `t.Setenv`
/// has no safe Rust equivalent (`std::env::set_var` is unsafe in edition
/// 2024 and the workspace denies unsafe code), and the seam also keeps the
/// env tests hermetic.
fn getenv(key: &str) -> String {
    #[cfg(test)]
    {
        if let Some(v) = test_env::get(key) {
            return v;
        }
    }
    std::env::var(key).unwrap_or_default()
}

/// Test-only environment overrides consulted by [`getenv`] — the port's
/// `t.Setenv` (see the [`getenv`] doc). While overrides are installed,
/// every key resolves through the table (missing keys read as unset only
/// if never `set`), so the real process env cannot leak into the Kitty
/// heuristic tests.
#[cfg(test)]
mod test_env {
    use std::collections::HashMap;
    use std::sync::Mutex;

    static OVERRIDES: Mutex<Option<HashMap<String, String>>> = Mutex::new(None);

    pub(super) fn get(key: &str) -> Option<String> {
        OVERRIDES
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .as_ref()
            .and_then(|m| m.get(key).cloned())
    }

    pub(super) fn set(key: &str, value: &str) {
        OVERRIDES
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .get_or_insert_with(HashMap::new)
            .insert(key.to_string(), value.to_string());
    }

    pub(super) fn clear() {
        *OVERRIDES.lock().unwrap_or_else(|e| e.into_inner()) = None;
    }
}

/// mediapane.go:1451-1463 `loadMediaImage`.
///
/// PARITY: the "open image: " / "decode image: " prefixes match Go; the
/// wrapped OS/decoder message text differs between Go and the `image`
/// crate (Tier-3). Go registers gif/jpeg/png decoders; the `image` crate
/// build here carries png+jpeg — gif files fail as decode errors until the
/// dependency gains the feature (PARITY.md §2.6).
fn load_media_image(path: &str) -> Result<Arc<SourceImage>, String> {
    let file = std::fs::File::open(path).map_err(|err| format!("open image: {err}"))?;
    let reader = image::ImageReader::new(std::io::BufReader::new(file))
        .with_guessed_format()
        .map_err(|err| format!("decode image: {err}"))?;
    let img = reader
        .decode()
        .map_err(|err| format!("decode image: {err}"))?;
    Ok(Arc::new(SourceImage::from_dynamic(&img)))
}

fn render_picture_glyph(
    img: &Arc<SourceImage>,
    width: isize,
    height: isize,
    dark: bool,
) -> Text<'static> {
    if width <= 0 || height <= 0 {
        return Text::default();
    }
    if img.width == 0 || img.height == 0 {
        return render_media_placeholder(width, height, "Empty image", dark);
    }

    let mut model = PictureModel::new();
    // PARITY: Go discards the returned cmds here (mediapane.go:1474-1475);
    // they are nil in Glyph mode.
    model.set_size(width as i64, height as i64);
    model.set_image(Some(img.clone()));
    let view = model.view();
    if view.lines.is_empty() {
        return render_media_placeholder(width, height, "Empty image", dark);
    }
    view
}

// Transliteration of mediapane_test.go (33 tests). Views are asserted via
// `text_to_string` (the plain-text cell grid — Go's stripANSI equivalent);
// SGR color assertions become span-style checks.
#[cfg(test)]
mod tests {
    use std::sync::Mutex;

    use leet_charts::styles::ANIMATION_DURATION;
    use pretty_assertions::{assert_eq, assert_ne};
    use ratatui::style::Color;

    use super::*;
    use crate::key::{KeyCode, KeyMods};
    use crate::layout::text_to_string;
    use crate::nav::test_helpers::nav_binding_msg;

    // --- helpers ---

    fn test_media_pane() -> (MediaPane, Rc<RefCell<MediaStore>>) {
        test_media_pane_with_grid(2, 3)
    }

    fn test_media_pane_with_grid(rows: isize, cols: isize) -> (MediaPane, Rc<RefCell<MediaStore>>) {
        let anim = AnimatedValue::new(true, 30);
        let mut pane = MediaPane::new(anim, Some(Box::new(move || (rows, cols))));

        // Instantly expand so Height() > 0.
        pane.toggle(); // start → expanding
        std::thread::sleep(ANIMATION_DURATION + Duration::from_millis(10));
        pane.update(Instant::now());

        let store = Rc::new(RefCell::new(MediaStore::new()));
        pane.set_store(Some(store.clone()));
        (pane, store)
    }

    fn media_key_msg(key: &str) -> KeyEvent {
        match key {
            "enter" => KeyEvent {
                code: KeyCode::Enter,
                text: None,
                mods: KeyMods::NONE,
            },
            "esc" => KeyEvent {
                code: KeyCode::Esc,
                text: None,
                mods: KeyMods::NONE,
            },
            _ => nav_binding_msg(key),
        }
    }

    /// Go `tea.KeyPressMsg{Code: 'k', Text: "k"}`.
    fn key_k() -> KeyEvent {
        KeyEvent {
            code: KeyCode::Char('k'),
            text: Some("k".to_string()),
            mods: KeyMods::NONE,
        }
    }

    /// Holds the env/capability lock for the duration of a test (Go
    /// `t.Setenv` implies serial execution; the trio of renderer-mode tests
    /// shares the [`test_env`] / [`test_kitty_cap`] override state).
    struct KittyEnvGuard {
        _lock: std::sync::MutexGuard<'static, ()>,
    }

    impl Drop for KittyEnvGuard {
        fn drop(&mut self) {
            test_env::clear();
            test_kitty_cap::clear();
        }
    }

    fn set_kitty_graphics_env(supported: bool) -> KittyEnvGuard {
        static LOCK: Mutex<()> = Mutex::new(());
        let lock = LOCK.lock().unwrap_or_else(|e| e.into_inner());
        for key in [
            "KITTY_WINDOW_ID",
            "KITTY_INSTALLATION_DIR",
            "WEZTERM_EXECUTABLE",
            "WEZTERM_PANE",
            "GHOSTTY_BIN_DIR",
            "GHOSTTY_RESOURCES_DIR",
            "TERM_PROGRAM",
        ] {
            test_env::set(key, "");
        }
        // Go: picture.ForceKittyCapability(...) — routed through the
        // override so the trio cannot race picture.rs's own capability
        // test on the process-wide global (see media_kitty_supported).
        if supported {
            test_env::set("TERM", "xterm-kitty");
            test_kitty_cap::set(KittyCapability::Supported);
        } else {
            test_env::set("TERM", "xterm-256color");
            test_kitty_cap::set(KittyCapability::Unsupported);
        }
        KittyEnvGuard { _lock: lock }
    }

    fn feed_images(store: &Rc<RefCell<MediaStore>>, key: &str, steps: &[f64]) {
        for &step in steps {
            let media = HashMap::from([(
                key.to_string(),
                vec![MediaPoint {
                    x: step,
                    file_path: "/img.png".to_string(),
                    caption: "c".to_string(),
                    ..MediaPoint::default()
                }],
            )]);
            store.borrow_mut().process_history(&media);
        }
    }

    fn feed_image_paths(store: &Rc<RefCell<MediaStore>>, keys: &[&str], path: &str) {
        let media: HashMap<String, Vec<MediaPoint>> = keys
            .iter()
            .map(|key| {
                (
                    key.to_string(),
                    vec![MediaPoint {
                        x: 0.0,
                        file_path: path.to_string(),
                        ..MediaPoint::default()
                    }],
                )
            })
            .collect();
        store.borrow_mut().process_history(&media);
    }

    fn write_test_image(dir: &tempfile::TempDir) -> String {
        let path = dir.path().join("img.png");
        let mut img = image::RgbaImage::new(4, 4);
        for y in 0..4u32 {
            for x in 0..4u32 {
                img.put_pixel(
                    x,
                    y,
                    image::Rgba([(64 * x) as u8, (64 * y) as u8, 200, 255]),
                );
            }
        }
        img.save(&path).expect("write png");
        path.to_string_lossy().into_owned()
    }

    fn write_band_test_image(dir: &tempfile::TempDir) -> String {
        let path = dir.path().join("bands.png");
        let mut img = image::RgbaImage::new(16, 16);
        for y in 0..16u32 {
            let c = if y < 2 {
                image::Rgba([255, 0, 0, 255])
            } else if y >= 14 {
                image::Rgba([0, 0, 255, 255])
            } else {
                image::Rgba([32, 32, 32, 255])
            };
            for x in 0..16u32 {
                img.put_pixel(x, y, c);
            }
        }
        img.put_pixel(0, 2, image::Rgba([0, 0, 0, 0]));
        img.put_pixel(0, 3, image::Rgba([0, 0, 0, 0]));
        img.put_pixel(1, 4, image::Rgba([0, 0, 0, 0]));
        img.put_pixel(2, 7, image::Rgba([0, 0, 0, 0]));

        img.save(&path).expect("write png");
        path.to_string_lossy().into_owned()
    }

    fn view_str(
        pane: &mut MediaPane,
        width: isize,
        height: isize,
        run_label: &str,
        hint: &str,
    ) -> String {
        text_to_string(&pane.view(width, height, run_label, hint, true))
    }

    fn has_span_color(t: &Text<'_>, c: Color) -> bool {
        t.lines
            .iter()
            .flat_map(|l| l.spans.iter())
            .any(|s| s.style.fg == Some(c) || s.style.bg == Some(c))
    }

    // --- MediaStore tests ---

    #[test]
    fn media_store_empty() {
        let store = MediaStore::new();
        assert!(store.empty());
        // PARITY: Go require.Nil on the returned slices.
        assert!(store.series_keys().is_empty());
        assert!(store.x_values().is_empty());
    }

    #[test]
    fn media_store_series_keys_sorted() {
        let store = Rc::new(RefCell::new(MediaStore::new()));
        feed_images(&store, "zeta", &[1.0]);
        feed_images(&store, "alpha", &[1.0]);
        feed_images(&store, "mu", &[1.0]);

        assert_eq!(
            store.borrow().series_keys(),
            vec!["alpha".to_string(), "mu".to_string(), "zeta".to_string()]
        );
        assert!(!store.borrow().empty());
    }

    #[test]
    fn media_store_x_values_union_across_series() {
        let store = Rc::new(RefCell::new(MediaStore::new()));
        feed_images(&store, "a", &[1.0, 3.0, 5.0]);
        feed_images(&store, "b", &[2.0, 3.0, 4.0]);

        assert_eq!(store.borrow().x_values(), vec![1.0, 2.0, 3.0, 4.0, 5.0]);
    }

    #[test]
    fn media_store_series_x_values() {
        let store = Rc::new(RefCell::new(MediaStore::new()));
        feed_images(&store, "a", &[3.0, 1.0, 2.0]);

        assert_eq!(store.borrow().series_x_values("a"), vec![1.0, 2.0, 3.0]);
        assert!(store.borrow().series_x_values("nonexistent").is_empty());
    }

    #[test]
    fn media_store_resolve_at_empty_series() {
        let store = MediaStore::new();
        assert!(store.resolve_at("a", 1.0).is_none());
    }

    #[test]
    fn media_store_process_history_empty_msg() {
        let mut store = MediaStore::new();
        assert!(!store.process_history(&HashMap::new()));
        assert!(store.empty());
    }

    #[test]
    fn media_store_process_history_empty_key() {
        let mut store = MediaStore::new();
        let changed = store.process_history(&HashMap::from([(
            String::new(),
            vec![MediaPoint {
                x: 1.0,
                file_path: "/img.png".to_string(),
                ..MediaPoint::default()
            }],
        )]));
        assert!(!changed);
        assert!(store.empty());
    }

    #[test]
    fn media_store_process_history_duplicate_no_change() {
        let mut store = MediaStore::new();
        let point = MediaPoint {
            x: 1.0,
            file_path: "/img.png".to_string(),
            caption: "c".to_string(),
            ..MediaPoint::default()
        };
        store.process_history(&HashMap::from([("a".to_string(), vec![point.clone()])]));
        // Same exact point again → no change.
        let changed = store.process_history(&HashMap::from([("a".to_string(), vec![point])]));
        assert!(!changed);
    }

    // --- MediaPane scrubbing ---

    #[test]
    fn media_pane_scrub() {
        let (mut pane, store) = test_media_pane();
        feed_images(&store, "s", &[0.0, 1.0, 2.0, 3.0, 4.0]);
        pane.set_store(Some(store.clone()));

        // Auto-follow puts us at the last step.
        assert!(pane.status_label().contains("X=_step 4"));

        pane.scrub(-2);
        assert!(pane.status_label().contains("X=_step 2"));

        // Scrub past the beginning clamps to 0.
        pane.scrub(-100);
        assert!(pane.status_label().contains("X=_step 0"));

        pane.scrub_to_end();
        assert!(pane.status_label().contains("X=_step 4"));

        pane.scrub_to_start();
        assert!(pane.status_label().contains("X=_step 0"));
    }

    #[test]
    fn media_pane_scrub_empty_store() {
        let (mut pane, _store) = test_media_pane();
        // Should not panic on empty store.
        pane.scrub(1);
        pane.scrub_to_start();
        pane.scrub_to_end();
    }

    #[test]
    fn media_pane_handle_key_scrub_bindings() {
        let (mut pane, store) = test_media_pane();
        feed_images(
            &store,
            "s",
            &[0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0],
        );
        pane.set_store(Some(store.clone()));
        pane.set_active(true);
        pane.scrub_to_start();

        let (handled, cmd) = pane.handle_key(&media_key_msg("right"));
        assert!(handled);
        assert!(cmd.is_empty());
        assert!(pane.status_label().contains("X=_step 1"));

        let (handled, cmd) = pane.handle_key(&media_key_msg("down"));
        assert!(handled);
        assert!(cmd.is_empty());
        assert!(pane.status_label().contains("X=_step 11"));

        let (handled, cmd) = pane.handle_key(&media_key_msg("left"));
        assert!(handled);
        assert!(cmd.is_empty());
        assert!(pane.status_label().contains("X=_step 10"));

        let (handled, cmd) = pane.handle_key(&media_key_msg("up"));
        assert!(handled);
        assert!(cmd.is_empty());
        assert!(pane.status_label().contains("X=_step 0"));

        let (handled, cmd) = pane.handle_key(&media_key_msg("end"));
        assert!(handled);
        assert!(cmd.is_empty());
        assert!(pane.status_label().contains("X=_step 11"));

        let (handled, cmd) = pane.handle_key(&media_key_msg("home"));
        assert!(handled);
        assert!(cmd.is_empty());
        assert!(pane.status_label().contains("X=_step 0"));
    }

    #[test]
    fn media_pane_linked_scrub_shared_cursor() {
        let (mut pane, store) = test_media_pane();
        feed_images(&store, "a", &[0.0, 1.0, 2.0, 3.0, 4.0]);
        feed_images(&store, "b", &[0.0, 2.0, 4.0]);
        pane.set_store(Some(store.clone()));
        pane.set_active(true);

        // Linking starts the shared cursor at the most advanced position
        // (X=4).
        let _ = pane.handle_key(&media_key_msg("l"));
        assert!(pane.status_label().contains("X=_step 4"));

        // One press moves the cursor by one union step; each tile resolves
        // to its latest sample at or before the cursor.
        let _ = pane.handle_key(&media_key_msg("left"));
        assert!(pane.status_label().contains("Media: a"));
        assert!(pane.status_label().contains("X=_step 3"));
        pane.navigate_page(1); // select "b": latest sample ≤ 3 is 2
        assert!(pane.status_label().contains("Media: b"));
        assert!(pane.status_label().contains("X=_step 2"));
        pane.navigate_page(-1);

        // Scrubbing past the start clamps the cursor to the first union
        // step.
        let _ = pane.handle_key(&media_key_msg("up"));
        assert!(pane.status_label().contains("X=_step 0"));

        let _ = pane.handle_key(&media_key_msg("end"));
        assert!(pane.status_label().contains("X=_step 4"));
        pane.navigate_page(1);
        assert!(pane.status_label().contains("X=_step 4"));

        let _ = pane.handle_key(&media_key_msg("home"));
        assert!(pane.status_label().contains("X=_step 0"));
        pane.navigate_page(-1);
        assert!(pane.status_label().contains("X=_step 0"));
    }

    #[test]
    fn media_pane_linked_scrub_mixed_cadence() {
        let (mut pane, store) = test_media_pane();
        feed_images(&store, "a", &[0.0, 1.0, 2.0, 3.0, 4.0]);
        feed_images(&store, "b", &[3.0, 4.0]); // starts later
        pane.set_store(Some(store.clone()));
        pane.set_active(true);

        let _ = pane.handle_key(&media_key_msg("l"));
        let _ = pane.handle_key(&media_key_msg("home"));
        assert!(pane.status_label().contains("X=_step 0"));

        // One press moves the shared cursor by exactly one union step, even
        // though "b" has no sample there.
        let _ = pane.handle_key(&media_key_msg("right"));
        assert!(pane.status_label().contains("X=_step 1"));

        // "b" has no sample at or before the cursor: its tile shows a
        // placeholder rather than a "future" image.
        pane.navigate_page(1);
        assert!(pane.status_label().contains("Media: b"));
        assert!(pane.status_label().contains("X=_step 1"));
        assert!(view_str(&mut pane, 40, 14, "", "").contains("No image at X"));

        // Once the cursor reaches b's first sample, the tile resolves.
        let _ = pane.handle_key(&media_key_msg("right"));
        let _ = pane.handle_key(&media_key_msg("right"));
        assert!(pane.status_label().contains("X=_step 3"));
    }

    #[test]
    fn media_pane_handle_key_linked_scrub_bindings() {
        let (mut pane, store) = test_media_pane();
        feed_images(
            &store,
            "a",
            &[0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0],
        );
        feed_images(&store, "b", &[0.0, 10.0]);
        pane.set_store(Some(store.clone()));
        pane.set_active(true);

        // "l" links scrubbing across all series.
        let (handled, cmd) = pane.handle_key(&media_key_msg("l"));
        assert!(handled);
        assert!(cmd.is_empty());
        assert!(pane.status_label().contains("sync"));

        let (handled, cmd) = pane.handle_key(&media_key_msg("home"));
        assert!(handled);
        assert!(cmd.is_empty());
        assert!(pane.status_label().contains("X=_step 0"));

        let (handled, cmd) = pane.handle_key(&media_key_msg("right"));
        assert!(handled);
        assert!(cmd.is_empty());
        assert!(pane.status_label().contains("X=_step 1"));

        let (handled, cmd) = pane.handle_key(&media_key_msg("down"));
        assert!(handled);
        assert!(cmd.is_empty());
        assert!(pane.status_label().contains("X=_step 11"));
        pane.navigate_page(1); // "b" aligned to its latest sample ≤ 11
        assert!(pane.status_label().contains("Media: b"));
        assert!(pane.status_label().contains("X=_step 10"));
        pane.navigate_page(-1);

        let (handled, cmd) = pane.handle_key(&media_key_msg("up"));
        assert!(handled);
        assert!(cmd.is_empty());
        assert!(pane.status_label().contains("X=_step 1"));

        let (handled, cmd) = pane.handle_key(&media_key_msg("left"));
        assert!(handled);
        assert!(cmd.is_empty());
        assert!(pane.status_label().contains("X=_step 0"));

        let (handled, cmd) = pane.handle_key(&media_key_msg("end"));
        assert!(handled);
        assert!(cmd.is_empty());
        assert!(pane.status_label().contains("X=_step 11"));
        pane.navigate_page(1);
        assert!(pane.status_label().contains("X=_step 10"));
        pane.navigate_page(-1);

        // "l" again unlinks: plain scrubbing only moves the selected
        // series.
        let (handled, _) = pane.handle_key(&media_key_msg("l"));
        assert!(handled);
        assert!(!pane.status_label().contains("sync"));

        let (handled, _) = pane.handle_key(&media_key_msg("left"));
        assert!(handled);
        assert!(pane.status_label().contains("X=_step 10"));
        let _ = pane.handle_key(&media_key_msg("left"));
        assert!(pane.status_label().contains("X=_step 9"));
        pane.navigate_page(1); // "b" stays at its last sample
        assert!(pane.status_label().contains("X=_step 10"));
    }

    // --- MediaPane view state save/restore ---

    #[test]
    fn media_pane_view_state_save_restore() {
        let (mut pane, store) = test_media_pane();
        feed_images(&store, "a", &[0.0, 1.0, 2.0, 3.0]);
        feed_images(&store, "b", &[0.0, 1.0, 2.0]);
        pane.set_store(Some(store.clone()));

        // Move selection to "b" and scrub to step 1.
        pane.move_selection(1, 0);
        pane.scrub_to_start();
        pane.scrub(1);

        let state = pane.save_view_state();

        // Reset destroys position.
        pane.reset_view_state();
        assert!(pane.status_label().contains("X=_step 3"));

        // Restore brings it back.
        pane.restore_view_state(&state);
        assert!(pane.status_label().contains("X=_step 1"));
    }

    #[test]
    fn media_pane_view_state_linked_scrub() {
        let (mut pane, store) = test_media_pane();
        feed_images(&store, "a", &[0.0, 1.0, 2.0, 3.0]);
        feed_images(&store, "b", &[0.0, 1.0, 2.0]);
        pane.set_store(Some(store.clone()));
        pane.set_active(true);

        // Link and move the shared cursor to X=1.
        let _ = pane.handle_key(&media_key_msg("l"));
        let _ = pane.handle_key(&media_key_msg("home"));
        let _ = pane.handle_key(&media_key_msg("right"));
        assert!(pane.status_label().contains("sync"));
        assert!(pane.status_label().contains("X=_step 1"));

        let state = pane.save_view_state();

        // Reset unlinks and destroys the cursor.
        pane.reset_view_state();
        assert!(!pane.status_label().contains("sync"));
        assert!(pane.status_label().contains("X=_step 3"));

        // Restore brings both back.
        pane.restore_view_state(&state);
        assert!(pane.status_label().contains("sync"));
        assert!(pane.status_label().contains("X=_step 1"));
    }

    #[test]
    fn media_pane_view_state_reset() {
        let (mut pane, store) = test_media_pane();
        feed_images(&store, "a", &[0.0, 1.0, 2.0]);
        pane.set_store(Some(store.clone()));

        pane.scrub_to_start();
        assert!(pane.status_label().contains("X=_step 0"));

        pane.reset_view_state();
        // After reset, auto-follow → last step.
        assert!(pane.status_label().contains("X=_step 2"));
    }

    // --- MediaPane fullscreen ---

    #[test]
    fn media_pane_fullscreen() {
        let (mut pane, store) = test_media_pane();
        feed_images(&store, "s", &[0.0]);
        pane.set_store(Some(store.clone()));

        assert!(!pane.is_fullscreen());
        pane.toggle_fullscreen();
        assert!(pane.is_fullscreen());
        assert!(pane.active(), "fullscreen should activate pane");

        pane.exit_fullscreen();
        assert!(!pane.is_fullscreen());
    }

    #[test]
    fn media_pane_handle_key_toggle_fullscreen_binding() {
        let (mut pane, store) = test_media_pane();
        feed_images(&store, "s", &[0.0]);
        pane.set_store(Some(store.clone()));
        pane.set_active(true);

        let (handled, cmd) = pane.handle_key(&media_key_msg("enter"));
        assert!(handled);
        assert!(cmd.is_empty());
        assert!(pane.is_fullscreen());

        let (handled, cmd) = pane.handle_key(&media_key_msg("enter"));
        assert!(handled);
        assert!(cmd.is_empty());
        assert!(!pane.is_fullscreen());
    }

    #[test]
    fn media_pane_escape_only_consumes_fullscreen() {
        let (mut pane, _store) = test_media_pane();
        pane.set_active(true);

        let (handled, cmd) = pane.handle_key(&KeyEvent {
            code: KeyCode::Esc,
            text: None,
            mods: KeyMods::NONE,
        });
        assert!(!handled);
        assert!(cmd.is_empty());

        pane.toggle_fullscreen();
        let (handled, cmd) = pane.handle_key(&KeyEvent {
            code: KeyCode::Esc,
            text: None,
            mods: KeyMods::NONE,
        });
        assert!(handled);
        assert!(cmd.is_empty());
        assert!(!pane.is_fullscreen());
    }

    #[test]
    fn media_pane_view_fullscreen_renders_current_image() {
        let (mut pane, store) = test_media_pane_with_grid(1, 1);
        let dir = tempfile::tempdir().expect("tempdir");
        let path = write_test_image(&dir);
        feed_image_paths(&store, &["s"], &path);
        pane.set_store(Some(store.clone()));
        pane.toggle_fullscreen();

        let view = view_str(&mut pane, 80, 20, "run", "");
        assert!(view.contains("Media [fullscreen]"));
        assert!(view.contains("[ansi]"));
        assert!(view.contains("X=_step 0"));
        assert!(!view.contains("No media."));
    }

    // --- MediaPane navigation ---

    #[test]
    fn media_pane_move_selection() {
        let (mut pane, store) = test_media_pane();
        feed_images(&store, "a", &[0.0]);
        feed_images(&store, "b", &[0.0]);
        feed_images(&store, "c", &[0.0]);
        pane.set_store(Some(store.clone()));

        // Trigger grid layout so MoveSelection knows the page geometry.
        let _ = pane.view(120, 20, "", "", true);

        // Start on "a".
        assert!(pane.status_label().contains("Media: a"));

        pane.move_selection(1, 0);
        assert!(pane.status_label().contains("Media: b"));

        pane.move_selection(1, 0);
        assert!(pane.status_label().contains("Media: c"));

        // Clamped at boundary.
        pane.move_selection(1, 0);
        assert!(pane.status_label().contains("Media: c"));

        pane.move_selection(-1, 0);
        assert!(pane.status_label().contains("Media: b"));
    }

    #[test]
    fn media_pane_handle_key_selection_and_page_bindings() {
        let (mut pane, store) = test_media_pane_with_grid(2, 2);
        let dir = tempfile::tempdir().expect("tempdir");
        let path = write_test_image(&dir);
        feed_image_paths(&store, &["a", "b", "c", "d", "e"], &path);
        pane.set_store(Some(store.clone()));
        pane.set_active(true);
        let _ = pane.view(90, 22, "", "", true);

        let (handled, cmd) = pane.handle_key(&media_key_msg("d"));
        assert!(handled);
        assert!(cmd.is_empty());
        assert!(pane.status_label().contains("Media: b"));

        let (handled, cmd) = pane.handle_key(&media_key_msg("s"));
        assert!(handled);
        assert!(cmd.is_empty());
        assert!(pane.status_label().contains("Media: d"));

        let (handled, cmd) = pane.handle_key(&media_key_msg("a"));
        assert!(handled);
        assert!(cmd.is_empty());
        assert!(pane.status_label().contains("Media: c"));

        let (handled, cmd) = pane.handle_key(&media_key_msg("w"));
        assert!(handled);
        assert!(cmd.is_empty());
        assert!(pane.status_label().contains("Media: a"));

        let (handled, cmd) = pane.handle_key(&media_key_msg("pgdown"));
        assert!(handled);
        assert!(cmd.is_empty());
        assert!(pane.status_label().contains("Media: e"));

        let (handled, cmd) = pane.handle_key(&media_key_msg("pgup"));
        assert!(handled);
        assert!(cmd.is_empty());
        assert!(pane.status_label().contains("Media: a"));
    }

    // --- set_nav_page (Rust-only) ---
    //
    // Go writes `p.nav.currentPage = page` directly; these tests pin the
    // public-API emulation to that field write for every state the Go call
    // sites can produce.

    /// Rust-only: for every (totalPages, startPage, targetPage) with the
    /// target in [0, totalPages), the emulation lands exactly on the target
    /// and — unlike the old `GridNavigator::default()` fallback — never
    /// disturbs totalPages.
    #[test]
    fn set_nav_page_matches_go_field_write_in_range() {
        for total in 1..=4isize {
            for start in 0..total {
                for page in 0..total {
                    let mut nav = GridNavigator::default();
                    nav.update_total_pages(total, 1);
                    nav.go_home();
                    if start > 0 {
                        nav.navigate(start);
                    }
                    assert_eq!(
                        nav.current_page(),
                        start,
                        "setup total={total} start={start}"
                    );

                    set_nav_page(&mut nav, page);
                    assert_eq!(
                        nav.current_page(),
                        page,
                        "total={total} start={start} page={page}"
                    );
                    assert_eq!(
                        nav.total_pages(),
                        total,
                        "totalPages must survive the write (total={total} start={start} page={page})"
                    );
                }
            }
        }
    }

    /// Rust-only: ResetViewState while the store is empty. UpdateTotalPages
    /// skips its clamp when totalPages == 0 (panelgrid.go:174), so the
    /// current page can be stale; Go's raw write then yields
    /// {currentPage: 0, totalPages: 0}.
    #[test]
    fn set_nav_page_zero_resets_stale_page_when_empty() {
        let mut nav = GridNavigator::default();
        nav.update_total_pages(3, 1);
        nav.go_end();
        nav.update_total_pages(0, 1); // store emptied

        // Pin the panel_grid quirk this path relies on.
        assert_eq!(nav.total_pages(), 0);
        assert_eq!(
            nav.current_page(),
            2,
            "UpdateTotalPages must not clamp when totalPages == 0"
        );

        set_nav_page(&mut nav, 0);
        assert_eq!(nav.current_page(), 0);
        assert_eq!(nav.total_pages(), 0);
    }

    /// Rust-only: an out-of-range target is unreachable from this module's
    /// callers and Go's raw field write is not expressible through the
    /// public GridNavigator API; the emulation must fail loudly rather than
    /// silently wrap (see the PARITY note on set_nav_page).
    #[cfg(debug_assertions)]
    #[test]
    #[should_panic(expected = "set_nav_page")]
    fn set_nav_page_out_of_range_is_loud() {
        let mut nav = GridNavigator::default();
        nav.update_total_pages(2, 1);
        set_nav_page(&mut nav, 5);
    }

    // --- MediaPane auto-follow ---

    #[test]
    fn media_pane_auto_follow() {
        let (mut pane, store) = test_media_pane();
        feed_images(&store, "s", &[0.0, 1.0]);
        pane.set_store(Some(store.clone()));

        // Auto-follow → last step.
        assert!(pane.status_label().contains("X=_step 1"));

        // New data arrives → auto-follow tracks it.
        feed_images(&store, "s", &[2.0]);
        pane.set_store(Some(store.clone()));
        assert!(pane.status_label().contains("X=_step 2"));

        // Scrub away disables auto-follow.
        pane.scrub_to_start();
        assert!(pane.status_label().contains("X=_step 0"));

        // New data arrives → position stays pinned.
        feed_images(&store, "s", &[3.0]);
        pane.set_store(Some(store.clone()));
        assert!(pane.status_label().contains("X=_step 0"));
    }

    // --- MediaPane SetStore ---

    #[test]
    fn media_pane_set_store_nil() {
        let (mut pane, store) = test_media_pane();
        feed_images(&store, "s", &[0.0]);
        pane.set_store(Some(store.clone()));
        assert!(pane.has_data());

        pane.set_store(None);
        assert!(!pane.has_data());
        assert_eq!(pane.status_label(), "");
    }

    // --- MediaPane View ---

    #[test]
    fn media_pane_view_empty_store() {
        let (mut pane, _store) = test_media_pane();
        // Should not panic and should render something.
        let v = view_str(&mut pane, 80, 20, "", "No media.");
        assert!(v.contains("No media."));
    }

    #[test]
    fn media_pane_view_too_small() {
        let (mut pane, store) = test_media_pane();
        feed_images(&store, "s", &[0.0]);
        pane.set_store(Some(store.clone()));

        assert!(view_str(&mut pane, 0, 20, "", "").is_empty());
        assert!(view_str(&mut pane, 80, 0, "", "").is_empty());
        // Below mediaPaneMinHeight.
        assert!(view_str(&mut pane, 80, 5, "", "").is_empty());
    }

    #[test]
    fn media_pane_view_renders_image_with_picture_glyph() {
        let (mut pane, store) = test_media_pane();
        let dir = tempfile::tempdir().expect("tempdir");
        let path = write_test_image(&dir);
        feed_image_paths(&store, &["s"], &path);
        pane.set_store(Some(store.clone()));

        let view = view_str(&mut pane, 80, 20, "", "");
        assert!(!view.contains("open image"));
        assert!(!view.contains("No image at X"));
    }

    #[test]
    fn media_pane_view_ansi_keeps_top_and_bottom_rows() {
        let (mut pane, store) = test_media_pane_with_grid(1, 1);
        let dir = tempfile::tempdir().expect("tempdir");
        let path = write_band_test_image(&dir);
        feed_image_paths(&store, &["s"], &path);
        pane.set_store(Some(store.clone()));

        let view = pane.view(40, 14, "", "", true);
        // PARITY: Go asserts on raw SGR fragments ("255;0;0"); the span
        // model's equivalent is a styled span carrying the color.
        assert!(
            has_span_color(&view, Color::Rgb(255, 0, 0)),
            "top row color should be rendered"
        );
        assert!(
            has_span_color(&view, Color::Rgb(0, 0, 255)),
            "bottom row color should be rendered"
        );

        let text = text_to_string(&view);
        let lines: Vec<&str> = text.split('\n').collect();
        let mut footer_idx: isize = -1;
        for (i, line) in lines.iter().enumerate() {
            if line.contains('│') && line.contains("X=_step 0") {
                footer_idx = i as isize;
                break;
            }
        }
        assert_ne!(footer_idx, -1, "expected media tile footer");
        assert!(footer_idx > 0);
        assert!(
            !lines[footer_idx as usize - 1]
                .trim_matches([' ', '│'])
                .is_empty()
        );
    }

    #[test]
    fn media_pane_toggle_renderer_mode_title() {
        let _env = set_kitty_graphics_env(true);

        let (mut pane, store) = test_media_pane();
        let dir = tempfile::tempdir().expect("tempdir");
        let path = write_test_image(&dir);
        feed_image_paths(&store, &["s"], &path);
        pane.set_store(Some(store.clone()));
        pane.set_active(true);

        let view = view_str(&mut pane, 80, 20, "", "");
        assert!(view.contains("[ansi]"));
        assert!(!pane.status_label().contains("kitty"));

        let (handled, toggle_cmd) = pane.handle_key(&key_k());
        assert!(handled);
        assert!(toggle_cmd.is_empty());
        let view = view_str(&mut pane, 80, 20, "", "");
        assert!(view.contains("[full-res]"));
        assert!(!pane.status_label().contains("kitty"));

        let (handled, toggle_cmd) = pane.handle_key(&key_k());
        assert!(handled);
        assert!(toggle_cmd.is_empty());
        let view = view_str(&mut pane, 80, 20, "", "");
        assert!(view.contains("[ansi]"));
        assert!(!pane.status_label().contains("kitty"));
    }

    #[test]
    fn media_pane_toggle_renderer_mode_uses_terminal_env_fallback() {
        let _env = set_kitty_graphics_env(false);
        test_env::set("GHOSTTY_BIN_DIR", "/tmp/ghostty");
        media_force_kitty_capability(KittyCapability::Unsupported);

        let (mut pane, store) = test_media_pane();
        let dir = tempfile::tempdir().expect("tempdir");
        let path = write_test_image(&dir);
        feed_image_paths(&store, &["s"], &path);
        pane.set_store(Some(store.clone()));
        pane.set_active(true);

        let view = view_str(&mut pane, 80, 20, "", "");
        assert!(view.contains("[ansi]"));

        let (handled, toggle_cmd) = pane.handle_key(&key_k());
        assert!(handled);
        assert!(toggle_cmd.is_empty());

        let view = view_str(&mut pane, 80, 20, "", "");
        assert!(view.contains("[full-res]"));
        // Go: picture.KittySupported() — through the same seam.
        assert_eq!(media_kitty_supported(), KittyCapability::Supported);
    }

    #[test]
    fn media_pane_toggle_renderer_mode_unsupported_terminal_stays_ansi() {
        let _env = set_kitty_graphics_env(false);

        let (mut pane, store) = test_media_pane();
        let dir = tempfile::tempdir().expect("tempdir");
        let path = write_test_image(&dir);
        feed_image_paths(&store, &["s"], &path);
        pane.set_store(Some(store.clone()));
        pane.set_active(true);

        let (handled, toggle_cmd) = pane.handle_key(&key_k());
        assert!(handled);
        assert!(toggle_cmd.is_empty());

        let view = view_str(&mut pane, 80, 20, "", "");
        assert!(view.contains("[ansi]"));
        assert!(!view.contains("[full-res]"));
        assert!(!view.contains("\u{1b}_G"));
    }

    // -- handle_picture_msg (Go handlePictureMsg + IsPictureMsg gate) -----

    /// The uv.CellSizeEvent arm: remembered for pictures created later
    /// (mediapane.go:1260-1264).
    #[test]
    fn handle_picture_msg_routes_cell_size_to_renderer() {
        let (mut pane, _store) = test_media_pane();
        let cmds = pane.handle_picture_msg(&Event::CellSize {
            width: 9,
            height: 18,
        });
        assert!(cmds.expect("picture msg consumed").is_empty());
        assert_eq!(pane.renderer.cell_pixel_w, 9);
        assert_eq!(pane.renderer.cell_pixel_h, 18);
    }

    /// recordKittyResponse / recordKittyTimeout state machine
    /// (kitty_capability.go:190-211): a probe response resolves Supported,
    /// the timeout resolves Unsupported only from Unknown, and a late
    /// response overrides the timeout's pessimistic conclusion.
    #[test]
    fn handle_picture_msg_records_probe_response_and_timeout() {
        // Guard: serializes against the other capability-seam tests.
        let _env = set_kitty_graphics_env(false);
        let (mut pane, _store) = test_media_pane();

        // A response with a foreign image ID is not our probe.
        test_kitty_cap::set(KittyCapability::Unknown);
        pane.handle_picture_msg(&Event::KittyGraphics(KittyGraphicsMsg { id: 7 }))
            .expect("picture msg consumed");
        assert_eq!(media_kitty_supported(), KittyCapability::Unknown);

        // The probe's ID resolves Supported — even before the tick.
        pane.handle_picture_msg(&Event::KittyGraphics(KittyGraphicsMsg {
            id: crate::runtime::KITTY_PROBE_ID,
        }))
        .expect("picture msg consumed");
        assert_eq!(media_kitty_supported(), KittyCapability::Supported);

        // A late tick never downgrades a resolved capability.
        pane.handle_picture_msg(&Event::KittyProbeTick)
            .expect("picture msg consumed");
        assert_eq!(media_kitty_supported(), KittyCapability::Supported);

        // From Unknown, the tick concludes Unsupported.
        test_kitty_cap::set(KittyCapability::Unknown);
        pane.handle_picture_msg(&Event::KittyProbeTick)
            .expect("picture msg consumed");
        assert_eq!(media_kitty_supported(), KittyCapability::Unsupported);

        // ...and a late response is authoritative over that conclusion
        // (kitty_capability.go:190-196).
        pane.handle_picture_msg(&Event::KittyGraphics(KittyGraphicsMsg {
            id: crate::runtime::KITTY_PROBE_ID,
        }))
        .expect("picture msg consumed");
        assert_eq!(media_kitty_supported(), KittyCapability::Supported);
    }

    /// Non-picture events fall through (`picture.IsPictureMsg` == false);
    /// a KittyFrame with no live pictures is consumed without commands
    /// (every model ignores a foreign/stale frame, picture.go:438-440).
    #[test]
    fn handle_picture_msg_gates_like_is_picture_msg() {
        let (mut pane, _store) = test_media_pane();
        assert!(pane.handle_picture_msg(&Event::Heartbeat).is_none());
        assert!(pane.handle_picture_msg(&Event::Key(key_k())).is_none());

        let frame = crate::picture::KittyFrameMsg::default();
        let cmds = pane
            .handle_picture_msg(&Event::KittyFrame(Box::new(frame)))
            .expect("picture msg consumed");
        assert!(cmds.is_empty());
    }

    #[test]
    fn media_pane_header_shows_range_without_page_number() {
        let (mut pane, store) = test_media_pane();
        let dir = tempfile::tempdir().expect("tempdir");
        let path = write_test_image(&dir);
        feed_image_paths(&store, &["a", "b", "c", "d", "e", "f", "g"], &path);
        pane.set_store(Some(store.clone()));

        let view = view_str(&mut pane, 80, 20, "", "");
        assert!(view.contains("[1-6 of 7]"));
        assert!(!view.contains("p.1/2"));

        let header = view.split('\n').next().unwrap_or_default();
        assert!(header.trim_end_matches(' ').ends_with("[1-6 of 7]"));
    }
}
