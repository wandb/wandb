package leet_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
)

func TestParseRemoteURL(t *testing.T) {
	tests := []struct {
		name string
		url  string
		want *leet.RemoteRunParams
	}{
		{
			name: "run URL with runs segment",
			url:  "https://wandb.ai/my-entity/my-project/runs/abc123",
			want: &leet.RemoteRunParams{
				BaseURL: "https://wandb.ai",
				Entity:  "my-entity",
				Project: "my-project",
				RunID:   "abc123",
			},
		},
		{
			name: "run URL without runs segment",
			url:  "https://api.wandb.ai/my-entity/my-project/abc123",
			want: &leet.RemoteRunParams{
				BaseURL: "https://api.wandb.ai",
				Entity:  "my-entity",
				Project: "my-project",
				RunID:   "abc123",
			},
		},
		{
			name: "entity named runs",
			url:  "https://wandb.ai/runs/my-project/runs/abc123",
			want: &leet.RemoteRunParams{
				BaseURL: "https://wandb.ai",
				Entity:  "runs",
				Project: "my-project",
				RunID:   "abc123",
			},
		},
		{
			name: "trailing slash",
			url:  "http://localhost:8080/my-entity/my-project/runs/abc123/",
			want: &leet.RemoteRunParams{
				BaseURL: "http://localhost:8080",
				Entity:  "my-entity",
				Project: "my-project",
				RunID:   "abc123",
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := leet.ParseRemoteURL(tt.url)
			require.NoError(t, err)
			assert.Equal(t, tt.want, got)
		})
	}
}

func TestParseRemoteURL_Errors(t *testing.T) {
	urls := []string{
		"ftp://wandb.ai/entity/project/runs/abc123",
		"wandb.ai/entity/project/runs/abc123",
		"https:///entity/project/runs/abc123",
		"https://wandb.ai/entity/project",
		"https://wandb.ai/entity/project/sweeps/abc123",
		"https://wandb.ai/entity/project/runs/abc123/extra",
		"https://wandb.ai",
	}
	for _, url := range urls {
		t.Run(url, func(t *testing.T) {
			_, err := leet.ParseRemoteURL(url)
			require.Error(t, err)
		})
	}
}
