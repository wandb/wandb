//! A paginated key-value list with wrap-around navigation.

/// A single key-value item to display.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct KeyValuePair {
    pub key: String,
    pub value: String,
    /// Full path for nested items.
    pub path: Vec<String>,
}

/// A paginated list of items.
#[derive(Debug, Clone, Default)]
pub struct PagedList {
    pub title: String,
    pub items: Vec<KeyValuePair>,
    pub filtered_items: Vec<KeyValuePair>,

    items_per_page: usize,
    current_page: usize,
    current_line: usize,

    pub height: usize,
    pub active: bool,
}

impl PagedList {
    pub fn new(title: &str, active: bool) -> Self {
        Self {
            title: title.to_string(),
            active,
            ..Default::default()
        }
    }

    pub fn items_per_page(&self) -> usize {
        self.items_per_page
    }

    pub fn current_page(&self) -> usize {
        self.current_page
    }

    pub fn current_line(&self) -> usize {
        self.current_line
    }

    pub fn set_items_per_page(&mut self, n: usize) {
        self.items_per_page = n;
        self.clamp_cursor();
    }

    /// Navigates to the previous item, wrapping across pages.
    pub fn up(&mut self) {
        if !self.has_navigable_items() {
            self.reset_cursor();
            return;
        }

        if self.current_line > 0 {
            self.current_line -= 1;
            return;
        }

        if self.current_page > 0 {
            self.current_page -= 1;
        } else {
            self.current_page = self.total_pages() - 1;
        }
        self.current_line = self.items_on_page(self.current_page).saturating_sub(1);
    }

    /// Navigates to the next item, wrapping across pages.
    pub fn down(&mut self) {
        if !self.has_navigable_items() {
            self.reset_cursor();
            return;
        }

        self.current_line += 1;
        if self.current_line < self.items_on_page(self.current_page) {
            return;
        }

        self.current_page += 1;
        self.current_line = 0;
        if self.current_page >= self.total_pages() {
            self.current_page = 0;
        }
    }

    pub fn page_up(&mut self) {
        if !self.has_navigable_items() {
            self.reset_cursor();
            return;
        }

        self.current_line = 0;
        if self.current_page > 0 {
            self.current_page -= 1;
        } else {
            self.current_page = self.total_pages() - 1;
        }
    }

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

    pub fn home(&mut self) {
        self.current_page = 0;
        self.current_line = 0;
    }

    pub fn end(&mut self) {
        if !self.has_navigable_items() {
            self.reset_cursor();
            return;
        }

        self.current_page = self.total_pages() - 1;
        self.current_line = self.items_on_page(self.current_page).saturating_sub(1);
    }

    pub fn set_page_and_line(&mut self, page: usize, line: usize) {
        if !self.has_navigable_items() {
            self.reset_cursor();
            return;
        }
        if page >= self.total_pages() || line >= self.items_on_page(page) {
            return;
        }
        self.current_page = page;
        self.current_line = line;
    }

    pub fn current_item(&self) -> Option<&KeyValuePair> {
        if !self.has_navigable_items() {
            return None;
        }
        let idx = self.current_page * self.items_per_page + self.current_line;
        self.filtered_items.get(idx)
    }

    pub fn has_navigable_items(&self) -> bool {
        self.items_per_page > 0 && !self.filtered_items.is_empty()
    }

    fn total_pages(&self) -> usize {
        if !self.has_navigable_items() {
            return 0;
        }
        self.filtered_items.len().div_ceil(self.items_per_page)
    }

    fn items_on_page(&self, page: usize) -> usize {
        if !self.has_navigable_items() {
            return 0;
        }
        if page == self.total_pages() - 1 {
            let remainder = self.filtered_items.len() % self.items_per_page;
            if remainder != 0 {
                return remainder;
            }
        }
        self.items_per_page
    }

    fn clamp_cursor(&mut self) {
        if !self.has_navigable_items() {
            self.reset_cursor();
            return;
        }

        let total = self.total_pages();
        if self.current_page >= total {
            self.current_page = total - 1;
        }
        let on_page = self.items_on_page(self.current_page);
        if self.current_line >= on_page {
            self.current_line = on_page.saturating_sub(1);
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

    fn list(n: usize, per_page: usize) -> PagedList {
        let mut l = PagedList::new("t", true);
        l.items = (0..n)
            .map(|i| KeyValuePair {
                key: format!("k{i}"),
                value: format!("v{i}"),
                path: vec![],
            })
            .collect();
        l.filtered_items = l.items.clone();
        l.set_items_per_page(per_page);
        l
    }

    #[test]
    fn wraps_around() {
        let mut l = list(5, 2); // pages: [0,1], [2,3], [4]
        l.up(); // wrap to last item
        assert_eq!(l.current_page(), 2);
        assert_eq!(l.current_line(), 0);
        l.down(); // wrap to first
        assert_eq!(l.current_page(), 0);
        assert_eq!(l.current_line(), 0);
        l.down();
        assert_eq!(l.current_item().unwrap().key, "k1");
        l.page_down();
        assert_eq!(l.current_page(), 1);
        assert_eq!(l.current_line(), 0);
        l.end();
        assert_eq!(l.current_item().unwrap().key, "k4");
        l.home();
        assert_eq!(l.current_item().unwrap().key, "k0");
    }
}
