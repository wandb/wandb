package leet_test

import (
	"testing"

	tea "charm.land/bubbletea/v2"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
)

func primaryNavMsg(t *testing.T, intent leet.NavIntent) tea.KeyPressMsg {
	t.Helper()
	return navMsgAt(t, intent, 0)
}

func secondaryNavMsg(t *testing.T, intent leet.NavIntent) tea.KeyPressMsg {
	t.Helper()
	return navMsgAt(t, intent, 1)
}

func navMsgAt(t *testing.T, intent leet.NavIntent, variant int) tea.KeyPressMsg {
	t.Helper()
	keys := leet.NavKeysFor(intent)
	require.Greaterf(t, len(keys), variant,
		"intent %v is missing variant %d", intent, variant)
	return navBindingMsg(t, keys[variant])
}

func navBindingMsg(t *testing.T, key string) tea.KeyPressMsg {
	t.Helper()

	switch key {
	case "up":
		return tea.KeyPressMsg{Code: tea.KeyUp}
	case "down":
		return tea.KeyPressMsg{Code: tea.KeyDown}
	case "left":
		return tea.KeyPressMsg{Code: tea.KeyLeft}
	case "right":
		return tea.KeyPressMsg{Code: tea.KeyRight}
	case "pgup":
		return tea.KeyPressMsg{Code: tea.KeyPgUp}
	case "pgdown":
		return tea.KeyPressMsg{Code: tea.KeyPgDown}
	case "home":
		return tea.KeyPressMsg{Code: tea.KeyHome}
	case "end":
		return tea.KeyPressMsg{Code: tea.KeyEnd}
	}

	runes := []rune(key)
	require.Lenf(t, runes, 1, "unsupported nav binding %q", key)
	return tea.KeyPressMsg{Code: runes[0], Text: key}
}
