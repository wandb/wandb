//! A paged grid of charts, the shape leet uses for metrics and system
//! metrics: `rows x cols` cells per page, one focused cell.

use gpui::prelude::*;
use gpui::{Context, Div, Entity, Pixels, ScrollWheelEvent, SharedString, Stateful, div, px};

use crate::chart::{self, ChartSpec};
use crate::config::GridConfig;
use crate::theme;
use crate::workspace::{Filter, Workspace, pane_header, wheel_lines};

/// Cells shorter than this lose their axes, so a short pane shows fewer rows.
pub const MIN_CELL_HEIGHT: f32 = 90.;

pub struct Grid {
    pub rows: usize,
    pub cols: usize,
    pub page: usize,
    pub focused: usize,
    /// Rows that fit the pane at its current height, at most `rows`.
    pub visible_rows: usize,
}

impl Grid {
    pub fn new(config: GridConfig) -> Self {
        let rows = config.rows.max(1);
        Grid {
            rows,
            cols: config.cols.max(1),
            page: 0,
            focused: 0,
            visible_rows: rows,
        }
    }

    /// Fits the row count to a pane `height` pixels tall.
    pub fn fit(&mut self, height: f32) {
        let fits = (height / MIN_CELL_HEIGHT).floor().max(1.) as usize;
        self.visible_rows = fits.min(self.rows);
        self.focused = self.focused.min(self.per_page() - 1);
    }

    pub fn per_page(&self) -> usize {
        self.visible_rows * self.cols
    }

    pub fn pages(&self, cells: usize) -> usize {
        cells.div_ceil(self.per_page()).max(1)
    }

    /// The index into the full cell list of the focused cell.
    pub fn focused_index(&self, cells: usize) -> usize {
        let page = self.page.min(self.pages(cells) - 1);
        page * self.per_page()
            + self
                .focused
                .min(self.cells_on_page(cells).saturating_sub(1))
    }

    /// Moves the focus within the page, never onto an empty trailing cell.
    pub fn move_focus(&mut self, drow: isize, dcol: isize, cells_on_page: usize) {
        let cols = self.cols as isize;
        let row = (self.focused as isize / cols + drow).clamp(0, self.visible_rows as isize - 1);
        let col = (self.focused as isize % cols + dcol).clamp(0, cols - 1);
        self.focused = ((row * cols + col) as usize).min(cells_on_page.saturating_sub(1));
    }

    /// How many of `total` cells the current page holds.
    pub fn cells_on_page(&self, total: usize) -> usize {
        let page = self.page.min(self.pages(total) - 1);
        total
            .saturating_sub(page * self.per_page())
            .min(self.per_page())
    }

    pub fn turn_page(&mut self, delta: isize, cells: usize) {
        let pages = self.pages(cells) as isize;
        self.page = (self.page as isize + delta).clamp(0, pages - 1) as usize;
    }
}

pub struct Cell {
    pub title: SharedString,
    pub badge: Option<&'static str>,
    pub spec: ChartSpec,
}

pub struct GridView<'a> {
    pub id: &'static str,
    pub title: String,
    pub filter: &'a Filter,
    pub focused: bool,
    pub grid: &'a Grid,
    /// The cells of the current page only.
    pub cells: Vec<Cell>,
    pub total: usize,
    /// A fixed height for a lower-tier pane; the metrics grid takes the rest.
    pub height: Option<Pixels>,
    /// Why the grid has no cells, shown in place of them.
    pub empty: SharedString,
}

/// Cells keep the size the full grid gives them, so charts do not move
/// between pages; trailing slots on a short page stay blank. A grid whose
/// charts all fit on one page uses only the rows it needs.
pub fn render_grid(
    view: GridView<'_>,
    workspace: Entity<Workspace>,
    cx: &mut Context<Workspace>,
) -> Stateful<Div> {
    let GridView {
        id,
        title,
        filter,
        focused,
        grid,
        cells,
        total,
        height,
        empty,
    } = view;
    let pages = grid.pages(total);
    let page = grid.page.min(pages - 1);
    let header = format!("{title}  page {}/{pages}", page + 1);
    let on_page = cells.len();
    let rows_used = if total <= grid.per_page() {
        total.div_ceil(grid.cols).max(1)
    } else {
        grid.visible_rows
    };
    let focused_cell = grid.focused.min(on_page.saturating_sub(1));
    let mut cells = cells.into_iter().map(Some).collect::<Vec<_>>();
    cells.resize_with(rows_used * grid.cols, || None);
    let mut cells = cells.into_iter();

    div()
        .id(id)
        .map(|pane| match height {
            Some(height) => pane
                .h(height)
                .flex_shrink_0()
                .border_t_1()
                .border_color(theme::border()),
            None => pane.flex_1(),
        })
        .min_h_0()
        .min_w_0()
        .overflow_hidden()
        .flex()
        .flex_col()
        .child(pane_header(header, filter, focused))
        .when(total == 0, |pane| {
            pane.child(
                div()
                    .flex_1()
                    .flex()
                    .items_center()
                    .justify_center()
                    .text_color(theme::muted())
                    .child(empty),
            )
        })
        .when(total > 0, |pane| {
            pane.children((0..rows_used).map(|row| {
                div()
                    .flex_1()
                    .min_h_0()
                    .flex()
                    .flex_row()
                    .children((0..grid.cols).map(|col| {
                        let Some(cell) = cells.next().flatten() else {
                            return div().flex_1().m(px(3.));
                        };
                        let is_focused = focused && row * grid.cols + col == focused_cell;
                        let key = cell.spec.key.clone();
                        div()
                            .flex_1()
                            .min_w_0()
                            .m(px(3.))
                            .rounded(px(4.))
                            .border_1()
                            .border_color(if is_focused {
                                theme::focus()
                            } else {
                                theme::border()
                            })
                            .bg(theme::panel())
                            .flex()
                            .flex_col()
                            .on_scroll_wheel(cx.listener(
                                move |workspace, event: &ScrollWheelEvent, _, cx| {
                                    if let Some(lines) = wheel_lines(event) {
                                        workspace.request_zoom(
                                            key.clone(),
                                            1.25f64.powf(f64::from(-lines)),
                                            event.position.x,
                                        );
                                        cx.notify();
                                    }
                                },
                            ))
                            .child(
                                div()
                                    .h(px(22.))
                                    .px_2()
                                    .flex()
                                    .items_center()
                                    .gap_2()
                                    .text_color(theme::text())
                                    .child(
                                        div()
                                            .flex_1()
                                            .overflow_hidden()
                                            .whitespace_nowrap()
                                            .text_ellipsis()
                                            .child(cell.title),
                                    )
                                    .when_some(cell.badge, |title, badge| {
                                        title.child(div().text_color(theme::muted()).child(badge))
                                    }),
                            )
                            .child(
                                div()
                                    .flex_1()
                                    .min_h_0()
                                    .child(chart::chart(workspace.clone(), cell.spec)),
                            )
                    }))
            }))
        })
}
