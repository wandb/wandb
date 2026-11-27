// inspectorhandlers.go
//
// Keyboard and mouse input for the record inspector: focus, navigation,
// filtering, and pane resizing.
package leet

import (
	tea "charm.land/bubbletea/v2"
)

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
