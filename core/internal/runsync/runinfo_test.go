package runsync_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/runsync"
)

func TestRunInfo_URL(t *testing.T) {
	t.Run("produces clean escaped URL", func(t *testing.T) {
		runInfo := runsync.RunInfo{
			Entity:  "entity with space",
			Project: "project?",
			// Common special characters people include in run IDs.
			// Just the forward slash should be URL-escaped.
			RunID: "me@machine/x=1&y=+$2",
		}

		url, err := runInfo.URL("https://my-web-ui///")

		assert.NoError(t, err)
		assert.Equal(t,
			"https://my-web-ui/entity%20with%20space/project%3F/runs/me@machine%2Fx=1&y=+$2",
			url)
	})

	t.Run("no entity", func(t *testing.T) {
		runInfo := runsync.RunInfo{Project: "project", RunID: "id"}

		_, err := runInfo.URL("https://wandb.ai")

		assert.ErrorContains(t, err, "no entity")
	})

	t.Run("no project", func(t *testing.T) {
		runInfo := runsync.RunInfo{Entity: "entity", RunID: "id"}

		_, err := runInfo.URL("https://wandb.ai")

		assert.ErrorContains(t, err, "no project")
	})

	t.Run("no ID", func(t *testing.T) {
		runInfo := runsync.RunInfo{Entity: "entity", Project: "project"}

		_, err := runInfo.URL("https://wandb.ai")

		assert.ErrorContains(t, err, "no run ID")
	})
}
