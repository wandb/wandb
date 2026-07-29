package leet

import (
	"math"
	"strings"

	"charm.land/lipgloss/v2"
)

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

const (
	// sidebarDragMinWidth is the narrowest a sidebar override can make it.
	// Deliberately smaller than SidebarMinWidth so users can shrink
	// sidebars below the default clamp.
	sidebarDragMinWidth = 20

	// mainDragMinWidth is the narrowest the main content column can be
	// squeezed to by a sidebar override.
	mainDragMinWidth = 24
)

// expandedSidebarWidth returns a sidebar's expanded width: a user-dragged
// fraction of the terminal width when set (non-zero), or the golden-ratio
// default. Dragged widths may go below the default minimum but always leave
// room for the main content column.
func expandedSidebarWidth(terminalWidth int, oppositeVisible bool, frac float64) int {
	if frac > 0 {
		maxW := max(terminalWidth-mainDragMinWidth, sidebarDragMinWidth)
		w := int(math.Round(float64(terminalWidth) * frac))
		return clamp(w, sidebarDragMinWidth, maxW)
	}

	ratio := SidebarWidthRatio
	if oppositeVisible {
		ratio = SidebarWidthRatioBoth
	}
	return clamp(int(float64(terminalWidth)*ratio), SidebarMinWidth, SidebarMaxWidth)
}

// minFlexMetricsHeight is the shortest the flex metrics section can be
// squeezed to by the fixed panes below it.
const minFlexMetricsHeight = 5

// fitSidebarFractions clamps sidebar override fractions so both expanded
// sidebars together leave the main content column its minimum width. Only
// overridden (non-zero) fractions are adjusted; the golden-ratio defaults
// already fit jointly.
func fitSidebarFractions(
	width int,
	leftVisible, rightVisible bool,
	leftFrac, rightFrac float64,
) (float64, float64) {
	if width <= 0 || !leftVisible || !rightVisible ||
		(leftFrac <= 0 && rightFrac <= 0) {
		return leftFrac, rightFrac
	}

	leftW := expandedSidebarWidth(width, true, leftFrac)
	rightW := expandedSidebarWidth(width, true, rightFrac)
	total := width - mainDragMinWidth
	if leftW+rightW <= total {
		return leftFrac, rightFrac
	}

	newLeft, newRight := leftW, rightW
	switch {
	case rightFrac <= 0: // Only the left override can shrink.
		newLeft = total - rightW
	case leftFrac <= 0: // Only the right override can shrink.
		newRight = total - leftW
	default: // Shrink both, proportionally.
		newLeft = leftW * total / (leftW + rightW)
		newRight = total - newLeft
	}

	if leftFrac > 0 {
		leftFrac = float64(max(newLeft, sidebarDragMinWidth)) / float64(width)
	}
	if rightFrac > 0 {
		rightFrac = float64(max(newRight, sidebarDragMinWidth)) / float64(width)
	}
	return leftFrac, rightFrac
}

// paneHeightFor returns a stacked pane's expanded height for the given
// override fraction of the terminal height, or the fallback default when no
// override is set. The pane's own SetExpandedHeight enforces its minimum.
func paneHeightFor(frac float64, terminalHeight, fallback int) int {
	if frac <= 0 {
		return fallback
	}
	return int(math.Round(float64(terminalHeight) * frac))
}

// fitStackHeights lowers the fixed stacked panes' heights to fit budget so
// overridden panes cannot crowd out the flex metrics section or overflow
// the stack. Each pane gives up slack above its own minimum, proportionally
// — the panes re-inflate anything below their minimums, which would
// silently undo a plain proportional scale. When even the minimums exceed
// the budget the panes keep their minimums (tiny-terminal degradation the
// renderer crops).
func fitStackHeights(heights, minimums []int, budget int) {
	sum, slack := 0, 0
	for i := range heights {
		sum += heights[i]
		slack += max(heights[i]-minimums[i], 0)
	}
	over := sum - max(budget, 0)
	if over <= 0 {
		return
	}
	if over >= slack {
		for i := range heights {
			heights[i] = min(heights[i], minimums[i])
		}
		return
	}

	left := over
	for i := range heights {
		cut := over * max(heights[i]-minimums[i], 0) / slack
		heights[i] -= cut
		left -= cut
	}
	// Integer-division dust: take the remainder from panes with slack.
	for i := range heights {
		if left == 0 {
			break
		}
		cut := min(left, max(heights[i]-minimums[i], 0))
		heights[i] -= cut
		left -= cut
	}
}

// sidebarContentWidth returns the width available for text content inside a
// sidebar after subtracting the vertical border and both padding columns.
func sidebarContentWidth(totalWidth int) int {
	return max(totalWidth-SidebarOverhead, 0)
}

// sidebarInnerWidth returns the width to pass to the sidebar's lipgloss Style
// (includes content + padding, excludes the border column).
func sidebarInnerWidth(totalWidth int) int {
	return max(totalWidth-SidebarBorderCols, 0)
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

// placeMainColumn pads or crops content to exactly width x height. Mouse
// hit-testing maps screen rows to sections via computeVerticalStackLayout,
// so rendered content must never spill past its reserved rows —
// lipgloss.Place pads short content but never crops tall content (e.g. the
// metrics grid's minimum chart height in a short section).
func placeMainColumn(width, height int, content string) string {
	if width <= 0 || height <= 0 {
		return ""
	}
	if lines := strings.Split(content, "\n"); len(lines) > height {
		content = strings.Join(lines[:height], "\n")
	}
	return lipgloss.Place(width, height, lipgloss.Left, lipgloss.Top, content)
}
