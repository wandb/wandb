package leet

import (
	"fmt"
	"sort"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/wandb/wandb/core/internal/runconfig"
	"github.com/wandb/wandb/core/internal/runenvironment"
	"github.com/wandb/wandb/core/internal/runsummary"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
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

// LeftSidebar represents a collapsible sidebar panel that owns all run data.
type LeftSidebar struct {
	animState *AnimationState

	// Run data
	runID          string
	displayName    string
	project        string
	runConfig      *runconfig.RunConfig
	runEnvironment *runenvironment.RunEnvironment
	runSummary     *runsummary.RunSummary
	runState       RunState

	// Section management: Environment, Config, Summary.
	sections      []SectionView
	activeSection int

	// Filter state
	filterMode    bool   // Whether we're currently typing a filter
	filterQuery   string // Current filter being typed
	filterApplied bool   // Whether filter is applied (after Enter)
	appliedQuery  string // The query that was applied
	filterSection string // "@e", "@c", "@s", or ""

	// Dimensions
	height int
}

func NewLeftSidebar(config *ConfigManager) *LeftSidebar {
	animState := NewAnimationState(config.LeftSidebarVisible(), SidebarMinWidth)

	return &LeftSidebar{
		animState:      animState,
		runConfig:      runconfig.New(),
		runEnvironment: nil,
		runSummary:     runsummary.New(),
		sections: []SectionView{
			{Title: "Environment", ItemsPerPage: 10, Active: true},
			{Title: "Config", ItemsPerPage: 15},
			{Title: "Summary", ItemsPerPage: 20},
		},
		activeSection: 0,
		runState:      RunStateRunning,
	}
}

// ProcessRunMsg updates the sidebar with run information.
func (s *LeftSidebar) ProcessRunMsg(msg RunMsg) {
	s.runID = msg.ID
	s.displayName = msg.DisplayName
	s.project = msg.Project

	if msg.Config != nil {
		s.runConfig.ApplyChangeRecord(msg.Config, func(err error) {})
		s.updateSections()
	}
}

// ProcessSystemInfoMsg updates environment data.
func (s *LeftSidebar) ProcessSystemInfoMsg(record *spb.EnvironmentRecord) {
	if s.runEnvironment == nil && record != nil {
		s.runEnvironment = runenvironment.New(record.GetWriterId())
	}
	if s.runEnvironment != nil {
		s.runEnvironment.ProcessRecord(record)
		s.updateSections()
	}
}

// ProcessSummaryMsg updates summary data.
func (s *LeftSidebar) ProcessSummaryMsg(summary *spb.SummaryRecord) {
	if summary == nil {
		return
	}

	for _, update := range summary.Update {
		_ = s.runSummary.SetFromRecord(update)
	}
	for _, remove := range summary.Remove {
		s.runSummary.RemoveFromRecord(remove)
	}
	s.updateSections()
}

// SetRunState sets the run state for display.
func (s *LeftSidebar) SetRunState(state RunState) {
	s.runState = state
}

// flattenMap converts nested maps to flat key-value pairs.
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

	keys := make([]string, 0, len(data))
	for k := range data {
		keys = append(keys, k)
	}

	if len(keys) == 0 {
		return []KeyValuePair{}
	}

	sort.Strings(keys)
	firstKey := keys[0]

	firstValue, ok := data[firstKey]
	if !ok {
		return []KeyValuePair{}
	}

	if valueMap, ok := firstValue.(map[string]any); ok {
		result := make([]KeyValuePair, 0)
		flattenMap(valueMap, "", &result, []string{})
		return result
	}

	return []KeyValuePair{
		{Key: firstKey, Value: fmt.Sprintf("%v", firstValue), Path: []string{firstKey}},
	}
}

// updateSections updates section data from internal run data.
func (s *LeftSidebar) updateSections() {
	var currentKey, currentValue string
	if s.activeSection >= 0 && s.activeSection < len(s.sections) {
		currentKey, currentValue = s.GetSelectedItem()
	}

	// Update Environment section
	var envData map[string]any
	if s.runEnvironment != nil {
		envData = s.runEnvironment.ToRunConfigData()
	}
	envItems := processEnvironment(envData)
	s.sections[0].Items = envItems

	// Update Config section
	configItems := make([]KeyValuePair, 0)
	if s.runConfig != nil {
		flattenMap(s.runConfig.CloneTree(), "", &configItems, []string{})
	}
	s.sections[1].Items = configItems

	// Update Summary section
	summaryItems := make([]KeyValuePair, 0)
	if s.runSummary != nil {
		flattenMap(s.runSummary.ToNestedMaps(), "", &summaryItems, []string{})
	}
	s.sections[2].Items = summaryItems

	// Apply filter if active
	if s.filterMode || s.filterApplied {
		s.applyFilter()
	} else {
		for i := range s.sections {
			s.sections[i].FilteredItems = s.sections[i].Items
		}
	}

	s.calculateSectionHeights()

	// Restore selection
	if currentKey == "" {
		s.selectFirstAvailableItem()
	} else {
		s.restoreSelection(currentKey, currentValue)
	}
}

// restoreSelection attempts to restore the previously selected item.
func (s *LeftSidebar) restoreSelection(previousKey, previousValue string) {
	if s.activeSection >= 0 && s.activeSection < len(s.sections) {
		section := &s.sections[s.activeSection]
		for i, item := range section.FilteredItems {
			if item.Key == previousKey && item.Value == previousValue {
				page := i / section.ItemsPerPage
				posInPage := i % section.ItemsPerPage

				section.CurrentPage = page
				section.CursorPos = posInPage
				return
			}
		}

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

	// Try to find in any section
	for sectionIdx, section := range s.sections {
		for i, item := range section.FilteredItems {
			if item.Key == previousKey {
				s.sections[s.activeSection].Active = false
				s.activeSection = sectionIdx
				s.sections[sectionIdx].Active = true

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

	// Keep current position or select first available
	if s.activeSection >= 0 && s.activeSection < len(s.sections) {
		section := &s.sections[s.activeSection]
		if len(section.FilteredItems) == 0 || section.ItemsPerPage == 0 {
			s.selectFirstAvailableItem()
		}
	} else {
		s.selectFirstAvailableItem()
	}
}

// selectFirstAvailableItem selects the first item in the first non-empty section.
func (s *LeftSidebar) selectFirstAvailableItem() {
	foundSection := false
	for i := range s.sections {
		if len(s.sections[i].FilteredItems) > 0 && s.sections[i].ItemsPerPage > 0 {
			for j := range s.sections {
				s.sections[j].Active = false
			}
			s.activeSection = i
			s.sections[i].Active = true
			s.sections[i].CurrentPage = 0
			s.sections[i].CursorPos = 0
			foundSection = true
			break
		}
	}

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
func (s *LeftSidebar) applyFilter() {
	query := strings.TrimSpace(s.filterQuery)
	if s.filterApplied {
		query = strings.TrimSpace(s.appliedQuery)
	}

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

		if sectionFilter != "" {
			sectionName := strings.ToLower(section.Title)
			if !strings.HasPrefix(sectionName, sectionFilter) {
				section.FilteredItems = []KeyValuePair{}
				section.FilterMatches = 0
				continue
			}
		}

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
func (s *LeftSidebar) calculateSectionHeights() {
	if s.height == 0 {
		return
	}

	totalAvailable := s.calculateAvailableHeight()
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

// calculateAvailableHeight returns the height available for sections.
func (s *LeftSidebar) calculateAvailableHeight() int {
	const headerLines = 7
	availableHeight := s.height - headerLines

	activeSections := s.countActiveSections()
	if activeSections == 0 {
		return 0
	}

	spacingBetweenSections := 0
	if activeSections > 1 {
		spacingBetweenSections = activeSections - 1
	}

	return max(availableHeight-spacingBetweenSections, activeSections*2)
}

// countActiveSections returns the number of sections with items.
func (s *LeftSidebar) countActiveSections() int {
	count := 0
	for i := range s.sections {
		if len(s.sections[i].FilteredItems) > 0 {
			count++
		}
	}
	return count
}

// calculateDesiredHeights calculates the desired height for each section.
func (s *LeftSidebar) calculateDesiredHeights() []int {
	const (
		envMax     = 12
		configMax  = 20
		summaryMax = 25
	)
	maxHeights := []int{envMax, configMax, summaryMax}

	desired := make([]int, len(s.sections))

	for i := range s.sections {
		itemCount := len(s.sections[i].FilteredItems)
		if itemCount == 0 {
			s.sections[i].Height = 0
			desired[i] = 0
			continue
		}

		maxHeight := maxHeights[i]
		desired[i] = max(min(itemCount+1, maxHeight), 2)
	}

	return desired
}

// sumDesiredHeights returns the sum of all desired heights.
func (s *LeftSidebar) sumDesiredHeights(desired []int) int {
	total := 0
	for _, h := range desired {
		total += h
	}
	return total
}

// scaleHeightsProportionally scales section heights when total exceeds available.
func (s *LeftSidebar) scaleHeightsProportionally(desired []int, totalAvailable int) {
	totalDesired := s.sumDesiredHeights(desired)
	scaleFactor := float64(totalAvailable) / float64(totalDesired)

	allocated := 0
	for i := range s.sections {
		if desired[i] > 0 {
			scaled := int(float64(desired[i]) * scaleFactor)
			if scaled < 2 && len(s.sections[i].FilteredItems) > 0 {
				scaled = 2
			}
			s.sections[i].Height = scaled
			allocated += scaled
		} else {
			s.sections[i].Height = 0
		}
	}

	// Distribute remainder to last section with items
	if allocated < totalAvailable {
		remainder := totalAvailable - allocated
		s.allocateRemainder(remainder)
	}
}

// allocateDesiredHeights sets each section to its desired height.
func (s *LeftSidebar) allocateDesiredHeights(desired []int) {
	for i := range s.sections {
		s.sections[i].Height = desired[i]
	}
}

// distributeExtraSpace distributes unused space to sections that can use it.
func (s *LeftSidebar) distributeExtraSpace(totalAvailable, totalDesired int) {
	const (
		envMax     = 12
		configMax  = 20
		summaryMax = 25
	)
	maxHeights := []int{envMax, configMax, summaryMax}

	extraSpace := totalAvailable - totalDesired

	// Try to expand sections from bottom to top (summary, config, env)
	for i := 2; i >= 0 && extraSpace > 0; i-- {
		section := &s.sections[i]
		if section.Height == 0 {
			continue
		}

		itemCount := len(section.FilteredItems)
		currentItems := section.Height - 1

		if currentItems < itemCount {
			maxIncrease := min(maxHeights[i]-section.Height, itemCount+1-section.Height)
			increase := min(maxIncrease, extraSpace)

			section.Height += increase
			extraSpace -= increase
		}
	}
}

// allocateRemainder distributes remaining space to the last section with items.
func (s *LeftSidebar) allocateRemainder(remainder int) {
	// Try sections from bottom to top
	for i := 2; i >= 0; i-- {
		if len(s.sections[i].FilteredItems) > 0 && s.sections[i].Height > 0 {
			s.sections[i].Height += remainder
			return
		}
	}
}

// updateItemsPerPage updates the items per page for each section.
func (s *LeftSidebar) updateItemsPerPage() {
	for i := range s.sections {
		if s.sections[i].Height > 0 {
			s.sections[i].ItemsPerPage = max(s.sections[i].Height-1, 1)
		} else {
			s.sections[i].ItemsPerPage = 0
		}
	}
}

// UpdateDimensions updates the sidebar dimensions based on terminal width.
func (s *LeftSidebar) UpdateDimensions(terminalWidth int, rightSidebarVisible bool) {
	var calculatedWidth int

	if rightSidebarVisible {
		calculatedWidth = int(float64(terminalWidth) * SidebarWidthRatioBoth)
	} else {
		calculatedWidth = int(float64(terminalWidth) * SidebarWidthRatio)
	}

	expandedWidth := clamp(calculatedWidth, SidebarMinWidth, SidebarMaxWidth)
	s.animState.SetExpandedWidth(expandedWidth)
}

// Toggle toggles the sidebar state between expanded and collapsed.
func (s *LeftSidebar) Toggle() {
	s.animState.Toggle()

	if s.animState.State() == SidebarExpanding {
		s.selectFirstAvailableItem()
	}
}

// navigateUp moves cursor up within the active section.
func (s *LeftSidebar) navigateUp() {
	if s.activeSection < 0 || s.activeSection >= len(s.sections) {
		return
	}

	section := &s.sections[s.activeSection]
	if section.CursorPos > 0 {
		section.CursorPos--
	} else if section.CurrentPage > 0 {
		section.CurrentPage--
		section.CursorPos = section.ItemsPerPage - 1
	}
}

// navigateDown moves cursor down within the active section.
func (s *LeftSidebar) navigateDown() {
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
		section.CurrentPage++
		section.CursorPos = 0
	}
}

// navigateSection jumps between sections, skipping empty ones.
func (s *LeftSidebar) navigateSection(direction int) {
	if len(s.sections) == 0 {
		return
	}

	prev := s.activeSection
	idx := prev

	for i := 0; i < len(s.sections); i++ {
		idx += direction
		if idx < 0 {
			idx = len(s.sections) - 1
		} else if idx >= len(s.sections) {
			idx = 0
		}

		if len(s.sections[idx].FilteredItems) > 0 {
			s.sections[prev].Active = false
			s.activeSection = idx
			s.sections[idx].Active = true
			s.sections[idx].CurrentPage = 0
			s.sections[idx].CursorPos = 0
			return
		}

		if idx == prev {
			break
		}
	}
	s.sections[prev].Active = true
}

// navigatePage changes page within active section.
func (s *LeftSidebar) navigatePage(direction int) {
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

	section.CursorPos = 0
}

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

// clearFilter clears the active filter.
func (s *LeftSidebar) clearFilter() {
	s.filterMode = false
	s.filterApplied = false
	s.filterQuery = ""
	s.appliedQuery = ""
	s.filterSection = ""

	for i := range s.sections {
		s.sections[i].FilteredItems = s.sections[i].Items
		s.sections[i].CurrentPage = 0
		s.sections[i].CursorPos = 0
		s.sections[i].FilterMatches = 0
	}

	s.calculateSectionHeights()
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

// GetSelectedItem returns the currently selected key-value pair.
func (s *LeftSidebar) GetSelectedItem() (key, value string) {
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
func (s *LeftSidebar) Update(msg tea.Msg) (*LeftSidebar, tea.Cmd) {
	// Handle key input only when expanded
	if s.animState.State() == SidebarExpanded {
		if keyMsg, ok := msg.(tea.KeyMsg); ok {
			switch keyMsg.Type {
			case tea.KeyUp:
				s.navigateUp()
			case tea.KeyDown:
				s.navigateDown()
			case tea.KeyTab:
				s.navigateSection(1)
			case tea.KeyShiftTab:
				s.navigateSection(-1)
			case tea.KeyLeft:
				s.navigatePage(-1)
			case tea.KeyRight:
				s.navigatePage(1)
			}
		}
	}

	// Handle animation
	cmd, _ := s.animState.Update()

	return s, cmd
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
func (s *LeftSidebar) renderSection(idx int, width int) string {
	section := &s.sections[idx]

	if len(section.FilteredItems) == 0 || section.Height == 0 {
		return ""
	}

	var lines []string

	titleStyle := sidebarSectionStyle
	if section.Active {
		titleStyle = titleStyle.Foreground(lipgloss.Color("230")).Bold(true)
	}

	totalItems := len(section.Items)
	filteredItems := len(section.FilteredItems)

	startIdx := section.CurrentPage * section.ItemsPerPage
	endIdx := min(startIdx+section.ItemsPerPage, filteredItems)
	actualItemsToShow := endIdx - startIdx

	titleText := section.Title
	infoText := ""

	switch {
	case (s.filterMode || s.filterApplied) && filteredItems != totalItems:
		infoText = fmt.Sprintf(" [%d-%d of %d filtered from %d]",
			startIdx+1, endIdx, filteredItems, totalItems)
	case filteredItems > section.ItemsPerPage:
		infoText = fmt.Sprintf(" [%d-%d of %d]", startIdx+1, endIdx, filteredItems)
	case filteredItems > 0:
		infoText = fmt.Sprintf(" [%d items]", filteredItems)
	}

	lines = append(lines, titleStyle.Render(titleText)+navInfoStyle.Render(infoText))

	maxKeyWidth := (width * 2) / 5
	maxValueWidth := width - maxKeyWidth - 1

	itemsToRender := min(actualItemsToShow, section.ItemsPerPage)

	for i := range itemsToRender {
		itemIdx := startIdx + i
		if itemIdx >= len(section.FilteredItems) {
			break
		}

		item := section.FilteredItems[itemIdx]

		keyStyle := sidebarKeyStyle
		valueStyle := sidebarValueStyle

		if section.Active && i == section.CursorPos {
			keyStyle = keyStyle.Background(colorSelected)
			valueStyle = valueStyle.Background(colorSelected)
		}

		key := truncateValue(item.Key, maxKeyWidth)
		value := truncateValue(item.Value, maxValueWidth)

		line := fmt.Sprintf("%s %s",
			keyStyle.Width(maxKeyWidth).Render(key),
			valueStyle.Render(value))
		lines = append(lines, line)
	}

	return strings.Join(lines, "\n")
}

// View renders the sidebar.
func (s *LeftSidebar) View(height int) string {
	if s.animState.Width() <= 0 {
		return ""
	}

	s.height = height
	s.calculateSectionHeights()

	var lines []string
	lines = append(lines, sidebarHeaderStyle.Render("Run Overview"))

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

	if s.runID != "" {
		lines = append(lines, sidebarKeyStyle.Render("ID: ")+
			sidebarValueStyle.Render(s.runID))
	}
	if s.displayName != "" {
		lines = append(lines, sidebarKeyStyle.Render("Name: ")+
			sidebarValueStyle.Render(s.displayName))
	}
	if s.project != "" {
		lines = append(lines, sidebarKeyStyle.Render("Project: ")+
			sidebarValueStyle.Render(s.project))
	}

	lines = append(lines, "")

	contentWidth := s.animState.Width() - 4
	for i := range s.sections {
		if s.sections[i].Height == 0 {
			continue
		}

		sectionContent := s.renderSection(i, contentWidth)
		if sectionContent != "" {
			lines = append(lines, sectionContent)
			if i < len(s.sections)-1 {
				hasNextContent := false
				for j := i + 1; j < len(s.sections); j++ {
					if s.sections[j].Height > 0 {
						hasNextContent = true
						break
					}
				}
				if hasNextContent {
					lines = append(lines, "")
				}
			}
		}
	}

	content := strings.Join(lines, "\n")

	styledContent := sidebarStyle.
		Width(s.animState.Width() - 1).
		Height(height).
		MaxWidth(s.animState.Width() - 1).
		MaxHeight(height).
		Render(content)

	bordered := sidebarBorderStyle.
		Width(s.animState.Width()).
		Height(height).
		MaxWidth(s.animState.Width()).
		MaxHeight(height).
		Render(styledContent)

	return bordered
}

// Width returns the current width of the sidebar.
func (s *LeftSidebar) Width() int {
	return s.animState.Width()
}

// IsVisible returns true if the sidebar is visible.
func (s *LeftSidebar) IsVisible() bool {
	return s.animState.IsVisible()
}

// IsAnimating returns true if the sidebar is currently animating.
func (s *LeftSidebar) IsAnimating() bool {
	return s.animState.IsAnimating()
}
