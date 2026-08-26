package leet

import (
	"fmt"

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

// IsFiltering reports whether the filter input is capturing keystrokes.
func (ins *Inspector) IsFiltering() bool {
	return ins.filter.IsActive()
}

// CapturesEscape reports whether the next Esc is consumed internally
// (to unfocus the detail pane) rather than exiting the inspector.
func (ins *Inspector) CapturesEscape() bool {
	return ins.detailFocused()
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
