//! Port of `core/internal/leet/runoverviewsidebarnav.go` — section height
//! allocation and navigation for
//! [`RunOverviewSidebar`](crate::run_overview_sidebar::RunOverviewSidebar).

use crate::run_overview_sidebar::RunOverviewSidebar;

// Maximum heights for each section type.
// TODO: dynamically upscale if more space is available.
const SECTION_MAX_HEIGHT_ENVIRONMENT: isize = 12;
const SECTION_MAX_HEIGHT_CONFIG: isize = 20;
const SECTION_MAX_HEIGHT_SUMMARY: isize = 25;

/// Minimum section height when visible (title + 1 item).
const SECTION_MIN_HEIGHT: isize = 2;

impl RunOverviewSidebar {
    /// updateSectionHeights dynamically allocates heights to sections.
    pub(crate) fn update_section_heights(&mut self) {
        if self.height == 0 {
            return;
        }

        let total_available = self.available_height();
        if total_available <= 0 {
            return;
        }

        let desired = self.calculate_desired_heights();
        let total_desired = self.sum_desired_heights(&desired);

        if total_desired > total_available {
            self.scale_heights_proportionally(&desired, total_available);
        } else {
            self.allocate_desired_heights(&desired);
            self.distribute_extra_space(total_available, total_desired);
        }

        self.update_items_per_page();
    }

    /// availableHeight returns the height available for sections.
    fn available_height(&self) -> isize {
        let available_height = self.height - self.header_line_count();

        let active_sections = self.count_active_sections();
        if active_sections == 0 {
            return 0;
        }

        // Account for spacing between sections.
        let mut spacing_between_sections = 0;
        if active_sections > 1 {
            spacing_between_sections = active_sections - 1;
        }

        // Ensure minimum space for all active sections.
        let min_required = active_sections * SECTION_MIN_HEIGHT;
        (available_height - spacing_between_sections).max(min_required)
    }

    /// countActiveSections returns the number of sections with items.
    fn count_active_sections(&self) -> isize {
        let mut count = 0;
        for section in &self.sections {
            if !section.filtered_items.is_empty() {
                count += 1;
            }
        }
        count
    }

    /// calculateDesiredHeights calculates the desired height for each
    /// section.
    fn calculate_desired_heights(&mut self) -> Vec<isize> {
        let max_heights = [
            SECTION_MAX_HEIGHT_ENVIRONMENT,
            SECTION_MAX_HEIGHT_CONFIG,
            SECTION_MAX_HEIGHT_SUMMARY,
        ];

        let mut desired = vec![0isize; self.sections.len()];

        for (i, section) in self.sections.iter_mut().enumerate() {
            let item_count = section.filtered_items.len() as isize;
            if item_count == 0 {
                section.height = 0;
                desired[i] = 0;
                continue;
            }

            // Desired height is item count + 1 (for title), capped at max.
            let max_height = max_heights[i];
            desired[i] = (item_count + 1).min(max_height).max(SECTION_MIN_HEIGHT);
        }

        desired
    }

    /// sumDesiredHeights returns the sum of all desired heights.
    fn sum_desired_heights(&self, desired: &[isize]) -> isize {
        let mut total = 0;
        for &h in desired {
            total += h;
        }
        total
    }

    /// scaleHeightsProportionally scales section heights when total exceeds
    /// available.
    fn scale_heights_proportionally(&mut self, desired: &[isize], total_available: isize) {
        let total_desired = self.sum_desired_heights(desired);
        let scale_factor = total_available as f64 / total_desired as f64;

        let mut allocated = 0;
        for (i, section) in self.sections.iter_mut().enumerate() {
            if desired[i] > 0 {
                // PARITY: Go `int(float64(desired[i]) * scaleFactor)`
                // truncates toward zero; `as isize` matches.
                let mut scaled = (desired[i] as f64 * scale_factor) as isize;
                // Enforce minimum height for visible sections.
                if scaled < SECTION_MIN_HEIGHT && !section.filtered_items.is_empty() {
                    scaled = SECTION_MIN_HEIGHT;
                }
                section.height = scaled;
                allocated += scaled;
            } else {
                section.height = 0;
            }
        }

        // Distribute remainder to last section with items.
        if allocated < total_available {
            let remainder = total_available - allocated;
            self.allocate_remainder(remainder);
        }
    }

    /// allocateDesiredHeights sets each section to its desired height.
    fn allocate_desired_heights(&mut self, desired: &[isize]) {
        for (i, section) in self.sections.iter_mut().enumerate() {
            section.height = desired[i];
        }
    }

    /// distributeExtraSpace distributes unused space to sections that can
    /// use it.
    fn distribute_extra_space(&mut self, total_available: isize, total_desired: isize) {
        let max_heights = [
            SECTION_MAX_HEIGHT_ENVIRONMENT,
            SECTION_MAX_HEIGHT_CONFIG,
            SECTION_MAX_HEIGHT_SUMMARY,
        ];

        let mut extra_space = total_available - total_desired;

        // Try to expand sections from bottom to top (summary, config, env).
        for i in (0..=2usize).rev() {
            if extra_space <= 0 {
                break;
            }
            let section = &mut self.sections[i];
            if section.height == 0 {
                continue;
            }

            let item_count = section.filtered_items.len() as isize;
            let current_items = section.height - 1; // Subtract title line

            // Only expand if we have more items to show.
            if current_items < item_count {
                let max_increase =
                    (max_heights[i] - section.height).min(item_count + 1 - section.height);
                let increase = max_increase.min(extra_space);

                section.height += increase;
                extra_space -= increase;
            }
        }
    }

    /// allocateRemainder distributes remaining space to the last section
    /// with items.
    fn allocate_remainder(&mut self, remainder: isize) {
        // Try sections from bottom to top.
        for i in (0..=2usize).rev() {
            if !self.sections[i].filtered_items.is_empty() && self.sections[i].height > 0 {
                self.sections[i].height += remainder;
                return;
            }
        }
    }

    /// updateItemsPerPage updates the items per page for each section.
    fn update_items_per_page(&mut self) {
        for section in &mut self.sections {
            if section.height > 0 {
                // Height includes title line, so items per page is height - 1.
                section.set_items_per_page((section.height - 1).max(1));
            } else {
                section.set_items_per_page(0);
            }
        }
    }

    /// navigateUp moves cursor up within the active section.
    pub(crate) fn navigate_up(&mut self) {
        if !self.is_valid_active_section() {
            return;
        }

        let section = &mut self.sections[self.active_section as usize];
        section.up();
    }

    /// navigateDown moves cursor down within the active section.
    pub(crate) fn navigate_down(&mut self) {
        if !self.is_valid_active_section() {
            return;
        }

        let section = &mut self.sections[self.active_section as usize];
        section.down();
    }

    /// navigateSection jumps between sections, skipping empty ones.
    pub(crate) fn navigate_section(&mut self, direction: isize) {
        if self.sections.is_empty() {
            return;
        }

        let prev = self.active_section;
        let mut idx = prev;

        // Try each section in the given direction.
        for _ in 0..self.sections.len() {
            idx += direction;
            if idx < 0 {
                idx = self.sections.len() as isize - 1;
            } else if idx >= self.sections.len() as isize {
                idx = 0;
            }

            // Select first non-empty section.
            if !self.sections[idx as usize].filtered_items.is_empty() {
                self.set_active_section(idx);
                return;
            }

            // Wrapped around to starting section.
            if idx == prev {
                break;
            }
        }

        // No non-empty section found, keep current active.
        self.sections[prev as usize].active = true;
    }

    /// navigatePageUp changes page to previous within active section.
    pub(crate) fn navigate_page_up(&mut self) {
        if !self.is_valid_active_section() {
            return;
        }

        let section = &mut self.sections[self.active_section as usize];
        section.page_up();
    }

    /// navigatePageDown changes page to next within active section.
    pub(crate) fn navigate_page_down(&mut self) {
        if !self.is_valid_active_section() {
            return;
        }

        let section = &mut self.sections[self.active_section as usize];
        section.page_down();
    }

    /// navigateHome jumps to the first item of the active section.
    // PHASE-5: called from the run/workspace key handlers
    // (runhandlers.go:466, workspacehandlers.go:835).
    #[allow(dead_code)]
    pub(crate) fn navigate_home(&mut self) {
        if !self.is_valid_active_section() {
            return;
        }

        let section = &mut self.sections[self.active_section as usize];
        section.home();
    }

    /// navigateEnd jumps to the last item of the active section.
    // PHASE-5: called from the run/workspace key handlers
    // (runhandlers.go:482, workspacehandlers.go:855).
    #[allow(dead_code)]
    pub(crate) fn navigate_end(&mut self) {
        if !self.is_valid_active_section() {
            return;
        }

        let section = &mut self.sections[self.active_section as usize];
        section.end();
    }

    /// selectFirstAvailableItem selects the first item in the first
    /// non-empty section.
    pub(crate) fn select_first_available_item(&mut self) {
        // Find first non-empty section.
        for i in 0..self.sections.len() {
            if !self.sections[i].filtered_items.is_empty() && self.sections[i].items_per_page() > 0
            {
                self.set_active_section(i as isize);
                return;
            }
        }

        // No non-empty section found, default to first section.
        self.set_active_section(0);
    }

    /// restoreSelection attempts to restore the previously selected item.
    pub(crate) fn restore_selection(&mut self, previous_key: &str) {
        // Try to find key-only match in current active section.
        if self.try_restore_in_section(previous_key) {
            return;
        }

        // Could not restore, select first available.
        self.select_first_available_item();
    }

    /// tryRestoreInSection attempts to restore selection in a specific
    /// section.
    ///
    /// Returns true if successful.
    fn try_restore_in_section(&mut self, key: &str) -> bool {
        if self.active_section < 0 || self.active_section as usize >= self.sections.len() {
            return false;
        }

        let section = &mut self.sections[self.active_section as usize];
        if section.items_per_page() == 0 {
            return false;
        }

        // PARITY: Go returns from inside the range loop on the first key
        // match; the index is found first here to satisfy the borrow
        // checker (`SetPageAndLine` needs `&mut`).
        let mut found: Option<isize> = None;
        for (i, item) in section.filtered_items.iter().enumerate() {
            let key_match = item.key == key;

            if key_match {
                found = Some(i as isize);
                break;
            }
        }

        if let Some(i) = found {
            let page = i / section.items_per_page();
            let line = i % section.items_per_page();

            section.set_page_and_line(page, line);
            return true;
        }

        false
    }

    /// deactivateAllSections marks all sections as inactive, removing row
    /// highlights.
    pub(crate) fn deactivate_all_sections(&mut self) {
        for section in &mut self.sections {
            section.active = false;
        }
    }

    /// hasActiveSection reports whether any section is currently active.
    pub(crate) fn has_active_section(&self) -> bool {
        for section in &self.sections {
            if section.active {
                return true;
            }
        }
        false
    }

    /// setActiveSection changes the active section and resets navigation
    /// state.
    pub(crate) fn set_active_section(&mut self, idx: isize) {
        // Deactivate all sections.
        for section in &mut self.sections {
            section.active = false;
        }

        // Activate target section.
        self.active_section = idx;
        if idx >= 0 && (idx as usize) < self.sections.len() {
            self.sections[idx as usize].active = true;
        }
    }

    /// isValidActiveSection returns true if the active section index is
    /// valid.
    pub(crate) fn is_valid_active_section(&self) -> bool {
        self.active_section >= 0 && (self.active_section as usize) < self.sections.len()
    }
}
