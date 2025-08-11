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

// KeyValuePair represents a single key-value item to display
type KeyValuePair struct {
	Key   string
	Value string
	Path  []string // Full path for nested items
}

// SectionView represents a paginated section in the overview
type SectionView struct {
	Title         string
	Items         []KeyValuePair
	FilteredItems []KeyValuePair
	CurrentPage   int
	ItemsPerPage  int
	CursorPos     int // Position within current page
	Height        int // Allocated height for this section
	Active        bool
	FilterMatches int
}

// RunOverview contains the run information to display
type RunOverview struct {
	RunPath     string
	Project     string
	ID          string
	DisplayName string
	Config      map[string]any
	Summary     map[string]any
	Environment map[string]any
}

// Sidebar represents a collapsible sidebar panel
type Sidebar struct {
	state          SidebarState
	currentWidth   int
	targetWidth    int
	expandedWidth  int
	animationStep  int
	animationTimer time.Time
	runOverview    RunOverview

	// Section management - reordered: Environment, Config, Summary
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

// NewSidebar creates a new sidebar instance
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
		newPath := append(path, k)

		switch val := v.(type) {
		case map[string]any:
			flattenMap(val, fullKey, result, newPath)
		default:
			*result = append(*result, KeyValuePair{
				Key:   fullKey,
				Value: fmt.Sprintf("%v", v),
				Path:  newPath,
			})
		}
	}
}

// processEnvironment handles special processing for environment section
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

// updateSections updates section data from run overview
func (s *Sidebar) updateSections() {
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
			s.sections[i].CurrentPage = 0
			s.sections[i].CursorPos = 0
		}
	}

	// Calculate section heights
	s.calculateSectionHeights()
}

// applyFilter filters items based on current filter query
func (s *Sidebar) applyFilter() {
	query := strings.TrimSpace(s.filterQuery)
	if s.filterApplied {
		query = strings.TrimSpace(s.appliedQuery)
	}

	// Parse section prefix
	sectionFilter := ""
	if strings.HasPrefix(query, "@e ") {
		sectionFilter = "environment"
		query = strings.TrimPrefix(query, "@e ")
	} else if strings.HasPrefix(query, "@c ") {
		sectionFilter = "config"
		query = strings.TrimPrefix(query, "@c ")
	} else if strings.HasPrefix(query, "@s ") {
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

// calculateSectionHeights dynamically allocates heights to sections
func (s *Sidebar) calculateSectionHeights() {
	if s.height == 0 {
		return
	}

	// Reserve space for header - further reduced
	headerLines := 6                              // "Run Overview" (1 + 1 margin) + State + ID + Name + Project
	availableHeight := s.height - headerLines - 1 // -1 to ensure no overflow

	// Calculate heights for each section
	totalSections := 0
	for i := range s.sections {
		if len(s.sections[i].FilteredItems) > 0 {
			totalSections++
		}
	}

	if totalSections == 0 {
		return
	}

	// Overhead per section (title + minimal spacing)
	sectionOverhead := 2 // title line + 1 spacing
	availableForContent := availableHeight - (totalSections * sectionOverhead)

	if availableForContent < totalSections*3 {
		// Minimum viable space
		availableForContent = totalSections * 3
	}

	// Distribute space proportionally - increased limits to use more vertical space
	envMax := 12
	configMax := 20
	summaryMax := 25

	// First pass: allocate based on actual item counts
	totalDesired := 0
	for i := range s.sections {
		section := &s.sections[i]
		itemCount := len(section.FilteredItems)

		if itemCount == 0 {
			section.Height = 0
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

		section.Height = min(itemCount, maxHeight)
		totalDesired += section.Height
	}

	// Second pass: if we have extra space, distribute it proportionally
	if totalDesired < availableForContent {
		extraSpace := availableForContent - totalDesired

		for i := range s.sections {
			section := &s.sections[i]
			if section.Height > 0 && len(section.FilteredItems) > section.Height {
				// This section has more items to show
				var maxHeight int
				switch i {
				case 0: // Environment
					maxHeight = envMax
				case 1: // Config
					maxHeight = configMax
				case 2: // Summary
					maxHeight = summaryMax
				}

				// Give this section a proportional share of extra space
				proportion := float64(section.Height) / float64(totalDesired)
				extraForSection := int(float64(extraSpace) * proportion)

				newHeight := min(section.Height+extraForSection, len(section.FilteredItems))
				newHeight = min(newHeight, maxHeight)
				section.Height = newHeight
			}
		}
	}

	// Set items per page based on calculated height
	for i := range s.sections {
		s.sections[i].ItemsPerPage = s.sections[i].Height
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

// Toggle toggles the sidebar state between expanded and collapsed
func (s *Sidebar) Toggle() {
	switch s.state {
	case SidebarCollapsed:
		s.state = SidebarExpanding
		s.targetWidth = s.expandedWidth
		s.animationStep = 0
		s.animationTimer = time.Now()
	case SidebarExpanded:
		s.state = SidebarCollapsing
		s.targetWidth = 0
		s.animationStep = 0
		s.animationTimer = time.Now()
	}
}

// navigateUp moves cursor up within the active section
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

// navigateDown moves cursor down within the active section
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

// navigateSection jumps between sections
func (s *Sidebar) navigateSection(direction int) {
	// Find next non-empty section
	for i := 0; i < len(s.sections); i++ {
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
			break
		}
	}
}

// navigatePage changes page within active section
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

// startFilter activates filter mode
func (s *Sidebar) startFilter() {
	s.filterActive = true
	// If we have an applied filter, start with that value
	if s.filterApplied && s.appliedQuery != "" {
		s.filterQuery = s.appliedQuery
	} else {
		s.filterQuery = ""
	}
}

// updateFilter updates the filter query (for live preview)
func (s *Sidebar) updateFilter(query string) {
	s.filterQuery = query
	s.applyFilter()
	s.calculateSectionHeights()
}

// confirmFilter applies the filter (on Enter)
func (s *Sidebar) confirmFilter() {
	s.filterApplied = true
	s.appliedQuery = s.filterQuery // This line was already correct
	s.filterActive = false
	// Need to reapply the filter with the confirmed query
	s.applyFilter()
	s.calculateSectionHeights()
}

// clearFilter clears the active filter
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

// GetSelectedItem returns the currently selected key-value pair
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

// Update handles animation and input updates for the sidebar
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

// truncateValue truncates long values for display
func truncateValue(value string, maxWidth int) string {
	if lipgloss.Width(value) <= maxWidth {
		return value
	}
	if maxWidth <= 3 {
		return "..."
	}
	return value[:maxWidth-3] + "..."
}

// renderSection renders a single section
func (s *Sidebar) renderSection(idx int, width int) string {
	section := &s.sections[idx]

	if len(section.FilteredItems) == 0 {
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

	titleText := section.Title
	infoText := ""

	if (s.filterActive || s.filterApplied) && filteredItems != totalItems {
		infoText = fmt.Sprintf(" [%d-%d of %d filtered from %d]",
			startIdx+1, endIdx, filteredItems, totalItems)
	} else if filteredItems > section.ItemsPerPage {
		infoText = fmt.Sprintf(" [%d-%d of %d]", startIdx+1, endIdx, filteredItems)
	} else if filteredItems > 0 {
		infoText = fmt.Sprintf(" [%d items]", filteredItems)
	}

	lines = append(lines, titleStyle.Render(titleText)+
		lipgloss.NewStyle().Foreground(lipgloss.Color("240")).Render(infoText))

	// Render items - no colon, increased key width
	maxKeyWidth := (width * 2) / 5           // 40% for keys
	maxValueWidth := width - maxKeyWidth - 1 // Account for space between

	for i := startIdx; i < endIdx && i < len(section.FilteredItems); i++ {
		item := section.FilteredItems[i]

		keyStyle := sidebarKeyStyle
		valueStyle := sidebarValueStyle

		// Highlight cursor position if section is active
		if section.Active && i-startIdx == section.CursorPos {
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

// View renders the sidebar - optimized spacing
func (s *Sidebar) View(height int) string {
	if s.currentWidth <= 0 {
		return ""
	}

	s.height = height
	s.calculateSectionHeights()

	// Build header
	var lines []string

	// Add "Run Overview" title with no left padding and margin below
	titleStyle := lipgloss.NewStyle().
		Bold(true).
		Foreground(lipgloss.Color("230")).
		MarginBottom(1)
	lines = append(lines, titleStyle.Render("Run Overview"))

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
		sectionContent := s.renderSection(i, contentWidth)
		if sectionContent != "" {
			lines = append(lines, sectionContent)
			// Only add spacing between sections if not the last one
			if i < len(s.sections)-1 {
				// Check if next section has content
				hasNextContent := false
				for j := i + 1; j < len(s.sections); j++ {
					if len(s.sections[j].FilteredItems) > 0 {
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

// Width returns the current width of the sidebar
func (s *Sidebar) Width() int {
	return s.currentWidth
}

// IsVisible returns true if the sidebar is visible
func (s *Sidebar) IsVisible() bool {
	return s.state != SidebarCollapsed
}

// IsAnimating returns true if the sidebar is currently animating
func (s *Sidebar) IsAnimating() bool {
	return s.state == SidebarExpanding || s.state == SidebarCollapsing
}

// animationCmd returns a command to continue the animation
func (s *Sidebar) animationCmd() tea.Cmd {
	return tea.Tick(time.Millisecond*16, func(t time.Time) tea.Msg {
		return SidebarAnimationMsg{}
	})
}

// IsFiltering returns true if the sidebar is in filter mode or has an applied filter
func (s *Sidebar) IsFiltering() bool {
	return s.filterActive || s.filterApplied
}

// GetFilterQuery returns the current or applied filter query
func (s *Sidebar) GetFilterQuery() string {
	if s.filterApplied {
		return s.appliedQuery
	}
	return s.filterQuery
}

// GetFilterInfo returns formatted filter information for status bar
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
				fmt.Sprintf("%s: %d", section.Title, section.FilterMatches))
		}
	}

	if len(matchInfo) == 0 {
		return "no matches"
	}

	return strings.Join(matchInfo, ", ")
}

// easeOutCubic provides smooth deceleration for animations
func easeOutCubic(t float64) float64 {
	t--
	return t*t*t + 1
}

// min returns the minimum of two integers
func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// SidebarAnimationMsg is sent during sidebar animations
type SidebarAnimationMsg struct{}
