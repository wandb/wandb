package leet_test

import (
	"testing"

	tea "charm.land/bubbletea/v2"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
)

func TestFilter_HandleKey_BackspaceIsRuneSafe(t *testing.T) {
	f := leet.NewFilter()
	f.Activate()

	require.True(t, f.HandleKey(tea.KeyPressMsg{Text: "é"}))
	require.Equal(t, "é", f.Query())

	require.True(t, f.HandleKey(tea.KeyPressMsg{Code: tea.KeyBackspace}))
	require.Equal(t, "", f.Query())
}

func TestFilter_HandleKey_NavigationKeyIsNoOp(t *testing.T) {
	f := leet.NewFilter()
	f.Activate()

	require.False(t, f.HandleKey(tea.KeyPressMsg{Code: tea.KeyUp}))
	require.Empty(t, f.Query())
}
