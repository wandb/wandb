package leet

import (
	"fmt"
	"strings"
	"time"

	"github.com/charmbracelet/lipgloss"
)

// Bottom bar constants.
const (
	// BottomBarHeightRatio is the fraction of content height allocated to the
	// bottom panel. Derived from the golden ratio: 1 − 1/φ ≈ 0.382.
	BottomBarHeightRatio = SidebarWidthRatio // 0.382

	// BottomBarMinHeight is the minimum usable height for the panel.
	BottomBarMinHeight = 2

	// bottomBarHeader is the default title rendered in the panel header.
	bottomBarHeader = "Console Logs"

	// bottomBarBorderLines accounts for the top-border decoration.
	bottomBarBorderLines = 1

	// bottomBarHeaderLines accounts for the header row inside the panel.
	bottomBarHeaderLines = 1

	// bottomBarKeyWidthRatio controls the timestamp column width.
	bottomBarKeyWidthRatio = 0.12
)

// BottomBar represents a collapsible bottom panel for console logs.
//
// It reuses [AnimationState] to animate the panel height, mirroring how
// sidebars animate their width. Console log content is rendered through
// a [PagedList] using key-value pairs (timestamp → content).
type BottomBar struct {
	animState   *AnimationState
	consoleLogs PagedList

	// autoScroll tracks whether the view follows new output.
	// Enabled by default, disabled when the user scrolls away from the end.
	autoScroll bool
}

// NewBottomBar creates a new collapsed bottom bar.
func NewBottomBar() *BottomBar {
	return &BottomBar{
		animState:  NewAnimationState(false, BottomBarMinHeight),
		autoScroll: true,
	}
}

// Toggle toggles between expanded and collapsed states.
func (b *BottomBar) Toggle() {
	b.animState.Toggle()
}

// Height returns the current animated height (0 when fully collapsed).
func (b *BottomBar) Height() int {
	return b.animState.Width()
}

// IsVisible reports whether the panel occupies any vertical space.
func (b *BottomBar) IsVisible() bool {
	return b.animState.IsVisible()
}

// IsAnimating reports whether the panel is mid-animation.
func (b *BottomBar) IsAnimating() bool {
	return b.animState.IsAnimating()
}

// IsExpanded reports whether the panel is stably expanded.
func (b *BottomBar) IsExpanded() bool {
	return b.animState.IsExpanded()
}

// Active reports whether the bottom bar currently has keyboard focus.
func (b *BottomBar) Active() bool {
	return b.consoleLogs.Active
}

// SetActive sets the keyboard focus state.
func (b *BottomBar) SetActive(active bool) {
	b.consoleLogs.Active = active
}

// Update advances the animation; returns true when complete.
func (b *BottomBar) Update(now time.Time) bool {
	return b.animState.Update(now)
}

// SetExpandedHeight updates the target expanded height, typically called
// on window resize so the panel tracks the golden-ratio proportion.
func (b *BottomBar) SetExpandedHeight(h int) {
	b.animState.SetExpandedWidth(max(h, BottomBarMinHeight))
}

// UpdateExpandedHeight recalculates the expanded height from the total
// content height (the area above the status bar).
func (b *BottomBar) UpdateExpandedHeight(totalContentHeight int) {
	h := int(float64(totalContentHeight) * BottomBarHeightRatio)
	b.SetExpandedHeight(h)
}

// SetConsoleLogs updates the displayed log lines from the data model.
//
// When auto-scroll is enabled (the default), the view jumps to the last
// page whenever new items arrive. Scrolling away from the last page
// disables auto-scroll; scrolling back to the end re-enables it.
func (b *BottomBar) SetConsoleLogs(items []KeyValuePair) {
	prevLen := len(b.consoleLogs.FilteredItems)
	b.consoleLogs.Items = items
	b.consoleLogs.FilteredItems = items

	if b.autoScroll && len(items) > prevLen {
		b.scrollToEnd()
	}
}

// ---- Navigation ----

// Up navigates one line up.
func (b *BottomBar) Up() {
	b.consoleLogs.Up()
	b.updateAutoScroll()
}

// Down navigates one line down.
func (b *BottomBar) Down() {
	b.consoleLogs.Down()
	b.updateAutoScroll()
}

// PageUp navigates one page up.
func (b *BottomBar) PageUp() {
	b.consoleLogs.PageUp()
	b.updateAutoScroll()
}

// PageDown navigates one page down.
func (b *BottomBar) PageDown() {
	b.consoleLogs.PageDown()
	b.updateAutoScroll()
}

// ScrollToEnd jumps to the last page and re-enables auto-scroll.
func (b *BottomBar) ScrollToEnd() {
	b.scrollToEnd()
	b.autoScroll = true
}

func (b *BottomBar) scrollToEnd() {
	total := len(b.consoleLogs.FilteredItems)
	if total == 0 || b.consoleLogs.ItemsPerPage() == 0 {
		return
	}
	lastPage := (total - 1) / b.consoleLogs.ItemsPerPage()
	lastLine := (total - 1) % b.consoleLogs.ItemsPerPage()
	b.consoleLogs.SetPageAndLine(lastPage, lastLine)
}

// updateAutoScroll disables auto-scroll when the user navigates away
// from the last page, and re-enables it when they return.
func (b *BottomBar) updateAutoScroll() {
	total := len(b.consoleLogs.FilteredItems)
	if total == 0 || b.consoleLogs.ItemsPerPage() == 0 {
		return
	}
	lastPage := (total - 1) / b.consoleLogs.ItemsPerPage()
	b.autoScroll = b.consoleLogs.CurrentPage() == lastPage
}

// ---- Rendering ----

// View renders the bottom bar panel.
func (b *BottomBar) View(width int) string {
	h := b.Height()
	if h <= 0 || width <= 0 {
		return ""
	}

	innerH := h - bottomBarBorderLines
	if innerH <= BottomBarMinHeight {
		return ""
	}

	contentLines := max(innerH-bottomBarHeaderLines, 1)

	// Column layout: key occupies maxKeyWidth cols (its PaddingLeft is
	// inside that width), then a 1-col gap, then value fills the rest.
	// No padding on the value — mirrors renderItem in RunOverviewSidebar.
	maxKeyWidth := int(float64(width) * bottomBarKeyWidthRatio)
	maxValueWidth := width - maxKeyWidth - 1

	// Set items-per-page to an upper bound (one item per line), then
	// refine based on how many items actually fit with multi-line wrapping.
	b.consoleLogs.SetItemsPerPage(contentLines)
	visibleItems := b.countVisibleItems(maxValueWidth, contentLines)
	b.consoleLogs.SetItemsPerPage(visibleItems)

	header := b.renderHeader(width)
	content := b.renderContent(maxKeyWidth, maxValueWidth, contentLines)
	body := lipgloss.JoinVertical(lipgloss.Left, header, content)

	rendered := bottomBarBorderStyle.
		Width(width).
		MaxWidth(width).
		Render(body)

	// Force exact dimensions: clips overflow (small h) and pads
	// underflow (border/content height mismatch) so the caller can
	// rely on Height() for arithmetic without visual surprises.
	return lipgloss.Place(width, h, lipgloss.Left, lipgloss.Top, rendered)
}

// countVisibleItems returns how many items fit in contentLines visual
// rows, accounting for multi-line wrapping.
func (b *BottomBar) countVisibleItems(maxValueWidth, contentLines int) int {
	total := len(b.consoleLogs.FilteredItems)
	if total == 0 {
		return max(contentLines, 1)
	}

	startIdx := b.consoleLogs.CurrentPage() * b.consoleLogs.ItemsPerPage()
	usedLines := 0
	count := 0

	for i := startIdx; i < total && usedLines < contentLines; i++ {
		n := wrappedLineCount(b.consoleLogs.FilteredItems[i].Value, maxValueWidth)
		if usedLines+n > contentLines && count > 0 {
			break
		}
		usedLines += n
		count++
	}

	return max(count, 1)
}

// renderHeader renders the panel title with optional pagination info.
//
// The header style is constant regardless of focus state, matching the
// behavior of run list and overview sidebar headers.
func (b *BottomBar) renderHeader(width int) string {
	title := bottomBarHeaderStyle.Render(bottomBarHeader)

	total := len(b.consoleLogs.FilteredItems)
	if total == 0 {
		return title
	}

	startIdx := b.consoleLogs.CurrentPage() * b.consoleLogs.ItemsPerPage()
	endIdx := min(startIdx+b.consoleLogs.ItemsPerPage(), total)
	info := navInfoStyle.Render(
		fmt.Sprintf(" [%d-%d of %d]", startIdx+1, endIdx, total),
	)

	return title + info
}

// renderContent renders the visible page of log lines, wrapping long
// values across multiple visual rows.
func (b *BottomBar) renderContent(maxKeyWidth, maxValueWidth, contentLines int) string {
	total := len(b.consoleLogs.FilteredItems)
	if total == 0 {
		return strings.Repeat("\n", max(contentLines-1, 0))
	}

	startIdx := b.consoleLogs.CurrentPage() * b.consoleLogs.ItemsPerPage()
	endIdx := min(startIdx+b.consoleLogs.ItemsPerPage(), total)

	var lines []string
	usedLines := 0

	for i := startIdx; i < endIdx && usedLines < contentLines; i++ {
		item := b.consoleLogs.FilteredItems[i]
		posInPage := i - startIdx
		remaining := contentLines - usedLines

		entry := b.renderEntry(item, posInPage, maxKeyWidth, maxValueWidth, remaining)
		entryHeight := strings.Count(entry, "\n") + 1

		lines = append(lines, entry)
		usedLines += entryHeight
	}

	// Pad remaining lines to fill the content area exactly.
	for usedLines < contentLines {
		lines = append(lines, "")
		usedLines++
	}

	return lipgloss.JoinVertical(lipgloss.Left, lines...)
}

// renderEntry renders a single log entry, potentially spanning multiple
// visual lines. Long values wrap at maxValueWidth; if the wrapped output
// exceeds maxLines the final visual line is truncated with "...".
func (b *BottomBar) renderEntry(
	item KeyValuePair,
	posInPage, maxKeyWidth, maxValueWidth, maxLines int,
) string {
	isHighlighted := b.consoleLogs.Active && posInPage == b.consoleLogs.CurrentLine()

	// Default styles mirror the RunOverviewSidebar pattern:
	//   key   = subtle timestamp with left indent (PaddingLeft baked in)
	//   value = colorItemValue, no padding
	keyStyle := bottomBarTimestampStyle
	valueStyle := bottomBarValueStyle

	if isHighlighted {
		// Selection background on both columns. PaddingLeft on the key
		// preserves the indent that bottomBarTimestampStyle provides.
		keyStyle = bottomBarHighlightedTimestampStyle
		valueStyle = bottomBarHighlightedValueStyle
	}

	key := truncateValue(item.Key, maxKeyWidth)
	valueLines := wrapText(item.Value, maxValueWidth)

	// Truncate wrapped lines that exceed available visual space.
	if len(valueLines) > maxLines {
		valueLines = valueLines[:maxLines]
		last := valueLines[len(valueLines)-1]
		valueLines[len(valueLines)-1] = truncateValue(last, maxValueWidth)
	}

	rendered := make([]string, 0, len(valueLines))
	for i, vline := range valueLines {
		var k string
		if i == 0 {
			k = keyStyle.Width(maxKeyWidth).Render(key)
		} else {
			// Continuation line: blank key column preserves alignment.
			k = keyStyle.Width(maxKeyWidth).Render("")
		}

		if isHighlighted {
			gap := bottomBarHighlightedValueStyle.Render(" ")
			rendered = append(rendered, k+gap+valueStyle.Width(maxValueWidth).Render(vline))
		} else {
			rendered = append(rendered, k+" "+valueStyle.Render(vline))
		}
	}

	return strings.Join(rendered, "\n")
}

// ---- Text wrapping ----

// wrapText breaks text into lines of at most maxWidth visual columns,
// splitting at character boundaries. Returns a single-element slice when
// the text fits or maxWidth is non-positive.
func wrapText(text string, maxWidth int) []string {
	if maxWidth <= 0 || lipgloss.Width(text) <= maxWidth {
		return []string{text}
	}

	runes := []rune(text)
	var lines []string
	start := 0

	for start < len(runes) {
		end := start
		for end < len(runes) && lipgloss.Width(string(runes[start:end+1])) <= maxWidth {
			end++
		}
		if end == start {
			// At least one rune per line to guarantee progress.
			end = start + 1
		}
		lines = append(lines, string(runes[start:end]))
		start = end
	}

	return lines
}

// wrappedLineCount returns the number of visual lines needed to display
// text within maxWidth columns, without allocating the line slices.
func wrappedLineCount(text string, maxWidth int) int {
	w := lipgloss.Width(text)
	if maxWidth <= 0 || w <= maxWidth {
		return 1
	}
	return (w + maxWidth - 1) / maxWidth
}
