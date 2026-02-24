package leet

import (
	"fmt"
	"strings"
	"time"

	"github.com/charmbracelet/lipgloss"
	"github.com/mattn/go-runewidth"
)

// BottomBar layout constants.
const (
	// BottomBarHeightRatio controls the fraction of total terminal height
	// allocated to the bottom bar when expanded. Uses the same golden-ratio
	// derived value as the sidebar width.
	BottomBarHeightRatio = SidebarWidthRatio

	// BottomBarMinHeight is the minimum total height for the bottom bar.
	BottomBarMinHeight = bottomBarBorderLines +
		bottomBarPaddingLines + bottomBarHeaderLines + 1

	bottomBarHeader       = "Console Logs"
	bottomBarBorderLines  = 1
	bottomBarPaddingLines = 1
	bottomBarHeaderLines  = 1

	// bottomBarKeyWidthRatio is the fraction of the bar's width reserved
	// for the timestamp key column.
	bottomBarKeyWidthRatio = 0.12
)

// BottomBar is a collapsible, scrollable panel that displays console log
// output below the main metrics area.
//
// It supports animated expand/collapse via [AnimatedValue], virtual
// scrolling over wrapped log entries, auto-scroll to follow new output,
// and manual navigation (up/down/page-up/page-down) that freezes
// auto-scroll when the user moves away from the tail.
type BottomBar struct {
	animState *AnimatedValue

	logs []KeyValuePair

	// cursor is the selected log index (logical row).
	cursor int
	// top is the first visible log index.
	top int

	active     bool
	autoScroll bool

	// Cached layout params from the most recent [View] call, used by
	// navigation methods (PageUp/PageDown) to compute page boundaries
	// without re-deriving the layout.
	lastValueWidth   int
	lastContentLines int
}

// NewBottomBar returns a collapsed BottomBar with auto-scroll enabled.
func NewBottomBar() *BottomBar {
	return &BottomBar{
		animState:  NewAnimatedValue(false, BottomBarMinHeight),
		autoScroll: true,
	}
}

// Height returns the current rendered height (may be mid-animation).
func (b *BottomBar) Height() int { return b.animState.Value() }

// IsVisible reports whether the bar occupies any screen space.
func (b *BottomBar) IsVisible() bool { return b.animState.IsVisible() }

// IsAnimating reports whether an expand/collapse animation is in progress.
func (b *BottomBar) IsAnimating() bool { return b.animState.IsAnimating() }

// IsExpanded reports whether the bar is stably at its expanded height.
func (b *BottomBar) IsExpanded() bool { return b.animState.IsExpanded() }

// Toggle initiates an expand or collapse animation.
func (b *BottomBar) Toggle() { b.animState.Toggle() }

// Update advances the animation by one frame. Returns true when complete.
func (b *BottomBar) Update(now time.Time) bool { return b.animState.Update(now) }

// Active reports whether the bottom bar currently holds keyboard focus.
func (b *BottomBar) Active() bool { return b.active }

// SetActive sets whether the bottom bar holds keyboard focus.
func (b *BottomBar) SetActive(active bool) { b.active = active }

// SetExpandedHeight sets the expanded height, clamped to [BottomBarMinHeight].
func (b *BottomBar) SetExpandedHeight(h int) {
	b.animState.SetExpanded(max(h, BottomBarMinHeight))
}

// UpdateExpandedHeight recalculates the expanded height from the terminal
// height using [BottomBarHeightRatio].
func (b *BottomBar) UpdateExpandedHeight(maxTerminalHeight int) {
	maxHeight := int(float64(maxTerminalHeight) * BottomBarHeightRatio)
	b.SetExpandedHeight(maxHeight)
}

// SetConsoleLogs replaces the displayed log entries and adjusts the
// viewport. If auto-scroll is enabled, the view snaps to the tail.
func (b *BottomBar) SetConsoleLogs(items []KeyValuePair) {
	b.logs = items

	if len(b.logs) == 0 {
		b.cursor = 0
		b.top = 0
		b.autoScroll = true
		return
	}

	b.cursor = clamp(b.cursor, 0, len(b.logs)-1)
	b.top = clamp(b.top, 0, len(b.logs)-1)

	if b.autoScroll {
		b.scrollToEnd()
	} else {
		b.ensureCursorVisible()
	}
}

// View renders the bottom bar at the given width.
//
// Returns an empty string when the bar is collapsed or the width is
// insufficient. The rendered output includes the border, header with
// range indicator, and wrapped/truncated log content.
func (b *BottomBar) View(width int, runLabel, hint string) string {
	h := b.Height()
	if width <= 0 || h < BottomBarMinHeight {
		return ""
	}

	// innerH is the content area inside border + padding.
	// lipgloss renders: border(1) + Height(innerH) + padding(1) = h total.
	innerH := h - bottomBarBorderLines - bottomBarPaddingLines
	contentLines := max(innerH-bottomBarHeaderLines, 1)

	maxKeyWidth := max(int(float64(width)*bottomBarKeyWidthRatio), 1)
	maxKeyWidth = min(maxKeyWidth, max(width-2, 1))
	maxValueWidth := max(width-maxKeyWidth-1, 1)

	b.lastValueWidth = maxValueWidth
	b.lastContentLines = contentLines

	if b.autoScroll {
		b.scrollToEnd()
	} else {
		b.ensureCursorVisible()
	}

	end := b.visibleEnd(b.top, maxValueWidth, contentLines)

	header := b.renderHeader(width, runLabel, b.top, end, len(b.logs))
	content := b.renderContent(maxKeyWidth, maxValueWidth, contentLines, b.top, end, hint)

	body := lipgloss.JoinVertical(lipgloss.Left, header, content)
	placed := lipgloss.Place(width, innerH, lipgloss.Left, lipgloss.Top, body)

	return bottomBarBorderStyle.Width(width).Height(innerH).Render(placed)
}

// renderHeader returns the "Console Logs • <runLabel>     [X-Y of N]" line,
func (b *BottomBar) renderHeader(width int, runLabel string, startIdx, endIdx, total int) string {
	title := bottomBarHeaderStyle.Render(bottomBarHeader)
	navInfo := navInfoStyle.Render(b.buildNavigationInfo(startIdx, endIdx, total))

	left := title
	if runLabel != "" {
		sep := " • "
		maxRunWidth := width - lipgloss.Width(title) - lipgloss.Width(navInfo) - lipgloss.Width(sep)
		if maxRunWidth > 0 {
			left = lipgloss.JoinHorizontal(
				lipgloss.Left,
				title,
				navInfoStyle.Render(sep+truncateValue(runLabel, maxRunWidth)),
			)
		}
	}

	fillerWidth := width - lipgloss.Width(left) - lipgloss.Width(navInfo)
	filler := strings.Repeat(" ", max(fillerWidth, 0))
	return lipgloss.JoinHorizontal(lipgloss.Left, left, filler, navInfo)
}

// buildNavigationInfo formats the "[X-Y of N]" range indicator.
func (b *BottomBar) buildNavigationInfo(startIdx, endIdx, total int) string {
	if total == 0 {
		return ""
	}
	return fmt.Sprintf(" [%d-%d of %d]", startIdx+1, endIdx, total)
}

// renderContent builds the visible log lines, padding with blank lines
// if the content doesn't fill the available space.
func (b *BottomBar) renderContent(
	maxKeyWidth, maxValueWidth, contentLines, startIdx, endIdx int,
	hint string,
) string {
	if contentLines <= 0 {
		return ""
	}
	if len(b.logs) == 0 {
		if hint == "" {
			hint = "No data."
		}
		if contentLines <= 1 {
			return bottomBarTimestampStyle.Render(hint)
		}
		return bottomBarTimestampStyle.Render(
			hint + strings.Repeat("\n", contentLines-1))
	}

	startIdx = clamp(startIdx, 0, len(b.logs)-1)
	endIdx = clamp(endIdx, startIdx, len(b.logs))

	var out []string
	used := 0

	for i := startIdx; i < endIdx && used < contentLines; i++ {
		remaining := contentLines - used
		entry, lines := b.renderEntry(
			b.logs[i], i == b.cursor && b.active, maxKeyWidth, maxValueWidth, remaining)
		out = append(out, entry)
		used += lines
	}

	for used < contentLines {
		out = append(out, "")
		used++
	}

	return lipgloss.JoinVertical(lipgloss.Left, out...)
}

// renderEntry renders a single log entry, wrapping the value and showing
// the timestamp key only on the first line. If the entry exceeds maxLines,
// it is truncated with an ellipsis.
func (b *BottomBar) renderEntry(
	item KeyValuePair, highlighted bool, maxKeyWidth, maxValueWidth, maxLines int) (string, int) {
	keyStyle := bottomBarTimestampStyle
	valueStyle := bottomBarValueStyle
	if highlighted {
		keyStyle = bottomBarHighlightedTimestampStyle
		valueStyle = bottomBarHighlightedValueStyle
	}

	key := truncateValue(item.Key, maxKeyWidth)
	lines := WrapText(item.Value, maxValueWidth)

	truncated := false
	if len(lines) > maxLines {
		lines = lines[:maxLines]
		truncated = true
	}
	if truncated && len(lines) > 0 {
		lines[len(lines)-1] = WithEllipsis(lines[len(lines)-1], maxValueWidth)
	}

	var rendered []string
	for i, v := range lines {
		k := ""
		if i == 0 {
			k = keyStyle.Width(maxKeyWidth).Render(key)
		} else {
			k = keyStyle.Width(maxKeyWidth).Render("")
		}

		if highlighted {
			gap := bottomBarHighlightedValueStyle.Render(" ")
			rendered = append(rendered, k+gap+valueStyle.Width(maxValueWidth).Render(v))
		} else {
			rendered = append(rendered, k+" "+valueStyle.Render(v))
		}
	}

	if len(rendered) == 0 {
		k := keyStyle.Width(maxKeyWidth).Render(key)
		rendered = []string{k + " " + valueStyle.Width(maxValueWidth).Render("")}
	}

	return strings.Join(rendered, "\n"), len(rendered)
}

// ---- Navigation ----

// Up moves the cursor one entry toward the top, wrapping to the last
// entry when at the beginning.
func (b *BottomBar) Up() {
	if len(b.logs) == 0 {
		return
	}
	if b.cursor == 0 {
		b.cursor = len(b.logs) - 1
		b.scrollToEnd()
	} else {
		b.cursor--
		b.ensureCursorVisible()
	}
	b.updateAutoScroll()
}

// Down moves the cursor one entry toward the bottom, wrapping to the
// first entry when at the end.
func (b *BottomBar) Down() {
	if len(b.logs) == 0 {
		return
	}
	if b.cursor == len(b.logs)-1 {
		b.cursor = 0
		b.top = 0
	} else {
		b.cursor++
		b.ensureCursorVisible()
	}
	b.updateAutoScroll()
}

// PageDown advances the viewport by one screenful, wrapping to the top
// when past the end.
func (b *BottomBar) PageDown() {
	if len(b.logs) == 0 {
		return
	}
	if b.lastContentLines <= 0 || b.lastValueWidth <= 0 {
		b.Down()
		return
	}

	end := b.visibleEnd(b.top, b.lastValueWidth, b.lastContentLines)
	if end >= len(b.logs) {
		b.cursor = 0
		b.top = 0
		b.updateAutoScroll()
		return
	}

	b.top = end
	b.cursor = end
	b.ensureCursorVisible()
	b.updateAutoScroll()
}

// PageUp moves the viewport back by one screenful, wrapping to the end
// when before the start.
func (b *BottomBar) PageUp() {
	if len(b.logs) == 0 {
		return
	}
	if b.lastContentLines <= 0 || b.lastValueWidth <= 0 {
		b.Up()
		return
	}

	if b.top == 0 {
		b.cursor = len(b.logs) - 1
		b.scrollToEnd()
		b.updateAutoScroll()
		return
	}

	newTop := b.top
	used := 0
	for newTop > 0 && used < b.lastContentLines {
		prev := newTop - 1
		h := wrappedLineCount(b.logs[prev].Value, b.lastValueWidth)
		if used+h > b.lastContentLines && used > 0 {
			break
		}
		used += min(h, b.lastContentLines-used)
		newTop = prev
	}

	b.top = newTop
	b.cursor = newTop
	b.ensureCursorVisible()
	b.updateAutoScroll()
}

// ScrollToEnd snaps the viewport to show the last log entry and
// re-enables auto-scroll.
func (b *BottomBar) ScrollToEnd() {
	b.autoScroll = true
	b.scrollToEnd()
}

// ---- Internal scrolling ----

// updateAutoScroll enables auto-scroll when the cursor is on the last
// entry, and disables it otherwise.
func (b *BottomBar) updateAutoScroll() {
	if len(b.logs) == 0 {
		b.autoScroll = true
		return
	}
	if b.cursor == len(b.logs)-1 {
		b.autoScroll = true
		b.scrollToEnd()
		return
	}
	b.autoScroll = false
}

// ensureCursorVisible adjusts top so that the cursor entry is within the
// visible window.
func (b *BottomBar) ensureCursorVisible() {
	if len(b.logs) == 0 {
		b.cursor = 0
		b.top = 0
		return
	}

	b.cursor = clamp(b.cursor, 0, len(b.logs)-1)
	b.top = clamp(b.top, 0, len(b.logs)-1)

	if b.cursor < b.top {
		b.top = b.cursor
		return
	}

	for b.cursor >= b.visibleEnd(
		b.top, b.lastValueWidth, b.lastContentLines) && b.top < len(b.logs)-1 {
		b.top++
	}
}

// scrollToEnd positions the viewport so the last entry is at the bottom.
func (b *BottomBar) scrollToEnd() {
	if len(b.logs) == 0 {
		b.cursor = 0
		b.top = 0
		return
	}
	b.cursor = len(b.logs) - 1

	if b.lastContentLines <= 0 || b.lastValueWidth <= 0 {
		b.top = b.cursor
		return
	}

	top := b.cursor
	used := min(wrappedLineCount(b.logs[top].Value, b.lastValueWidth), b.lastContentLines)

	for top > 0 && used < b.lastContentLines {
		prev := top - 1
		h := wrappedLineCount(b.logs[prev].Value, b.lastValueWidth)
		if used+h > b.lastContentLines {
			break
		}
		used += h
		top = prev
	}

	b.top = top
}

// visibleEnd returns the exclusive end index of log entries that fit
// within contentLines screen rows starting from startIdx, accounting
// for line wrapping.
func (b *BottomBar) visibleEnd(startIdx, maxValueWidth, contentLines int) int {
	if len(b.logs) == 0 {
		return 0
	}
	startIdx = clamp(startIdx, 0, len(b.logs)-1)

	used := 0
	i := startIdx
	for i < len(b.logs) && used < contentLines {
		remaining := contentLines - used
		h := wrappedLineCount(b.logs[i].Value, maxValueWidth)
		used += min(h, remaining)
		i++
	}
	return i
}

// ---- Text utilities ----

// WithEllipsis truncates line so that the visible width including a
// trailing "..." marker fits within maxWidth.
func WithEllipsis(line string, maxWidth int) string {
	const marker = "..."
	mw := runewidth.StringWidth(marker)
	if maxWidth <= mw {
		return marker[:max(0, maxWidth)]
	}

	target := maxWidth - mw
	var b strings.Builder
	w := 0
	for _, r := range line {
		rw := runewidth.RuneWidth(r)
		if w+rw > target {
			break
		}
		b.WriteRune(r)
		w += rw
	}
	b.WriteString(marker)
	return b.String()
}

// wrappedLineCount counts how many screen lines text occupies when
// soft-wrapped at maxWidth. Embedded newlines are respected.
func wrappedLineCount(text string, maxWidth int) int {
	if maxWidth <= 0 {
		return 1
	}
	parts := strings.Split(text, "\n")
	total := 0
	for _, p := range parts {
		w := runewidth.StringWidth(p)
		if w == 0 {
			total++
			continue
		}
		total += (w + maxWidth - 1) / maxWidth
	}
	return max(total, 1)
}

// WrapText soft-wraps text into multiple lines at maxWidth, preserving
// embedded newlines.
func WrapText(text string, maxWidth int) []string {
	if maxWidth <= 0 {
		return []string{text}
	}

	var out []string
	for _, part := range strings.Split(text, "\n") {
		out = append(out, wrapSingleLine(part, maxWidth)...)
	}
	if len(out) == 0 {
		return []string{""}
	}
	return out
}

// wrapSingleLine breaks a single line (no embedded newlines) into
// chunks that each fit within maxWidth display columns.
func wrapSingleLine(s string, maxWidth int) []string {
	if runewidth.StringWidth(s) <= maxWidth {
		return []string{s}
	}

	runes := []rune(s)
	var lines []string

	for start := 0; start < len(runes); {
		w := 0
		end := start
		for end < len(runes) {
			rw := runewidth.RuneWidth(runes[end])
			if w+rw > maxWidth && end > start {
				break
			}
			w += rw
			end++
			if w >= maxWidth {
				break
			}
		}
		lines = append(lines, string(runes[start:end]))
		start = end
	}

	return lines
}
