// inspectorview.go
//
// Rendering for the record inspector: the record list, the prototext
// detail pane, and the status bar.
package leet

import (
	"fmt"
	"strings"

	"charm.land/lipgloss/v2"
)

// listWidth returns the record list pane width including its border: the
// user-dragged fraction of the terminal width when set, or the
// golden-ratio default, like the main app's sidebars.
func (ins *Inspector) listWidth() int {
	w := expandedSidebarWidth(ins.width, false, ins.drag.overrides().LeftSidebar)
	return min(w, max(ins.width-mainDragMinWidth, 0))
}

// listRowsVisible returns how many record rows fit in the list pane.
func (ins *Inspector) listRowsVisible() int {
	return max(ins.height-StatusBarHeight-inspectorHeaderLines, 0)
}

// renderMainView renders the record list, the detail pane, and the status bar.
func (ins *Inspector) renderMainView() string {
	contentH := max(ins.height-StatusBarHeight, 0)
	listW := ins.listWidth()

	list := ins.renderList(listW, contentH)
	detail := ins.renderDetail(contentH)

	mainView := lipgloss.JoinHorizontal(lipgloss.Top, list, detail)
	statusBar := ins.renderStatusBar()

	fullView := lipgloss.JoinVertical(lipgloss.Left, mainView, statusBar)
	return lipgloss.Place(ins.width, ins.height, lipgloss.Left, lipgloss.Top, fullView)
}

// renderList renders the record list pane with its right border.
func (ins *Inspector) renderList(width, height int) string {
	innerW := max(width-SidebarOverhead, 0)

	lines := make([]string, 0, ins.listRowsVisible()+inspectorHeaderLines)
	lines = append(lines, ins.renderListHeader(innerW))

	if len(ins.list.FilteredItems) == 0 {
		empty := "No records yet."
		if len(ins.list.Items) > 0 {
			empty = "No records match the filter."
		}
		lines = append(lines, labelStyle.Render(truncateValue(empty, innerW)))
	}

	start, end := ins.list.PageBounds()
	numW := 1
	if n := len(ins.list.Items); n > 0 {
		numW = len(fmt.Sprint(ins.list.Items[n-1].Num))
	}
	for i := start; i < end; i++ {
		lines = append(lines, ins.renderListRow(ins.list.FilteredItems[i],
			i-start == ins.list.CurrentLine(), numW, innerW))
	}

	block := lipgloss.NewStyle().
		Width(width-SidebarBorderCols).
		Height(height).
		Padding(0, ContentPadding).
		Render(strings.Join(lines, "\n"))
	return leftSidebarBorderStyle.Render(block)
}

// renderListHeader renders the list title with pagination info, following
// the metrics pane's "[first-last of total]" convention.
func (ins *Inspector) renderListHeader(width int) string {
	header := ins.paneHeader(ins.list.Title, !ins.detailFocused(), width)

	info := ins.listNavInfo()
	if info == "" {
		return header
	}
	return header + navInfoStyle.Render(
		truncateValue(info, max(width-lipgloss.Width(header), 0)))
}

// listNavInfo builds the record list's pagination/count info string.
func (ins *Inspector) listNavInfo() string {
	total := len(ins.list.Items)
	filtered := len(ins.list.FilteredItems)
	start, end := ins.list.PageBounds()

	switch {
	case ins.filter.Query() != "" && filtered != total:
		return fmt.Sprintf(" [%d-%d of %d filtered from %d]",
			start+1, end, filtered, total)
	case filtered > ins.list.ItemsPerPage():
		return fmt.Sprintf(" [%d-%d of %d]", start+1, end, filtered)
	case filtered > 0:
		return fmt.Sprintf(" [%d records]", filtered)
	default:
		return ""
	}
}

// renderListRow renders one record row: number, type, and summary hint.
//
// The selected row is highlighted brightly while the list has focus and
// dimmed while the detail pane does, matching the workspace runs list.
func (ins *Inspector) renderListRow(
	e RecordEntry,
	selected bool,
	numW, width int,
) string {
	num := fmt.Sprintf("%*d", numW, e.Num)
	text := truncateValue(
		strings.TrimRight(num+" "+e.Type+"  "+e.Summary, " "), width)

	if selected {
		style := runOverviewSidebarHighlightedItem
		if ins.detailFocused() {
			style = selectedRunInactiveStyle
		}
		pad := max(width-lipgloss.Width(text), 0)
		return style.Render(text + strings.Repeat(" ", pad))
	}

	// Style the segments individually: number quiet, type prominent,
	// summary regular.
	styled := runOverviewSidebarKeyStyle.Render(num) + " "
	rest := strings.TrimPrefix(text, num+" ")
	if cut := strings.Index(rest, "  "); cut >= 0 {
		styled += runOverviewSidebarValueStyle.Render(rest[:cut])
		styled += "  " + labelStyle.Render(rest[cut+2:])
	} else {
		styled += runOverviewSidebarValueStyle.Render(rest)
	}
	return styled
}

// renderDetail renders the prototext pane for the selected record.
func (ins *Inspector) renderDetail(height int) string {
	title := "no record selected"
	if e, ok := ins.list.CurrentItem(); ok {
		title = fmt.Sprintf("record %d: %s", e.Num, e.Type)
	}

	innerW := max(ins.width-ins.listWidth()-ContentPaddingCols, 0)
	header := ins.paneHeader(title, ins.detailFocused(), innerW)
	if info := ins.detailScrollInfo(); info != "" {
		header += navInfoStyle.Render(
			truncateValue(info, max(innerW-lipgloss.Width(header), 0)))
	}

	body := lipgloss.NewStyle().
		Width(innerW).
		Height(max(height-inspectorHeaderLines, 0)).
		MaxHeight(max(height-inspectorHeaderLines, 0)).
		Render(ins.detail.View())

	return lipgloss.NewStyle().
		Padding(0, ContentPadding).
		Render(lipgloss.JoinVertical(lipgloss.Left, header, body))
}

// paneHeader renders a pane title, highlighted when the pane has focus.
func (ins *Inspector) paneHeader(title string, focused bool, width int) string {
	style := headerStyle
	if focused {
		style = style.Foreground(colorLayoutHighlight)
	}
	return style.Render(truncateValue(title, max(width, 0)))
}

// detailScrollInfo reports the scroll position of the detail pane, or ""
// when the whole record fits on screen.
func (ins *Inspector) detailScrollInfo() string {
	if ins.detail.AtTop() && ins.detail.AtBottom() {
		return ""
	}
	return fmt.Sprintf(" [%d%%]", int(ins.detail.ScrollPercent()*100))
}

// runState maps the file's scan state onto a run state for the status
// bar's indicator dot.
func (ins *Inspector) runState() RunState {
	switch {
	case ins.finished && ins.exitCode == 0:
		return RunStateFinished
	case ins.finished:
		return RunStateFailed
	default:
		return RunStateRunning
	}
}

// renderStatusBar renders the state dot, status text, and help hint.
func (ins *Inspector) renderStatusBar() string {
	indicator := renderStateIndicator(ins.runState())
	barWidth := max(ins.width-lipgloss.Width(indicator), 0)

	statusText := ins.buildStatusText()
	helpText := ins.buildHelpText()

	// Keep the bar on one line: trim the status text's head (usually a
	// long file path, whose tail matters most) to leave room for the
	// help hint.
	innerWidth := max(barWidth-2*StatusBarPadding, 0)
	statusText = truncateHead(
		statusText, max(innerWidth-lipgloss.Width(helpText)-1, 0))

	spaceForHelp := max(innerWidth-lipgloss.Width(statusText), 0)
	rightAligned := lipgloss.PlaceHorizontal(spaceForHelp, lipgloss.Right, helpText)

	return indicator + statusBarStyle.
		Width(barWidth).
		MaxWidth(barWidth).
		Render(statusText+rightAligned)
}

// truncateHead truncates s to maxW display columns by dropping characters
// from the start, prefixing an ellipsis when truncation happens.
func truncateHead(s string, maxW int) string {
	if lipgloss.Width(s) <= maxW {
		return s
	}
	if maxW <= 3 {
		return "..."
	}

	r := []rune(s)
	for lipgloss.Width(string(r)) > maxW-3 && len(r) > 0 {
		r = r[1:]
	}
	return "..." + string(r)
}

// buildStatusText chooses the status text for the current state.
func (ins *Inspector) buildStatusText() string {
	if ins.filter.IsActive() {
		return fmt.Sprintf(
			"Filter (%s): %s%s [%d/%d] (Enter to apply • Tab to toggle mode)",
			ins.filter.Mode().String(),
			ins.filter.Query(),
			string(mediumShadeBlock),
			len(ins.list.FilteredItems), len(ins.list.Items),
		)
	}
	if ins.lastError != "" {
		return "Error: " + ins.lastError
	}

	var parts []string
	if ins.runFile != "" {
		parts = append(parts, ins.runFile)
	}
	if ins.filter.Query() != "" {
		parts = append(parts, fmt.Sprintf(
			"filter: %q (ctrl+/ to clear)", ins.filter.Query()))
	}
	if !ins.finished && ins.scanStore != nil {
		parts = append(parts, "live")
	}
	if ins.corrupt > 0 {
		parts = append(parts,
			fmt.Sprintf("%d corrupt regions skipped", ins.corrupt))
	}

	return strings.Join(parts, " • ")
}

func (ins *Inspector) buildHelpText() string {
	if ins.filter.IsActive() {
		return ""
	}
	return "h: help"
}

// renderHelpScreen renders the full-screen help overlay with the standard
// LEET status bar treatment.
func (ins *Inspector) renderHelpScreen() string {
	helpView := ins.help.View().Content

	helpText := "h: help"
	spaceForHelp := max(ins.width-2*StatusBarPadding, 0)
	rightAligned := lipgloss.PlaceHorizontal(spaceForHelp, lipgloss.Right, helpText)

	statusBar := statusBarStyle.
		Width(ins.width).
		MaxWidth(ins.width).
		Render(rightAligned)

	content := lipgloss.JoinVertical(lipgloss.Left, helpView, statusBar)
	return lipgloss.Place(ins.width, ins.height, lipgloss.Left, lipgloss.Top, content)
}
