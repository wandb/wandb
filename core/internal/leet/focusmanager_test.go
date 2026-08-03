package leet_test

import (
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
)

// newTwoRegionFocusManager builds a manager with an overview and a logs
// region whose availability is controlled by the returned pointers.
func newTwoRegionFocusManager(
	overviewAvailable, logsAvailable *bool,
	overviewActive, logsActive *bool,
) *leet.FocusManager {
	return leet.NewFocusManager([]leet.FocusRegionDef{
		{
			Target:     leet.FocusTargetOverview,
			Available:  func() bool { return *overviewAvailable },
			Activate:   func(int) { *overviewActive = true },
			Deactivate: func() { *overviewActive = false },
		},
		{
			Target:     leet.FocusTargetConsoleLogs,
			Available:  func() bool { return *logsAvailable },
			Activate:   func(int) { *logsActive = true },
			Deactivate: func() { *logsActive = false },
		},
	})
}

func TestFocusManagerResolveKeepsAvailableFocus(t *testing.T) {
	overviewAvailable, logsAvailable := true, true
	var overviewActive, logsActive bool
	fm := newTwoRegionFocusManager(
		&overviewAvailable, &logsAvailable, &overviewActive, &logsActive)

	fm.SetTarget(leet.FocusTargetOverview, 1)
	fm.Resolve()

	require.True(t, fm.IsTarget(leet.FocusTargetOverview))
	require.True(t, overviewActive)
}

func TestFocusManagerResolveClearsUnavailableFocus(t *testing.T) {
	overviewAvailable, logsAvailable := true, true
	var overviewActive, logsActive bool
	fm := newTwoRegionFocusManager(
		&overviewAvailable, &logsAvailable, &overviewActive, &logsActive)

	fm.SetTarget(leet.FocusTargetOverview, 1)
	require.True(t, overviewActive)

	// The focused region disappears: focus clears rather than jumping to
	// another region.
	overviewAvailable = false
	fm.Resolve()

	require.True(t, fm.IsTarget(leet.FocusTargetNone))
	require.False(t, overviewActive)
	require.False(t, logsActive)
}

func TestFocusManagerResolveIsNoOpWhenNothingFocused(t *testing.T) {
	overviewAvailable, logsAvailable := true, true
	var overviewActive, logsActive bool
	fm := newTwoRegionFocusManager(
		&overviewAvailable, &logsAvailable, &overviewActive, &logsActive)

	fm.Resolve()

	require.True(t, fm.IsTarget(leet.FocusTargetNone))
	require.False(t, overviewActive)
	require.False(t, logsActive)
}

func TestFocusManagerTabSkipsUnavailableRegions(t *testing.T) {
	overviewAvailable, logsAvailable := false, true
	var overviewActive, logsActive bool
	fm := newTwoRegionFocusManager(
		&overviewAvailable, &logsAvailable, &overviewActive, &logsActive)

	fm.Tab(1)

	require.True(t, fm.IsTarget(leet.FocusTargetConsoleLogs))
	require.True(t, logsActive)
	require.False(t, overviewActive)
}
