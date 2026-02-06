package leet

const (
	// Maximum heights for each section type.
	// TODO: dynamically upscale if more space is available.
	sectionMaxHeightEnvironment = 12
	sectionMaxHeightConfig      = 20
	sectionMaxHeightSummary     = 25

	// Minimum section height when visible (title + 1 item).
	sectionMinHeight = 2
)

// updateSectionHeights dynamically allocates heights to sections.
func (s *RunOverviewSidebar) updateSectionHeights() {
	if s.height == 0 {
		return
	}

	totalAvailable := s.availableHeight()
	if totalAvailable <= 0 {
		return
	}

	desired := s.calculateDesiredHeights()
	totalDesired := s.sumDesiredHeights(desired)

	if totalDesired > totalAvailable {
		s.scaleHeightsProportionally(desired, totalAvailable)
	} else {
		s.allocateDesiredHeights(desired)
		s.distributeExtraSpace(totalAvailable, totalDesired)
	}

	s.updateItemsPerPage()
}

// availableHeight returns the height available for sections.
func (s *RunOverviewSidebar) availableHeight() int {
	availableHeight := s.height - sidebarHeaderLines

	activeSections := s.countActiveSections()
	if activeSections == 0 {
		return 0
	}

	// Account for spacing between sections.
	spacingBetweenSections := 0
	if activeSections > 1 {
		spacingBetweenSections = activeSections - 1
	}

	// Ensure minimum space for all active sections.
	minRequired := activeSections * sectionMinHeight
	return max(availableHeight-spacingBetweenSections, minRequired)
}

// countActiveSections returns the number of sections with items.
func (s *RunOverviewSidebar) countActiveSections() int {
	count := 0
	for i := range s.sections {
		if len(s.sections[i].FilteredItems) > 0 {
			count++
		}
	}
	return count
}

// calculateDesiredHeights calculates the desired height for each section.
func (s *RunOverviewSidebar) calculateDesiredHeights() []int {
	maxHeights := []int{
		sectionMaxHeightEnvironment,
		sectionMaxHeightConfig,
		sectionMaxHeightSummary,
	}

	desired := make([]int, len(s.sections))

	for i := range s.sections {
		itemCount := len(s.sections[i].FilteredItems)
		if itemCount == 0 {
			s.sections[i].Height = 0
			desired[i] = 0
			continue
		}

		// Desired height is item count + 1 (for title), capped at max.
		maxHeight := maxHeights[i]
		desired[i] = max(min(itemCount+1, maxHeight), sectionMinHeight)
	}

	return desired
}

// sumDesiredHeights returns the sum of all desired heights.
func (s *RunOverviewSidebar) sumDesiredHeights(desired []int) int {
	total := 0
	for _, h := range desired {
		total += h
	}
	return total
}

// scaleHeightsProportionally scales section heights when total exceeds available.
func (s *RunOverviewSidebar) scaleHeightsProportionally(desired []int, totalAvailable int) {
	totalDesired := s.sumDesiredHeights(desired)
	scaleFactor := float64(totalAvailable) / float64(totalDesired)

	allocated := 0
	for i := range s.sections {
		if desired[i] > 0 {
			scaled := int(float64(desired[i]) * scaleFactor)
			// Enforce minimum height for visible sections.
			if scaled < sectionMinHeight && len(s.sections[i].FilteredItems) > 0 {
				scaled = sectionMinHeight
			}
			s.sections[i].Height = scaled
			allocated += scaled
		} else {
			s.sections[i].Height = 0
		}
	}

	// Distribute remainder to last section with items.
	if allocated < totalAvailable {
		remainder := totalAvailable - allocated
		s.allocateRemainder(remainder)
	}
}

// allocateDesiredHeights sets each section to its desired height.
func (s *RunOverviewSidebar) allocateDesiredHeights(desired []int) {
	for i := range s.sections {
		s.sections[i].Height = desired[i]
	}
}

// distributeExtraSpace distributes unused space to sections that can use it.
func (s *RunOverviewSidebar) distributeExtraSpace(totalAvailable, totalDesired int) {
	maxHeights := []int{
		sectionMaxHeightEnvironment,
		sectionMaxHeightConfig,
		sectionMaxHeightSummary,
	}

	extraSpace := totalAvailable - totalDesired

	// Try to expand sections from bottom to top (summary, config, env).
	for i := 2; i >= 0 && extraSpace > 0; i-- {
		section := &s.sections[i]
		if section.Height == 0 {
			continue
		}

		itemCount := len(section.FilteredItems)
		currentItems := section.Height - 1 // Subtract title line

		// Only expand if we have more items to show.
		if currentItems < itemCount {
			maxIncrease := min(maxHeights[i]-section.Height, itemCount+1-section.Height)
			increase := min(maxIncrease, extraSpace)

			section.Height += increase
			extraSpace -= increase
		}
	}
}

// allocateRemainder distributes remaining space to the last section with items.
func (s *RunOverviewSidebar) allocateRemainder(remainder int) {
	// Try sections from bottom to top.
	for i := 2; i >= 0; i-- {
		if len(s.sections[i].FilteredItems) > 0 && s.sections[i].Height > 0 {
			s.sections[i].Height += remainder
			return
		}
	}
}

// updateItemsPerPage updates the items per page for each section.
func (s *RunOverviewSidebar) updateItemsPerPage() {
	for i := range s.sections {
		if s.sections[i].Height > 0 {
			// Height includes title line, so items per page is height - 1.
			s.sections[i].SetItemsPerPage(max(s.sections[i].Height-1, 1))
		} else {
			s.sections[i].SetItemsPerPage(0)
		}
	}
}

// navigateUp moves cursor up within the active section.
func (s *RunOverviewSidebar) navigateUp() {
	if !s.isValidActiveSection() {
		return
	}

	section := &s.sections[s.activeSection]
	section.Up()
}

// navigateDown moves cursor down within the active section.
func (s *RunOverviewSidebar) navigateDown() {
	if !s.isValidActiveSection() {
		return
	}

	section := &s.sections[s.activeSection]
	section.Down()
}

// navigateSection jumps between sections, skipping empty ones.
func (s *RunOverviewSidebar) navigateSection(direction int) {
	if len(s.sections) == 0 {
		return
	}

	prev := s.activeSection
	idx := prev

	// Try each section in the given direction.
	for range len(s.sections) {
		idx += direction
		if idx < 0 {
			idx = len(s.sections) - 1
		} else if idx >= len(s.sections) {
			idx = 0
		}

		// Select first non-empty section.
		if len(s.sections[idx].FilteredItems) > 0 {
			s.setActiveSection(idx)
			return
		}

		// Wrapped around to starting section.
		if idx == prev {
			break
		}
	}

	// No non-empty section found, keep current active.
	s.sections[prev].Active = true
}

// navigatePageUp changes page to previous within active section.
func (s *RunOverviewSidebar) navigatePageUp() {
	if !s.isValidActiveSection() {
		return
	}

	section := &s.sections[s.activeSection]
	section.PageUp()
}

// navigatePageDown changes page to next within active section.
func (s *RunOverviewSidebar) navigatePageDown() {
	if !s.isValidActiveSection() {
		return
	}

	section := &s.sections[s.activeSection]
	section.PageDown()
}

// selectFirstAvailableItem selects the first item in the first non-empty section.
func (s *RunOverviewSidebar) selectFirstAvailableItem() {
	// Find first non-empty section.
	for i := range s.sections {
		if len(s.sections[i].FilteredItems) > 0 && s.sections[i].ItemsPerPage() > 0 {
			s.setActiveSection(i)
			return
		}
	}

	// No non-empty section found, default to first section.
	s.setActiveSection(0)
}

// restoreSelection attempts to restore the previously selected item.
func (s *RunOverviewSidebar) restoreSelection(previousKey string) {
	// Try to find key-only match in current active section.
	if s.tryRestoreInSection(previousKey) {
		return
	}

	// Could not restore, select first available.
	s.selectFirstAvailableItem()
}

// tryRestoreInSection attempts to restore selection in a specific section.
//
// Returns true if successful.
func (s *RunOverviewSidebar) tryRestoreInSection(key string) bool {
	if s.activeSection < 0 || s.activeSection >= len(s.sections) {
		return false
	}

	section := &s.sections[s.activeSection]
	if section.ItemsPerPage() == 0 {
		return false
	}

	for i, item := range section.FilteredItems {
		keyMatch := item.Key == key

		if keyMatch {
			page := i / section.ItemsPerPage()
			line := i % section.ItemsPerPage()

			section.SetPageAndLine(page, line)
			return true
		}
	}

	return false
}

// setActiveSection changes the active section and resets navigation state.
func (s *RunOverviewSidebar) setActiveSection(idx int) {
	// Deactivate all sections.
	for i := range s.sections {
		s.sections[i].Active = false
	}

	// Activate target section.
	s.activeSection = idx
	if idx >= 0 && idx < len(s.sections) {
		s.sections[idx].Active = true
	}
}

// isValidActiveSection returns true if the active section index is valid.
func (s *RunOverviewSidebar) isValidActiveSection() bool {
	return s.activeSection >= 0 && s.activeSection < len(s.sections)
}
