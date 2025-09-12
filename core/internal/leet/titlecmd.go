//go:build !race

package leet

import tea "github.com/charmbracelet/bubbletea"

func windowTitleCmd() tea.Cmd {
	return tea.SetWindowTitle("wandb leet")
}
