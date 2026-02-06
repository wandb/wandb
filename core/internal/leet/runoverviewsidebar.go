package leet

import (
	"fmt"
	"slices"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

type SidebarSide int

const (
	SidebarSideUndefined SidebarSide = iota
	SidebarSideLeft
	SidebarSideRight
)

const (
	// Sidebar header lines (title + state + ID + name + project + blank line).
	// TODO: replace with len(LeftSidebar.buildHeaderLines())
	sidebarHeaderLines = 6
)

// RunOverviewSidebar stores and displays run metadata.
//
// It handles presentation concerns: sections, filtering, navigation, layout, and rendering.
// All data processing is delegated to the RunOverview model.
type RunOverviewSidebar struct {
	animState   *AnimationState
	runOverview *RunOverview

	// UI state: sections, filtering, navigation.
	// TODO: encapsulate and refactor
	sections      []PagedList
	activeSection int

	// Filter state.
	filter *Filter

	// Placement and dimensions.
	side   SidebarSide
	height int
}

func NewRunOverviewSidebar(
	animState *AnimationState,
	runOverview *RunOverview,
	side SidebarSide,
) *RunOverviewSidebar {
	es := PagedList{Title: "Environment", Active: true}
	es.SetItemsPerPage(10)
	cs := PagedList{Title: "Config"}
	cs.SetItemsPerPage(15)
	ss := PagedList{Title: "Summary"}
	ss.SetItemsPerPage(20)

	return &RunOverviewSidebar{
		animState:     animState,
		runOverview:   runOverview,
		sections:      []PagedList{es, cs, ss},
		activeSection: 0,
		filter:        NewFilter(),
		side:          side,
	}
}

// Toggle toggles the sidebar between expanded and collapsed states.
func (s *RunOverviewSidebar) Toggle() {
	s.animState.Toggle()

	if s.animState.IsExpanding() {
		s.selectFirstAvailableItem()
	}
}

// Update handles animation and input updates for the sidebar.
func (s *RunOverviewSidebar) Update(msg tea.Msg) (*RunOverviewSidebar, tea.Cmd) {
	// Handle key input only when expanded.
	// TODO: hook up with keybindings.
	if s.animState.IsExpanded() {
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
				s.navigatePageUp()
			case tea.KeyRight:
				s.navigatePageDown()
			}
		}
	}

	// Handle animation.
	if s.animState.IsAnimating() {
		if complete := s.animState.Update(time.Now()); !complete {
			cmd := s.animationCmd()
			return s, cmd
		}
	}

	return s, nil
}

func (s *RunOverviewSidebar) contentPadding() int {
	switch s.side {
	case SidebarSideLeft:
		return leftSidebarContentPadding
	case SidebarSideRight:
		return rightSidebarContentPadding
	}
	return 0
}

func (s *RunOverviewSidebar) style() lipgloss.Style {
	switch s.side {
	case SidebarSideLeft:
		return leftSidebarStyle
	case SidebarSideRight:
		return rightSidebarStyle
	}
	return lipgloss.NewStyle()
}

func (s *RunOverviewSidebar) borderStyle() lipgloss.Style {
	switch s.side {
	case SidebarSideLeft:
		return leftSidebarBorderStyle
	case SidebarSideRight:
		return rightSidebarBorderStyle
	}
	return lipgloss.NewStyle()
}

func (s *RunOverviewSidebar) headerStyle() lipgloss.Style {
	switch s.side {
	case SidebarSideLeft:
		return leftSidebarHeaderStyle
	case SidebarSideRight:
		return rightSidebarHeaderStyle
	}
	return lipgloss.NewStyle()
}

// View renders the sidebar.
func (s *RunOverviewSidebar) View(height int) string {
	if s.animState.Width() <= 0 {
		return ""
	}

	s.height = height

	lines := make([]string, 0)

	lines = append(lines, s.headerStyle().Render(runOverviewHeader))

	if s.runOverview != nil {
		headerLines := s.buildHeaderLines()
		contentWidth := s.animState.Width() - s.contentPadding()
		s.updateSectionHeights()
		sectionLines := s.buildSectionLines(contentWidth)

		lines = slices.Concat(lines, headerLines, sectionLines)
	} else {
		lines = append(lines, "No data.")
	}

	content := lipgloss.JoinVertical(lipgloss.Top, lines...)

	styledContent := s.style().
		Width(s.animState.Width()).
		Height(height).
		MaxWidth(s.animState.Width()).
		MaxHeight(height).
		Render(content)

	return s.borderStyle().
		Width(s.animState.Width() - 2).
		Height(height + 1).
		MaxWidth(s.animState.Width()).
		MaxHeight(height + 1).
		Render(styledContent)
}

func (s *RunOverviewSidebar) SetRunOverview(ro *RunOverview) {
	s.runOverview = ro
}

// Sync synchronizes section view with the s.runOverview.
//
// It pulls data from the model and updates UI sections.
func (s *RunOverviewSidebar) Sync() {
	if s.runOverview == nil {
		return
	}

	var selectedKey string
	if s.activeSection >= 0 && s.activeSection < len(s.sections) {
		selectedKey, _ = s.SelectedItem()
	}

	s.sections[0].Items = s.runOverview.EnvironmentItems()
	s.sections[1].Items = s.runOverview.ConfigItems()
	s.sections[2].Items = s.runOverview.SummaryItems()

	if s.IsFilterMode() || s.IsFiltering() {
		s.ApplyFilter()
	} else {
		for i := range s.sections {
			s.sections[i].FilteredItems = s.sections[i].Items
		}
	}

	s.updateSectionHeights()

	if selectedKey == "" {
		s.selectFirstAvailableItem()
	} else {
		s.restoreSelection(selectedKey)
	}
}

// UpdateDimensions updates the sidebar dimensions based on terminal width
// and the visibility of the sidebar on the opposite side.
func (s *RunOverviewSidebar) UpdateDimensions(terminalWidth int, oppositeSidebarVisible bool) {
	var calculatedWidth int

	if oppositeSidebarVisible {
		calculatedWidth = int(float64(terminalWidth) * SidebarWidthRatioBoth)
	} else {
		calculatedWidth = int(float64(terminalWidth) * SidebarWidthRatio)
	}

	expandedWidth := clamp(calculatedWidth, SidebarMinWidth, SidebarMaxWidth)
	s.animState.SetExpandedWidth(expandedWidth)
}

// Width returns the current width of the sidebar.
func (s *RunOverviewSidebar) Width() int {
	return s.animState.Width()
}

// IsVisible returns true if the sidebar is visible.
func (s *RunOverviewSidebar) IsVisible() bool {
	return s.animState.IsVisible()
}

// IsAnimating returns true if the sidebar is currently animating.
func (s *RunOverviewSidebar) IsAnimating() bool {
	return s.animState.IsAnimating()
}

// SelectedItem returns the currently selected key-value pair.
func (s *RunOverviewSidebar) SelectedItem() (key, value string) {
	if s.activeSection < 0 || s.activeSection >= len(s.sections) {
		return "", ""
	}

	section := &s.sections[s.activeSection]
	if len(section.FilteredItems) == 0 {
		return "", ""
	}

	startIdx := section.CurrentPage() * section.ItemsPerPage()
	itemIdx := startIdx + section.CurrentLine()

	if itemIdx >= 0 && itemIdx < len(section.FilteredItems) {
		item := section.FilteredItems[itemIdx]
		return item.Key, item.Value
	}

	return "", ""
}

// animationCmd returns a command to continue the animation on section toggle.
func (s *RunOverviewSidebar) animationCmd() tea.Cmd {
	return tea.Tick(AnimationFrame, func(t time.Time) tea.Msg {
		switch s.side {
		case SidebarSideLeft:
			return LeftSidebarAnimationMsg{}
		case SidebarSideRight:
			return RightSidebarAnimationMsg{}
		}
		return nil
	})
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

// buildHeaderLines builds the header section from the data model.
func (s *RunOverviewSidebar) buildHeaderLines() []string {
	lines := make([]string, 0, 5)

	if s.runOverview.State() != RunStateUnknown {
		lines = append(lines,
			runOverviewSidebarKeyStyle.Render("State: ")+
				runOverviewSidebarValueStyle.Render(s.runOverview.StateString()))
	}
	if id := s.runOverview.ID(); id != "" {
		lines = append(lines,
			runOverviewSidebarKeyStyle.Render("ID: ")+runOverviewSidebarValueStyle.Render(id))
	}
	if name := s.runOverview.DisplayName(); name != "" {
		lines = append(lines,
			runOverviewSidebarKeyStyle.Render("Name: ")+runOverviewSidebarValueStyle.Render(name))
	}
	if project := s.runOverview.Project(); project != "" {
		lines = append(lines,
			runOverviewSidebarKeyStyle.Render("Project: ")+
				runOverviewSidebarValueStyle.Render(project))
	}

	// Blank separator line.
	lines = append(lines, "")

	return lines
}

// buildSectionLines builds all section content lines.
func (s *RunOverviewSidebar) buildSectionLines(contentWidth int) []string {
	var lines []string

	for i := range s.sections {
		if s.sections[i].Height == 0 {
			continue
		}

		sectionContent := s.renderSection(i, contentWidth)
		if sectionContent != "" {
			lines = append(lines, sectionContent)

			// Add spacing between sections if there's a next section.
			if s.hasNextVisibleSection(i) {
				lines = append(lines, "")
			}
		}
	}

	return lines
}

// renderSection renders a single section.
func (s *RunOverviewSidebar) renderSection(idx, width int) string {
	section := &s.sections[idx]

	if len(section.FilteredItems) == 0 || section.Height == 0 {
		return ""
	}

	var lines []string

	// Render section header.
	lines = append(lines, s.renderSectionHeader(section))

	// Render section items.
	itemLines := s.renderSectionItems(section, width)
	lines = append(lines, itemLines...)

	return lipgloss.JoinVertical(lipgloss.Top, lines...)
}

// renderSectionHeader renders the section title with pagination info.
func (s *RunOverviewSidebar) renderSectionHeader(section *PagedList) string {
	titleStyle := runOverviewSidebarSectionStyle
	if section.Active {
		titleStyle = runOverviewSidebarSectionHeaderStyle
	}

	totalItems := len(section.Items)
	filteredItems := len(section.FilteredItems)

	startIdx := section.CurrentPage() * section.ItemsPerPage()
	endIdx := min(startIdx+section.ItemsPerPage(), filteredItems)

	titleText := section.Title
	infoText := s.buildSectionInfo(section, totalItems, filteredItems, startIdx, endIdx)

	return titleStyle.Render(titleText) + navInfoStyle.Render(infoText)
}

// buildSectionInfo builds the pagination/count info string for a section.
func (s *RunOverviewSidebar) buildSectionInfo(
	section *PagedList,
	totalItems, filteredItems, startIdx, endIdx int,
) string {
	switch {
	case (s.IsFilterMode() || s.filter.Query() != "") && filteredItems != totalItems:
		// Filtered view with pagination.
		return fmt.Sprintf(" [%d-%d of %d filtered from %d]",
			startIdx+1, endIdx, filteredItems, totalItems)
	case filteredItems > section.ItemsPerPage():
		// Paginated view.
		return fmt.Sprintf(" [%d-%d of %d]", startIdx+1, endIdx, filteredItems)
	case filteredItems > 0:
		// All items fit on one page.
		return fmt.Sprintf(" [%d items]", filteredItems)
	default:
		return ""
	}
}

// renderSectionItems renders the items for a section.
func (s *RunOverviewSidebar) renderSectionItems(section *PagedList, width int) []string {
	maxKeyWidth := int(float64(width) * sidebarKeyWidthRatio)
	maxValueWidth := width - maxKeyWidth - 1

	itemCount := len(section.FilteredItems)
	if itemCount == 0 {
		return nil
	}

	startIdx := section.CurrentPage() * section.ItemsPerPage()
	endIdx := min(startIdx+section.ItemsPerPage(), itemCount)

	itemsToRender := min(endIdx-startIdx, section.ItemsPerPage())

	lines := make([]string, 0, itemsToRender)
	for i := range itemsToRender {
		itemIdx := startIdx + i
		if itemIdx >= itemCount {
			break
		}

		item := section.FilteredItems[itemIdx]
		line := s.renderItem(item, i, section, maxKeyWidth, maxValueWidth)
		lines = append(lines, line)
	}

	return lines
}

// renderItem renders a single key-value item.
func (s *RunOverviewSidebar) renderItem(
	item KeyValuePair,
	posInPage int,
	section *PagedList,
	maxKeyWidth, maxValueWidth int,
) string {
	keyStyle := runOverviewSidebarKeyStyle
	valueStyle := runOverviewSidebarValueStyle

	isHighlighted := section.Active && posInPage == section.CurrentLine()
	if isHighlighted {
		keyStyle = runOverviewSidebarHighlightedItem
		valueStyle = runOverviewSidebarHighlightedItem
	}

	key := truncateValue(item.Key, maxKeyWidth)
	value := truncateValue(item.Value, maxValueWidth)

	renderedKey := keyStyle.Width(maxKeyWidth).Render(key)

	if isHighlighted {
		gap := runOverviewSidebarHighlightedItem.Render(" ")
		return renderedKey + gap + valueStyle.Width(maxValueWidth).Render(value)
	}
	return renderedKey + " " + valueStyle.Render(value)
}

// hasNextVisibleSection returns true if there's another visible section after idx.
func (s *RunOverviewSidebar) hasNextVisibleSection(idx int) bool {
	for j := idx + 1; j < len(s.sections); j++ {
		if s.sections[j].Height > 0 {
			return true
		}
	}
	return false
}
