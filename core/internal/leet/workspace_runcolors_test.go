package leet

import (
	"fmt"
	"path/filepath"
	"testing"

	"charm.land/lipgloss/v2"
	"charm.land/lipgloss/v2/compat"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observability"
)

func TestWorkspaceRunColorsAssignUniqueWithinWorkspace(t *testing.T) {
	palette := []compat.AdaptiveColor{{
		Light: lipgloss.Color("#3DBAC4"),
		Dark:  lipgloss.Color("#58D3DB"),
	}}
	colors := newWorkspaceRunColors(palette)

	seen := make(map[string]string)
	for i := range 24 {
		runPath := fmt.Sprintf("/tmp/run-%02d.wandb", i)
		key := workspaceRunColorKey(colors.Assign(runPath))
		if previous, ok := seen[key]; ok {
			t.Fatalf(
				"workspace color collision: %s and %s both mapped to %s",
				previous, runPath, key,
			)
		}
		seen[key] = runPath
	}
}

func TestWorkspaceRunColorsReleaseAllowsReuse(t *testing.T) {
	palette := []compat.AdaptiveColor{{
		Light: lipgloss.Color("#3DBAC4"),
		Dark:  lipgloss.Color("#58D3DB"),
	}}
	colors := newWorkspaceRunColors(palette)

	first := colors.Assign("/tmp/first.wandb")
	second := colors.Assign("/tmp/second.wandb")
	require.NotEqual(t, workspaceRunColorKey(first), workspaceRunColorKey(second))

	colors.Release("/tmp/first.wandb")
	third := colors.Assign("/tmp/third.wandb")
	require.Equal(t, workspaceRunColorKey(first), workspaceRunColorKey(third))
}

func TestWorkspaceApplyRunKeysAssignsUniqueColors(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	w := NewWorkspace(t.TempDir(), cfg, logger)

	runKeys := make([]string, 0, 24)
	for i := 0; i < 24; i++ {
		runKeys = append(runKeys, fmt.Sprintf("run-20260209_%06d-%08x", 10100+i, i))
	}

	w.applyRunKeys(runKeys)

	seen := make(map[string]string)
	for _, runKey := range runKeys {
		key := workspaceRunColorKey(w.runColorForKey(runKey))
		if previous, ok := seen[key]; ok {
			t.Fatalf(
				"workspace run color collision: %s and %s both mapped to %s",
				previous, runKey, key,
			)
		}
		seen[key] = runKey
	}
}
