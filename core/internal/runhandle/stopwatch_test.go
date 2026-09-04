package runhandle_test

import (
	"testing"
	"testing/synctest"
	"time"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/runhandle"
)

func TestStopwatch_ZeroIsPaused(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		var stopwatch runhandle.Stopwatch

		assert.Zero(t, stopwatch.Elapsed())
		synctest.Sleep(time.Minute)
		assert.Zero(t, stopwatch.Elapsed())
	})
}

func TestStopwatch_TracksTimeWhileRunning(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		var stopwatch runhandle.Stopwatch

		stopwatch.Start()
		synctest.Sleep(11 * time.Second)
		stopwatch.Stop()
		synctest.Sleep(2 * time.Second)
		stopwatch.Start()
		synctest.Sleep(7 * time.Second)

		assert.Equal(t, 18*time.Second, stopwatch.Elapsed())
	})
}

func TestStopwatch_CanBeAdjusted(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		var stopwatch runhandle.Stopwatch

		stopwatch.Start()
		stopwatch.Adjust(2 * time.Second)
		synctest.Sleep(3 * time.Second)
		stopwatch.Adjust(4 * time.Second)
		stopwatch.Stop()
		stopwatch.Adjust(5 * time.Second)

		assert.Equal(t, 14*time.Second, stopwatch.Elapsed())
	})
}

func TestStopwatch_StartIdempotent(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		var stopwatch runhandle.Stopwatch

		stopwatch.Start()
		synctest.Sleep(time.Minute)
		stopwatch.Start()
		synctest.Sleep(2 * time.Minute)

		assert.Equal(t, 3*time.Minute, stopwatch.Elapsed())
	})
}

func TestStopwatch_StopIdempotent(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		var stopwatch runhandle.Stopwatch

		stopwatch.Start()
		synctest.Sleep(time.Minute)
		stopwatch.Stop()
		synctest.Sleep(2 * time.Minute)
		stopwatch.Stop()
		synctest.Sleep(3 * time.Minute)

		assert.Equal(t, time.Minute, stopwatch.Elapsed())
	})
}
