package leet

import (
	"fmt"
	"slices"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	// Sidebar header lines (title + state + ID + name + project + blank line).
	// TODO: replace with len(LeftSidebar.buildHeaderLines())
	sidebarHeaderLines = 7
)

// LeftSidebar stores and displays run metadata.
//
// It handles presentation concerns: sections, filtering, navigation, layout, and rendering.
// All data processing is delegated to the RunOverview model.
type LeftSidebar struct {
	animState   *AnimationState
	runOverview *RunOverview

	// UI state: sections, filtering, navigation.
	// TODO: encapsulate and refactor
	sections      []PagedList
	activeSection int

	// Filter state.
	filter *Filter

	// Dimensions.
	height int
}

func NewLeftSidebar(config *ConfigManager) *LeftSidebar {
	animState := NewAnimationState(config.LeftSidebarVisible(), SidebarMinWidth)

	es := PagedList{Title: "Environment", Active: true}
	es.SetItemsPerPage(10)
	cs := PagedList{Title: "Config"}
	cs.SetItemsPerPage(15)
	ss := PagedList{Title: "Summary"}
	ss.SetItemsPerPage(20)

	return &LeftSidebar{
		animState:     animState,
		runOverview:   NewRunOverview(),
		sections:      []PagedList{es, cs, ss},
		activeSection: 0,
		filter:        NewFilter(),
	}
}

// Toggle toggles the sidebar between expanded and collapsed states.
func (s *LeftSidebar) Toggle() {
	s.animState.Toggle()

	if s.animState.IsExpanding() {
		s.selectFirstAvailableItem()
	}
}

// Update handles animation and input updates for the sidebar.
func (s *LeftSidebar) Update(msg tea.Msg) (*LeftSidebar, tea.Cmd) {
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
		complete := s.animState.Update(time.Now())
		if !complete {
			return s, s.animationCmd()
		}
	}

	return s, nil
}

// View renders the sidebar.
func (s *LeftSidebar) View(height int) string {
	if s.animState.Width() <= 0 {
		return ""
	}

	s.height = height
	s.updateSectionHeights()

	headerLines := s.buildHeaderLines()

	contentWidth := s.animState.Width() - leftSidebarContentPadding
	sectionLines := s.buildSectionLines(contentWidth)

	allLines := slices.Concat(headerLines, sectionLines)
	content := strings.Join(allLines, "\n")

	styledContent := leftSidebarStyle.
		Width(s.animState.Width()).
		Height(height + 1).
		MaxWidth(s.animState.Width()).
		MaxHeight(height + 1).
		Render(content)

	return leftSidebarBorderStyle.
		Width(s.animState.Width() - 2).
		Height(height + 2).
		MaxWidth(s.animState.Width()).
		MaxHeight(height + 2).
		Render(styledContent)
}

// ProcessRunMsg delegates to the data model and updates UI.
func (s *LeftSidebar) ProcessRunMsg(msg RunMsg) {
	s.runOverview.ProcessRunMsg(msg)
	s.updateSections()
}

// ProcessSystemInfoMsg delegates to the data model and updates UI.
func (s *LeftSidebar) ProcessSystemInfoMsg(record *spb.EnvironmentRecord) {
	s.runOverview.ProcessSystemInfoMsg(record)
	s.updateSections()
}

// ProcessSummaryMsg delegates to the data model and updates UI.
func (s *LeftSidebar) ProcessSummaryMsg(summary []*spb.SummaryRecord) {
	s.runOverview.ProcessSummaryMsg(summary)
	s.updateSections()
}

// SetRunState delegates to the data model.
func (s *LeftSidebar) SetRunState(state RunState) {
	s.runOverview.SetRunState(state)
}

// UpdateDimensions updates the sidebar dimensions based on terminal width
// and the visibility of the right sidebar.
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

// SelectedItem returns the currently selected key-value pair.
func (s *LeftSidebar) SelectedItem() (key, value string) {
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

// updateSections pulls data from the model and updates UI sections.
func (s *LeftSidebar) updateSections() {
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

// animationCmd returns a command to continue the animation on section toggle.
func (s *LeftSidebar) animationCmd() tea.Cmd {
	return tea.Tick(AnimationFrame, func(t time.Time) tea.Msg {
		return LeftSidebarAnimationMsg{}
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
func (s *LeftSidebar) buildHeaderLines() []string {
	lines := make([]string, 0, sidebarHeaderLines)

	// Title.
	lines = append(lines, leftSidebarHeaderStyle.Render(runOverviewHeader))

	if s.runOverview.State() != RunStateUnknown {
		lines = append(lines,
			leftSidebarKeyStyle.Render("State: ")+
				leftSidebarValueStyle.Render(s.runOverview.StateString()))
	}

	if id := s.runOverview.ID(); id != "" {
		lines = append(lines,
			leftSidebarKeyStyle.Render("ID: ")+leftSidebarValueStyle.Render(id))
	}
	if name := s.runOverview.DisplayName(); name != "" {
		lines = append(lines,
			leftSidebarKeyStyle.Render("Name: ")+leftSidebarValueStyle.Render(name))
	}
	if project := s.runOverview.Project(); project != "" {
		lines = append(lines,
			leftSidebarKeyStyle.Render("Project: ")+leftSidebarValueStyle.Render(project))
	}

	// Blank separator line.
	lines = append(lines, "")

	return lines
}

// buildSectionLines builds all section content lines.
func (s *LeftSidebar) buildSectionLines(contentWidth int) []string {
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
func (s *LeftSidebar) renderSection(idx int, width int) string {
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

	return strings.Join(lines, "\n")
}

// renderSectionHeader renders the section title with pagination info.
func (s *LeftSidebar) renderSectionHeader(section *PagedList) string {
	titleStyle := leftSidebarSectionStyle
	if section.Active {
		titleStyle = leftSidebarSectionHeaderStyle
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
func (s *LeftSidebar) buildSectionInfo(
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
func (s *LeftSidebar) renderSectionItems(section *PagedList, width int) []string {
	maxKeyWidth := int(float64(width) * leftSidebarKeyWidthRatio)
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
func (s *LeftSidebar) renderItem(
	item KeyValuePair,
	posInPage int,
	section *PagedList,
	maxKeyWidth, maxValueWidth int,
) string {
	keyStyle := leftSidebarKeyStyle
	valueStyle := leftSidebarValueStyle

	// Highlight selected item.
	if section.Active && posInPage == section.CurrentLine() {
		keyStyle = keyStyle.Background(colorSelected)
		valueStyle = valueStyle.Background(colorSelected)
	}

	key := truncateValue(item.Key, maxKeyWidth)
	value := truncateValue(item.Value, maxValueWidth)

	return fmt.Sprintf("%s %s",
		keyStyle.Width(maxKeyWidth).Render(key),
		valueStyle.Render(value))
}

// hasNextVisibleSection returns true if there's another visible section after idx.
func (s *LeftSidebar) hasNextVisibleSection(idx int) bool {
	for j := idx + 1; j < len(s.sections); j++ {
		if s.sections[j].Height > 0 {
			return true
		}
	}
	return false
}
