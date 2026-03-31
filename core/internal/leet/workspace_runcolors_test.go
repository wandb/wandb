package leet

import (
	"fmt"
	"image/color"
	"path/filepath"
	"testing"

	"charm.land/lipgloss/v2"
	"charm.land/lipgloss/v2/compat"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observability"
)

func testWorkspaceRunColorPalette() []compat.AdaptiveColor {
	return []compat.AdaptiveColor{{
		Light: lipgloss.Color("#3DBAC4"),
		Dark:  lipgloss.Color("#58D3DB"),
	}}
}

func TestWorkspaceRunColorsAssignUniqueWithinWorkspace(t *testing.T) {
	colors := newWorkspaceRunColors(testWorkspaceRunColorPalette())

	seen := make(map[string]string)
	for i := range 256 {
		runPath := fmt.Sprintf("/tmp/run-%03d.wandb", i)
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
	colors := newWorkspaceRunColors(testWorkspaceRunColorPalette())

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
	w := NewWorkspace(NewLocalWorkspaceBackend(t.TempDir(), logger), cfg, logger)

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

func TestWorkspaceApplyRunKeysReusesReleasedColor(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	w := NewWorkspace(NewLocalWorkspaceBackend(t.TempDir(), logger), cfg, logger)
	w.runColors = newWorkspaceRunColors(testWorkspaceRunColorPalette())

	const (
		runA = "run-20260209_010100-aaaabbbb"
		runB = "run-20260209_010101-bbbbcccc"
		runC = "run-20260209_010102-ccccdddd"
	)

	w.applyRunKeys([]string{runA, runB})
	colorA := workspaceRunColorKey(w.runColorForKey(runA))
	colorB := workspaceRunColorKey(w.runColorForKey(runB))
	require.NotEqual(t, colorA, colorB)

	w.applyRunKeys([]string{runB})
	w.applyRunKeys([]string{runB, runC})
	colorC := workspaceRunColorKey(w.runColorForKey(runC))
	require.Equal(t, colorA, colorC)
}

func TestWorkspaceRunColorComponentRGBAcceptsColorColor(t *testing.T) {
	r, g, b, ok := workspaceRunColorComponentRGB(
		color.RGBA{R: 0x3D, G: 0xBA, B: 0xC4, A: 0xFF})
	require.True(t, ok)
	require.Equal(t, uint8(0x3D), r)
	require.Equal(t, uint8(0xBA), g)
	require.Equal(t, uint8(0xC4), b)
}
