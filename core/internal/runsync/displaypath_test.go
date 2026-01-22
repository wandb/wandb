package runsync_test

import (
	"testing"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/runsync"
)

func TestDisplayPath(t *testing.T) {
	testCases := []struct {
		name     string
		path     string
		cwd      string
		expected string
	}{
		{
			"uses sync dir",
			"offline-run-xyz/run-xyz.wandb",
			"",
			"offline-run-xyz",
		},
		{
			"uses path if no sync dir",
			"run-xyz.wandb",
			"",
			"run-xyz.wandb",
		},
		{
			"relative to CWD",
			"/my/cwd/run-xyz.wandb",
			"/my/cwd",
			"run-xyz.wandb",
		},
		{
			"relative to CWD but outside it",
			"/path/run-xyz.wandb",
			"/path/cwd",
			"../run-xyz.wandb",
		},
		{
			"not relative to CWD if longer",
			"/other/run-xyz.wandb",
			"/cwd",
			"/other/run-xyz.wandb",
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			displayPath := runsync.ToDisplayPath(tc.path, tc.cwd)
			assert.Equal(t, tc.expected, string(displayPath))
		})
	}
}
