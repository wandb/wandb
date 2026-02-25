package leet

import (
	"fmt"
	"strings"
	"time"

	"github.com/charmbracelet/lipgloss"
	"github.com/mattn/go-runewidth"
)

// ConsoleLogsPane layout constants.
const (
	// ConsoleLogsPaneHeightRatio controls the fraction of total terminal height
	// allocated to the bottom bar when expanded. Uses the same golden-ratio
	// derived value as the sidebar width.
	ConsoleLogsPaneHeightRatio = SidebarWidthRatio

	// ConsoleLogsPaneMinHeight is the minimum total height for the bottom bar.
	ConsoleLogsPaneMinHeight = consoleLogsBorderLines +
		consoleLogsPaddingLines + consoleLogsHeaderLines + 1

	consoleLogsPaneHeader   = "Console Logs"
	consoleLogsBorderLines  = 1
	consoleLogsPaddingLines = 1
	consoleLogsHeaderLines  = 1

	// consoleLogsKeyWidthRatio is the fraction of the bar's width reserved
	// for the timestamp key column.
	consoleLogsKeyWidthRatio = 0.12

	consoleLogTimestampFullWidth  = len("00:00:00") // HH:MM:SS
	consoleLogTimestampShortWidth = len("00:00")    // HH:MM
)

// consoleLogKeyForWidth returns the key text to render within the timestamp column.
//
// It adapts to narrow columns to avoid showing partial timestamps:
//   - "HH:MM:SS" when there is room
//   - "HH:MM" when there is room for minutes but not seconds
//   - "" when there isn't room for "HH:MM"
func consoleLogKeyForWidth(
	key string,
	maxKeyWidth int,
	keyStyle *lipgloss.Style,
) string {
	// The timestamp styles include padding. Subtract the style's "empty render" width
	// so we only consider the columns available for the timestamp text itself.
	available := maxKeyWidth - lipgloss.Width(keyStyle.Render(""))
	if available < consoleLogTimestampShortWidth {
		return ""
	}
	if available < consoleLogTimestampFullWidth {
		return key[:consoleLogTimestampShortWidth]
	}
	return key
}

// ConsoleLogsPane is a collapsible, scrollable panel that displays console log
// output at the bottom of the main content area.
//
// It supports animated expand/collapse via [AnimatedValue], virtual
// scrolling over wrapped log entries, auto-scroll to follow new output,
// and manual navigation (up/down/page-up/page-down) that freezes
// auto-scroll when the user moves away from the tail.
type ConsoleLogsPane struct {
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

// NewConsoleLogsPane returns a collapsed ConsoleLogsPane with auto-scroll enabled.
func NewConsoleLogsPane() *ConsoleLogsPane {
	return &ConsoleLogsPane{
		animState:  NewAnimatedValue(false, ConsoleLogsPaneMinHeight),
		autoScroll: true,
	}
}

// Height returns the current rendered height (may be mid-animation).
func (c *ConsoleLogsPane) Height() int { return c.animState.Value() }

// IsVisible reports whether the bar occupies any screen space.
func (c *ConsoleLogsPane) IsVisible() bool { return c.animState.IsVisible() }

// IsAnimating reports whether an expand/collapse animation is in progress.
func (c *ConsoleLogsPane) IsAnimating() bool { return c.animState.IsAnimating() }

// IsExpanded reports whether the bar is stably at its expanded height.
func (c *ConsoleLogsPane) IsExpanded() bool { return c.animState.IsExpanded() }

// Toggle initiates an expand or collapse animation.
func (c *ConsoleLogsPane) Toggle() { c.animState.Toggle() }

// Update advances the animation by one frame. Returns true when complete.
func (c *ConsoleLogsPane) Update(now time.Time) bool { return c.animState.Update(now) }

// Active reports whether the bottom bar currently holds keyboard focus.
func (c *ConsoleLogsPane) Active() bool { return c.active }

// SetActive sets whether the bottom bar holds keyboard focus.
func (c *ConsoleLogsPane) SetActive(active bool) { c.active = active }

// SetExpandedHeight sets the expanded height, clamped to [ConsoleLogsPaneMinHeight].
func (c *ConsoleLogsPane) SetExpandedHeight(h int) {
	c.animState.SetExpanded(max(h, ConsoleLogsPaneMinHeight))
}

// UpdateExpandedHeight recalculates the expanded height from the terminal
// height using [ConsoleLogsPaneHeightRatio].
func (c *ConsoleLogsPane) UpdateExpandedHeight(maxTerminalHeight int) {
	maxHeight := int(float64(maxTerminalHeight) * ConsoleLogsPaneHeightRatio)
	c.SetExpandedHeight(maxHeight)
}

// SetConsoleLogs replaces the displayed log entries and adjusts the
// viewport. If auto-scroll is enabled, the view snaps to the tail.
func (c *ConsoleLogsPane) SetConsoleLogs(items []KeyValuePair) {
	c.logs = items

	if len(c.logs) == 0 {
		c.cursor = 0
		c.top = 0
		c.autoScroll = true
		return
	}

	c.cursor = clamp(c.cursor, 0, len(c.logs)-1)
	c.top = clamp(c.top, 0, len(c.logs)-1)

	if c.autoScroll {
		c.scrollToEnd()
	} else {
		c.ensureCursorVisible()
	}
}

// View renders the console logs pane at the given width.
//
// Returns an empty string when the pane is collapsed or the width is
// insufficient. The rendered output includes the border, header with
// range indicator, and wrapped/truncated log content.
func (c *ConsoleLogsPane) View(width int, runLabel, hint string) string {
	h := c.Height()
	if width <= 0 || h < ConsoleLogsPaneMinHeight {
		return ""
	}

	// innerH is the content area inside border + padding.
	// lipgloss renders: border(1) + Height(innerH) + padding(1) = h total.
	innerH := h - consoleLogsBorderLines - consoleLogsPaddingLines
	contentLines := max(innerH-consoleLogsHeaderLines, 1)

	maxKeyWidth := max(int(float64(width)*consoleLogsKeyWidthRatio), 1)
	maxKeyWidth = min(maxKeyWidth, max(width-2, 1))
	maxValueWidth := max(width-maxKeyWidth-1, 1)

	c.lastValueWidth = maxValueWidth
	c.lastContentLines = contentLines

	if c.autoScroll {
		c.scrollToEnd()
	} else {
		c.ensureCursorVisible()
	}

	end := c.visibleEnd(c.top, maxValueWidth, contentLines)

	header := c.renderHeader(width, runLabel, c.top, end, len(c.logs))
	content := c.renderContent(maxKeyWidth, maxValueWidth, contentLines, c.top, end, hint)

	body := lipgloss.JoinVertical(lipgloss.Left, header, content)
	placed := lipgloss.Place(width, innerH, lipgloss.Left, lipgloss.Top, body)

	return consoleLogsPaneBorderStyle.Width(width).Height(innerH).Render(placed)
}

// renderHeader returns the "Console Logs • <runLabel>     [X-Y of N]" line,
func (c *ConsoleLogsPane) renderHeader(
	width int, runLabel string, startIdx, endIdx, total int) string {
	title := consoleLogsPaneHeaderStyle.Render(consoleLogsPaneHeader)
	navInfo := navInfoStyle.Render(c.buildNavigationInfo(startIdx, endIdx, total))

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
func (c *ConsoleLogsPane) buildNavigationInfo(startIdx, endIdx, total int) string {
	if total == 0 {
		return ""
	}
	return fmt.Sprintf(" [%d-%d of %d]", startIdx+1, endIdx, total)
}

// renderContent builds the visible log lines, padding with blank lines
// if the content doesn't fill the available space.
func (c *ConsoleLogsPane) renderContent(
	maxKeyWidth, maxValueWidth, contentLines, startIdx, endIdx int,
	hint string,
) string {
	if contentLines <= 0 {
		return ""
	}
	if len(c.logs) == 0 {
		if hint == "" {
			hint = "No data."
		}
		if contentLines <= 1 {
			return consoleLogsPaneTimestampStyle.Render(hint)
		}
		return consoleLogsPaneTimestampStyle.Render(
			hint + strings.Repeat("\n", contentLines-1))
	}

	startIdx = clamp(startIdx, 0, len(c.logs)-1)
	endIdx = clamp(endIdx, startIdx, len(c.logs))

	var out []string
	used := 0

	for i := startIdx; i < endIdx && used < contentLines; i++ {
		remaining := contentLines - used
		entry, lines := c.renderEntry(
			c.logs[i], i == c.cursor && c.active, maxKeyWidth, maxValueWidth, remaining)
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
func (c *ConsoleLogsPane) renderEntry(
	item KeyValuePair, highlighted bool, maxKeyWidth, maxValueWidth, maxLines int) (string, int) {
	keyStyle := consoleLogsPaneTimestampStyle
	valueStyle := consoleLogsPaneValueStyle
	if highlighted {
		keyStyle = consoleLogsPaneHighlightedTimestampStyle
		valueStyle = consoleLogsPaneHighlightedValueStyle
	}

	key := consoleLogKeyForWidth(item.Key, maxKeyWidth, &keyStyle)
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
			gap := consoleLogsPaneHighlightedValueStyle.Render(" ")
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
func (c *ConsoleLogsPane) Up() {
	if len(c.logs) == 0 {
		return
	}
	if c.cursor == 0 {
		c.cursor = len(c.logs) - 1
		c.scrollToEnd()
	} else {
		c.cursor--
		c.ensureCursorVisible()
	}
	c.updateAutoScroll()
}

// Down moves the cursor one entry toward the bottom, wrapping to the
// first entry when at the end.
func (c *ConsoleLogsPane) Down() {
	if len(c.logs) == 0 {
		return
	}
	if c.cursor == len(c.logs)-1 {
		c.cursor = 0
		c.top = 0
	} else {
		c.cursor++
		c.ensureCursorVisible()
	}
	c.updateAutoScroll()
}

// PageDown advances the viewport by one screenful, wrapping to the top
// when past the end.
func (c *ConsoleLogsPane) PageDown() {
	if len(c.logs) == 0 {
		return
	}
	if c.lastContentLines <= 0 || c.lastValueWidth <= 0 {
		c.Down()
		return
	}

	end := c.visibleEnd(c.top, c.lastValueWidth, c.lastContentLines)
	if end >= len(c.logs) {
		c.cursor = 0
		c.top = 0
		c.updateAutoScroll()
		return
	}

	c.top = end
	c.cursor = end
	c.ensureCursorVisible()
	c.updateAutoScroll()
}

// PageUp moves the viewport back by one screenful, wrapping to the end
// when before the start.
func (c *ConsoleLogsPane) PageUp() {
	if len(c.logs) == 0 {
		return
	}
	if c.lastContentLines <= 0 || c.lastValueWidth <= 0 {
		c.Up()
		return
	}

	if c.top == 0 {
		c.cursor = len(c.logs) - 1
		c.scrollToEnd()
		c.updateAutoScroll()
		return
	}

	newTop := c.top
	used := 0
	for newTop > 0 && used < c.lastContentLines {
		prev := newTop - 1
		h := wrappedLineCount(c.logs[prev].Value, c.lastValueWidth)
		if used+h > c.lastContentLines && used > 0 {
			break
		}
		used += min(h, c.lastContentLines-used)
		newTop = prev
	}

	c.top = newTop
	c.cursor = newTop
	c.ensureCursorVisible()
	c.updateAutoScroll()
}

// ScrollToEnd snaps the viewport to show the last log entry and
// re-enables auto-scroll.
func (c *ConsoleLogsPane) ScrollToEnd() {
	c.autoScroll = true
	c.scrollToEnd()
}

// ---- Internal scrolling ----

// updateAutoScroll enables auto-scroll when the cursor is on the last
// entry, and disables it otherwise.
func (c *ConsoleLogsPane) updateAutoScroll() {
	if len(c.logs) == 0 {
		c.autoScroll = true
		return
	}
	if c.cursor == len(c.logs)-1 {
		c.autoScroll = true
		c.scrollToEnd()
		return
	}
	c.autoScroll = false
}

// ensureCursorVisible adjusts top so that the cursor entry is within the
// visible window.
func (c *ConsoleLogsPane) ensureCursorVisible() {
	if len(c.logs) == 0 {
		c.cursor = 0
		c.top = 0
		return
	}

	c.cursor = clamp(c.cursor, 0, len(c.logs)-1)
	c.top = clamp(c.top, 0, len(c.logs)-1)

	if c.cursor < c.top {
		c.top = c.cursor
		return
	}

	for c.cursor >= c.visibleEnd(
		c.top, c.lastValueWidth, c.lastContentLines) && c.top < len(c.logs)-1 {
		c.top++
	}
}

// scrollToEnd positions the viewport so the last entry is at the bottom.
func (c *ConsoleLogsPane) scrollToEnd() {
	if len(c.logs) == 0 {
		c.cursor = 0
		c.top = 0
		return
	}
	c.cursor = len(c.logs) - 1

	if c.lastContentLines <= 0 || c.lastValueWidth <= 0 {
		c.top = c.cursor
		return
	}

	top := c.cursor
	used := min(wrappedLineCount(c.logs[top].Value, c.lastValueWidth), c.lastContentLines)

	for top > 0 && used < c.lastContentLines {
		prev := top - 1
		h := wrappedLineCount(c.logs[prev].Value, c.lastValueWidth)
		if used+h > c.lastContentLines {
			break
		}
		used += h
		top = prev
	}

	c.top = top
}

// visibleEnd returns the exclusive end index of log entries that fit
// within contentLines screen rows starting from startIdx, accounting
// for line wrapping.
func (c *ConsoleLogsPane) visibleEnd(startIdx, maxValueWidth, contentLines int) int {
	if len(c.logs) == 0 {
		return 0
	}
	startIdx = clamp(startIdx, 0, len(c.logs)-1)

	used := 0
	i := startIdx
	for i < len(c.logs) && used < contentLines {
		remaining := contentLines - used
		h := wrappedLineCount(c.logs[i].Value, maxValueWidth)
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
