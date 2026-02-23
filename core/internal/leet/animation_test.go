package leet_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
)

func TestAnimatedValue_ToggleStartsAnimation(t *testing.T) {
	anim := leet.NewAnimatedValue(false, 40)
	anim.Toggle()
	require.True(t, anim.IsAnimating())
	for anim.IsAnimating() {
		time.Sleep(20 * time.Millisecond)
		anim.Update(time.Now())
	}
	require.True(t, anim.IsVisible())
	require.True(t, anim.IsExpanded())
	require.Equal(t, 40, anim.Value())

	anim.Toggle()
	require.True(t, anim.IsAnimating())
	for anim.IsAnimating() {
		time.Sleep(20 * time.Millisecond)
		anim.Update(time.Now())
	}
	require.True(t, anim.IsCollapsed())
	require.False(t, anim.IsVisible())
	require.Equal(t, 0, anim.Value())
}

func TestAnimatedValue_UpdateAnimatesToCompletion(t *testing.T) {
	anim := leet.NewAnimatedValue(false, 50)

	valuesSeen := make(map[int]struct{})
	maxIterations := 100
	iterations := 0

	anim.Toggle()

	for anim.IsAnimating() && iterations < maxIterations {
		complete := anim.Update(time.Now())
		valuesSeen[anim.Value()] = struct{}{}

		if !complete {
			time.Sleep(10 * time.Millisecond)
		}
		iterations++
	}

	// Should have seen multiple intermediate values.
	require.Greater(t, len(valuesSeen), 2, "animation should progress through multiple values")
	require.Equal(t, 50, anim.Value(), "should end at target value")
	require.False(t, anim.IsAnimating(), "animation should be complete")
}

func TestAnimatedValue_ToggleDuringAnimation(t *testing.T) {
	anim := leet.NewAnimatedValue(false, 50)
	anim.Toggle()

	// Let it animate partway.
	time.Sleep(50 * time.Millisecond)
	anim.Update(time.Now())

	partialValue := anim.Value()
	require.Greater(t, partialValue, 0, "should have started expanding")
	require.Less(t, partialValue, 50, "should not be fully expanded")

	// Toggle during animation should revert back to the original state.
	anim.Toggle()
	for anim.IsAnimating() {
		time.Sleep(10 * time.Millisecond)
		anim.Update(time.Now())
	}
	require.Equal(t, 0, anim.Value())
}

func TestAnimatedValue_SetExpanded_SnapsWhenAlreadyExpanded(t *testing.T) {
	anim := leet.NewAnimatedValue(true, 40) // expanded at 40
	require.True(t, anim.IsExpanded())
	require.Equal(t, 40, anim.Value())

	anim.SetExpanded(80) // first WindowSizeMsg computes larger target

	// Should snap immediately because we were stably expanded.
	require.True(t, anim.IsExpanded())
	require.Equal(t, 80, anim.Value())
}

func TestAnimatedValue_SetExpanded_DoesNotSnapWhenCollapsed(t *testing.T) {
	anim := leet.NewAnimatedValue(false, 40) // collapsed
	require.False(t, anim.IsVisible())

	anim.SetExpanded(80)
	// Still collapsed; only the future target changed.
	require.False(t, anim.IsVisible())
	require.Equal(t, 0, anim.Value())
}
