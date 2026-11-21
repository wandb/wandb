package leet

import (
	"cmp"
	"fmt"
	"image/color"
	"maps"
	"math"
	"slices"
	"strings"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	computev1 "github.com/wandb/wandb/core/internal/leet/computeproto"
)

// compassHeaderLines is the number of rows above the body.
const compassHeaderLines = 3

func (c *Compass) View() tea.View {
	if c.width == 0 || c.height == 0 {
		return tea.NewView("Loading...")
	}
	height := max(c.height-compassHeaderLines-1, 0)
	body := c.renderOverview(height)
	if c.tab == "teams" {
		body = c.renderTeams(height)
	}
	body = lipgloss.NewStyle().MaxHeight(height).Render(body)
	content := lipgloss.JoinVertical(lipgloss.Left,
		c.renderHeader(),
		lipgloss.Place(c.width, height, lipgloss.Left, lipgloss.Top, body),
		c.renderStatusBar(),
	)
	view := tea.NewView(content)
	view.WindowTitle = "wandb leet compass"
	view.AltScreen = true
	return view
}

func (c *Compass) renderHeader() string {
	tabs := make([]string, len(compassTabs))
	for i, tab := range compassTabs {
		style := navInfoStyle
		if tab == c.tab {
			style = headerStyle.Underline(true)
		}
		tabs[i] = style.Render(strings.ToUpper(tab[:1]) + tab[1:])
	}
	title := headerStyle.Render("Compute Compass") + "  " +
		labelStyle.Render(cmp.Or(c.params.Org, c.params.Entity)) + "    " +
		strings.Join(tabs, "  ")

	through := "data through unavailable"
	if !c.asOf.IsZero() {
		through = "data through " + c.asOf.UTC().Format("2006-01-02 15:04 UTC")
	}
	scope := fmt.Sprintf("Team %s · Period %s, %s to %s · Device %s · Tags %s · %s",
		cmp.Or(c.params.Entity, c.team, "all"),
		c.period, c.resolved.GetStart(), c.resolved.GetEnd(),
		cmp.Or(strings.Join(c.models, ", "), "all"),
		cmp.Or(strings.Join(c.tags, ", "), "none"),
		through)
	return symonContainerStyle.Render(title + "\n" + labelStyle.Render(scope) + "\n")
}

func (c *Compass) renderStatusBar() string {
	badge := statusBarBadgeStyle.Render(statusBarBadge)
	barWidth := max(c.width-lipgloss.Width(badge), 0)
	status := "Compute Compass"
	switch {
	case c.err != nil:
		status += " • " + c.err.Error()
	case c.pending > 0:
		status += " • loading"
	}
	help := "tab: view • w/m: week/month • t: team • d: device • o: hierarchy" +
		" • ←/→: fold • r: reload • q: quit"
	innerWidth := max(barWidth-2*StatusBarPadding, 0)
	status = truncateRight(status, max(innerWidth-lipgloss.Width(help)-1, 0))
	spaceForHelp := max(innerWidth-lipgloss.Width(status), 0)
	return badge + statusBarStyle.Width(barWidth).MaxWidth(barWidth).
		Render(status+lipgloss.PlaceHorizontal(spaceForHelp, lipgloss.Right, help))
}

// compassHours formats GPU-hours. Unset is not zero.
func compassHours(hours *float64, unset string) string {
	if hours == nil {
		return unset
	}
	return fmt.Sprintf("%.1f", *hours)
}

func compassPercent(ratio *float64, unset string) string {
	if ratio == nil {
		return unset
	}
	return fmt.Sprintf("%.1f%%", *ratio*100)
}

// compassShare is part over whole, or nil when either is unset or zero.
func compassShare(part, whole *computev1.UsageRow) *float64 {
	if part.GpuHours == nil || whole.GetGpuHours() == 0 {
		return nil
	}
	share := part.GetGpuHours() / whole.GetGpuHours()
	return &share
}

// compassHardware lists device models by their share of the GPU-hours.
func compassHardware(hardware map[string]float64) string {
	total := 0.0
	for _, hours := range hardware {
		total += hours
	}
	models := slices.SortedFunc(maps.Keys(hardware), func(a, b string) int {
		return cmp.Or(cmp.Compare(hardware[b], hardware[a]), cmp.Compare(a, b))
	})
	for i, model := range models {
		models[i] = fmt.Sprintf("%s %.0f%%", model, 100*hardware[model]/total)
	}
	return cmp.Or(strings.Join(models, " · "), "n/a")
}

// compassActivityColor is the designs' scale from 0% to 100% GPU activity.
func compassActivityColor(ratio *float64) color.Color {
	if ratio == nil {
		return colorSubtle
	}
	stops := [3][3]uint8{{105, 61, 158}, {200, 100, 141}, {239, 180, 86}}
	x := min(max(*ratio, 0), 1) * 2
	i := min(int(x), 1)
	a, b := stops[i], stops[i+1]
	return blendRGB(a[0], a[1], a[2], b[0], b[1], b[2], x-float64(i))
}

// compassBar draws share of width columns in the color of the activity.
func compassBar(share, activity *float64, width int) string {
	bar := ""
	if share != nil && *share > 0 {
		eighths := max(int(math.Round(*share*float64(width)*8)), 1)
		bar = strings.Repeat("█", eighths/8) +
			[]string{"", "▏", "▎", "▍", "▌", "▋", "▊", "▉"}[eighths%8]
	}
	return lipgloss.NewStyle().Foreground(compassActivityColor(activity)).Width(width).Render(bar)
}

// compassCell fits plain text into width columns.
func compassCell(text string, width int, align lipgloss.Position) string {
	return lipgloss.PlaceHorizontal(width, align, truncateRight(text, width))
}

func (c *Compass) renderOverview(height int) string {
	tiles := c.renderTiles()
	listHeight := height - lipgloss.Height(tiles)
	half := c.width / 2
	return lipgloss.JoinVertical(lipgloss.Left, tiles, lipgloss.JoinHorizontal(lipgloss.Top,
		c.renderList("Projects", "project", c.projects, half, listHeight),
		c.renderList("Users", "user", c.users, c.width-half, listHeight)))
}

func (c *Compass) renderTiles() string {
	tiles := [][4]string{
		{"GPU-hours", "unavailable", "physical basis"},
		{"GPU activity", "unavailable", "mean GPU utilization", "weighted by device time"},
		{
			"Assigned idle GPU-hours",
			"unavailable",
			"held by a job or process",
			"not counted as used",
		},
		{"Coverage", "unavailable"},
		{
			"Projects advancing",
			"not configured",
			"needs a project key metric",
			"no progress data in the API",
		},
		{
			"Compute w/o new progress",
			"not configured",
			"needs a project key metric",
			"no progress data in the API",
		},
	}
	if row := c.total; row != nil {
		coverage := row.GetCoverage()
		expected := "?"
		if coverage != nil && coverage.WritersExpected != nil {
			expected = fmt.Sprint(coverage.GetWritersExpected())
		}
		tiles[0][1] = compassHours(row.GpuHours, "unavailable")
		tiles[0][3] = fmt.Sprintf("%d runs · %d devices", row.GetRuns(), row.GetDevices())
		tiles[1][1] = compassPercent(row.GpuUtilizationRatio, "unavailable")
		tiles[2][1] = compassHours(row.AssignedIdleGpuHours, "unavailable")
		tiles[3][1] = fmt.Sprintf("%d of %s writers", coverage.GetWritersReporting(), expected)
		if observed := coverage.GetObservedShare(); coverage.GetWritersReporting() > 0 {
			tiles[3][2] = compassPercent(&observed, "") + " of time observed"
		}
		tiles[3][3] = fmt.Sprintf("%d runs without samples", coverage.GetRunsWithoutSamples())
	}

	perRow := len(tiles)
	if c.width < perRow*26 {
		perRow /= 2
	}
	width := c.width / perRow
	var rows []string
	for chunk := range slices.Chunk(tiles, perRow) {
		var boxes []string
		for _, tile := range chunk {
			value := headerStyle
			if tile[1] == "not configured" || tile[1] == "unavailable" {
				value = navInfoStyle
			}
			boxes = append(
				boxes,
				borderStyle.Width(width).Padding(0, 1).Render(strings.Join([]string{
					titleStyle.Render(truncateRight(tile[0], width-4)),
					value.Render(truncateRight(tile[1], width-4)),
					labelStyle.Render(truncateRight(tile[2], width-4)),
					labelStyle.Render(truncateRight(tile[3], width-4)),
				}, "\n")),
			)
		}
		rows = append(rows, lipgloss.JoinHorizontal(lipgloss.Top, boxes...))
	}
	return strings.Join(rows, "\n")
}

// renderList renders the groups of the scope ranked by GPU-hours.
func (c *Compass) renderList(
	title, key string,
	rows []*computev1.UsageRow,
	width, height int,
) string {
	const runsW, hoursW, activityW = 6, 10, 9
	flexible := max(width-2*ContentPadding-runsW-hoursW-activityW-4, 0)
	nameW := flexible / 2
	line := func(name, runs, hours, activity, hardware string) string {
		return strings.Join([]string{
			compassCell(name, nameW, lipgloss.Left),
			compassCell(runs, runsW, lipgloss.Right),
			compassCell(hours, hoursW, lipgloss.Right),
			compassCell(activity, activityW, lipgloss.Right),
			compassCell(hardware, flexible-nameW, lipgloss.Left),
		}, " ")
	}
	lines := []string{
		headerStyle.Render(
			title,
		) + navInfoStyle.Render(
			fmt.Sprintf("  %d by GPU-hours", len(rows)),
		),
		navInfoStyle.Render(line(key, "runs", "GPU-hours", "activity", "hardware")),
	}
	team := cmp.Or(c.params.Entity, c.team)
	for i, row := range rows {
		if len(lines) == height-1 && len(rows)-i > 1 {
			lines = append(lines, navInfoStyle.Render(fmt.Sprintf("… %d more", len(rows)-i)))
			break
		}
		lines = append(lines, labelStyle.Render(line(
			cmp.Or(strings.TrimPrefix(row.GetGroup()[key], team+"/"), "(none)"),
			fmt.Sprint(row.GetRuns()),
			compassHours(row.GpuHours, "n/a"),
			compassPercent(row.GpuUtilizationRatio, "n/a"),
			compassHardware(row.GetHardware()),
		)))
	}
	return symonContainerStyle.Width(width).Render(strings.Join(lines, "\n"))
}

func (c *Compass) renderTeams(height int) string {
	detailW := min(max(c.width*2/5, 40), c.width/2)
	return lipgloss.JoinHorizontal(lipgloss.Top,
		c.renderTree(c.width-detailW, height),
		c.renderDetail(detailW, height))
}

// renderTree renders the hierarchy with a bar per row: its length is the
// row's share of the scope's GPU-hours and its color the GPU activity.
func (c *Compass) renderTree(width, height int) string {
	const hoursW, activityW = 10, 9
	inner := width - 2*ContentPadding
	barW := max(inner/4, 8)
	nameW := max(inner-2-barW-hoursW-activityW-3, 0)
	levels := make([]string, len(c.order))
	for i, level := range c.order {
		levels[i] = strings.ToUpper(level[:1]) + level[1:]
	}

	var lines []string
	selected := 0
	var walk func(n *compassNode, depth int)
	walk = func(n *compassNode, depth int) {
		row := cmp.Or(n.row, &computev1.UsageRow{})
		marker, name := "  ", labelStyle
		if n == c.selected {
			selected = len(lines)
			marker, name = "❯ ", headerStyle
		}
		fold := "  "
		if depth < len(c.order) {
			fold = "▸ "
			if n.expanded {
				fold = "▾ "
			}
		}
		indent := strings.Repeat("  ", depth)
		lines = append(lines, strings.Join([]string{
			lipgloss.NewStyle().Foreground(colorSelected).Render(marker) +
				name.Render(compassCell(indent+fold+c.label(n), nameW, lipgloss.Left)),
			compassBar(compassShare(row, c.total), row.GpuUtilizationRatio, barW),
			labelStyle.Render(
				compassCell(compassHours(row.GpuHours, "n/a"), hoursW, lipgloss.Right),
			),
			labelStyle.Render(compassCell(
				compassPercent(row.GpuUtilizationRatio, "n/a"), activityW, lipgloss.Right)),
		}, " "))
		if !n.expanded {
			return
		}
		for _, child := range n.children {
			walk(child, depth+1)
		}
		switch {
		case n.loading:
			lines = append(lines, navInfoStyle.Render("    "+indent+"loading"))
		case n.more > 0:
			lines = append(
				lines,
				navInfoStyle.Render(fmt.Sprintf("    %s… %d more runs, %.1f GPU-hours",
					indent, n.more, n.moreHours)),
			)
		}
	}
	walk(c.root, 0)

	height -= 2
	top := min(max(selected-height/2, 0), max(len(lines)-height, 0))
	lines = lines[top:min(top+max(height, 0), len(lines))]
	header := []string{
		headerStyle.Render("Hierarchy") + navInfoStyle.Render("  "+strings.Join(levels, " → ")),
		navInfoStyle.Render("  " + compassCell("", nameW, lipgloss.Left) + " " +
			compassCell("share of GPU-hours", barW, lipgloss.Left) + " " +
			compassCell("GPU-hours", hoursW, lipgloss.Right) + " " +
			compassCell("activity", activityW, lipgloss.Right)),
	}
	return symonContainerStyle.Width(width).Render(strings.Join(append(header, lines...), "\n"))
}

// renderDetail renders the selected node of the hierarchy.
func (c *Compass) renderDetail(width, height int) string {
	node := c.selected
	row := cmp.Or(node.row, &computev1.UsageRow{})
	inner := width - 2*ContentPadding - 1
	const keyW = 20

	var trail []string
	for n := node; n.parent != nil; n = n.parent {
		trail = append([]string{n.level + ": " + c.label(n)}, trail...)
	}
	var parent *computev1.UsageRow
	if node.parent != nil {
		parent = node.parent.row
	}
	coverage := "unavailable"
	if cov := row.GetCoverage(); cov.GetWritersReporting() > 0 {
		observed := cov.GetObservedShare()
		coverage = fmt.Sprintf("%d writers, %s observed",
			cov.GetWritersReporting(), compassPercent(&observed, "n/a"))
	}

	lines := []string{
		navInfoStyle.Render(cmp.Or(node.level, "scope")),
		headerStyle.Render(truncateRight(c.label(node), inner)),
		labelStyle.Render(truncateRight(strings.Join(trail, " / "), inner)),
		"",
	}
	for _, item := range [][2]string{
		{"GPU-hours", compassHours(row.GpuHours, "unavailable")},
		{"Runs", fmt.Sprint(row.GetRuns())},
		{"Share of total", compassPercent(compassShare(row, c.total), "unavailable")},
		{"Share of parent", compassPercent(compassShare(row, parent), "unavailable")},
		{"GPU activity", compassPercent(row.GpuUtilizationRatio, "unavailable")},
		{"Assigned idle", compassHours(row.AssignedIdleGpuHours, "unavailable")},
		{"Coverage", coverage},
	} {
		lines = append(
			lines,
			runOverviewSidebarKeyStyle.Render(compassCell(item[0], keyW, lipgloss.Left))+
				runOverviewSidebarValueStyle.Render(truncateRight(item[1], inner-keyW)),
		)
	}

	lines = append(lines, "", headerStyle.Render("Hardware mix"))
	hardware := row.GetHardware()
	const modelW, hoursW = 24, 9
	barW := max(inner-modelW-hoursW, 0)
	for _, model := range slices.SortedFunc(maps.Keys(hardware), func(a, b string) int {
		return cmp.Or(cmp.Compare(hardware[b], hardware[a]), cmp.Compare(a, b))
	}) {
		hours := hardware[model]
		share := hours / row.GetGpuHours()
		lines = append(
			lines,
			runOverviewSidebarKeyStyle.Render(compassCell(model, modelW, lipgloss.Left))+
				compassBar(&share, row.GpuUtilizationRatio, barW)+
				runOverviewSidebarValueStyle.Render(
					compassCell(compassHours(&hours, ""), hoursW, lipgloss.Right),
				),
		)
	}
	if len(hardware) == 0 {
		lines = append(lines, navInfoStyle.Render("unavailable"))
	}

	return lipgloss.NewStyle().
		Border(lipgloss.NormalBorder(), false, false, false, true).
		BorderForeground(colorLayout).
		Padding(0, ContentPadding).
		Width(width).
		Height(height).
		Render(strings.Join(lines, "\n"))
}
