package leet

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestExpandedSidebarWidth(t *testing.T) {
	// No override: golden-ratio default.
	require.Equal(t, 76, expandedSidebarWidth(200, false, 0)) // 200 * 0.382
	require.Equal(t, 47, expandedSidebarWidth(200, true, 0))  // 200 * 0.236

	// Override fraction of terminal width.
	require.Equal(t, 50, expandedSidebarWidth(200, false, 0.25))

	// Overrides can go below the default minimum, but not the drag minimum.
	require.Equal(t, sidebarDragMinWidth, expandedSidebarWidth(200, false, 0.05))

	// The main content column keeps its minimum width.
	require.Equal(t, 200-mainDragMinWidth, expandedSidebarWidth(200, false, 0.99))
}

func TestPaneHeightFor(t *testing.T) {
	require.Equal(t, 17, paneHeightFor(0, 60, 17))
	require.Equal(t, 30, paneHeightFor(0.5, 60, 17))
}
