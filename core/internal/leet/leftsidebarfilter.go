package leet

import (
	"fmt"
	"strings"
)

// StartFilter activates filter mode.
func (s *LeftSidebar) StartFilter() {
	s.filterMode = true
	if s.filterApplied && s.appliedQuery != "" {
		s.filterQuery = s.appliedQuery
	} else {
		s.filterQuery = ""
	}
}

// UpdateFilter updates the filter query (for live preview).
func (s *LeftSidebar) UpdateFilter(query string) {
	s.filterQuery = query
	s.applyFilter()
	s.calculateSectionHeights()
}

// ConfirmFilter applies the filter (on Enter).
func (s *LeftSidebar) ConfirmFilter() {
	s.filterApplied = true
	s.appliedQuery = s.filterQuery
	s.filterMode = false
	s.applyFilter()
	s.calculateSectionHeights()
}

// CancelFilter cancels the current filter input and restores the previous state.
func (s *LeftSidebar) CancelFilter() {
	s.filterMode = false
	s.filterQuery = ""
	if s.filterApplied && s.appliedQuery != "" {
		s.filterQuery = s.appliedQuery
		s.applyFilter()
		s.calculateSectionHeights()
	} else {
		s.filterQuery = ""
		s.applyFilter()
		s.calculateSectionHeights()
	}
}

// IsFilterMode returns true if the sidebar is currently in filter input mode.
func (s *LeftSidebar) IsFilterMode() bool {
	return s.filterMode
}

// GetFilterInput returns the current filter input being typed.
func (s *LeftSidebar) GetFilterInput() string {
	return s.filterQuery
}

// IsFiltering returns true if the sidebar has an applied filter.
func (s *LeftSidebar) IsFiltering() bool {
	return s.filterApplied
}

// GetFilterQuery returns the current or applied filter query.
func (s *LeftSidebar) GetFilterQuery() string {
	if s.filterApplied {
		return s.appliedQuery
	}
	return s.filterQuery
}

// GetFilterInfo returns formatted filter information for status bar.
func (s *LeftSidebar) GetFilterInfo() string {
	if (!s.filterMode && !s.filterApplied) || (s.filterQuery == "" && s.appliedQuery == "") {
		return ""
	}

	totalMatches := 0
	var matchInfo []string

	for _, section := range s.sections {
		if section.FilterMatches > 0 {
			totalMatches += section.FilterMatches
			matchInfo = append(matchInfo,
				fmt.Sprintf("@%s: %d", strings.ToLower(section.Title)[:1], section.FilterMatches))
		}
	}

	if len(matchInfo) == 0 {
		return "no matches"
	}

	return strings.Join(matchInfo, ", ")
}

// clearFilter clears the active filter.
func (s *LeftSidebar) clearFilter() {
	s.filterMode = false
	s.filterApplied = false
	s.filterQuery = ""
	s.appliedQuery = ""

	for i := range s.sections {
		s.sections[i].FilteredItems = s.sections[i].Items
		s.sections[i].CurrentPage = 0
		s.sections[i].CursorPos = 0
		s.sections[i].FilterMatches = 0
	}

	s.calculateSectionHeights()
}

// applyFilter filters items based on current filter query.
func (s *LeftSidebar) applyFilter() {
	query := s.getActiveFilterQuery()
	sectionFilter := s.extractSectionFilter(&query)
	query = strings.ToLower(query)

	for i := range s.sections {
		s.filterSection(i, sectionFilter, query)
	}

	// Auto-focus section with most matches.
	if query != "" {
		s.focusBestMatchSection()
	}
}

// getActiveFilterQuery returns the current active filter query.
func (s *LeftSidebar) getActiveFilterQuery() string {
	query := strings.TrimSpace(s.filterQuery)
	if s.filterApplied {
		query = strings.TrimSpace(s.appliedQuery)
	}
	return query
}

// extractSectionFilter extracts and removes section prefix from query.
func (s *LeftSidebar) extractSectionFilter(query *string) string {
	sectionFilter := ""
	switch {
	case strings.HasPrefix(*query, "@e "):
		sectionFilter = "environment"
		*query = strings.TrimPrefix(*query, "@e ")
	case strings.HasPrefix(*query, "@c "):
		sectionFilter = "config"
		*query = strings.TrimPrefix(*query, "@c ")
	case strings.HasPrefix(*query, "@s "):
		sectionFilter = "summary"
		*query = strings.TrimPrefix(*query, "@s ")
	}
	return sectionFilter
}

// filterSection filters a single section based on the query and section filter.
func (s *LeftSidebar) filterSection(idx int, sectionFilter, query string) {
	section := &s.sections[idx]

	// Skip section if section filter doesn't match.
	if sectionFilter != "" {
		sectionName := strings.ToLower(section.Title)
		if !strings.HasPrefix(sectionName, sectionFilter) {
			section.FilteredItems = []KeyValuePair{}
			section.FilterMatches = 0
			section.CurrentPage = 0
			section.CursorPos = 0
			return
		}
	}

	// Filter items based on query.
	filtered := make([]KeyValuePair, 0)
	for _, item := range section.Items {
		if query == "" ||
			strings.Contains(strings.ToLower(item.Key), query) ||
			strings.Contains(strings.ToLower(item.Value), query) {
			filtered = append(filtered, item)
		}
	}

	section.FilteredItems = filtered
	section.FilterMatches = len(filtered)
	section.CurrentPage = 0
	section.CursorPos = 0
}

// focusBestMatchSection focuses the section with the most filter matches.
func (s *LeftSidebar) focusBestMatchSection() {
	maxMatches := 0
	bestSection := s.activeSection

	for i, section := range s.sections {
		if section.FilterMatches > maxMatches {
			maxMatches = section.FilterMatches
			bestSection = i
		}
	}

	if maxMatches > 0 {
		s.activeSection = bestSection
		for i := range s.sections {
			s.sections[i].Active = i == s.activeSection
		}
	}
}
