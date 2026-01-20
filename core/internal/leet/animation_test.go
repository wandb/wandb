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
	for anim.IsAnimating() {
		time.Sleep(20 * time.Millisecond)
		anim.Update(time.Now())
	}
	require.True(t, anim.IsVisible())
	require.True(t, anim.IsExpanded())
	require.Equal(t, 40, anim.Width())

	anim.Toggle()
	require.True(t, anim.IsAnimating())
	for anim.IsAnimating() {
		time.Sleep(20 * time.Millisecond)
		anim.Update(time.Now())
	}
	require.True(t, anim.IsCollapsed())
	require.False(t, anim.IsVisible())
	require.Equal(t, 0, anim.Width())
}

func TestAnimationState_UpdateAnimatesToCompletion(t *testing.T) {
	anim := leet.NewAnimationState(false, 50)

	widthsSeen := make(map[int]struct{})
	maxIterations := 100
	iterations := 0

	anim.Toggle()

	for anim.IsAnimating() && iterations < maxIterations {
		complete := anim.Update(time.Now())
		widthsSeen[anim.Width()] = struct{}{}

		if !complete {
			time.Sleep(10 * time.Millisecond)
		}
		iterations++
	}

	// Should have seen multiple intermediate widths.
	require.Greater(t, len(widthsSeen), 2, "animation should progress through multiple widths")
	require.Equal(t, 50, anim.Width(), "should end at target width")
	require.False(t, anim.IsAnimating(), "animation should be complete")
}

func TestAnimationState_ToggleDuringAnimation(t *testing.T) {
	anim := leet.NewAnimationState(false, 50)
	anim.Toggle()

	// Let it animate partway.
	time.Sleep(50 * time.Millisecond)
	anim.Update(time.Now())

	partialWidth := anim.Width()
	require.Greater(t, partialWidth, 0, "should have started expanding")
	require.Less(t, partialWidth, 50, "should not be fully expanded")

	// Toggle during animation should revert back to the original state.
	anim.Toggle()
	for anim.IsAnimating() {
		time.Sleep(10 * time.Millisecond)
		anim.Update(time.Now())
	}
	require.Equal(t, 0, anim.Width())
}

func TestAnimationState_SetExpandedWidth_SnapsWhenAlreadyExpanded(t *testing.T) {
	anim := leet.NewAnimationState(true, 40) // expanded at 40
	require.True(t, anim.IsExpanded())
	require.Equal(t, 40, anim.Width())

	anim.SetExpandedWidth(80) // first WindowSizeMsg computes larger target

	// Should snap immediately because we were stably expanded.
	require.True(t, anim.IsExpanded())
	require.Equal(t, 80, anim.Width())
}

func TestAnimationState_SetExpandedWidth_DoesNotSnapWhenCollapsed(t *testing.T) {
	anim := leet.NewAnimationState(false, 40) // collapsed
	require.False(t, anim.IsVisible())

	anim.SetExpandedWidth(80)
	// Still collapsed; only the future target changed.
	require.False(t, anim.IsVisible())
	require.Equal(t, 0, anim.Width())
}
