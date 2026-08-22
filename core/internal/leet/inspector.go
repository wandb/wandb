package leet

import (
	"fmt"
	"path/filepath"
	"strings"
	"time"

	"charm.land/bubbles/v2/viewport"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	"google.golang.org/protobuf/encoding/prototext"

	"github.com/wandb/wandb/core/internal/observability"
)

const (
	// inspectorPollInterval is how often the inspector re-checks a live
	// .wandb file for appended records after catching up with its end.
	inspectorPollInterval = time.Second

	// inspectorHeaderLines is the number of rows above each pane's content.
	inspectorHeaderLines = 1

	// Bounds for the record list pane width.
	inspectorListMinWidth = 36
	inspectorListMaxWidth = 72

	// inspectorWheelStep is how many rows a mouse wheel tick moves the
	// record list selection.
	inspectorWheelStep = 3
)

// inspectorMarshal renders records for the detail pane and the dump output.
var inspectorMarshal = prototext.MarshalOptions{Multiline: true, Indent: "  "}

// InspectorPollMsg triggers a scan for records appended to a live file.
type InspectorPollMsg struct{}

// InspectorParams configures the record inspector.
type InspectorParams struct {
	// RunFile is the path to the .wandb transaction log to inspect.
	RunFile string

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

	runFile string
	store   *InspectorStore

	// entries is the index of all scanned records.
	entries []RecordEntry

	// filter narrows the list by record type and summary text.
	filter *Filter

	// filtered holds the indices into entries that match the filter.
	filtered []int

	// cursor is the selected row and top the first visible row, both
	// indices into filtered.
	cursor int
	top    int

	// detail shows the selected record as prototext.
	detail viewport.Model

	// detailFocused routes navigation keys to the detail pane.
	detailFocused bool

	// detailNum is the Num of the entry currently rendered in the detail
	// pane, or 0 when the pane is empty.
	detailNum int

	// loaded is set once the initial scan reaches the end of the file.
	loaded bool

	// finished is set when an exit record is seen: the file is complete.
	finished bool
	exitCode int32

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

	help := NewHelp()
	help.SetMode(viewModeInspect)

	return &Inspector{
		keyMap:  buildKeyMap(InspectorKeyBindings()),
		help:    help,
		runFile: params.RunFile,
		filter:  NewFilter(),
		detail:  viewport.New(),
		logger:  logger,
	}
}

// Init opens the store and starts scanning the file.
//
// Implements tea.Model.Init.
func (ins *Inspector) Init() tea.Cmd {
	return tea.Batch(
		tea.RequestBackgroundColor,
		InitializeInspectorStore(ins.runFile, ins.logger),
	)
}

// IsFiltering reports whether the filter input is capturing keystrokes.
func (ins *Inspector) IsFiltering() bool {
	return ins.filter.IsActive()
}

// CapturesEscape reports whether the next Esc is consumed internally
// (to unfocus the detail pane) rather than exiting the inspector.
func (ins *Inspector) CapturesEscape() bool {
	return ins.detailFocused
}

// Cleanup closes the store's readers.
//
// Safe to call multiple times. Called after the program exits.
func (ins *Inspector) Cleanup() {
	if ins.store != nil {
		ins.store.Close()
		ins.store = nil
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
		ins.store = msg.Store
		return ins, ReadInspectorBatch(ins.store)

	case InspectorBatchMsg:
		return ins, ins.handleBatch(msg)

	case InspectorPollMsg:
		if ins.store == nil || ins.finished {
			return ins, nil
		}
		return ins, ReadInspectorBatch(ins.store)

	case ErrorMsg:
		ins.lastError = msg.Err.Error()
		ins.loaded = true
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
	switch {
	case ins.help.IsActive():
		content = ins.renderHelpScreen()
	case !ins.loaded && len(ins.entries) == 0:
		content = ins.renderLoadingScreen()
	default:
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

// handleBatch folds newly scanned entries into the index and decides how
// to continue: keep scanning, poll a live file, or stop.
func (ins *Inspector) handleBatch(msg InspectorBatchMsg) tea.Cmd {
	ins.appendEntries(msg.Entries)
	if ins.store == nil {
		return nil
	}
	ins.finished, ins.exitCode = ins.store.ExitSeen()

	if !msg.AtEOF {
		return ReadInspectorBatch(ins.store)
	}

	ins.loaded = true
	if ins.finished {
		return nil
	}
	return tea.Tick(inspectorPollInterval, func(time.Time) tea.Msg {
		return InspectorPollMsg{}
	})
}

// appendEntries adds entries to the index, keeping the filtered view and
// the selection consistent. A selection resting on the last row follows
// the tail as a live file grows.
func (ins *Inspector) appendEntries(entries []RecordEntry) {
	if len(entries) == 0 {
		return
	}

	hadRows := len(ins.filtered) > 0
	atTail := hadRows && ins.cursor == len(ins.filtered)-1

	match := ins.filter.Matcher()
	filtering := ins.filter.Query() != ""
	for _, e := range entries {
		ins.entries = append(ins.entries, e)
		if !filtering || matchRecordEntry(match, e) {
			ins.filtered = append(ins.filtered, len(ins.entries)-1)
		}
	}

	if !hadRows || atTail {
		ins.cursor = max(len(ins.filtered)-1, 0)
		if !hadRows {
			ins.cursor = 0
		}
		ins.ensureCursorVisible()
	}
	ins.syncDetail(false)
}

// matchRecordEntry reports whether the filter matcher accepts the entry.
func matchRecordEntry(match func(string) bool, e RecordEntry) bool {
	return match(e.Type) || match(e.Summary)
}

// applyFilter recomputes the filtered view, keeping the current selection
// when it still matches.
func (ins *Inspector) applyFilter() {
	selected := -1
	if len(ins.filtered) > 0 && ins.cursor < len(ins.filtered) {
		selected = ins.filtered[ins.cursor]
	}

	match := ins.filter.Matcher()
	filtering := ins.filter.Query() != ""
	ins.filtered = ins.filtered[:0]
	for i, e := range ins.entries {
		if !filtering || matchRecordEntry(match, e) {
			ins.filtered = append(ins.filtered, i)
		}
	}

	ins.cursor = 0
	for i, idx := range ins.filtered {
		if idx == selected {
			ins.cursor = i
			break
		}
	}
	ins.ensureCursorVisible()
	ins.syncDetail(false)
}

// selectedEntry returns the entry under the cursor.
func (ins *Inspector) selectedEntry() (RecordEntry, bool) {
	if len(ins.filtered) == 0 || ins.cursor >= len(ins.filtered) {
		return RecordEntry{}, false
	}
	return ins.entries[ins.filtered[ins.cursor]], true
}

// syncDetail re-reads and renders the selected record in the detail pane.
// Unless force is set, it is a no-op when the pane already shows the
// selected record.
func (ins *Inspector) syncDetail(force bool) {
	e, ok := ins.selectedEntry()
	if !ok {
		if ins.detailNum != 0 {
			ins.detail.SetContent("")
			ins.detailNum = 0
		}
		return
	}
	if !force && e.Num == ins.detailNum {
		return
	}
	if ins.store == nil {
		return
	}

	var text string
	record, err := ins.store.RecordAt(e.Offset)
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
	ins.detailNum = e.Num
}

// --------------------------------------------------------------------
// Input handling
// --------------------------------------------------------------------

// handleResize recomputes pane dimensions from the terminal size.
func (ins *Inspector) handleResize(msg tea.WindowSizeMsg) {
	ins.width, ins.height = msg.Width, msg.Height
	ins.help.SetSize(msg.Width, msg.Height)

	detailW := max(ins.width-ins.listWidth()-ContentPaddingCols, 0)
	detailH := max(ins.height-StatusBarHeight-inspectorHeaderLines, 0)
	ins.detail.SetWidth(detailW)
	ins.detail.SetHeight(detailH)

	ins.ensureCursorVisible()
	ins.syncDetail(true)
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

// handleEscape unfocuses the detail pane.
func (ins *Inspector) handleEscape(tea.KeyPressMsg) tea.Cmd {
	ins.detailFocused = false
	return nil
}

// handleToggleFocus moves keyboard focus between the list and the detail.
func (ins *Inspector) handleToggleFocus(tea.KeyPressMsg) tea.Cmd {
	ins.detailFocused = !ins.detailFocused
	return nil
}

// handleVerticalNav moves the list selection or scrolls the detail pane.
func (ins *Inspector) handleVerticalNav(msg tea.KeyPressMsg) tea.Cmd {
	delta := 1
	if DecodeNav(msg) == NavIntentUp {
		delta = -1
	}

	if ins.detailFocused {
		if delta < 0 {
			ins.detail.ScrollUp(1)
		} else {
			ins.detail.ScrollDown(1)
		}
		return nil
	}

	ins.moveCursor(delta)
	return nil
}

// handlePageNav moves the selection or detail scroll by a page.
func (ins *Inspector) handlePageNav(msg tea.KeyPressMsg) tea.Cmd {
	up := DecodeNav(msg) == NavIntentPageUp

	if ins.detailFocused {
		if up {
			ins.detail.PageUp()
		} else {
			ins.detail.PageDown()
		}
		return nil
	}

	page := max(ins.listRowsVisible(), 1)
	if up {
		page = -page
	}
	ins.moveCursor(page)
	return nil
}

// handleNavHome jumps to the first record or the top of the detail pane.
func (ins *Inspector) handleNavHome(tea.KeyPressMsg) tea.Cmd {
	if ins.detailFocused {
		ins.detail.GotoTop()
		return nil
	}
	ins.setCursor(0)
	return nil
}

// handleNavEnd jumps to the last record or the bottom of the detail pane.
//
// On a live file, a selection on the last record follows new records as
// they arrive.
func (ins *Inspector) handleNavEnd(tea.KeyPressMsg) tea.Cmd {
	if ins.detailFocused {
		ins.detail.GotoBottom()
		return nil
	}
	ins.setCursor(len(ins.filtered) - 1)
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

// moveCursor moves the list selection by delta rows, clamped to the list.
func (ins *Inspector) moveCursor(delta int) {
	ins.setCursor(ins.cursor + delta)
}

// setCursor selects the given filtered row, clamped to the list.
func (ins *Inspector) setCursor(row int) {
	if len(ins.filtered) == 0 {
		ins.cursor = 0
		ins.top = 0
		return
	}
	ins.cursor = clamp(row, 0, len(ins.filtered)-1)
	ins.ensureCursorVisible()
	ins.syncDetail(false)
}

// ensureCursorVisible scrolls the list window to contain the cursor.
func (ins *Inspector) ensureCursorVisible() {
	rows := max(ins.listRowsVisible(), 1)
	if ins.cursor < ins.top {
		ins.top = ins.cursor
	}
	if ins.cursor >= ins.top+rows {
		ins.top = ins.cursor - rows + 1
	}
	ins.top = clamp(ins.top, 0, max(len(ins.filtered)-1, 0))
}

// handleMouse selects list rows on click, scrolls with the wheel, and
// moves focus to the pane under the pointer.
func (ins *Inspector) handleMouse(msg tea.MouseMsg) {
	mouse := msg.Mouse()
	inList := mouse.X < ins.listWidth()

	switch m := msg.(type) {
	case tea.MouseWheelMsg:
		switch {
		case !inList:
			ins.detail, _ = ins.detail.Update(msg)
		case m.Button == tea.MouseWheelUp:
			ins.moveCursor(-inspectorWheelStep)
		case m.Button == tea.MouseWheelDown:
			ins.moveCursor(inspectorWheelStep)
		}

	case tea.MouseClickMsg:
		if m.Button != tea.MouseLeft {
			return
		}
		ins.detailFocused = !inList
		if !inList {
			return
		}
		row := ins.top + mouse.Y - inspectorHeaderLines
		if mouse.Y >= inspectorHeaderLines && row < len(ins.filtered) {
			ins.setCursor(row)
		}
	}
}

// --------------------------------------------------------------------
// Rendering
// --------------------------------------------------------------------

// listWidth returns the record list pane width, including its border.
func (ins *Inspector) listWidth() int {
	w := int(float64(ins.width) * SidebarWidthRatio)
	w = clamp(w, inspectorListMinWidth, inspectorListMaxWidth)
	return min(w, ins.width/2)
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
	lines = append(lines, ins.paneHeader("Records", !ins.detailFocused, innerW))

	numW := len(fmt.Sprint(len(ins.entries)))
	last := min(ins.top+ins.listRowsVisible(), len(ins.filtered))
	for i := ins.top; i < last; i++ {
		lines = append(lines, ins.renderListRow(ins.entries[ins.filtered[i]],
			i == ins.cursor, numW, innerW))
	}

	block := lipgloss.NewStyle().
		Width(width-SidebarBorderCols).
		Height(height).
		Padding(0, ContentPadding).
		Render(strings.Join(lines, "\n"))
	return leftSidebarBorderStyle.Render(block)
}

// renderListRow renders one record row: number, type, and summary hint.
func (ins *Inspector) renderListRow(
	e RecordEntry,
	selected bool,
	numW, width int,
) string {
	num := fmt.Sprintf("%*d", numW, e.Num)
	text := truncateValue(
		strings.TrimRight(num+" "+e.Type+"  "+e.Summary, " "), width)

	if selected {
		pad := max(width-lipgloss.Width(text), 0)
		return runOverviewSidebarHighlightedItem.Render(
			text + strings.Repeat(" ", pad))
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
	if e, ok := ins.selectedEntry(); ok {
		title = fmt.Sprintf("record %d: %s", e.Num, e.Type)
	}

	innerW := max(ins.width-ins.listWidth()-ContentPaddingCols, 0)
	header := ins.paneHeader(title, ins.detailFocused, innerW)

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

// runState maps the file's scan state onto a run state for the status
// bar's indicator dot.
func (ins *Inspector) runState() RunState {
	switch {
	case ins.finished && ins.exitCode == 0:
		return RunStateFinished
	case ins.finished:
		return RunStateFailed
	case ins.loaded:
		return RunStateRunning
	default:
		return RunStateUnknown
	}
}

// renderLoadingScreen shows the logo while the first scan is in flight.
func (ins *Inspector) renderLoadingScreen() string {
	logo := renderLogoArt(ins.width, max(ins.height-StatusBarHeight, 0))
	return lipgloss.JoinVertical(lipgloss.Left, logo, ins.renderStatusBar())
}

// renderStatusBar renders the state dot, status text, and help hint.
func (ins *Inspector) renderStatusBar() string {
	indicator := renderStateIndicator(ins.runState())
	barWidth := max(ins.width-lipgloss.Width(indicator), 0)

	statusText := ins.buildStatusText()
	helpText := ins.buildHelpText()

	innerWidth := max(barWidth-2*StatusBarPadding, 0)
	spaceForHelp := max(innerWidth-lipgloss.Width(statusText), 0)
	rightAligned := lipgloss.PlaceHorizontal(spaceForHelp, lipgloss.Right, helpText)

	return indicator + statusBarStyle.
		Width(barWidth).
		MaxWidth(barWidth).
		Render(statusText+rightAligned)
}

// buildStatusText chooses the status text for the current state.
func (ins *Inspector) buildStatusText() string {
	if ins.filter.IsActive() {
		return fmt.Sprintf(
			"Filter (%s): %s%s [%d/%d] (Enter to apply • Tab to toggle mode)",
			ins.filter.Mode().String(),
			ins.filter.Query(),
			string(mediumShadeBlock),
			len(ins.filtered), len(ins.entries),
		)
	}
	if ins.lastError != "" {
		return "Error: " + ins.lastError
	}

	parts := []string{filepath.Base(ins.runFile)}

	switch {
	case !ins.loaded:
		parts = append(parts, fmt.Sprintf("loading... [%d records]", len(ins.entries)))
	case ins.filter.Query() != "":
		parts = append(parts, fmt.Sprintf(
			"%d/%d records (filter: %q, ctrl+/ to clear)",
			len(ins.filtered), len(ins.entries), ins.filter.Query()))
	default:
		parts = append(parts, countSummary(len(ins.entries), "record"))
	}

	if ins.loaded && !ins.finished {
		parts = append(parts, "live")
	}
	if ins.store != nil {
		if corrupt := ins.store.CorruptCount(); corrupt > 0 {
			parts = append(parts,
				fmt.Sprintf("%d corrupt regions skipped", corrupt))
		}
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
