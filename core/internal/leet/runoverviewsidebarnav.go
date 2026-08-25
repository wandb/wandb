package leet

const (
	// Each section's default share of the sidebar's vertical space when
	// the sections want more rows than fit. The shares sum to 1, so a
	// value reads directly as that section's slice of the area, in the
	// same unit as the dragged overview_* fractions.
	sectionWeightEnvironment = 0.20
	sectionWeightConfig      = 0.35
	sectionWeightSummary     = 0.45

	// Minimum section height when visible (title + 1 item).
	sectionMinHeight = 2
)

// sectionWeights returns each visible section's share of the section area:
// the user-dragged fraction where set, otherwise the built-in default.
// proportionalShares normalizes the weights, so dragged sections keep their
// exact shares while all of them are set and every section degrades
// proportionally when the data changes underneath.
func (s *RunOverviewSidebar) sectionWeights(needs []int) []float64 {
	defaults := []float64{
		sectionWeightEnvironment,
		sectionWeightConfig,
		sectionWeightSummary,
	}

	var o LayoutOverrides
	if s.overridesSource != nil {
		o = s.overridesSource()
	}
	fracs := o.overviewFractions()

	weights := make([]float64, len(needs))
	for i, need := range needs {
		if need <= 0 {
			continue
		}
		if fracs[i] > 0 {
			weights[i] = fracs[i]
		} else {
			weights[i] = defaults[i]
		}
	}
	return weights
}

// sectionNeeds returns the rows each section can usefully fill (title +
// items), 0 for empty sections.
func (s *RunOverviewSidebar) sectionNeeds() []int {
	needs := make([]int, len(s.sections))
	for i := range s.sections {
		if itemCount := len(s.sections[i].FilteredItems); itemCount > 0 {
			needs[i] = itemCount + 1 // Title line.
		}
	}
	return needs
}

// updateSectionHeights divides the sidebar rows below the header among the
// sections and re-derives every section's page size from its height.
func (s *RunOverviewSidebar) updateSectionHeights() {
	if s.height == 0 {
		return
	}

	needs := s.sectionNeeds()
	heights := flexSectionHeights(s.sectionsArea(needs), s.sectionWeights(needs), needs)
	for i := range s.sections {
		s.sections[i].Height = heights[i]
	}

	s.updateItemsPerPage()
}

// sectionsArea returns the rows available to sections: the sidebar height
// minus the header block and one spacing row between adjacent sections.
func (s *RunOverviewSidebar) sectionsArea(needs []int) int {
	visible := 0
	for _, need := range needs {
		if need > 0 {
			visible++
		}
	}
	return s.height - s.headerLineCount() - max(visible-1, 0)
}

// flexSectionHeights divides area rows among sections proportionally to
// weights. Sections with need 0 are hidden and get no rows. A visible
// section is capped at its need (title + items) so surplus rows go to
// sections that can still grow, and floored at sectionMinHeight so it stays
// usable when squeezed. When even the minimums do not fit, the total
// overflows area and the renderer crops it (tiny-terminal degradation).
func flexSectionHeights(area int, weights []float64, needs []int) []int {
	heights := make([]int, len(needs))
	active := make([]int, 0, len(needs))
	for i, need := range needs {
		if need > 0 {
			active = append(active, i)
		}
	}

	remaining := area
	for len(active) > 0 {
		shares := proportionalShares(active, weights, remaining)

		// Sections offered more rows than their items can fill keep only
		// their need; the surplus re-divides among the rest next pass.
		if next := settleSections(active, heights, &remaining, func(k, i int) (int, bool) {
			return needs[i], shares[k] >= float64(needs[i])
		}); len(next) < len(active) {
			active = next
			continue
		}

		// Sections offered fewer rows than the minimum take the minimum
		// anyway; the deficit comes out of the rest next pass.
		if next := settleSections(active, heights, &remaining, func(k, i int) (int, bool) {
			return min(sectionMinHeight, needs[i]), shares[k] < sectionMinHeight
		}); len(next) < len(active) {
			active = next
			continue
		}

		// Steady state: every share fits between its minimum and its need.
		roundShares(active, shares, heights, remaining)
		break
	}

	return heights
}

// proportionalShares splits remaining rows across the active sections in
// proportion to their weights (evenly, if the weights sum to zero).
func proportionalShares(active []int, weights []float64, remaining int) []float64 {
	var weightSum float64
	for _, i := range active {
		weightSum += weights[i]
	}

	shares := make([]float64, len(active))
	for k, i := range active {
		if weightSum > 0 {
			shares[k] = float64(remaining) * weights[i] / weightSum
		} else {
			shares[k] = float64(remaining) / float64(len(active))
		}
	}
	return shares
}

// settleSections assigns a final height to each active section that decide
// settles and returns the still-active rest.
func settleSections(
	active []int,
	heights []int,
	remaining *int,
	decide func(k, i int) (int, bool),
) []int {
	rest := make([]int, 0, len(active))
	for k, i := range active {
		if h, settled := decide(k, i); settled {
			heights[i] = h
			*remaining -= h
		} else {
			rest = append(rest, i)
		}
	}
	return rest
}

// roundShares converts fractional shares to whole rows, handing the leftover
// rows to the largest fractional remainders (ties to the earlier section).
func roundShares(active []int, shares []float64, heights []int, remaining int) {
	leftover := remaining
	fracs := make([]float64, len(active))
	for k, i := range active {
		heights[i] = int(shares[k])
		fracs[k] = shares[k] - float64(heights[i])
		leftover -= heights[i]
	}

	for ; leftover > 0; leftover-- {
		best := 0
		for k := range fracs {
			if fracs[k] > fracs[best] {
				best = k
			}
		}
		heights[active[best]]++
		fracs[best] = -1
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

// navigateHome jumps to the first item of the active section.
func (s *RunOverviewSidebar) navigateHome() {
	if !s.isValidActiveSection() {
		return
	}

	section := &s.sections[s.activeSection]
	section.Home()
}

// navigateEnd jumps to the last item of the active section.
func (s *RunOverviewSidebar) navigateEnd() {
	if !s.isValidActiveSection() {
		return
	}

	section := &s.sections[s.activeSection]
	section.End()
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

// deactivateAllSections marks all sections as inactive, removing row highlights.
func (s *RunOverviewSidebar) deactivateAllSections() {
	for i := range s.sections {
		s.sections[i].Active = false
	}
}

// hasActiveSection reports whether any section is currently active.
func (s *RunOverviewSidebar) hasActiveSection() bool {
	for i := range s.sections {
		if s.sections[i].Active {
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
