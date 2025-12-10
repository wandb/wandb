package leet

import (
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/wandb/wandb/core/internal/observability"
)

// Workspace is the multi‑run view.
type Workspace struct {
	wandbDir string

	runsAnimState *AnimationState

	runs PagedList

	// runPicker *runPicker --> This is an unnecessary level of abstraction, just use Workspace.
	// filesystem view of the wandb dir.
	// each line is selectable with Space.
	// selecting a run loads metric data of the run in the container
	// and turns on watching if it's a live run.
	// display a colored block next to run id; use that color for the run's plots
	// option to "pin" a run. "queue" for the "order"?

	// wandbDirWatcher *WandbDirWatcher. make it part of the runPicker!
	// watch for new runs, or simply ls the wandb dir every N seconds.
	// once a run is added, add it to the container.

	// runs container. make it part of the runPicker!
	// on load, populated with everything in the wandb dir and
	// selects the latest run or the exact one provided in the command.
	// preloads basic run metadata from the run record.
	// marks finished runs? or only after one is selected?
	// selected runs add data to a container in epochlinecharts.
	// draw method pulls data to plot from there based on the current
	// selected runs.
	//
	// when no run is selected, display the wandb leet ascii art.

	filter Filter

	config *ConfigManager
	logger *observability.CoreLogger

	width, height int
}

// NewWorkspace constructs a workspace bound to a W&B directory.
func NewWorkspace(
	wandbDir string,
	cfg *ConfigManager,
	logger *observability.CoreLogger,
) *Workspace {
	runs := PagedList{ // TODO: refactor to allow non-KeyValue items + make filtered ones pointers
		Title:  "Runs",
		Active: true,
	}
	// Avoid zero itemsPerPage; we'll refine on first resize.
	runs.SetItemsPerPage(1)

	return &Workspace{
		runsAnimState: NewAnimationState(true, SidebarMinWidth), // TODO: make visibility configurable
		wandbDir:  wandbDir,
		config:        cfg,
		logger:        logger,
		runs:          runs,
	}
}

// SetSize updates the workspace dimensions and recomputes pagination capacity.
func (w *Workspace) SetSize(width, height int) {
	w.width, w.height = width, height

	available := max(height-workspaceTopMarginLines-workspaceHeaderLines, 1)
	w.runs.SetItemsPerPage(available)
}

func (w *Workspace) Update(msg tea.Msg) tea.Cmd {
	switch t := msg.(type) {
	case tea.WindowSizeMsg:
		w.updateDimensions(t.Width, t.Height)

	case tea.KeyMsg:
		switch t.String() {
		case "q":
			return tea.Quit
		case "[":
			w.runsAnimState.Toggle()
			return w.runsAnimationCmd()
		}

		// Handle wandb dir navigation and run selection.
		if !w.runsAnimState.IsExpanded() {
			return nil
		}

		// Nothing to navigate yet.
		if len(w.runs.FilteredItems) == 0 {
			return nil
		}

		switch t.Type {
		case tea.KeyUp:
			w.runs.Up()
		case tea.KeyDown:
			w.runs.Down()
		case tea.KeyPgUp, tea.KeyRight:
			w.runs.PageUp()
		case tea.KeyPgDown, tea.KeyLeft:
			w.runs.PageDown()
		case tea.KeyHome:
			w.runs.Home()
		}

	case WorkspaceRunsAnimationMsg:
		w.logger.Debug(fmt.Sprintf("%v", "UPDATING sfad"))
		if !w.runsAnimState.Update(time.Now()) {
			return w.runsAnimationCmd()
		}
	}

	return nil
}

// View renders the runs section: header + paginated list with zebra rows.
func (w *Workspace) View() string {
	w.logger.Info(fmt.Sprintf("CALLED VIEW %v", w.runsAnimState))
	var parts []string

	// Render left sidebar with run picker.
	// TODO: move to separate helper function.
	if w.runsAnimState.IsVisible() {
		parts = append(parts, w.renderRuns())
	}

	// TODO: Render main metrics area.
	parts = append(parts, w.renderMetrics())

	mainView := lipgloss.JoinHorizontal(lipgloss.Top, parts...)
	statusBar := w.renderStatusBar()

	fullView := lipgloss.JoinVertical(lipgloss.Left, mainView, statusBar)
	return lipgloss.Place(w.width, w.height, lipgloss.Left, lipgloss.Top, fullView)
}

func (w *Workspace) renderRuns() string {
	// TODO: do this on the first load and when told by the dir watcher/heartbeat
	// outside of View().
	w.updateRunItems()

	contentWidth := w.runsAnimState.Width() - leftSidebarContentPadding

	startIdx, endIdx := w.syncRunsPage()
	header := w.renderRunsHeader(startIdx, endIdx) + "\n"
	lines := w.renderRunLines(startIdx, endIdx, contentWidth)

	if len(lines) == 0 {
		lines = []string{"(no runs found)"}
	}

	content := strings.Join(append([]string{header}, lines...), "\n") + "\n"

	styledContent := leftSidebarStyle.
		Width(w.runsAnimState.Width()).
		Height(w.height - StatusBarHeight).
		MaxWidth(w.runsAnimState.Width()).
		MaxHeight(w.height - StatusBarHeight).
		Render(content)

	return leftSidebarBorderStyle.
		Width(w.runsAnimState.Width() - 2).
		Height(w.height - StatusBarHeight + 1).
		MaxWidth(w.runsAnimState.Width()).
		MaxHeight(w.height - StatusBarHeight + 1).
		Render(styledContent)
}

func (w *Workspace) renderMetrics() string {
	// TODO
	artStyle := lipgloss.NewStyle().
		Foreground(colorHeading).
		Bold(true)

	logoContent := lipgloss.JoinVertical(
		lipgloss.Center,
		artStyle.Render(wandbArt),
		artStyle.Render(leetArt),
	)

	centeredLogo := lipgloss.Place(
		w.width-w.runsAnimState.Width(),
		w.height-StatusBarHeight-1,
		lipgloss.Center,
		lipgloss.Center,
		logoContent,
	)

	header := headerContainerStyle.Render(headerStyle.Render(metricsHeader))
	return lipgloss.JoinVertical(lipgloss.Left, header, centeredLogo)
}

func (w *Workspace) renderStatusBar() string {
	statusText := w.buildStatusText()
	helpText := w.buildHelpText()

	innerWidth := max(w.width-2*StatusBarPadding, 0)
	spaceForHelp := max(innerWidth-lipgloss.Width(statusText), 0)
	rightAligned := lipgloss.PlaceHorizontal(spaceForHelp, lipgloss.Right, helpText)

	fullStatus := statusText + rightAligned

	return statusBarStyle.
		Width(w.width).
		MaxWidth(w.width).
		Render(fullStatus)
}

func (w *Workspace) buildStatusText() string {
	return w.wandbDir
}

// buildHelpText builds the help text for the status bar.
func (w *Workspace) buildHelpText() string {
	// TODO: return "" in filtering mode (runs or metrics)
	return "h: help"
}

func (w *Workspace) updateDimensions(width, height int) {
	w.SetSize(width, height)
	// TODO: take right sidebar visibility into account once wired.
	calculatedWidth := int(float64(width) * SidebarWidthRatio)
	expandedWidth := clamp(calculatedWidth, SidebarMinWidth, SidebarMaxWidth)
	w.runsAnimState.SetExpandedWidth(expandedWidth)
}

// // computeViewports returns (leftW, contentW, rightW, contentH).
// func (w *Workspace) computeViewports() Layout {
// 	leftW, rightW := 0, 0
// 	if w.runsAnimState.IsVisible() {
// 		leftW = w.runsAnimState.currentWidth
// 	}

// 	contentW := max(w.width-leftW-rightW-2, 1)
// 	contentH := max(w.height-StatusBarHeight, 1)

// 	return Layout{leftW, contentW, rightW, contentH}
// }

// runsAnimationCmd returns a command to continue the animation on section toggle.
func (w *Workspace) runsAnimationCmd() tea.Cmd {
	return tea.Tick(AnimationFrame, func(t time.Time) tea.Msg {
		return WorkspaceRunsAnimationMsg{}
	})
}

// parseRunDirTimestamp extracts the timestamp from a run folder name.
//
// Expected formats: "run-YYYYMMDD_HHMMSS-runid" or "offline-run-YYYYMMDD_HHMMSS-runid"
// Returns zero time if parsing fails.
func parseRunDirTimestamp(name string) time.Time {
	// Strip prefix to get "YYYYMMDD_HHMMSS-runid"
	var rest string
	if after, ok := strings.CutPrefix(name, "offline-run-"); ok {
		rest = after
	} else if after, ok := strings.CutPrefix(name, "run-"); ok {
		rest = after
	} else {
		return time.Time{}
	}

	if len(rest) < 15 {
		return time.Time{}
	}

	t, err := time.Parse("20060102_150405", rest[:15])
	if err != nil {
		return time.Time{}
	}
	return t
}

// updateRunItems rebuilds Items/FilteredItems from the wandb directory.
func (w *Workspace) updateRunItems() {
	entries, err := os.ReadDir(w.wandbDir)
	if err != nil {
		return
	}

	items := w.runs.Items[:0]

	for _, entry := range entries {
		name := entry.Name()

		// Only show run folders (matching previous behavior).
		if !strings.HasPrefix(name, "run") &&
			!strings.HasPrefix(name, "offline-run") {
			continue
		}
		items = append(items, KeyValuePair{Key: name})
	}

	// Sort by most recent first (descending timestamp).
	slices.SortFunc(items, func(a, b KeyValuePair) int {
		ta, tb := parseRunDirTimestamp(a.Key), parseRunDirTimestamp(b.Key)
		return tb.Compare(ta)
	})

	w.runs.Items = items

	// Filter hook: once workspace filtering is wired, this will just work.
	if w.filter.Query() == "" && !w.filter.IsActive() {
		w.runs.FilteredItems = items
		return
	}

	matcher := w.filter.Matcher()
	filtered := make([]KeyValuePair, 0, len(items))
	for _, it := range items {
		if matcher(it.Key) {
			filtered = append(filtered, it)
		}
	}
	w.runs.FilteredItems = filtered
}

// syncRunsPage clamps the SectionView page/line against the current item set
// and returns the bounds of the visible slice [startIdx, endIdx).
func (w *Workspace) syncRunsPage() (startIdx, endIdx int) {
	total := len(w.runs.FilteredItems)
	itemsPerPage := w.runs.ItemsPerPage()

	if total == 0 || itemsPerPage <= 0 {
		w.runs.Home()
		return 0, 0
	}

	totalPages := (total + itemsPerPage - 1) / itemsPerPage
	if totalPages <= 0 {
		totalPages = 1
	}
	page := max(w.runs.CurrentPage(), 0)
	if page >= totalPages {
		page = totalPages - 1
	}

	startIdx = page * itemsPerPage
	endIdx = min(startIdx+itemsPerPage, total)

	maxLine := max(endIdx-startIdx-1, 0)
	line := min(max(w.runs.CurrentLine(), 0), maxLine)

	w.runs.SetPageAndLine(page, line)
	return startIdx, endIdx
}

// renderRunsHeader renders "Runs [X‑Y of N]" (or "[N items]" for single‑page).
func (w *Workspace) renderRunsHeader(startIdx, endIdx int) string {
	title := leftSidebarSectionHeaderStyle.Render("Runs")

	total := len(w.runs.FilteredItems)
	info := ""

	if total > 0 {
		ipp := w.runs.ItemsPerPage()
		if ipp > 0 && total > ipp {
			// X‑Y are 1‑based indices for the current page.
			info = fmt.Sprintf(" [%d-%d of %d]", startIdx+1, endIdx, total)
		} else {
			info = fmt.Sprintf(" [%d items]", total)
		}
	}

	return title + navInfoStyle.Render(info)
}

// renderRunLines renders the visible slice with zebra background and selection.
func (w *Workspace) renderRunLines(startIdx, endIdx, contentWidth int) []string {
	items := w.runs.FilteredItems
	if len(items) == 0 || startIdx >= endIdx || startIdx >= len(items) {
		return nil
	}

	lines := make([]string, 0, endIdx-startIdx)

	// Selection index relative to the current page (for highlighting).
	selectedLine := w.runs.CurrentLine()
	pageSpan := endIdx - startIdx
	if selectedLine < 0 || selectedLine >= pageSpan {
		selectedLine = -1 // nothing selected on this page
	}

	for i := range pageSpan {
		idx := startIdx + i
		if idx >= len(items) {
			break
		}
		name := truncateValue(items[idx].Key, contentWidth)

		// Zebra by global index for stability across pages.
		style := evenRunStyle
		if idx%2 == 1 {
			style = oddRunStyle
		}

		if i == selectedLine {
			style = selectedRunStyle
		}

		// Apply full width so background extends to edge.
		lines = append(lines, style.Width(contentWidth).Render(name))
	}

	return lines
}

// SelectedRunWandbFile returns the full path to the .wandb file for the selected run.
//
// Returns empty string if no run is selected.
func (w *Workspace) SelectedRunWandbFile() string {
	total := len(w.runs.FilteredItems)
	if total == 0 {
		return ""
	}

	startIdx := w.runs.CurrentPage() * w.runs.ItemsPerPage()
	idx := startIdx + w.runs.CurrentLine()
	if idx < 0 || idx >= total {
		return ""
	}

	folderName := w.runs.FilteredItems[idx].Key
	runID := extractRunID(folderName)
	if runID == "" {
		return ""
	}

	return filepath.Join(w.wandbDir, folderName, "run-"+runID+".wandb")
}

// extractRunID extracts the run ID from a folder name.
//
// "run-20250731_170606-iazb7i1k" -> "iazb7i1k"
// "offline-run-20250731_170606-abc123" -> "abc123"
func extractRunID(folderName string) string {
	lastHyphen := strings.LastIndex(folderName, "-")
	if lastHyphen == -1 || lastHyphen == len(folderName)-1 {
		return ""
	}
	return folderName[lastHyphen+1:]
}
