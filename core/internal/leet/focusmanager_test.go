package leet_test

import (
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
)

func TestFocusManagerResolveAfterVisibilityChangeUsesTargetAvailability(t *testing.T) {
	currentOverviewVisible := true
	targetOverviewVisible := true
	overviewActive := false
	logsActive := false

	fm := leet.NewFocusManager([]leet.FocusRegionDef{
		{
			Target:          leet.FocusTargetOverview,
			Available:       func() bool { return currentOverviewVisible },
			AvailableTarget: func() bool { return targetOverviewVisible },
			Activate:        func(int) { overviewActive = true },
			Deactivate:      func() { overviewActive = false },
		},
		{
			Target:          leet.FocusTargetConsoleLogs,
			Available:       func() bool { return true },
			AvailableTarget: func() bool { return true },
			Activate:        func(int) { logsActive = true },
			Deactivate:      func() { logsActive = false },
		},
	})

	fm.SetTarget(leet.FocusTargetOverview, 1)
	require.True(t, fm.IsTarget(leet.FocusTargetOverview))
	require.True(t, overviewActive)

	targetOverviewVisible = false
	fm.ResolveAfterVisibilityChange()

	require.True(t, fm.IsTarget(leet.FocusTargetConsoleLogs))
	require.False(t, overviewActive)
	require.True(t, logsActive)
}
