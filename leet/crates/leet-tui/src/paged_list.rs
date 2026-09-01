//! Port of `core/internal/leet/pagedlist.go`.
//!
//! Go int fields go transiently negative during navigation, so they port
//! as `isize` (PORTING.md numeric rules).

use leet_data::run_overview::KeyValuePair;

/// PagedList represents a paginated list of items.
#[derive(Debug, Clone, Default)]
pub struct PagedList {
    pub title: String,
    pub items: Vec<KeyValuePair>,
    pub filtered_items: Vec<KeyValuePair>,

    items_per_page: isize,
    current_page: isize,
    current_line: isize,

    pub height: isize,
    pub active: bool,
}

impl PagedList {
    pub fn items_per_page(&self) -> isize {
        self.items_per_page
    }

    pub fn current_page(&self) -> isize {
        self.current_page
    }

    pub fn current_line(&self) -> isize {
        self.current_line
    }

    pub fn set_items_per_page(&mut self, n: isize) {
        self.items_per_page = n.max(0);
        self.clamp_cursor();
    }

    /// Navigates to the previous item.
    pub fn up(&mut self) {
        if !self.has_navigable_items() {
            self.reset_cursor();
            return;
        }

        self.current_line -= 1;

        // Still on the same page?
        if self.current_line >= 0 {
            return;
        }

        let total_pages = self.total_pages();

        self.current_page -= 1;

        if self.current_page >= 0 {
            // Moved to previous page - go to last line.
            self.current_line = self.items_on_page(self.current_page) - 1;
            return;
        }

        // Wrapped around to last page.
        self.current_page = total_pages - 1;
        self.current_line = self.items_on_page(self.current_page) - 1;
    }

    /// Navigates to the next item.
    pub fn down(&mut self) {
        if !self.has_navigable_items() {
            self.reset_cursor();
            return;
        }

        self.current_line += 1;

        let items_on_page = self.items_on_page(self.current_page);
        if self.current_line < items_on_page {
            return;
        }

        // Move to next page - go to first line.
        self.current_page += 1;
        self.current_line = 0;

        // Wrapped around to first page.
        if self.current_page >= self.total_pages() {
            self.current_page = 0;
        }
    }

    /// Navigates to the previous page.
    pub fn page_up(&mut self) {
        if !self.has_navigable_items() {
            self.reset_cursor();
            return;
        }

        self.current_line = 0;
        self.current_page -= 1;

        if self.current_page < 0 {
            self.current_page = self.total_pages() - 1;
        }
    }

    /// Navigates to the next page.
    pub fn page_down(&mut self) {
        if !self.has_navigable_items() {
            self.reset_cursor();
            return;
        }

        self.current_line = 0;
        self.current_page += 1;

        if self.current_page >= self.total_pages() {
            self.current_page = 0;
        }
    }

    /// Navigates to the start page.
    pub fn home(&mut self) {
        self.current_page = 0;
        self.current_line = 0;
    }

    /// Navigates to the last item on the last page.
    pub fn end(&mut self) {
        if !self.has_navigable_items() {
            self.reset_cursor();
            return;
        }

        let total_pages = self.total_pages();
        self.current_page = total_pages - 1;
        self.current_line = self.items_on_page(self.current_page) - 1;
    }

    pub fn set_page_and_line(&mut self, page: isize, line: isize) {
        if !self.has_navigable_items() {
            self.reset_cursor();
            return;
        }

        let total_pages = self.total_pages();
        if page < 0 || page > total_pages - 1 {
            return;
        }

        let items_on_page = self.items_on_page(page);
        if line < 0 || line > items_on_page - 1 {
            return;
        }

        self.current_page = page;
        self.current_line = line;
    }

    pub fn current_item(&self) -> Option<&KeyValuePair> {
        if !self.has_navigable_items() {
            return None;
        }

        let start = self.current_page * self.items_per_page;
        let idx = start + self.current_line;
        if idx < 0 || idx >= self.filtered_items.len() as isize {
            return None;
        }
        Some(&self.filtered_items[idx as usize])
    }

    fn has_navigable_items(&self) -> bool {
        self.items_per_page > 0 && !self.filtered_items.is_empty()
    }

    fn total_pages(&self) -> isize {
        if !self.has_navigable_items() {
            return 0;
        }
        (self.filtered_items.len() as isize + self.items_per_page - 1) / self.items_per_page
    }

    fn items_on_page(&self, page: isize) -> isize {
        if !self.has_navigable_items() {
            return 0;
        }
        let mut items_on_page = self.items_per_page;
        if page == self.total_pages() - 1 {
            let remainder = self.filtered_items.len() as isize % self.items_per_page;
            if remainder != 0 {
                items_on_page = remainder;
            }
        }
        items_on_page
    }

    fn clamp_cursor(&mut self) {
        if !self.has_navigable_items() {
            self.reset_cursor();
            return;
        }

        let total_pages = self.total_pages();
        if self.current_page >= total_pages {
            self.current_page = total_pages - 1;
        }
        if self.current_page < 0 {
            self.current_page = 0;
        }

        let items_on_page = self.items_on_page(self.current_page);
        if self.current_line >= items_on_page {
            self.current_line = items_on_page - 1;
        }
        if self.current_line < 0 {
            self.current_line = 0;
        }
    }

    fn reset_cursor(&mut self) {
        self.current_page = 0;
        self.current_line = 0;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn kv(key: &str) -> KeyValuePair {
        KeyValuePair {
            key: key.to_string(),
            ..Default::default()
        }
    }

    #[test]
    fn empty_navigation_is_stable() {
        let mut list = PagedList::default();

        list.up();
        list.down();
        list.page_up();
        list.page_down();
        list.home();

        assert!(list.current_item().is_none());
        assert_eq!(list.current_page(), 0);
        assert_eq!(list.current_line(), 0);
    }

    #[test]
    fn set_items_per_page_zero_disables_navigation() {
        let mut list = PagedList {
            filtered_items: vec![kv("a"), kv("b")],
            ..Default::default()
        };

        list.set_items_per_page(0);
        assert_eq!(list.items_per_page(), 0);

        list.down();
        list.page_down();
        assert!(list.current_item().is_none());
        assert_eq!(list.current_page(), 0);
        assert_eq!(list.current_line(), 0);

        list.set_items_per_page(1);
        assert_eq!(list.current_item().unwrap().key, "a");
    }

    #[test]
    fn end_jumps_to_last_item() {
        // 5 items, 2 per page -> 3 pages: [a b][c d][e]; End -> last page, last line.
        let mut list = PagedList {
            filtered_items: vec![kv("a"), kv("b"), kv("c"), kv("d"), kv("e")],
            ..Default::default()
        };
        list.set_items_per_page(2);

        list.end();
        assert_eq!(list.current_item().unwrap().key, "e");
        assert_eq!(list.current_page(), 2);
        assert_eq!(list.current_line(), 0);

        // Full last page: 4 items, 2 per page -> End lands on (page 1, line 1).
        let mut full = PagedList {
            filtered_items: vec![kv("a"), kv("b"), kv("c"), kv("d")],
            ..Default::default()
        };
        full.set_items_per_page(2);
        full.end();
        assert_eq!(full.current_page(), 1);
        assert_eq!(full.current_line(), 1);
    }

    /// Wrap-around behavior implied by the Go implementation (Up from the
    /// first item lands on the last item; Down from the last wraps to the
    /// first) — kept under test because navigation depends on it.
    #[test]
    fn up_down_wrap_around() {
        let mut list = PagedList {
            filtered_items: vec![kv("a"), kv("b"), kv("c"), kv("d"), kv("e")],
            ..Default::default()
        };
        list.set_items_per_page(2);

        list.up();
        assert_eq!(list.current_item().unwrap().key, "e");
        list.down();
        assert_eq!(list.current_item().unwrap().key, "a");
    }
}
