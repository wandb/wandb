//go:build !wandb_core

package leet

import (
	"fmt"
	"sort"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// SidebarState represents the state of the sidebar
type SidebarState int

const (
	SidebarCollapsed SidebarState = iota
	SidebarExpanded
	SidebarCollapsing
	SidebarExpanding
)

// KeyValuePair represents a single key-value item to display.
type KeyValuePair struct {
	Key   string
	Value string
	Path  []string // Full path for nested items
}

// SectionView represents a paginated section in the overview.
type SectionView struct {
	Title         string
	Items         []KeyValuePair
	FilteredItems []KeyValuePair
	CurrentPage   int
	ItemsPerPage  int
	CursorPos     int // Position within current page
	Height        int // Total allocated height for this section (including title)
	Active        bool
	FilterMatches int
}

// RunOverview contains the run information to display.
type RunOverview struct {
	RunPath     string
	Project     string
	ID          string
	DisplayName string
	Config      map[string]any
	Summary     map[string]any
	Environment map[string]any
}

// Sidebar represents a collapsible sidebar panel.
type Sidebar struct {
	state          SidebarState
	currentWidth   int
	targetWidth    int
	expandedWidth  int
	animationStep  int
	animationTimer time.Time
	runOverview    RunOverview

	// Section management - reordered: Environment, Config, Summary.
	sections      []SectionView
	activeSection int

	// Filter state
	filterActive  bool
	filterQuery   string
	filterApplied bool   // Whether filter is applied (after Enter)
	appliedQuery  string // The query that was applied
	filterSection string // "@e", "@c", "@s", or ""

	// Dimensions
	height int

	// Run state (moved from model)
	runState RunState
}

func NewSidebar() *Sidebar {
	return &Sidebar{
		state:         SidebarCollapsed,
		currentWidth:  0,
		targetWidth:   0,
		expandedWidth: SidebarMinWidth,
		sections: []SectionView{
			{Title: "Environment", ItemsPerPage: 10, Active: true}, // First now
			{Title: "Config", ItemsPerPage: 15},
			{Title: "Summary", ItemsPerPage: 20},
		},
		activeSection: 0,
		runState:      RunStateRunning,
	}
}

// SetRunState sets the run state for display
func (s *Sidebar) SetRunState(state RunState) {
	s.runState = state
}

// flattenMap converts nested maps to flat key-value pairs
func flattenMap(data map[string]any, prefix string, result *[]KeyValuePair, path []string) {
	if data == nil {
		return
	}

	keys := make([]string, 0, len(data))
	for k := range data {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	for _, k := range keys {
		v := data[k]
		fullKey := k
		if prefix != "" {
			fullKey = prefix + "." + k
		}
		path := append(path, k)

		switch val := v.(type) {
		case map[string]any:
			flattenMap(val, fullKey, result, path)
		default:
			*result = append(*result, KeyValuePair{
				Key:   fullKey,
				Value: fmt.Sprintf("%v", v),
				Path:  path,
			})
		}
	}
}

// processEnvironment handles special processing for environment section.
func processEnvironment(data map[string]any) []KeyValuePair {
	if data == nil {
		return []KeyValuePair{}
	}

	// Get the first writer ID's data
	keys := make([]string, 0, len(data))
	for k := range data {
		keys = append(keys, k)
	}

	if len(keys) == 0 {
		return []KeyValuePair{}
	}

	sort.Strings(keys)
	firstKey := keys[0]

	// Get the value for the first key
	firstValue, ok := data[firstKey]
	if !ok {
		return []KeyValuePair{}
	}

	// If it's a map, flatten it
	if valueMap, ok := firstValue.(map[string]any); ok {
		result := make([]KeyValuePair, 0)
		flattenMap(valueMap, "", &result, []string{})
		return result
	}

	// Otherwise, return as is
	return []KeyValuePair{
		{Key: firstKey, Value: fmt.Sprintf("%v", firstValue), Path: []string{firstKey}},
	}
}

// updateSections updates section data from run overview.
func (s *Sidebar) updateSections() {
	// Preserve current selection state
	var currentKey, currentValue string
	if s.activeSection >= 0 && s.activeSection < len(s.sections) {
		currentKey, currentValue = s.GetSelectedItem()
	}

	// Update Environment section (index 0)
	envItems := processEnvironment(s.runOverview.Environment)
	s.sections[0].Items = envItems

	// Update Config section (index 1)
	configItems := make([]KeyValuePair, 0)
	flattenMap(s.runOverview.Config, "", &configItems, []string{})
	s.sections[1].Items = configItems

	// Update Summary section (index 2)
	summaryItems := make([]KeyValuePair, 0)
	flattenMap(s.runOverview.Summary, "", &summaryItems, []string{})
	s.sections[2].Items = summaryItems

	// Apply filter if active
	if s.filterActive || s.filterApplied {
		s.applyFilter()
	} else {
		// Use original items as filtered items
		for i := range s.sections {
			s.sections[i].FilteredItems = s.sections[i].Items
		}
	}

	// Calculate section heights
	s.calculateSectionHeights()

	// Restore selection or select first available if nothing was selected
	if currentKey == "" {
		// Only select first item if nothing was previously selected
		s.selectFirstAvailableItem()
	} else {
		// Try to restore previous selection
		s.restoreSelection(currentKey, currentValue)
	}
}

// restoreSelection attempts to restore the previously selected item
func (s *Sidebar) restoreSelection(previousKey, previousValue string) {
	// First try to find the exact same item in the current section
	if s.activeSection >= 0 && s.activeSection < len(s.sections) {
		section := &s.sections[s.activeSection]
		for i, item := range section.FilteredItems {
			if item.Key == previousKey && item.Value == previousValue {
				// Calculate which page this item is on
				page := i / section.ItemsPerPage
				posInPage := i % section.ItemsPerPage

				section.CurrentPage = page
				section.CursorPos = posInPage
				return
			}
		}

		// If exact item not found in current section, just try to find by key
		for i, item := range section.FilteredItems {
			if item.Key == previousKey {
				page := i / section.ItemsPerPage
				posInPage := i % section.ItemsPerPage

				section.CurrentPage = page
				section.CursorPos = posInPage
				return
			}
		}
	}

	// If we couldn't restore in the current section, try to find it in any section
	for sectionIdx, section := range s.sections {
		for i, item := range section.FilteredItems {
			if item.Key == previousKey {
				// Switch to this section
				s.sections[s.activeSection].Active = false
				s.activeSection = sectionIdx
				s.sections[sectionIdx].Active = true

				// Set position
				if section.ItemsPerPage > 0 {
					page := i / section.ItemsPerPage
					posInPage := i % section.ItemsPerPage

					section.CurrentPage = page
					section.CursorPos = posInPage
				}
				return
			}
		}
	}

	// If we still couldn't find it, keep current section/position if valid
	// or select first available item
	if s.activeSection >= 0 && s.activeSection < len(s.sections) {
		section := &s.sections[s.activeSection]
		if len(section.FilteredItems) == 0 || section.ItemsPerPage == 0 {
			// Current section is now empty, find first non-empty
			s.selectFirstAvailableItem()
		}
		// else keep current position (it's still valid)
	} else {
		s.selectFirstAvailableItem()
	}
}

// selectFirstAvailableItem selects the first item in the first non-empty section
// This should only be called when there's no previous selection to preserve
func (s *Sidebar) selectFirstAvailableItem() {
	// Find first non-empty section
	foundSection := false
	for i := range s.sections {
		if len(s.sections[i].FilteredItems) > 0 && s.sections[i].ItemsPerPage > 0 {
			// Deactivate all sections first
			for j := range s.sections {
				s.sections[j].Active = false
			}
			// Activate this section
			s.activeSection = i
			s.sections[i].Active = true
			s.sections[i].CurrentPage = 0
			s.sections[i].CursorPos = 0
			foundSection = true
			break
		}
	}

	// If no sections have items, set safe defaults
	if !foundSection {
		s.activeSection = 0
		for i := range s.sections {
			s.sections[i].Active = i == 0
			s.sections[i].CurrentPage = 0
			s.sections[i].CursorPos = 0
		}
	}
}

// applyFilter filters items based on current filter query.
func (s *Sidebar) applyFilter() {
	query := strings.TrimSpace(s.filterQuery)
	if s.filterApplied {
		query = strings.TrimSpace(s.appliedQuery)
	}

	// Parse section prefix
	sectionFilter := ""
	switch {
	case strings.HasPrefix(query, "@e "):
		sectionFilter = "environment"
		query = strings.TrimPrefix(query, "@e ")
	case strings.HasPrefix(query, "@c "):
		sectionFilter = "config"
		query = strings.TrimPrefix(query, "@c ")
	case strings.HasPrefix(query, "@s "):
		sectionFilter = "summary"
		query = strings.TrimPrefix(query, "@s ")
	}

	query = strings.ToLower(query)

	for i := range s.sections {
		section := &s.sections[i]

		// Skip sections not matching filter
		if sectionFilter != "" {
			sectionName := strings.ToLower(section.Title)
			if !strings.HasPrefix(sectionName, sectionFilter) {
				section.FilteredItems = []KeyValuePair{}
				section.FilterMatches = 0
				continue
			}
		}

		// Filter items
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

	// Auto-focus section with most matches
	if query != "" {
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
}

// calculateSectionHeights dynamically allocates heights to sections.
//
//gocyclo:ignore
func (s *Sidebar) calculateSectionHeights() {
	if s.height == 0 {
		return
	}

	// Reserve space for header
	headerLines := 7 // "Run Overview" (1 + 1 margin) + State + ID + Name + Project + 1 empty line before sections
	availableHeight := s.height - headerLines

	// Calculate how many sections have items
	activeSections := 0
	for i := range s.sections {
		if len(s.sections[i].FilteredItems) > 0 {
			activeSections++
		}
	}

	if activeSections == 0 {
		return
	}

	// Calculate available space for all sections
	// We need 1 line spacing between sections (activeSections - 1)
	spacingBetweenSections := 0
	if activeSections > 1 {
		spacingBetweenSections = activeSections - 1
	}

	totalAvailable := availableHeight - spacingBetweenSections
	if totalAvailable < activeSections*2 {
		// Not enough space, give minimum to each
		totalAvailable = activeSections * 2
	}

	// Distribute space proportionally
	envMax := 12 // Total lines including title
	configMax := 20
	summaryMax := 25

	// First pass: calculate desired heights
	totalDesired := 0
	desiredHeights := make([]int, len(s.sections))

	for i := range s.sections {
		section := &s.sections[i]
		itemCount := len(section.FilteredItems)

		if itemCount == 0 {
			section.Height = 0
			desiredHeights[i] = 0
			continue
		}

		var maxHeight int
		switch i {
		case 0: // Environment
			maxHeight = envMax
		case 1: // Config
			maxHeight = configMax
		case 2: // Summary
			maxHeight = summaryMax
		}

		// Calculate desired height (title + items)
		// We need at least 2 lines (title + 1 item)
		desired := min(itemCount+1, maxHeight) // +1 for title
		if desired < 2 {
			desired = 2
		}

		desiredHeights[i] = desired
		totalDesired += desired
	}

	// Second pass: scale down if necessary
	if totalDesired > totalAvailable {
		// Scale down proportionally
		scaleFactor := float64(totalAvailable) / float64(totalDesired)

		allocated := 0
		for i := range s.sections {
			if desiredHeights[i] > 0 {
				scaled := int(float64(desiredHeights[i]) * scaleFactor)
				if scaled < 2 && s.sections[i].FilteredItems != nil && len(s.sections[i].FilteredItems) > 0 {
					scaled = 2 // Minimum for non-empty sections
				}
				s.sections[i].Height = scaled
				allocated += scaled
			} else {
				s.sections[i].Height = 0
			}
		}

		// Distribute any remaining space to the largest section
		if allocated < totalAvailable {
			remainder := totalAvailable - allocated
			// Give remainder to Summary section if it has items
			switch {
			case len(s.sections[2].FilteredItems) > 0 && s.sections[2].Height > 0:
				s.sections[2].Height += remainder
			case len(s.sections[1].FilteredItems) > 0 && s.sections[1].Height > 0:
				s.sections[1].Height += remainder
			case len(s.sections[0].FilteredItems) > 0 && s.sections[0].Height > 0:
				s.sections[0].Height += remainder
			}
		}
	} else {
		// We have enough space, use desired heights
		for i := range s.sections {
			s.sections[i].Height = desiredHeights[i]
		}

		// Distribute extra space if available
		if totalDesired < totalAvailable {
			extraSpace := totalAvailable - totalDesired

			// Prioritize Summary, then Config, then Environment
			for i := 2; i >= 0 && extraSpace > 0; i-- {
				section := &s.sections[i]
				if section.Height > 0 {
					itemCount := len(section.FilteredItems)
					currentItems := section.Height - 1 // Subtract title

					if currentItems < itemCount {
						var maxHeight int
						switch i {
						case 0: // Environment
							maxHeight = envMax
						case 1: // Config
							maxHeight = configMax
						case 2: // Summary
							maxHeight = summaryMax
						}

						// How much more can this section take?
						maxIncrease := min(maxHeight-section.Height, itemCount+1-section.Height)
						increase := min(maxIncrease, extraSpace)

						section.Height += increase
						extraSpace -= increase
					}
				}
			}
		}
	}

	// Set items per page based on calculated height
	// ItemsPerPage is the number of data items we can show (excluding title)
	for i := range s.sections {
		if s.sections[i].Height > 0 {
			s.sections[i].ItemsPerPage = s.sections[i].Height - 1 // -1 for title
			if s.sections[i].ItemsPerPage < 1 {
				s.sections[i].ItemsPerPage = 1
			}
		} else {
			s.sections[i].ItemsPerPage = 0
		}
	}
}

// SetRunOverview sets the run overview information and triggers a content update
func (s *Sidebar) SetRunOverview(overview RunOverview) {
	s.runOverview = overview
	s.updateSections()
}

// UpdateDimensions updates the sidebar dimensions based on terminal width
func (s *Sidebar) UpdateDimensions(terminalWidth int, rightSidebarVisible bool) {
	var calculatedWidth int

	if rightSidebarVisible {
		calculatedWidth = int(float64(terminalWidth) * SidebarWidthRatioBoth)
	} else {
		calculatedWidth = int(float64(terminalWidth) * SidebarWidthRatio)
	}

	// Clamp to min/max
	switch {
	case calculatedWidth < SidebarMinWidth:
		s.expandedWidth = SidebarMinWidth
	case calculatedWidth > SidebarMaxWidth:
		s.expandedWidth = SidebarMaxWidth
	default:
		s.expandedWidth = calculatedWidth
	}

	if s.state == SidebarExpanded {
		s.targetWidth = s.expandedWidth
		s.currentWidth = s.expandedWidth
	}
}

// Toggle toggles the sidebar state between expanded and collapsed.
func (s *Sidebar) Toggle() {
	switch s.state {
	case SidebarCollapsed:
		s.state = SidebarExpanding
		s.targetWidth = s.expandedWidth
		s.animationStep = 0
		s.animationTimer = time.Now()
		// Ensure first available item is selected when opening
		s.selectFirstAvailableItem()
	case SidebarExpanded:
		s.state = SidebarCollapsing
		s.targetWidth = 0
		s.animationStep = 0
		s.animationTimer = time.Now()
	}
}

// navigateUp moves cursor up within the active section.
func (s *Sidebar) navigateUp() {
	if s.activeSection < 0 || s.activeSection >= len(s.sections) {
		return
	}

	section := &s.sections[s.activeSection]
	if section.CursorPos > 0 {
		section.CursorPos--
	} else if section.CurrentPage > 0 {
		// Move to previous page
		section.CurrentPage--
		section.CursorPos = section.ItemsPerPage - 1
	}
}

// navigateDown moves cursor down within the active section.
func (s *Sidebar) navigateDown() {
	if s.activeSection < 0 || s.activeSection >= len(s.sections) {
		return
	}

	section := &s.sections[s.activeSection]
	startIdx := section.CurrentPage * section.ItemsPerPage
	endIdx := min(startIdx+section.ItemsPerPage, len(section.FilteredItems))
	itemsOnPage := endIdx - startIdx

	if section.CursorPos < itemsOnPage-1 {
		section.CursorPos++
	} else if endIdx < len(section.FilteredItems) {
		// Move to next page
		section.CurrentPage++
		section.CursorPos = 0
	}
}

// navigateSection jumps between sections.
func (s *Sidebar) navigateSection(direction int) {
	// Find next non-empty section
	startSection := s.activeSection
	attempts := 0

	for attempts < len(s.sections) {
		newSection := s.activeSection + direction
		if newSection < 0 {
			newSection = len(s.sections) - 1
		} else if newSection >= len(s.sections) {
			newSection = 0
		}

		if len(s.sections[newSection].FilteredItems) > 0 {
			s.sections[s.activeSection].Active = false
			s.activeSection = newSection
			s.sections[s.activeSection].Active = true
			// Reset cursor to first item when switching sections
			s.sections[s.activeSection].CursorPos = 0
			break
		}

		// Update activeSection for next iteration
		s.activeSection = newSection
		attempts++

		// If we've cycled through all sections and found nothing, break
		if s.activeSection == startSection {
			break
		}
	}

	// If no non-empty sections found, stay on current
	if attempts == len(s.sections) {
		s.activeSection = startSection
	}
}

// navigatePage changes page within active section.
func (s *Sidebar) navigatePage(direction int) {
	if s.activeSection < 0 || s.activeSection >= len(s.sections) {
		return
	}

	section := &s.sections[s.activeSection]
	totalPages := (len(section.FilteredItems) + section.ItemsPerPage - 1) / section.ItemsPerPage

	if totalPages <= 1 {
		return
	}

	section.CurrentPage += direction
	if section.CurrentPage < 0 {
		section.CurrentPage = totalPages - 1
	} else if section.CurrentPage >= totalPages {
		section.CurrentPage = 0
	}

	// Reset cursor to first item of new page
	section.CursorPos = 0
}

// startFilter activates filter mode.
func (s *Sidebar) startFilter() {
	s.filterActive = true
	// If we have an applied filter, start with that value
	if s.filterApplied && s.appliedQuery != "" {
		s.filterQuery = s.appliedQuery
	} else {
		s.filterQuery = ""
	}
}

// updateFilter updates the filter query (for live preview).
func (s *Sidebar) updateFilter(query string) {
	s.filterQuery = query
	s.applyFilter()
	s.calculateSectionHeights()
}

// confirmFilter applies the filter (on Enter).
func (s *Sidebar) confirmFilter() {
	s.filterApplied = true
	s.appliedQuery = s.filterQuery
	s.filterActive = false
	// Need to reapply the filter with the confirmed query
	s.applyFilter()
	s.calculateSectionHeights()
}

// clearFilter clears the active filter.
func (s *Sidebar) clearFilter() {
	s.filterActive = false
	s.filterApplied = false
	s.filterQuery = ""
	s.appliedQuery = ""
	s.filterSection = ""

	// Restore original items
	for i := range s.sections {
		s.sections[i].FilteredItems = s.sections[i].Items
		s.sections[i].CurrentPage = 0
		s.sections[i].CursorPos = 0
		s.sections[i].FilterMatches = 0
	}

	s.calculateSectionHeights()
}

// GetSelectedItem returns the currently selected key-value pair.
func (s *Sidebar) GetSelectedItem() (key, value string) {
	if s.activeSection < 0 || s.activeSection >= len(s.sections) {
		return "", ""
	}

	section := &s.sections[s.activeSection]
	if len(section.FilteredItems) == 0 {
		return "", ""
	}

	startIdx := section.CurrentPage * section.ItemsPerPage
	itemIdx := startIdx + section.CursorPos

	if itemIdx >= 0 && itemIdx < len(section.FilteredItems) {
		item := section.FilteredItems[itemIdx]
		return item.Key, item.Value
	}

	return "", ""
}

// Update handles animation and input updates for the sidebar.
func (s *Sidebar) Update(msg tea.Msg) (*Sidebar, tea.Cmd) {
	var cmds []tea.Cmd

	// Handle key input only when expanded
	if s.state == SidebarExpanded {
		switch msg := msg.(type) {
		case tea.KeyMsg:
			switch msg.Type {
			case tea.KeyUp:
				s.navigateUp()
			case tea.KeyDown:
				s.navigateDown()
			case tea.KeyTab:
				// Tab to navigate between sections (vim-inspired alternative)
				s.navigateSection(1)
			case tea.KeyShiftTab:
				// Shift+Tab to go backwards
				s.navigateSection(-1)
			case tea.KeyLeft:
				s.navigatePage(-1)
			case tea.KeyRight:
				s.navigatePage(1)
			}
		default:
		}
	}

	// Handle animation
	if s.state == SidebarExpanding || s.state == SidebarCollapsing {
		elapsed := time.Since(s.animationTimer)
		progress := float64(elapsed) / float64(AnimationDuration)

		if progress >= 1.0 {
			s.currentWidth = s.targetWidth
			if s.state == SidebarExpanding {
				s.state = SidebarExpanded
			} else {
				s.state = SidebarCollapsed
			}
		} else {
			if s.state == SidebarExpanding {
				s.currentWidth = int(easeOutCubic(progress) * float64(s.expandedWidth))
			} else {
				s.currentWidth = int((1 - easeOutCubic(progress)) * float64(s.expandedWidth))
			}
			cmds = append(cmds, s.animationCmd())
		}
	}

	return s, tea.Batch(cmds...)
}

// truncateValue truncates long values for display.
func truncateValue(value string, maxWidth int) string {
	if lipgloss.Width(value) <= maxWidth {
		return value
	}
	if maxWidth <= 3 {
		return "..."
	}
	return value[:maxWidth-3] + "..."
}

// renderSection renders a single section.
func (s *Sidebar) renderSection(idx int, width int) string {
	section := &s.sections[idx]

	if len(section.FilteredItems) == 0 || section.Height == 0 {
		return ""
	}

	var lines []string

	// Section title with info
	titleStyle := sidebarSectionStyle
	if section.Active {
		titleStyle = titleStyle.Foreground(lipgloss.Color("230")).Bold(true)
	}

	totalItems := len(section.Items)
	filteredItems := len(section.FilteredItems)

	// Calculate page info
	startIdx := section.CurrentPage * section.ItemsPerPage
	endIdx := min(startIdx+section.ItemsPerPage, filteredItems)
	actualItemsToShow := endIdx - startIdx

	titleText := section.Title
	infoText := ""

	switch {
	case (s.filterActive || s.filterApplied) && filteredItems != totalItems:
		infoText = fmt.Sprintf(" [%d-%d of %d filtered from %d]",
			startIdx+1, endIdx, filteredItems, totalItems)
	case filteredItems > section.ItemsPerPage:
		infoText = fmt.Sprintf(" [%d-%d of %d]", startIdx+1, endIdx, filteredItems)
	case filteredItems > 0:
		infoText = fmt.Sprintf(" [%d items]", filteredItems)
	}

	lines = append(lines, titleStyle.Render(titleText)+
		lipgloss.NewStyle().Foreground(lipgloss.Color("240")).Render(infoText))

	// Render items - no colon, increased key width
	maxKeyWidth := (width * 2) / 5           // 40% for keys
	maxValueWidth := width - maxKeyWidth - 1 // Account for space between

	// Only render as many items as we have space for
	itemsToRender := min(actualItemsToShow, section.ItemsPerPage)

	for i := 0; i < itemsToRender; i++ {
		itemIdx := startIdx + i
		if itemIdx >= len(section.FilteredItems) {
			break
		}

		item := section.FilteredItems[itemIdx]

		keyStyle := sidebarKeyStyle
		valueStyle := sidebarValueStyle

		// Highlight cursor position if section is active
		if section.Active && i == section.CursorPos {
			keyStyle = keyStyle.Background(lipgloss.Color("237"))
			valueStyle = valueStyle.Background(lipgloss.Color("237"))
		}

		key := truncateValue(item.Key, maxKeyWidth)
		value := truncateValue(item.Value, maxValueWidth)

		// Render without colon
		line := fmt.Sprintf("%s %s",
			keyStyle.Width(maxKeyWidth).Render(key),
			valueStyle.Render(value))
		lines = append(lines, line)
	}

	return strings.Join(lines, "\n")
}

// View renders the sidebar - optimized spacing.
func (s *Sidebar) View(height int) string {
	if s.currentWidth <= 0 {
		return ""
	}

	s.height = height
	s.calculateSectionHeights()

	// Build header
	var lines []string
	lines = append(lines, sidebarHeaderStyle.Render("Run Overview"))

	// Add run state first
	stateText := "State: "
	switch s.runState {
	case RunStateRunning:
		stateText += "Running"
	case RunStateFinished:
		stateText += "Finished"
	case RunStateFailed:
		stateText += "Failed"
	case RunStateCrashed:
		stateText += "Error"
	}
	lines = append(lines, sidebarKeyStyle.Render("State: ")+
		sidebarValueStyle.Render(strings.TrimPrefix(stateText, "State: ")))

	if s.runOverview.ID != "" {
		lines = append(lines, sidebarKeyStyle.Render("ID: ")+
			sidebarValueStyle.Render(s.runOverview.ID))
	}
	if s.runOverview.DisplayName != "" {
		lines = append(lines, sidebarKeyStyle.Render("Name: ")+
			sidebarValueStyle.Render(s.runOverview.DisplayName))
	}
	if s.runOverview.Project != "" {
		lines = append(lines, sidebarKeyStyle.Render("Project: ")+
			sidebarValueStyle.Render(s.runOverview.Project))
	}

	// Single empty line before sections
	lines = append(lines, "")

	// Render sections
	contentWidth := s.currentWidth - 4 // Account for padding and border
	for i := range s.sections {
		if s.sections[i].Height == 0 {
			continue
		}

		sectionContent := s.renderSection(i, contentWidth)
		if sectionContent != "" {
			lines = append(lines, sectionContent)
			// Only add spacing between sections if not the last one
			if i < len(s.sections)-1 {
				// Check if next section has content
				hasNextContent := false
				for j := i + 1; j < len(s.sections); j++ {
					if s.sections[j].Height > 0 {
						hasNextContent = true
						break
					}
				}
				if hasNextContent {
					lines = append(lines, "") // Add spacing between sections
				}
			}
		}
	}

	content := strings.Join(lines, "\n")

	// Apply styles - ensure exact height
	styledContent := sidebarStyle.
		Width(s.currentWidth - 1).
		Height(height).
		MaxWidth(s.currentWidth - 1).
		MaxHeight(height).
		Render(content)

	// Apply border
	bordered := sidebarBorderStyle.
		Width(s.currentWidth).
		Height(height).
		MaxWidth(s.currentWidth).
		MaxHeight(height).
		Render(styledContent)

	return bordered
}

// Width returns the current width of the sidebar.
func (s *Sidebar) Width() int {
	return s.currentWidth
}

// IsVisible returns true if the sidebar is visible.
func (s *Sidebar) IsVisible() bool {
	return s.state != SidebarCollapsed
}

// IsAnimating returns true if the sidebar is currently animating.
func (s *Sidebar) IsAnimating() bool {
	return s.state == SidebarExpanding || s.state == SidebarCollapsing
}

// animationCmd returns a command to continue the animation.
func (s *Sidebar) animationCmd() tea.Cmd {
	return tea.Tick(time.Millisecond*16, func(t time.Time) tea.Msg {
		return SidebarAnimationMsg{}
	})
}

// IsFiltering returns true if the sidebar is in filter mode or has an applied filter.
func (s *Sidebar) IsFiltering() bool {
	return s.filterActive || s.filterApplied
}

// GetFilterQuery returns the current or applied filter query.
func (s *Sidebar) GetFilterQuery() string {
	if s.filterApplied {
		return s.appliedQuery
	}
	return s.filterQuery
}

// GetFilterInfo returns formatted filter information for status bar.
func (s *Sidebar) GetFilterInfo() string {
	if (!s.filterActive && !s.filterApplied) || (s.filterQuery == "" && s.appliedQuery == "") {
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

// easeOutCubic provides smooth deceleration for animations.
func easeOutCubic(t float64) float64 {
	t--
	return t*t*t + 1
}

// SidebarAnimationMsg is sent during sidebar animations.
type SidebarAnimationMsg struct{}
