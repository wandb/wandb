package leet

import (
	"fmt"
	"strings"
	"time"

	"github.com/charmbracelet/lipgloss"
	"github.com/mattn/go-runewidth"
)

const (
	// Same ratio you already use.
	BottomBarHeightRatio = SidebarWidthRatio

	// Minimum *total* height: border + header + 1 content line.
	BottomBarMinHeight = 3

	bottomBarHeader      = "Console Logs"
	bottomBarBorderLines = 1
	bottomBarHeaderLines = 1

	bottomBarKeyWidthRatio = 0.12
)

type BottomBar struct {
	animState *AnimationState

	logs []KeyValuePair

	// cursor is the selected log index (logical row).
	cursor int
	// top is the first visible log index.
	top int

	active     bool
	autoScroll bool

	// Cached layout params from most recent View().
	lastValueWidth   int
	lastContentLines int
}

func NewBottomBar() *BottomBar {
	return &BottomBar{
		animState:  NewAnimationState(false, BottomBarMinHeight),
		autoScroll: true,
	}
}

func (b *BottomBar) Height() int               { return b.animState.Width() }
func (b *BottomBar) IsVisible() bool           { return b.animState.IsVisible() }
func (b *BottomBar) IsAnimating() bool         { return b.animState.IsAnimating() }
func (b *BottomBar) IsExpanded() bool          { return b.animState.IsExpanded() }
func (b *BottomBar) Toggle()                   { b.animState.Toggle() }
func (b *BottomBar) Update(now time.Time) bool { return b.animState.Update(now) }

func (b *BottomBar) Active() bool          { return b.active }
func (b *BottomBar) SetActive(active bool) { b.active = active }

func (b *BottomBar) SetExpandedHeight(h int) {
	b.animState.SetExpandedWidth(max(h, BottomBarMinHeight))
}

func (b *BottomBar) UpdateExpandedHeight(maxTerminalHeight int) {
	maxHeight := int(float64(maxTerminalHeight) * BottomBarHeightRatio)
	b.SetExpandedHeight(maxHeight)
}

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

func (b *BottomBar) View(width int) string {
	h := b.Height()
	if width <= 0 || h < BottomBarMinHeight {
		return ""
	}

	innerH := h - bottomBarBorderLines
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

	header := b.renderHeader(b.top, end, len(b.logs))
	content := b.renderContent(maxKeyWidth, maxValueWidth, contentLines, b.top, end)

	body := lipgloss.JoinVertical(lipgloss.Left, header, content)
	placed := lipgloss.Place(width, h, lipgloss.Left, lipgloss.Top, body)

	return bottomBarBorderStyle.Width(width).Height(h).Render(placed)
}

func (b *BottomBar) renderHeader(startIdx, endIdx, total int) string {
	title := bottomBarHeaderStyle.Render(bottomBarHeader)

	if total == 0 {
		return title
	}

	info := fmt.Sprintf(" [%d-%d of %d]", startIdx+1, endIdx, total)
	return title + navInfoStyle.Render(info)
}

func (b *BottomBar) renderContent(
	maxKeyWidth, maxValueWidth, contentLines, startIdx, endIdx int,
) string {
	if contentLines <= 0 {
		return ""
	}
	if len(b.logs) == 0 {
		return strings.Repeat("\n", contentLines-1)
	}

	startIdx = clamp(startIdx, 0, len(b.logs)-1)
	endIdx = clamp(endIdx, startIdx, len(b.logs))

	var out []string
	used := 0

	for i := startIdx; i < endIdx && used < contentLines; i++ {
		remaining := contentLines - used
		entry, lines := b.renderEntry(b.logs[i], i == b.cursor && b.active, maxKeyWidth, maxValueWidth, remaining)
		out = append(out, entry)
		used += lines
	}

	for used < contentLines {
		out = append(out, "")
		used++
	}

	return lipgloss.JoinVertical(lipgloss.Left, out...)
}

func (b *BottomBar) renderEntry(item KeyValuePair, highlighted bool, maxKeyWidth, maxValueWidth, maxLines int) (string, int) {
	keyStyle := bottomBarTimestampStyle
	valueStyle := bottomBarValueStyle
	if highlighted {
		keyStyle = bottomBarHighlightedTimestampStyle
		valueStyle = bottomBarHighlightedValueStyle
	}

	key := truncateValue(item.Key, maxKeyWidth)
	lines := wrapText(item.Value, maxValueWidth)

	truncated := false
	if len(lines) > maxLines {
		lines = lines[:maxLines]
		truncated = true
	}
	if truncated && len(lines) > 0 {
		lines[len(lines)-1] = withEllipsis(lines[len(lines)-1], maxValueWidth)
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

func (b *BottomBar) ScrollToEnd() {
	b.autoScroll = true
	b.scrollToEnd()
}

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

	for b.cursor >= b.visibleEnd(b.top, b.lastValueWidth, b.lastContentLines) && b.top < len(b.logs)-1 {
		b.top++
	}
}

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

func withEllipsis(line string, maxWidth int) string {
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

// wrappedLineCount counts how many screen lines text occupies when wrapped at maxWidth.
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

// wrapText wraps text into multiple lines at maxWidth (preserving embedded newlines).
func wrapText(text string, maxWidth int) []string {
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
