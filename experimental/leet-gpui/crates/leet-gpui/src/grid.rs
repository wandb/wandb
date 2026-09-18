//! A paged grid of charts, the shape leet uses for metrics and system
//! metrics: `rows x cols` cells per page, one focused cell.

use gpui::prelude::*;
use gpui::{Context, Div, Entity, Pixels, SharedString, Stateful, div, px};

use crate::chart::{self, ChartSpec};
use crate::config::GridConfig;
use crate::theme;
use crate::workspace::{Filter, Workspace, pane_header};

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
        self.page.min(self.pages(cells) - 1) * self.per_page() + self.focused
    }

    pub fn move_focus(&mut self, drow: isize, dcol: isize) {
        let cols = self.cols as isize;
        let row = (self.focused as isize / cols + drow).clamp(0, self.visible_rows as isize - 1);
        let col = (self.focused as isize % cols + dcol).clamp(0, cols - 1);
        self.focused = (row * cols + col) as usize;
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
}

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
    } = view;
    let pages = grid.pages(total);
    let page = grid.page.min(pages - 1);
    let header = format!("{title}  page {}/{pages}", page + 1);
    let mut cells = cells.into_iter().map(Some).collect::<Vec<_>>();
    cells.resize_with(grid.per_page(), || None);
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
        .flex()
        .flex_col()
        .on_mouse_move(cx.listener(|_, _, _, cx| cx.notify()))
        .child(pane_header(header, filter, focused))
        .children((0..grid.visible_rows).map(|row| {
            div()
                .flex_1()
                .min_h_0()
                .flex()
                .flex_row()
                .children((0..grid.cols).map(|col| {
                    let cell = cells.next().flatten();
                    let is_focused = focused && row * grid.cols + col == grid.focused;
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
                        .when_some(cell, |cell_div, cell| {
                            cell_div
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
                                            title.child(
                                                div().text_color(theme::muted()).child(badge),
                                            )
                                        }),
                                )
                                .child(
                                    div()
                                        .flex_1()
                                        .min_h_0()
                                        .child(chart::chart(workspace.clone(), cell.spec)),
                                )
                        })
                }))
        }))
}
