package leet

import (
	"cmp"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"charm.land/lipgloss/v2"

	"github.com/wandb/wandb/core/internal/monitor"
)

const (
	symonRunsHeader      = "Runs"
	symonRunsHeaderLines = 1

	// symonRunsPaneMinHeight is the header and one run.
	symonRunsPaneMinHeight = symonRunsHeaderLines + 1

	// symonRunsPaneDefaultRows caps how many runs the pane shows before it
	// pages, unless the user drags it taller.
	symonRunsPaneDefaultRows = 6
)

// symonRun is a live run with the CPU share and resident memory of the
// process tree that started it.
type symonRun struct {
	SymonRun
	cpuPercent float64
	rss        uint64
}

// symonRunsPane lists the W&B runs live on this machine below the charts.
type symonRunsPane struct {
	visible bool
	runs    PagedList[symonRun]
}

func newSymonRunsPane(config *ConfigManager) *symonRunsPane {
	return &symonRunsPane{visible: config.SymonRunsVisible()}
}

// setRuns replaces the runs, attributing each the CPU and memory of its
// client's process tree.
func (p *symonRunsPane) setRuns(runs []SymonRun, procs []monitor.ProcessStat) {
	children := make(map[int32][]int32, len(procs))
	byPID := make(map[int32]monitor.ProcessStat, len(procs))
	for _, proc := range procs {
		byPID[proc.PID] = proc
		children[proc.PPID] = append(children[proc.PPID], proc.PID)
	}

	items := make([]symonRun, 0, len(runs))
	for i := range runs {
		item := symonRun{SymonRun: runs[i]}
		seen := make(map[int32]bool)
		var queue []int32
		if item.ClientPID > 0 {
			queue = append(queue, item.ClientPID)
		}
		for len(queue) > 0 {
			pid := queue[0]
			queue = queue[1:]
			if seen[pid] {
				continue
			}
			seen[pid] = true
			if proc, ok := byPID[pid]; ok {
				item.cpuPercent += proc.CPUPercent
				item.rss += proc.RSS
			}
			queue = append(queue, children[pid]...)
		}
		items = append(items, item)
	}
	p.runs.Items = items
	p.runs.FilteredItems = items
	p.runs.SetItemsPerPage(p.runs.ItemsPerPage())
}

// hasRuns reports whether there is anything to show.
func (p *symonRunsPane) hasRuns() bool {
	return len(p.runs.Items) > 0
}

// defaultHeight is the pane height without a drag override: the header
// plus one row per run, up to symonRunsPaneDefaultRows.
func (p *symonRunsPane) defaultHeight() int {
	return symonRunsHeaderLines + min(len(p.runs.Items), symonRunsPaneDefaultRows)
}

// View renders the header and the current page of runs, highlighting the
// cursor row while the pane has focus.
func (p *symonRunsPane) View(width, height int) string {
	contentW := max(width-ContentPaddingCols, 0)
	rows := max(height-symonRunsHeaderLines, 0)
	p.runs.SetItemsPerPage(rows)

	title := consoleLogsPaneHeaderStyle.Render(symonRunsHeader)
	start, end := p.runs.PageBounds()
	navInfo := fmt.Sprintf(" [%d-%d of %d]", start+1, end, len(p.runs.Items))
	lines := []string{title + navInfoStyle.Render(navInfo)}

	for i := start; i < end; i++ {
		run := p.runs.FilteredItems[i]
		line := truncateValue(p.row(run, contentW), contentW)
		if p.runs.Active && i-start == p.runs.CurrentLine() {
			lines = append(lines, runOverviewSidebarHighlightedItem.Width(contentW).Render(line))
		} else {
			lines = append(lines, runOverviewSidebarValueStyle.Render(line))
		}
	}
	return symonContainerStyle.Render(lipgloss.JoinVertical(lipgloss.Left, lines...))
}

// row renders one run: name and project from its log, progress, the
// followed metric with a sparkline, then its process tree's cost and age.
// The columns have fixed widths so rows line up, and trailing columns go
// when the row does not fit.
func (p *symonRunsPane) row(run symonRun, width int) string {
	name := cmp.Or(run.Name, strings.TrimSuffix(filepath.Base(run.Path), ".wandb"))
	progress := "no history yet"
	switch {
	case run.Finished:
		progress = "finished"
	case run.Step >= 0:
		progress = fmt.Sprintf("step %-7d %5.1f/s", run.Step, run.StepRate)
	}
	var metric, value, spark string
	if len(run.Values) > 0 {
		metric = truncateValue(run.Metric, 10)
		value = formatSigFigs(run.Values[len(run.Values)-1], 4)
		spark = sparkline(run.Values, 12)
	}
	parts := []string{
		fmt.Sprintf("%-20s", truncateValue(name, 20)),
		fmt.Sprintf("%-12s", truncateValue(run.Project, 12)),
		fmt.Sprintf("%-20s", progress),
		fmt.Sprintf("%-10s %6s %-12s", metric, value, spark),
		fmt.Sprintf("CPU %4.0f%%", run.cpuPercent),
		fmt.Sprintf("MEM %-7s", formatBytesBinary(float64(run.rss))),
		fmt.Sprintf("since %-6s", formatUptime(time.Since(run.Since))),
	}
	line := strings.Join(parts, "  ")
	for len(parts) > 1 && lipgloss.Width(line) > width {
		parts = parts[:len(parts)-1]
		line = strings.Join(parts, "  ")
	}
	return line
}

// sparkline draws the last values as a row of block glyphs scaled from the
// lowest to the highest of them.
func sparkline(values []float64, width int) string {
	const glyphs = "▁▂▃▄▅▆▇█"
	if len(values) > width {
		values = values[len(values)-width:]
	}
	lo, hi := slices.Min(values), slices.Max(values)
	var b strings.Builder
	for _, v := range values {
		level := 0
		if hi > lo {
			level = int((v - lo) / (hi - lo) * 7.999)
		}
		b.WriteRune([]rune(glyphs)[level])
	}
	return b.String()
}

// selectAt moves the cursor to the run rendered at the given row of the
// pane, if there is one.
func (p *symonRunsPane) selectAt(row int) {
	p.runs.SetPageAndLine(p.runs.CurrentPage(), row-symonRunsHeaderLines)
}

// selectedPath returns the .wandb path under the cursor.
func (p *symonRunsPane) selectedPath() string {
	run, ok := p.runs.CurrentItem()
	if !ok {
		return ""
	}
	return run.Path
}

// abbreviateHome shortens a path under the home directory to ~/...
func abbreviateHome(path string) string {
	home, err := os.UserHomeDir()
	if err != nil || home == "" {
		return path
	}
	rest, ok := strings.CutPrefix(path, home)
	if ok && (rest == "" || strings.HasPrefix(rest, string(filepath.Separator))) {
		return "~" + rest
	}
	return path
}
