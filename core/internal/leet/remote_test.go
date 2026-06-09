package leet_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
)

func TestParseRemoteURL_HappyPath(t *testing.T) {
	cases := []struct {
		name string
		in   string
		want leet.RemoteRunParams
	}{
		{
			name: "with /runs/",
			in:   "https://wandb.ai/team/proj/runs/abc123",
			want: leet.RemoteRunParams{
				BaseURL: "https://wandb.ai",
				Entity:  "team",
				Project: "proj",
				RunId:   "abc123",
			},
		},
		{
			name: "without /runs/",
			in:   "https://wandb.ai/team/proj/abc123",
			want: leet.RemoteRunParams{
				BaseURL: "https://wandb.ai",
				Entity:  "team",
				Project: "proj",
				RunId:   "abc123",
			},
		},
		{
			name: "with /sweeps/",
			in:   "https://wandb.ai/team/proj/sweeps/sw1",
			want: leet.RemoteRunParams{
				BaseURL: "https://wandb.ai",
				Entity:  "team",
				Project: "proj",
				RunId:   "sw1",
			},
		},
		{
			name: "custom host with port and http",
			in:   "http://wandb.local:8080/team/proj/runs/r1",
			want: leet.RemoteRunParams{
				BaseURL: "http://wandb.local:8080",
				Entity:  "team",
				Project: "proj",
				RunId:   "r1",
			},
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, err := leet.ParseRemoteURL(tc.in)
			require.NoError(t, err)
			assert.Equal(t, tc.want, *got)
		})
	}
}

func TestParseRemoteURL_Rejects(t *testing.T) {
	cases := []struct {
		name string
		in   string
	}{
		{"empty", ""},
		{"non-http scheme", "ftp://wandb.ai/team/proj/r1"},
		{"missing host", "https:///team/proj/r1"},
		{"too few segments", "https://wandb.ai/team/proj"},
		{"too many segments", "https://wandb.ai/team/proj/runs/r1/extra"},
		{"empty entity", "https://wandb.ai//proj/r1"},
		{"unparseable", "not a url at all\n://"},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := leet.ParseRemoteURL(tc.in)
			assert.Error(t, err)
		})
	}
}
