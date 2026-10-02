//! Paged lists, leet's `PagedList`: a list shows the page that holds its
//! cursor, so moving the cursor past the page's edge turns the page and
//! the cursor is always on screen.

use std::ops::Range;

pub struct Paged {
    /// Rows that fit the pane at its current height.
    pub rows: usize,
}

impl Paged {
    pub fn new() -> Self {
        Paged { rows: 1 }
    }

    pub fn fit(&mut self, height: f32, row_height: f32) {
        self.rows = ((height / row_height).floor() as usize).max(1);
    }

    pub fn pages(&self, total: usize) -> usize {
        total.div_ceil(self.rows).max(1)
    }

    pub fn page(&self, cursor: usize) -> usize {
        cursor / self.rows
    }

    /// The items on the page holding `cursor`.
    pub fn range(&self, cursor: usize, total: usize) -> Range<usize> {
        let start = (self.page(cursor) * self.rows).min(total);
        start..(start + self.rows).min(total)
    }

    /// `page k/n` for a pane header.
    pub fn label(&self, cursor: usize, total: usize) -> String {
        format!(
            "page {}/{}",
            self.page(cursor.min(total.saturating_sub(1))) + 1,
            self.pages(total)
        )
    }
}
