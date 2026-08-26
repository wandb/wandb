package leet

import (
	"fmt"
	"strings"

	"charm.land/bubbles/v2/viewport"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	"google.golang.org/protobuf/encoding/prototext"

	"github.com/wandb/wandb/core/internal/observability"
)

const (
	// inspectorHeaderLines is the number of rows above each pane's content.
	inspectorHeaderLines = 1

	// inspectorWheelStep is how many rows a mouse wheel tick moves the
	// record list selection.
	inspectorWheelStep = 3
)

// inspectorMarshal renders records for the detail pane and the dump output.
var inspectorMarshal = prototext.MarshalOptions{Multiline: true, Indent: "  "}

// InspectorFileChangedMsg reports that the inspected .wandb file grew.
//
// It is emitted by the inspector's own file watcher; a distinct type keeps
// the inspector's watcher pump independent from a run view's.
type InspectorFileChangedMsg struct{}

// InspectorParams configures the record inspector.
type InspectorParams struct {
	// RunFile is the path to the .wandb transaction log to inspect. When
	// empty, the latest run in WandbDir is used.
	RunFile string

	// WandbDir is the wandb directory used to resolve the latest run.
	WandbDir string

	Config *ConfigManager
	Logger *observability.CoreLogger
}

// Inspector is a browser for the raw records in a .wandb transaction log:
// a filterable list of records next to a prototext view of the selected
// record. Live files are followed as they grow.
//
// Implements tea.Model.
type Inspector struct {
	keyMap map[string]func(*Inspector, tea.KeyPressMsg) tea.Cmd
	help   *HelpModel
	config *ConfigManager

	runFile  string
	wandbDir string

	// scanStore reads the file sequentially to build the record index;
	// detailStore re-reads individual records by offset on demand.
	scanStore   *LiveStore
	detailStore *LiveStore

	// watcherMgr triggers incremental scans as a live file grows.
	watcherMgr *WatcherManager

	// list is the paginated record index. Items holds every scanned
	// record; FilteredItems the ones matching the filter (the same slice
	// when no filter is applied).
	list PagedList[RecordEntry]

	// filter narrows the list by record type and summary text.
	filter *Filter

	// focusMgr moves keyboard focus between the list and the detail pane.
	focusMgr *FocusManager

	// detail shows the selected record as prototext.
	detail viewport.Model

	// drag owns mouse resizing of the list/detail boundary.
	drag paneDragger

	// finished is set when an exit record is seen: the file is complete.
	finished bool
	exitCode int32

	// corrupt counts corrupt regions skipped by the scan.
	corrupt int

	lastError string

	width, height int

	logger *observability.CoreLogger
}

// NewInspector creates a record inspector for the given .wandb file.
func NewInspector(params InspectorParams) *Inspector {
	logger := params.Logger
	if logger == nil {
		logger = observability.NewNoOpLogger()
	}

	cfg := params.Config
	if cfg == nil {
		cfg = NewConfigManager(leetConfigPath(), logger)
	}

	help := NewHelp()
	help.SetMode(viewModeInspect)

	ins := &Inspector{
		keyMap:     buildKeyMap(InspectorKeyBindings()),
		help:       help,
		config:     cfg,
		runFile:    params.RunFile,
		wandbDir:   params.WandbDir,
		watcherMgr: NewWatcherManager(make(chan tea.Msg, 16), logger),
		list:       PagedList[RecordEntry]{Title: "Records"},
		filter:     NewFilter(),
		detail:     viewport.New(),
		logger:     logger,
	}

	ins.focusMgr = NewFocusManager([]FocusRegionDef{
		{
			Target:     FocusTargetRecordList,
			Available:  func() bool { return true },
			Activate:   func(int) { ins.list.Active = true },
			Deactivate: func() { ins.list.Active = false },
		},
		{
			Target:     FocusTargetRecordDetail,
			Available:  func() bool { return true },
			Activate:   func(int) {},
			Deactivate: func() {},
		},
	})
	ins.focusMgr.SetTarget(FocusTargetRecordList, 1)

	ins.drag = paneDragger{
		saved:    cfg.InspectorLayout,
		persist:  cfg.SetInspectorLayout,
		relayout: ins.applyLayout,
		logger:   logger,
	}

	return ins
}

// Init opens the stores and starts scanning the file.
//
// Implements tea.Model.Init.
func (ins *Inspector) Init() tea.Cmd {
	return tea.Batch(
		tea.RequestBackgroundColor,
		InitializeInspector(ins.runFile, ins.wandbDir, ins.logger),
	)
}

// detailFocused reports whether the detail pane holds keyboard focus.
func (ins *Inspector) detailFocused() bool {
	return ins.focusMgr.IsTarget(FocusTargetRecordDetail)
}

// Cleanup stops the file watcher and closes the transaction log readers.
//
// Safe to call multiple times. Called after the program exits.
func (ins *Inspector) Cleanup() {
	ins.watcherMgr.Finish()
	if ins.scanStore != nil {
		ins.scanStore.Close()
		ins.scanStore = nil
	}
	if ins.detailStore != nil {
		ins.detailStore.Close()
		ins.detailStore = nil
	}
}

// Update handles incoming events.
//
// Implements tea.Model.Update.
func (ins *Inspector) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if ws, ok := msg.(tea.WindowSizeMsg); ok {
		ins.handleResize(ws)
	}

	if bgMsg, ok := msg.(tea.BackgroundColorMsg); ok {
		SetDarkBackground(bgMsg.IsDark())
	}

	if handled, cmd := ins.handleHelp(msg); handled {
		return ins, cmd
	}

	switch msg := msg.(type) {
	case tea.KeyPressMsg:
		if ins.filter.IsActive() {
			ins.handleFilterKey(msg)
			return ins, nil
		}
		if handler, ok := ins.keyMap[normalizeKey(msg.String())]; ok {
			return ins, handler(ins, msg)
		}
		return ins, nil

	case tea.MouseMsg:
		ins.handleMouse(msg)
		return ins, nil

	case InspectorInitMsg:
		ins.runFile = msg.RunFile
		ins.scanStore = msg.Scan
		ins.detailStore = msg.Detail
		return ins, ReadInspectorBatch(ins.scanStore, ins.nextNum())

	case InspectorBatchMsg:
		cmd := ins.handleBatch(msg)
		return ins, cmd

	case InspectorFileChangedMsg:
		if ins.scanStore == nil {
			return ins, nil
		}
		return ins, tea.Batch(
			ReadInspectorBatch(ins.scanStore, ins.nextNum()),
			ins.waitForFileEvent,
		)

	case ErrorMsg:
		ins.lastError = msg.Err.Error()
		return ins, nil

	default:
		return ins, nil
	}
}

// View renders the record inspector or its help overlay.
//
// Implements tea.Model.View.
func (ins *Inspector) View() tea.View {
	if ins.width == 0 || ins.height == 0 {
		return tea.NewView("Loading...")
	}

	var content string
	if ins.help.IsActive() {
		content = ins.renderHelpScreen()
	} else {
		content = ins.renderMainView()
	}

	view := tea.NewView(content)
	view.WindowTitle = "wandb leet inspect"
	view.AltScreen = true
	view.MouseMode = tea.MouseModeCellMotion
	return view
}

// --------------------------------------------------------------------
// Data flow
// --------------------------------------------------------------------

// nextNum returns the sequence number for the next scanned record.
func (ins *Inspector) nextNum() int {
	return len(ins.list.Items) + 1
}

// waitForFileEvent blocks until the file watcher reports a change.
func (ins *Inspector) waitForFileEvent() tea.Msg {
	if ins.watcherMgr.WaitForMsg() == nil {
		return nil
	}
	return InspectorFileChangedMsg{}
}

// handleBatch folds newly scanned entries into the index and decides how
// to continue: keep scanning, watch a live file for growth, or stop.
func (ins *Inspector) handleBatch(msg InspectorBatchMsg) tea.Cmd {
	if ins.scanStore == nil {
		return nil
	}

	ins.appendEntries(msg.Entries)
	ins.corrupt += msg.Corrupt
	if msg.ExitSeen {
		ins.finished, ins.exitCode = true, msg.ExitCode
	}

	if !msg.AtEOF {
		return ReadInspectorBatch(ins.scanStore, ins.nextNum())
	}
	if ins.finished {
		// The run exited; the file will not grow anymore.
		ins.watcherMgr.Finish()
		return nil
	}
	if ins.watcherMgr.IsStarted() {
		return nil
	}

	if err := ins.watcherMgr.Start(ins.runFile); err != nil {
		ins.logger.CaptureError(
			"leet",
			fmt.Errorf("inspector: failed to start watcher: %v", err),
		)
		return nil
	}
	// Catch anything written between reaching EOF and the watch starting,
	// then wait for change notifications.
	return tea.Batch(
		ReadInspectorBatch(ins.scanStore, ins.nextNum()),
		ins.waitForFileEvent,
	)
}

// appendEntries adds entries to the index, keeping the filtered view and
// the selection consistent. A selection resting on the last row follows
// the tail as a live file grows.
func (ins *Inspector) appendEntries(entries []RecordEntry) {
	if len(entries) == 0 {
		return
	}

	hadRows := len(ins.list.FilteredItems) > 0
	atTail := hadRows && ins.list.CurrentIndex() == len(ins.list.FilteredItems)-1

	ins.list.Items = append(ins.list.Items, entries...)
	if ins.filter.Query() == "" {
		ins.list.FilteredItems = ins.list.Items
	} else {
		match := ins.filter.Matcher()
		for _, e := range entries {
			if matchRecordEntry(match, e) {
				ins.list.FilteredItems = append(ins.list.FilteredItems, e)
			}
		}
	}

	switch {
	case !hadRows:
		ins.list.Home()
	case atTail:
		ins.list.End()
	default:
		return
	}
	ins.showSelected()
}

// matchRecordEntry reports whether the filter matcher accepts the entry.
func matchRecordEntry(match func(string) bool, e RecordEntry) bool {
	return match(e.Type) || match(e.Summary)
}

// applyFilter recomputes the filtered view, keeping the current selection
// when it still matches.
func (ins *Inspector) applyFilter() {
	selectedNum := 0
	if e, ok := ins.list.CurrentItem(); ok {
		selectedNum = e.Num
	}

	if ins.filter.Query() == "" {
		ins.list.FilteredItems = ins.list.Items
	} else {
		match := ins.filter.Matcher()
		filtered := make([]RecordEntry, 0, len(ins.list.Items))
		for _, e := range ins.list.Items {
			if matchRecordEntry(match, e) {
				filtered = append(filtered, e)
			}
		}
		ins.list.FilteredItems = filtered
	}

	ins.list.Home()
	if per := ins.list.ItemsPerPage(); per > 0 && selectedNum != 0 {
		for i, e := range ins.list.FilteredItems {
			if e.Num == selectedNum {
				ins.list.SetPageAndLine(i/per, i%per)
				break
			}
		}
	}
	ins.showSelected()
}

// showSelected renders the record under the cursor into the detail pane,
// re-reading it from the file by offset.
func (ins *Inspector) showSelected() {
	e, ok := ins.list.CurrentItem()
	if !ok {
		ins.detail.SetContent("")
		return
	}
	if ins.detailStore == nil {
		return
	}

	var text string
	record, err := ins.detailStore.ReadAt(e.Offset)
	if err != nil {
		text = fmt.Sprintf("failed to read record %d: %v", e.Num, err)
	} else {
		text = inspectorMarshal.Format(record)
	}

	// Soft-wrap so long values (e.g. JSON blobs) stay readable.
	if w := ins.detail.Width(); w > 0 {
		text = lipgloss.NewStyle().Width(w).Render(text)
	}
	ins.detail.SetContent(text)
	ins.detail.GotoTop()
}

// --------------------------------------------------------------------
// Input handling
// --------------------------------------------------------------------

// handleResize recomputes pane dimensions from the terminal size.
func (ins *Inspector) handleResize(msg tea.WindowSizeMsg) {
	ins.width, ins.height = msg.Width, msg.Height
	ins.help.SetSize(msg.Width, msg.Height)
	ins.list.SetItemsPerPage(ins.listRowsVisible())
	ins.applyLayout()
}

// applyLayout re-derives the detail pane dimensions from the terminal
// size and the (possibly dragged) list width, re-wrapping the content.
func (ins *Inspector) applyLayout() {
	ins.detail.SetWidth(max(ins.width-ins.listWidth()-ContentPaddingCols, 0))
	ins.detail.SetHeight(max(ins.height-StatusBarHeight-inspectorHeaderLines, 0))
	ins.showSelected()
}

// handleHelp toggles the help overlay and routes input to it while active.
func (ins *Inspector) handleHelp(msg tea.Msg) (bool, tea.Cmd) {
	if ins.filter.IsActive() {
		return false, nil
	}

	if km, ok := msg.(tea.KeyPressMsg); ok {
		switch km.Code {
		case 'h', '?':
			ins.help.Toggle()
			return true, nil
		}
	}

	if ins.help.IsActive() {
		switch msg.(type) {
		case tea.KeyPressMsg, tea.MouseMsg:
			updated, cmd := ins.help.Update(msg)
			ins.help = updated
			return true, cmd
		}
	}
	return false, nil
}

// handleFilterKey processes a key press while the filter input is active.
func (ins *Inspector) handleFilterKey(msg tea.KeyPressMsg) {
	if ins.filter.HandleKey(msg) {
		ins.applyFilter()
	}
}

func (ins *Inspector) handleQuit(tea.KeyPressMsg) tea.Cmd {
	return tea.Quit
}

// handleEscape returns keyboard focus to the record list.
func (ins *Inspector) handleEscape(tea.KeyPressMsg) tea.Cmd {
	ins.focusMgr.SetTarget(FocusTargetRecordList, 1)
	return nil
}

// handleToggleFocus moves keyboard focus between the list and the detail.
func (ins *Inspector) handleToggleFocus(msg tea.KeyPressMsg) tea.Cmd {
	direction := 1
	if msg.String() == "shift+tab" {
		direction = -1
	}
	ins.focusMgr.Tab(direction)
	return nil
}

// handleResetLayout restores the default pane proportions.
func (ins *Inspector) handleResetLayout(tea.KeyPressMsg) tea.Cmd {
	ins.drag.reset()
	return nil
}

// handleVerticalNav moves the list selection or scrolls the detail pane.
func (ins *Inspector) handleVerticalNav(msg tea.KeyPressMsg) tea.Cmd {
	up := DecodeNav(msg) == NavIntentUp

	if ins.detailFocused() {
		if up {
			ins.detail.ScrollUp(1)
		} else {
			ins.detail.ScrollDown(1)
		}
		return nil
	}

	if up {
		ins.list.Up()
	} else {
		ins.list.Down()
	}
	ins.showSelected()
	return nil
}

// handlePageNav moves the selection or detail scroll by a page.
func (ins *Inspector) handlePageNav(msg tea.KeyPressMsg) tea.Cmd {
	up := DecodeNav(msg) == NavIntentPageUp

	if ins.detailFocused() {
		if up {
			ins.detail.PageUp()
		} else {
			ins.detail.PageDown()
		}
		return nil
	}

	if up {
		ins.list.PageUp()
	} else {
		ins.list.PageDown()
	}
	ins.showSelected()
	return nil
}

// handleNavHome jumps to the first record or the top of the detail pane.
func (ins *Inspector) handleNavHome(tea.KeyPressMsg) tea.Cmd {
	if ins.detailFocused() {
		ins.detail.GotoTop()
		return nil
	}
	ins.list.Home()
	ins.showSelected()
	return nil
}

// handleNavEnd jumps to the last record or the bottom of the detail pane.
//
// On a live file, a selection on the last record follows new records as
// they arrive.
func (ins *Inspector) handleNavEnd(tea.KeyPressMsg) tea.Cmd {
	if ins.detailFocused() {
		ins.detail.GotoBottom()
		return nil
	}
	ins.list.End()
	ins.showSelected()
	return nil
}

func (ins *Inspector) handleEnterFilter(tea.KeyPressMsg) tea.Cmd {
	ins.filter.Activate()
	ins.applyFilter()
	return nil
}

func (ins *Inspector) handleClearFilter(tea.KeyPressMsg) tea.Cmd {
	ins.filter.Clear()
	ins.applyFilter()
	return nil
}

// wheelCursor moves the list selection without the keyboard's wrap-around,
// so scrolling past either end of the list stops there.
func (ins *Inspector) wheelCursor(delta int) {
	for range max(delta, -delta) {
		idx := ins.list.CurrentIndex()
		if delta < 0 {
			if idx <= 0 {
				break
			}
			ins.list.Up()
		} else {
			if idx < 0 || idx >= len(ins.list.FilteredItems)-1 {
				break
			}
			ins.list.Down()
		}
	}
	ins.showSelected()
}

// dragLayout maps the inspector's two panes onto the drag-resize Layout:
// the record list acts as a left sidebar.
func (ins *Inspector) dragLayout() Layout {
	return Layout{
		leftSidebarWidth:       ins.listWidth(),
		mainContentAreaWidth:   max(ins.width-ins.listWidth(), 0),
		totalContentAreaHeight: max(ins.height-StatusBarHeight, 0),
	}
}

// handleMouse resizes the pane boundary on drag, selects list rows on
// click, scrolls with the wheel, and moves focus to the pane under the
// pointer.
func (ins *Inspector) handleMouse(msg tea.MouseMsg) {
	if ins.drag.handleMouse(msg, ins.dragLayout(), dragTargets{
		width:        ins.width,
		height:       ins.height,
		leftExpanded: true,
	}) {
		return
	}

	mouse := msg.Mouse()
	inList := mouse.X < ins.listWidth()

	switch m := msg.(type) {
	case tea.MouseWheelMsg:
		switch {
		case !inList:
			ins.detail, _ = ins.detail.Update(msg)
		case m.Button == tea.MouseWheelUp:
			ins.wheelCursor(-inspectorWheelStep)
		case m.Button == tea.MouseWheelDown:
			ins.wheelCursor(inspectorWheelStep)
		}

	case tea.MouseClickMsg:
		if m.Button != tea.MouseLeft {
			return
		}
		if !inList {
			ins.focusMgr.SetTarget(FocusTargetRecordDetail, 1)
			return
		}
		ins.focusMgr.SetTarget(FocusTargetRecordList, 1)
		line := mouse.Y - inspectorHeaderLines
		if line >= 0 {
			ins.list.SetPageAndLine(ins.list.CurrentPage(), line)
			ins.showSelected()
		}
	}
}

// --------------------------------------------------------------------
// Rendering
// --------------------------------------------------------------------

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
