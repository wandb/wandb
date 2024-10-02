package tensorboard_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/tensorboard"
)

func Test_Matches(t *testing.T) {
	filter := tensorboard.TFEventsFileFilter{
		Hostname:     "hostname",
		StartTimeSec: 5000,
	}

	t.Run("true if hostname and time are good", func(t *testing.T) {
		assert.True(t,
			filter.Matches("dir/events.out.tfevents.9000.hostname.9743.0.v2"))
	})

	t.Run("false if hostname is wrong", func(t *testing.T) {
		assert.False(t,
			filter.Matches("dir/events.out.tfevents.9000.WRONG.9743.0.v2"))
	})

	t.Run("false if time is too early", func(t *testing.T) {
		assert.False(t,
			filter.Matches("dir/events.out.tfevents.1000.hostname.9743.0.v2"))
	})

	t.Run("false with .profile-empty suffix", func(t *testing.T) {
		assert.False(t,
			filter.Matches("dir/events.out.tfevents.9000.hostname.9743.0.v2.profile-empty"))
	})

	t.Run("false with .sagemaker-uploaded suffix", func(t *testing.T) {
		assert.False(t,
			filter.Matches("dir/events.out.tfevents.9000.hostname.9743.0.v2.sagemaker-uploaded"))
	})

	t.Run("false if wrong format", func(t *testing.T) {
		assert.False(t, filter.Matches("not a file name"))
	})
}
