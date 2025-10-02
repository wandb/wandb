//go:build !race

package leet

import tea "github.com/charmbracelet/bubbletea"

// windowTitleCmd sets the terminal window title.
//
// This is a no-op under the `-race` build tag to avoid a known concurrent write
// on the renderer's compressed writer.
func windowTitleCmd() tea.Cmd {
	return tea.SetWindowTitle("wandb leet")
}
