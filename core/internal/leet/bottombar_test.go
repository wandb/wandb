package leet_test

import (
	"fmt"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
)

func expandBottomBar(t *testing.T, bb *leet.BottomBar, height int) {
	t.Helper()

	bb.SetExpandedHeight(height)
	bb.Toggle()

	// Complete the animation deterministically (no sleep).
	bb.Update(time.Now().Add(leet.AnimationDuration + time.Millisecond))

	require.True(t, bb.IsExpanded(), "bottom bar should be expanded")
	require.False(t, bb.IsAnimating(), "bottom bar animation should be complete")
	require.Equal(t, height, bb.Height(), "expanded bottom bar height should match")
}

func makeLogs(n int) []leet.KeyValuePair {
	logs := make([]leet.KeyValuePair, n)
	for i := range n {
		logs[i] = leet.KeyValuePair{
			Key:   fmt.Sprintf("t%02d", i+1),
			Value: fmt.Sprintf("log %02d", i+1),
		}
	}
	return logs
}

func TestBottomBar_AutoScrollFreezesWhenUserScrollsUp(t *testing.T) {
	bb := leet.NewBottomBar()
	expandBottomBar(t, bb, 5) // border + header + 3 content lines

	bb.SetConsoleLogs(makeLogs(10))
	out := stripANSI(bb.View(80))
	require.Contains(t, out, "[9-10 of 10]", "should auto-scroll to the end initially")

	// User scrolls off the last line -> autoScroll should turn off.
	bb.Up()

	// New logs arrive: view should NOT jump to show the new end.
	bb.SetConsoleLogs(makeLogs(11))
	out = stripANSI(bb.View(80))
	require.Contains(t, out, "[9-10 of 11]", "should not jump to end when autoScroll is disabled")

	// Explicit scroll-to-end should re-enable auto-scroll.
	bb.ScrollToEnd()
	out = stripANSI(bb.View(80))
	require.Contains(t, out, "[10-11 of 11]", "ScrollToEnd should jump back to the end")
}

func TestBottomBar_PageUpDown_WrapsAround(t *testing.T) {
	bb := leet.NewBottomBar()
	expandBottomBar(t, bb, 4) // border + header + 2 content lines

	bb.SetConsoleLogs(makeLogs(5))
	out := stripANSI(bb.View(80))
	require.Contains(t, out, "[5-5 of 5]", "should start at end when auto-scroll is on")

	// PageDown from the end should wrap to the top.
	bb.PageDown()
	out = stripANSI(bb.View(80))
	require.Contains(t, out, "[1-1 of 5]", "PageDown at end should wrap to start")

	// PageUp from the top should wrap back to the end.
	bb.PageUp()
	out = stripANSI(bb.View(80))
	require.Contains(t, out, "[5-5 of 5]", "PageUp at start should wrap to end")
}
