package leet

import (
	"fmt"
	"strings"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
)

// deleteRunModalMinWidth is the minimum inner (content) width of the modal.
const deleteRunModalMinWidth = 44

// deleteRunConfirmText is what the user must type to confirm a deletion.
const deleteRunConfirmText = "DELETE"

// DeleteRunModal is the confirmation dialog for permanently deleting a run
// directory from disk.
//
// To guard against accidental deletion, the user must type DELETE and
// press Enter. While active, the modal captures all key input.
type DeleteRunModal struct {
	active   bool
	blocked  bool   // run is live; deletion is refused
	deleting bool   // removal is in flight
	errText  string // non-empty after a failed deletion

	runKey string // run directory name being deleted
	typed  string
}

// Open activates the modal for the given run directory.
//
// A live run cannot be deleted; the modal then opens in a blocked state
// that only explains why.
func (m *DeleteRunModal) Open(runKey string, live bool) {
	*m = DeleteRunModal{
		active:  true,
		blocked: live,
		runKey:  runKey,
	}
}

// Close deactivates the modal and clears its state.
func (m *DeleteRunModal) Close() { *m = DeleteRunModal{} }

// Active reports whether the modal is visible and capturing key input.
func (m *DeleteRunModal) Active() bool { return m.active }

// RunKey returns the run directory name the modal is targeting.
func (m *DeleteRunModal) RunKey() string { return m.runKey }

// Fail keeps the modal open and displays a deletion error.
func (m *DeleteRunModal) Fail(err error) {
	m.deleting = false
	m.errText = fmt.Sprintf("%v", err)
}

// HandleKey processes a key press while the modal is active.
//
// Returns true when the user confirmed the deletion (typed DELETE and
// pressed Enter); the caller is expected to start the actual deletion.
func (m *DeleteRunModal) HandleKey(msg tea.KeyPressMsg) bool {
	if m.deleting {
		return false
	}
	if m.blocked || m.errText != "" {
		switch msg.Code {
		case tea.KeyEsc, tea.KeyEnter:
			m.Close()
		}
		return false
	}

	switch msg.Code {
	case tea.KeyEsc:
		m.Close()
	case tea.KeyEnter:
		if m.typed == deleteRunConfirmText {
			m.deleting = true
			return true
		}
	case tea.KeyBackspace:
		m.typed = trimLastRune(m.typed)
	default:
		if msg.Text != "" {
			m.typed += msg.Text
		}
	}
	return false
}

// View renders the modal box. The caller positions it on screen.
func (m *DeleteRunModal) View(maxWidth int) string {
	innerW := max(lipgloss.Width(m.runKey), deleteRunModalMinWidth)
	innerW = min(innerW, maxWidth-deleteRunModalBorderStyle.GetHorizontalFrameSize())
	innerW = max(innerW, 1)

	lines := []string{
		deleteRunModalTitleStyle.Render("Delete run"),
		"",
		deleteRunModalRunStyle.Render(truncateValue(m.runKey, innerW)),
		"",
	}
	lines = append(lines, m.bodyLines()...)

	return deleteRunModalBorderStyle.
		Width(innerW).
		Render(strings.Join(lines, "\n"))
}

// bodyLines renders the state-dependent portion of the modal.
func (m *DeleteRunModal) bodyLines() []string {
	switch {
	case m.blocked:
		return []string{
			labelStyle.Render("This run appears to be live and cannot be deleted."),
			"",
			navInfoStyle.Render("Esc: close"),
		}
	case m.deleting:
		return []string{labelStyle.Render("Deleting…")}
	case m.errText != "":
		return []string{
			deleteRunModalDangerStyle.Render("Delete failed: " + m.errText),
			"",
			navInfoStyle.Render("Esc: close"),
		}
	default:
		hint := "Esc: cancel"
		if m.typed == deleteRunConfirmText {
			hint = "Enter: delete • " + hint
		}
		return []string{
			labelStyle.Render("This permanently deletes the run directory from disk."),
			"",
			labelStyle.Render(fmt.Sprintf("Type %s to confirm:", deleteRunConfirmText)),
			deleteRunModalInputStyle.Render("> "+m.typed) + string(mediumShadeBlock),
			"",
			navInfoStyle.Render(hint),
		}
	}
}

// overlayCentered composites overlay centered on top of base.
func overlayCentered(base, overlay string, width, height int) string {
	x := max((width-lipgloss.Width(overlay))/2, 0)
	y := max((height-lipgloss.Height(overlay))/2, 0)

	// Layer offsets are resolved by the Compositor; drawing layers directly
	// onto a canvas would ignore X/Y/Z.
	canvas := lipgloss.NewCanvas(width, height)
	canvas.Compose(lipgloss.NewCompositor(
		lipgloss.NewLayer(base),
		lipgloss.NewLayer(overlay).X(x).Y(y).Z(1),
	))
	return canvas.Render()
}
