package leet

import (
	"fmt"
	"slices"
	"strings"
	"time"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
)

type SidebarSide int

const (
	SidebarSideUndefined SidebarSide = iota
	SidebarSideLeft
	SidebarSideRight
)

// RunOverviewSidebar stores and displays run metadata.
//
// It handles presentation concerns: sections, filtering, navigation, layout, and rendering.
// All data processing is delegated to the RunOverview model.
type RunOverviewSidebar struct {
	config *ConfigManager

	animState   *AnimatedValue
	runOverview *RunOverview

	// UI state: sections, filtering, navigation.
	// TODO: encapsulate and refactor
	sections      []PagedList[KeyValuePair]
	activeSection int

	// Filter state.
	filter *Filter

	// Placement and dimensions.
	side   SidebarSide
	height int

	// overridesSource returns the owning view's live layout overrides:
	// an in-progress drag's pending values, or the persisted config.
	// Nil means no overrides (built-in section weights).
	overridesSource func() LayoutOverrides

	// separators are the rules between sections as drawn by the last
	// render; mouse drags hit-test against them.
	separators []overviewSeparator
}

// overviewSeparator locates one rendered separator rule between sections.
type overviewSeparator struct {
	row          int // Screen row of the rule.
	above, below int // Section indices either side of it.
}

func NewRunOverviewSidebar(
	config *ConfigManager,
	animState *AnimatedValue,
	runOverview *RunOverview,
	side SidebarSide,
) *RunOverviewSidebar {
	sections := []PagedList[KeyValuePair]{
		{Title: "Environment", Active: true},
		{Title: "Config"},
		{Title: "Summary"},
	}
	for i := range sections {
		// Provisional page size for navigation that happens before the
		// first render computes the real section heights.
		sections[i].SetItemsPerPage(10)
	}

	return &RunOverviewSidebar{
		config:        config,
		animState:     animState,
		runOverview:   runOverview,
		sections:      sections,
		activeSection: 0,
		filter:        NewFilter(),
		side:          side,
	}
}

// Toggle toggles the sidebar between expanded and collapsed states.
func (s *RunOverviewSidebar) Toggle() {
	s.animState.Toggle()
}

// Update advances the sidebar's expand/collapse animation.
//
// Key input never reaches this method: all sidebar navigation flows through
// the owning view's FocusManager and key bindings.
func (s *RunOverviewSidebar) Update(msg tea.Msg) (*RunOverviewSidebar, tea.Cmd) {
	if s.animState.IsAnimating() {
		if complete := s.animState.Update(time.Now()); !complete {
			cmd := s.animationCmd()
			return s, cmd
		}
	}

	return s, nil
}

// style returns sidebar style depending on the its placement.
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
func (s *RunOverviewSidebar) View(height int) tea.View {
	// This render's rules are the drag targets; a sidebar that renders
	// nothing must offer nothing to grab.
	s.separators = s.separators[:0]

	width := s.animState.Value()
	if height <= 0 || width <= SidebarOverhead {
		return tea.NewView("")
	}

	s.height = height

	contentWidth := s.sidebarContentWidth(width)
	lines := []string{s.headerStyle().Render(runOverviewHeader)}

	if s.runOverview != nil {
		headerLines := s.buildHeaderLines(contentWidth)
		s.updateSectionHeights()
		sectionLines := s.buildSectionLines(contentWidth, 1+len(headerLines))

		lines = slices.Concat(lines, headerLines, sectionLines)
	} else {
		lines = append(lines, navInfoStyle.Render("No data."))
	}

	content := lipgloss.JoinVertical(lipgloss.Top, lines...)
	innerWidth := s.sidebarInnerWidth(width)
	if innerWidth <= 0 {
		return tea.NewView("")
	}

	styledContent := s.style().
		Width(innerWidth).
		Height(height).
		MaxWidth(innerWidth).
		MaxHeight(height).
		Render(content)

	bordered := s.borderStyle().
		Height(height).
		MaxHeight(height).
		Render(styledContent)

	return tea.NewView(
		lipgloss.Place(width, height, lipgloss.Left, lipgloss.Top, bordered),
	)
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

	hadActiveSection := s.hasActiveSection()
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

	if !hadActiveSection {
		s.deactivateAllSections()
	}
}

// UpdateDimensions updates the sidebar dimensions based on terminal width,
// the visibility of the sidebar on the opposite side, and an optional
// user-dragged width fraction (0 = default).
func (s *RunOverviewSidebar) UpdateDimensions(
	terminalWidth int,
	oppositeSidebarVisible bool,
	widthFrac float64,
) {
	s.animState.SetExpanded(expandedSidebarWidth(terminalWidth, oppositeSidebarVisible, widthFrac))
}

// Width returns the current width of the sidebar.
func (s *RunOverviewSidebar) Width() int {
	return s.animState.Value()
}

// IsVisible returns true if the sidebar is visible.
func (s *RunOverviewSidebar) IsVisible() bool {
	return s.animState.IsVisible()
}

// IsAnimating returns true if the sidebar is currently animating.
func (s *RunOverviewSidebar) IsAnimating() bool {
	return s.animState.IsAnimating()
}

// IsExpanded returns true if the sidebar is currently expanded.
func (s *RunOverviewSidebar) IsExpanded() bool {
	return s.animState.IsExpanded()
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

// truncateValue truncates string values that do not fit into available width.
func truncateValue(value string, maxWidth int) string {
	if lipgloss.Width(value) <= maxWidth {
		return value
	}
	if maxWidth <= 3 {
		return "..."
	}

	available := maxWidth - 4
	w := 0
	for i, r := range value {
		rw := lipgloss.Width(string(r))
		if w+rw > available {
			return value[:i] + "..."
		}
		w += rw
	}
	return value + "..."
}

// headerLineCount returns the number of lines the header area (the
// top-level title plus the metadata block) renders at the current width.
func (s *RunOverviewSidebar) headerLineCount() int {
	contentWidth := s.sidebarContentWidth(s.animState.Value())
	return 1 + len(s.buildHeaderLines(contentWidth))
}

// buildHeaderLines builds the width-aware header metadata section.
func (s *RunOverviewSidebar) buildHeaderLines(contentWidth int) []string {
	if s.runOverview == nil {
		return nil
	}

	lines := make([]string, 0, 8)

	if s.runOverview.State() != RunStateUnknown {
		lines = append(lines, s.renderStateHeaderLine())
	}

	lines = slices.Concat(
		lines,
		s.renderWrappedHeaderValue("ID: ", s.runOverview.ID(), contentWidth),
		s.renderWrappedHeaderValue("Name: ", s.runOverview.DisplayName(), contentWidth),
		s.renderWrappedHeaderValue("Project: ", s.runOverview.Project(), contentWidth),
		s.renderTagHeaderValue("Tags: ", s.runOverview.Tags(), contentWidth),
		s.renderWrappedHeaderValue("Notes: ", s.runOverview.Notes(), contentWidth),
	)

	if len(lines) > 0 {
		lines = append(lines, "")
	}

	return lines
}

// renderStateHeaderLine renders the "State:" field with state-aware coloring:
// green while the run is live, red when it crashed or failed.
func (s *RunOverviewSidebar) renderStateHeaderLine() string {
	prefixText := runOverviewSidebarKeyStyle.Render("State: ")
	valueStyle := runOverviewSidebarValueStyle

	switch s.runOverview.State() {
	case RunStateRunning:
		valueStyle = valueStyle.Foreground(colorRunning)
	case RunStateCrashed, RunStateFailed:
		valueStyle = valueStyle.Foreground(colorCrashed)
	}

	return prefixText + valueStyle.Render(s.runOverview.StateString())
}

// renderWrappedHeaderValue renders a single metadata field, wrapping the value
// onto continuation lines when needed.
func (s *RunOverviewSidebar) renderWrappedHeaderValue(
	prefix, value string, width int,
) []string {
	if strings.TrimSpace(value) == "" {
		return nil
	}

	prefixText := runOverviewSidebarKeyStyle.Render(prefix)
	prefixWidth := lipgloss.Width(prefixText)
	available := max(width-prefixWidth, 1)
	wrapped := wrapHeaderText(value, available)
	indent := strings.Repeat(" ", prefixWidth)

	lines := make([]string, 0, len(wrapped))
	for i, line := range wrapped {
		renderedValue := runOverviewSidebarValueStyle.Render(line)
		if i == 0 {
			lines = append(lines, prefixText+renderedValue)
			continue
		}
		lines = append(lines, indent+renderedValue)
	}

	return lines
}

// renderTagHeaderValue renders tags using stable, palette-based colored badges
// that wrap across lines as needed.
func (s *RunOverviewSidebar) renderTagHeaderValue(
	prefix string, tags []string, width int) []string {
	if len(tags) == 0 {
		return nil
	}

	prefixText := runOverviewSidebarKeyStyle.Render(prefix)
	prefixWidth := lipgloss.Width(prefixText)
	indent := strings.Repeat(" ", prefixWidth)
	maxChipTextWidth := max(width-prefixWidth-2, 1)

	currentLine := prefixText
	currentWidth := prefixWidth
	lines := make([]string, 0, 2)
	renderedAny := false

	for _, tag := range tags {
		if strings.TrimSpace(tag) == "" {
			continue
		}

		renderedAny = true
		chipText := truncateValue(tag, maxChipTextWidth)
		chip := runOverviewTagStyle(s.tagColorScheme(), tag).Render(chipText)
		chipWidth := lipgloss.Width(chip)

		separator := ""
		separatorWidth := 0
		if currentWidth > prefixWidth {
			separator = " "
			separatorWidth = 1
		}

		if currentWidth+separatorWidth+chipWidth > width && currentWidth > prefixWidth {
			lines = append(lines, currentLine)
			currentLine = indent + chip
			currentWidth = prefixWidth + chipWidth
			continue
		}

		currentLine += separator + chip
		currentWidth += separatorWidth + chipWidth
	}

	if !renderedAny {
		return nil
	}

	lines = append(lines, currentLine)
	return lines
}

// buildSectionLines builds all section content lines, recording the screen
// row of each separator rule it draws between adjacent sections. firstRow
// is the screen row of the first section line (the sidebar is drawn from
// the top row of its side of the screen, below its title and header).
func (s *RunOverviewSidebar) buildSectionLines(contentWidth, firstRow int) []string {
	var lines []string

	row := firstRow
	prev := -1
	for i := range s.sections {
		if s.sections[i].Height == 0 {
			continue
		}

		sectionContent := s.renderSection(i, contentWidth)
		if sectionContent == "" {
			continue
		}

		// Separate adjacent sections with the same rule the central
		// column draws between its stacked panes.
		if prev >= 0 {
			lines = append(lines, renderHorizontalSeparator(contentWidth))
			s.separators = append(s.separators,
				overviewSeparator{row: row, above: prev, below: i})
			row++
		}
		lines = append(lines, sectionContent)
		row += lipgloss.Height(sectionContent)
		prev = i
	}

	return lines
}

// renderSection renders a single section, always exactly Height rows so
// the layout matches the allocation and stays put while paging.
func (s *RunOverviewSidebar) renderSection(idx, width int) string {
	section := &s.sections[idx]

	if len(section.FilteredItems) == 0 || section.Height == 0 {
		return ""
	}

	var lines []string

	// Render section header.
	lines = append(lines, s.renderSectionHeader(section, width))

	// Render section items.
	itemLines := s.renderSectionItems(section, width)
	lines = append(lines, itemLines...)

	// A partial last page still occupies the section's allocated rows.
	for len(lines) < section.Height {
		lines = append(lines, "")
	}

	return lipgloss.JoinVertical(lipgloss.Top, lines...)
}

// renderSectionHeader renders the section title with pagination info,
// truncated to a single row (the section heights budget one row for it).
func (s *RunOverviewSidebar) renderSectionHeader(
	section *PagedList[KeyValuePair],
	width int,
) string {
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

	header := titleStyle.Render(titleText) + navInfoStyle.Render(infoText)
	return lipgloss.NewStyle().MaxWidth(width).Render(header)
}

// buildSectionInfo builds the pagination/count info string for a section.
func (s *RunOverviewSidebar) buildSectionInfo(
	section *PagedList[KeyValuePair],
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
func (s *RunOverviewSidebar) renderSectionItems(
	section *PagedList[KeyValuePair],
	width int,
) []string {
	maxKeyWidth := int(float64(width) * sidebarKeyWidthRatio)
	maxValueWidth := width - maxKeyWidth - 3

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
	section *PagedList[KeyValuePair],
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

	gap := " "
	if isHighlighted {
		gap = runOverviewSidebarHighlightedItem.Render(" ")
		renderedValue := valueStyle.Width(maxValueWidth).Render(value)
		return renderedKey + gap + renderedValue
	}
	return renderedKey + gap + valueStyle.MaxWidth(maxValueWidth).Render(value)
}

// activateSelection ensures that exactly one section is marked active (if possible).
// It is used when the sidebar gains focus after being deactivated.
func (s *RunOverviewSidebar) activateSelection() {
	if len(s.sections) == 0 {
		return
	}
	if s.hasActiveSection() {
		return
	}

	// Prefer the current activeSection if it is still usable.
	if s.isValidActiveSection() {
		sec := &s.sections[s.activeSection]
		if sec.ItemsPerPage() > 0 && len(sec.FilteredItems) > 0 {
			s.setActiveSection(s.activeSection)
			return
		}
	}

	s.selectFirstAvailableItem()
}

// focusableSectionBounds returns the first and last sections that currently have
// visible items and can accept navigation. If none exist, it returns (-1, -1).
func (s *RunOverviewSidebar) focusableSectionBounds() (first, last int) {
	first, last = -1, -1
	for i := range s.sections {
		sec := &s.sections[i]
		if sec.ItemsPerPage() == 0 || len(sec.FilteredItems) == 0 {
			continue
		}
		if first == -1 {
			first = i
		}
		last = i
	}
	return first, last
}

// sidebarContentWidth returns the width available for text content
// after subtracting border and padding.
func (s *RunOverviewSidebar) sidebarContentWidth(width int) int {
	return sidebarContentWidth(width)
}

// sidebarInnerWidth returns the width for the lipgloss Style
// (includes padding, excludes border).
func (s *RunOverviewSidebar) sidebarInnerWidth(width int) int {
	return sidebarInnerWidth(width)
}

func (s *RunOverviewSidebar) tagColorScheme() string {
	scheme := s.config.TagColorScheme()
	if _, ok := colorSchemes[scheme]; ok {
		return scheme
	}

	return DefaultTagColorScheme
}

func wrapHeaderText(text string, maxWidth int) []string {
	if maxWidth <= 0 {
		return []string{text}
	}

	parts := strings.Split(text, "\n")
	lines := make([]string, 0, len(parts))
	for _, part := range parts {
		if strings.TrimSpace(part) == "" {
			lines = append(lines, "")
			continue
		}
		lines = append(lines, wrapHeaderParagraph(part, maxWidth)...)
	}
	if len(lines) == 0 {
		return []string{""}
	}
	return lines
}

func wrapHeaderParagraph(text string, maxWidth int) []string {
	words := strings.Fields(text)
	if len(words) == 0 {
		return []string{""}
	}

	lines := make([]string, 0, 1)
	current := words[0]
	if lipgloss.Width(current) > maxWidth {
		forced := wrapSingleLine(current, maxWidth)
		lines = append(lines, forced[:len(forced)-1]...)
		current = forced[len(forced)-1]
	}

	for _, word := range words[1:] {
		candidate := current + " " + word
		if lipgloss.Width(candidate) <= maxWidth {
			current = candidate
			continue
		}

		lines = append(lines, current)
		if lipgloss.Width(word) <= maxWidth {
			current = word
			continue
		}

		forced := wrapSingleLine(word, maxWidth)
		lines = append(lines, forced[:len(forced)-1]...)
		current = forced[len(forced)-1]
	}

	lines = append(lines, current)
	return lines
}
