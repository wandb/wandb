package leet

import "charm.land/lipgloss/v2"

// stackSectionID identifies a vertically stacked pane in the main content area.
type stackSectionID int

const (
	stackSectionMetrics stackSectionID = iota
	stackSectionSystemMetrics
	stackSectionMedia
	stackSectionConsoleLogs
	stackSectionCount
)

// stackSectionSpec describes one pane in a vertical stack.
type stackSectionSpec struct {
	ID      stackSectionID
	Visible bool
	Height  int
	Flex    bool
}

// stackSectionLayout stores the computed origin and height of one pane.
type stackSectionLayout struct {
	Y      int
	Height int
}

// verticalStackLayout is a small flexbox-style layout for the central column.
//
// Fixed-height panes (system/media/logs) keep their current animated heights.
// The optional flex pane (metrics) consumes the remaining height after gaps.
type verticalStackLayout struct {
	TotalHeight  int
	VisibleCount int
	Sections     [stackSectionCount]stackSectionLayout
}

// computeVerticalStackLayout computes a top-to-bottom stack with a 1-line gap
// between adjacent visible panes.
func computeVerticalStackLayout(
	totalHeight int,
	specs ...stackSectionSpec,
) verticalStackLayout {
	layout := verticalStackLayout{TotalHeight: max(totalHeight, 0)}

	visible := make([]stackSectionSpec, 0, len(specs))
	fixedHeight := 0
	flexIndex := -1
	for _, spec := range specs {
		if !spec.Visible {
			continue
		}
		spec.Height = max(spec.Height, 0)
		if spec.Flex {
			flexIndex = len(visible)
		} else {
			fixedHeight += spec.Height
		}
		visible = append(visible, spec)
	}

	layout.VisibleCount = len(visible)
	if len(visible) == 0 {
		return layout
	}

	gapLines := max(len(visible)-1, 0)
	remaining := max(layout.TotalHeight-fixedHeight-gapLines, 0)
	if flexIndex >= 0 {
		visible[flexIndex].Height = remaining
	}

	y := 0
	for i, spec := range visible {
		layout.Sections[spec.ID] = stackSectionLayout{Y: y, Height: spec.Height}
		y += spec.Height
		if i < len(visible)-1 {
			y++
		}
	}

	return layout
}

func (l verticalStackLayout) Height(id stackSectionID) int {
	if id < 0 || id >= stackSectionCount {
		return 0
	}
	return l.Sections[id].Height
}

func (l verticalStackLayout) Y(id stackSectionID) int {
	if id < 0 || id >= stackSectionCount {
		return 0
	}
	return l.Sections[id].Y
}

func expandedSidebarWidth(terminalWidth int, oppositeVisible bool) int {
	ratio := SidebarWidthRatio
	if oppositeVisible {
		ratio = SidebarWidthRatioBoth
	}
	return clamp(int(float64(terminalWidth)*ratio), SidebarMinWidth, SidebarMaxWidth)
}

func filterNonEmptySections(sections []string) []string {
	filtered := make([]string, 0, len(sections))
	for _, section := range sections {
		if section == "" {
			continue
		}
		filtered = append(filtered, section)
	}
	return filtered
}

func placeMainColumn(width, height int, content string) string {
	if width <= 0 || height <= 0 {
		return ""
	}
	return lipgloss.Place(width, height, lipgloss.Left, lipgloss.Top, content)
}
