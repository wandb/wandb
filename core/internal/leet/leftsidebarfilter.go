package leet

import (
	"fmt"
	"strings"
)

// StartFilter activates filter mode.
func (s *LeftSidebar) StartFilter() {
	s.filter.inputActive = true
	if s.filter.applied != "" {
		s.filter.draft = s.filter.applied
	} else {
		s.filter.draft = ""
	}
}

// UpdateFilter updates the filter query (for live preview).
func (s *LeftSidebar) UpdateFilter(query string) {
	s.filter.draft = query
	s.applyFilter()
	s.calculateSectionHeights()
}

// ConfirmFilter applies the filter (on Enter).
func (s *LeftSidebar) ConfirmFilter() {
	s.filter.applied = s.filter.draft
	s.filter.inputActive = false
	s.applyFilter()
	s.calculateSectionHeights()
}

// CancelFilter cancels the current filter input and restores the previous state.
func (s *LeftSidebar) CancelFilter() {
	s.filter.inputActive = false
	s.filter.draft = ""
	if s.filter.applied != "" {
		s.filter.draft = s.filter.applied
	} else {
		s.filter.draft = ""
	}
	s.applyFilter()
	s.calculateSectionHeights()
}

// IsFilterMode returns true if the sidebar is currently in filter input mode.
func (s *LeftSidebar) IsFilterMode() bool {
	return s.filter.inputActive
}

// FilterDraft returns the current filter input being typed.
func (s *LeftSidebar) FilterDraft() string {
	return s.filter.draft
}

// IsFiltering returns true if the sidebar has an applied filter.
func (s *LeftSidebar) IsFiltering() bool {
	return s.filter.applied != ""
}

// FilterQuery returns the current or applied filter query.
func (s *LeftSidebar) FilterQuery() string {
	if s.filter.applied != "" {
		return s.filter.applied
	}
	return s.filter.draft
}

// FilterInfo returns formatted filter information for status bar.
func (s *LeftSidebar) FilterInfo() string {
	if (!s.filter.inputActive && s.filter.applied == "") || (s.filter.draft == "" && s.filter.applied == "") {
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
	s.filter.inputActive = false
	s.filter.draft = ""
	s.filter.applied = ""

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
	query := s.filterQuery()
	sectionFilter := s.extractSectionFilter(&query)
	query = strings.ToLower(query)

	for i := range s.sections {
		s.filterSection(&s.sections[i], sectionFilter, query)
	}

	// Auto-focus section with most matches.
	if query != "" {
		s.focusBestMatchSection()
	}
}

// filterQuery returns the current active filter query.
func (s *LeftSidebar) filterQuery() string {
	query := strings.TrimSpace(s.filter.draft)
	if s.filter.applied != "" {
		query = strings.TrimSpace(s.filter.applied)
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
func (s *LeftSidebar) filterSection(sv *SectionView, filter, query string) {
	// Skip section if section filter doesn't match.
	if filter != "" {
		sectionName := strings.ToLower(sv.Title)
		if !strings.HasPrefix(sectionName, filter) {
			sv.FilteredItems = []KeyValuePair{}
			sv.FilterMatches = 0
			sv.CurrentPage = 0
			sv.CursorPos = 0
			return
		}
	}

	// Filter items based on query.
	filtered := make([]KeyValuePair, 0)
	for _, item := range sv.Items {
		if query == "" ||
			strings.Contains(strings.ToLower(item.Key), query) ||
			strings.Contains(strings.ToLower(item.Value), query) {
			filtered = append(filtered, item)
		}
	}

	sv.FilteredItems = filtered
	sv.FilterMatches = len(filtered)
	sv.CurrentPage = 0
	sv.CursorPos = 0
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
