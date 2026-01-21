package leet

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
)

// EnterFilterMode activates filter mode (draft initialized from applied).
func (s *LeftSidebar) EnterFilterMode() {
	s.filter.Activate()
}

// UpdateFilterDraft updates the in‑progress filter text (for live preview).
func (s *LeftSidebar) UpdateFilterDraft(msg tea.KeyMsg) {
	s.filter.UpdateDraft(msg)
}

// ExitFilterMode exits filter input mode and optionally applies the filter.
func (s *LeftSidebar) ExitFilterMode(apply bool) {
	if apply {
		s.filter.Commit()
	} else {
		s.filter.Cancel()
	}
	s.ApplyFilter()
	s.updateSectionHeights()
}

// ClearFilter removes any applied/draft filter and restores all items.
func (s *LeftSidebar) ClearFilter() {
	s.filter.Clear()
	s.ApplyFilter()
	s.updateSectionHeights()
}

// ToggleFilterMatchMode flips regex <-> glob and reapplies the live preview.
func (s *LeftSidebar) ToggleFilterMatchMode() {
	s.filter.ToggleMode()
	s.ApplyFilter()
	s.updateSectionHeights()
}

// IsFilterMode reports whether we are currently typing a filter.
func (s *LeftSidebar) IsFilterMode() bool {
	return s.filter.IsActive()
}

// FilterMode exposes the current filter match mode.
func (s *LeftSidebar) FilterMode() FilterMatchMode {
	return s.filter.Mode()
}

// FilterQuery returns the currently effective query (applied if set, else draft).
func (s *LeftSidebar) FilterQuery() string {
	return s.filter.Query()
}

// IsFiltering returns true if an applied (non‑empty) filter exists.
func (s *LeftSidebar) IsFiltering() bool {
	return s.filter.Query() != ""
}

// ApplyFilter recomputes FilteredItems for each section based on the current matcher.
// Also auto‑focuses the section with most matches while the query is non‑empty.
func (s *LeftSidebar) ApplyFilter() {
	matcher := s.filter.Matcher()

	for i := range s.sections {
		items := s.sections[i].Items
		// fresh slice so there's no aliasing with Items
		filtered := make([]KeyValuePair, 0, len(items))
		for _, it := range items {
			// Match on either key or value.
			if matcher(it.Key) || matcher(it.Value) {
				filtered = append(filtered, it)
			}
		}
		s.sections[i].FilteredItems = filtered
		s.sections[i].Home()
	}

	// While query is non‑empty (draft or applied), drive focus to the best section.
	if s.filter.Query() != "" {
		s.focusBestMatchSection()
	}
}

// focusBestMatchSection focuses the section that has the most filter matches.
// Ties are resolved by keeping the current active section.
// No-ops if no section has matches.
func (s *LeftSidebar) focusBestMatchSection() {
	best := s.activeSection
	maximum := 0

	for i := range s.sections {
		if m := len(s.sections[i].FilteredItems); m > maximum {
			maximum = m
			best = i
		}
	}

	if maximum == 0 || best == s.activeSection {
		return
	}
	s.setActiveSection(best) // centralizes deactivation + cursor/page reset
}

// FilterInfo returns a compact, human‑readable per‑section match summary for the status bar.
func (s *LeftSidebar) FilterInfo() string {
	// Only show during input or with an active filter.
	if !s.IsFilterMode() && s.FilterQuery() == "" {
		return ""
	}

	var parts []string
	for _, sec := range s.sections {
		filterMatches := len(sec.FilteredItems)
		if filterMatches == 0 {
			continue
		}

		title := sec.Title
		if title == "Environment" {
			title = "Env"
		}
		parts = append(parts, fmt.Sprintf("%s: %d", title, filterMatches))
	}
	if len(parts) == 0 {
		return "no matches"
	}
	return strings.Join(parts, ", ")
}
