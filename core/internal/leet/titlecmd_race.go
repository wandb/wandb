//go:build race

package leet

import tea "github.com/charmbracelet/bubbletea"

// Under -race, skip SetWindowTitle to avoid a known concurrent write on the renderer's
// compressed writer. This only affects terminal title, not UI content.
func windowTitleCmd() tea.Cmd { return nil }
