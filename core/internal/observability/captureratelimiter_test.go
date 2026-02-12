package observability_test

import (
	"testing"
	"testing/synctest"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observability"
)

func TestCaptureRateLimiter(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		rl, err := observability.NewCaptureRateLimiter(2, time.Minute)
		require.NoError(t, err)

		// Messages should be allowed initially.
		assert.True(t, rl.AllowCapture("message 1"))
		assert.True(t, rl.AllowCapture("message 2"))

		// Let 30 seconds pass. Neither message can go through yet.
		time.Sleep(30 * time.Second)
		assert.False(t, rl.AllowCapture("message 1"))
		assert.False(t, rl.AllowCapture("message 2"))

		// Let 31 seconds pass. Messages can go through now.
		time.Sleep(31 * time.Second)
		assert.True(t, rl.AllowCapture("message 1"))
		assert.True(t, rl.AllowCapture("message 2"))
	})
}

func TestCaptureRateLimiterNil(t *testing.T) {
	var rl *observability.CaptureRateLimiter

	// Shouldn't panic and should return true.
	assert.True(t, rl.AllowCapture("test"))
}
