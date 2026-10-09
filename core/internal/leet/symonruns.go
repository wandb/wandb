package leet

import (
	"fmt"
	"os"
	"path/filepath"
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
	monitor.LiveRun
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
func (p *symonRunsPane) setRuns(runs []monitor.LiveRun, procs []monitor.ProcessStat) {
	children := make(map[int32][]int32, len(procs))
	byPID := make(map[int32]monitor.ProcessStat, len(procs))
	for _, proc := range procs {
		byPID[proc.PID] = proc
		children[proc.PPID] = append(children[proc.PPID], proc.PID)
	}

	items := make([]symonRun, 0, len(runs))
	for _, run := range runs {
		item := symonRun{LiveRun: run}
		seen := make(map[int32]bool)
		var queue []int32
		if run.ClientPID > 0 {
			queue = append(queue, run.ClientPID)
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
		line := fmt.Sprintf("%-36s  since %-7s  CPU %5.0f%%  MEM %8s  %s",
			truncateValue(filepath.Base(filepath.Dir(run.Path)), 36),
			formatUptime(time.Since(run.Since)),
			run.cpuPercent,
			formatBytesBinary(float64(run.rss)),
			abbreviateHome(filepath.Dir(run.Path)),
		)
		line = truncateValue(line, contentW)
		if p.runs.Active && i-start == p.runs.CurrentLine() {
			lines = append(lines, runOverviewSidebarHighlightedItem.Width(contentW).Render(line))
		} else {
			lines = append(lines, runOverviewSidebarValueStyle.Render(line))
		}
	}
	return symonContainerStyle.Render(lipgloss.JoinVertical(lipgloss.Left, lines...))
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
