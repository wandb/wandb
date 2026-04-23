package leet_test

import (
	"fmt"
	"image/color"
	"path/filepath"
	"testing"

	"charm.land/lipgloss/v2"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func testWorkspaceRunColorPalette() []leet.AdaptiveColor {
	return []leet.AdaptiveColor{{
		Light: lipgloss.Color("#3DBAC4"),
		Dark:  lipgloss.Color("#58D3DB"),
	}}
}

func TestWorkspaceRunColorsAssignUniqueWithinWorkspace(t *testing.T) {
	colors := leet.TestNewWorkspaceRunColors(testWorkspaceRunColorPalette())

	seen := make(map[string]string)
	for i := range 256 {
		runPath := fmt.Sprintf("/tmp/run-%03d.wandb", i)
		key := leet.TestWorkspaceRunColorKey(colors.Assign(runPath))
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
	colors := leet.TestNewWorkspaceRunColors(testWorkspaceRunColorPalette())

	first := colors.Assign("/tmp/first.wandb")
	second := colors.Assign("/tmp/second.wandb")
	require.NotEqual(t, leet.TestWorkspaceRunColorKey(first), leet.TestWorkspaceRunColorKey(second))

	colors.Release("/tmp/first.wandb")
	third := colors.Assign("/tmp/third.wandb")
	require.Equal(t, leet.TestWorkspaceRunColorKey(first), leet.TestWorkspaceRunColorKey(third))
}

func TestWorkspaceApplyRunKeysAssignsUniqueColors(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	w := leet.NewWorkspace(t.TempDir(), cfg, logger)

	runKeys := make([]string, 0, 24)
	for i := 0; i < 24; i++ {
		runKeys = append(runKeys, fmt.Sprintf("run-20260209_%06d-%08x", 10100+i, i))
	}

	w.TestApplyRunKeys(runKeys)

	seen := make(map[string]string)
	for _, runKey := range runKeys {
		key := leet.TestWorkspaceRunColorKey(w.TestRunColorForKey(runKey))
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
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	w := leet.NewWorkspace(t.TempDir(), cfg, logger)
	w.TestSetRunColors(testWorkspaceRunColorPalette())

	const (
		runA = "run-20260209_010100-aaaabbbb"
		runB = "run-20260209_010101-bbbbcccc"
		runC = "run-20260209_010102-ccccdddd"
	)

	w.TestApplyRunKeys([]string{runA, runB})
	colorA := leet.TestWorkspaceRunColorKey(w.TestRunColorForKey(runA))
	colorB := leet.TestWorkspaceRunColorKey(w.TestRunColorForKey(runB))
	require.NotEqual(t, colorA, colorB)

	w.TestApplyRunKeys([]string{runB})
	w.TestApplyRunKeys([]string{runB, runC})
	colorC := leet.TestWorkspaceRunColorKey(w.TestRunColorForKey(runC))
	require.Equal(t, colorA, colorC)
}

func TestWorkspaceRunColorComponentRGBAcceptsColorColor(t *testing.T) {
	r, g, b, ok := leet.TestWorkspaceRunColorComponentRGB(
		color.RGBA{R: 0x3D, G: 0xBA, B: 0xC4, A: 0xFF})
	require.True(t, ok)
	require.Equal(t, uint8(0x3D), r)
	require.Equal(t, uint8(0xBA), g)
	require.Equal(t, uint8(0xC4), b)
}
