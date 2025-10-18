package leet_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/leet"
)

func TestAnimationState_ToggleStartsAnimation(t *testing.T) {
	anim := leet.NewAnimationState(false, 40)
	anim.Toggle()
	require.True(t, anim.IsAnimating())
	require.True(t, anim.IsVisible())

	for anim.IsAnimating() {
		time.Sleep(20 * time.Millisecond)
		anim.Update()
	}

	require.Equal(t, 40, anim.Width())
	require.Equal(t, leet.SidebarExpanded, anim.State())

	anim.Toggle()
	require.True(t, anim.IsAnimating())

	for anim.IsAnimating() {
		time.Sleep(20 * time.Millisecond)
		anim.Update()
	}

	require.Equal(t, 0, anim.Width())
	require.Equal(t, leet.SidebarCollapsed, anim.State())
}

func TestAnimationState_UpdateAnimatesToCompletion(t *testing.T) {
	anim := leet.NewAnimationState(false, 50)
	anim.Toggle()

	widthsSeen := make(map[int]bool)
	maxIterations := 100
	iterations := 0

	for anim.IsAnimating() && iterations < maxIterations {
		complete := anim.Update()
		widthsSeen[anim.Width()] = true

		if !complete {
			time.Sleep(10 * time.Millisecond)
		}
		iterations++
	}

	// Should have seen multiple intermediate widths
	require.Greater(t, len(widthsSeen), 2, "animation should progress through multiple widths")
	require.Equal(t, 50, anim.Width(), "should end at target width")
	require.False(t, anim.IsAnimating(), "animation should be complete")
}

func TestAnimationState_ToggleDuringAnimation(t *testing.T) {
	anim := leet.NewAnimationState(false, 50)
	anim.Toggle()

	// Let it animate partway
	time.Sleep(50 * time.Millisecond)
	anim.Update()

	partialWidth := anim.Width()
	require.Greater(t, partialWidth, 0, "should have started expanding")
	require.Less(t, partialWidth, 50, "should not be fully expanded")

	// Toggle during animation does nothing (only works from stable states).
	anim.Toggle()
	time.Sleep(50 * time.Millisecond)
	anim.Update()

	// Should continue expanding to completion.
	for anim.IsAnimating() {
		time.Sleep(10 * time.Millisecond)
		anim.Update()
	}

	require.Equal(t, 50, anim.Width())
}
