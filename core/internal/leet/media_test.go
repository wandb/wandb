package leet_test

import (
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestParseHistory_ImageFile(t *testing.T) {
	runPath := filepath.Join("/tmp", "offline-run-123", "run-123.wandb")
	relPath := filepath.Join("media", "images", "media", "generated_sample_7.png")

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{
			{NestedKey: []string{"_step"}, ValueJson: "7"},
			{NestedKey: []string{"media/generated_sample", "_type"}, ValueJson: `"image-file"`},
			{NestedKey: []string{"media/generated_sample", "path"}, ValueJson: `"` + relPath + `"`},
			{NestedKey: []string{"media/generated_sample", "format"}, ValueJson: `"png"`},
			{NestedKey: []string{"media/generated_sample", "width"}, ValueJson: "64"},
			{NestedKey: []string{"media/generated_sample", "height"}, ValueJson: "64"},
			{NestedKey: []string{"media/generated_sample", "caption"}, ValueJson: `"step=7"`},
		},
	}

	msg, ok := leet.ParseHistory(runPath, history).(leet.HistoryMsg)
	require.True(t, ok)
	require.Contains(t, msg.Media, "media/generated_sample")
	require.Len(t, msg.Media["media/generated_sample"], 1)

	point := msg.Media["media/generated_sample"][0]
	require.Equal(t, 7.0, point.X)
	require.Equal(t, filepath.Join(filepath.Dir(runPath), "files", relPath), point.FilePath)
	require.Equal(t, relPath, point.RelativePath)
	require.Equal(t, "step=7", point.Caption)
	require.Equal(t, "png", point.Format)
	require.Equal(t, 64, point.Width)
	require.Equal(t, 64, point.Height)
}

func TestMediaStoreResolveAt(t *testing.T) {
	store := leet.NewMediaStore()

	require.True(t, store.ProcessHistory(leet.HistoryMsg{
		Media: map[string][]leet.MediaPoint{
			"media/generated_sample": {{X: 1, FilePath: "/tmp/1.png", Caption: "step=1"}},
		},
	}))
	require.True(t, store.ProcessHistory(leet.HistoryMsg{
		Media: map[string][]leet.MediaPoint{
			"media/generated_sample": {{X: 5, FilePath: "/tmp/5.png", Caption: "step=5"}},
		},
	}))

	point, ok := store.ResolveAt("media/generated_sample", 4)
	require.True(t, ok)
	require.Equal(t, "/tmp/1.png", point.FilePath)
	require.Equal(t, "step=1", point.Caption)

	point, ok = store.ResolveAt("media/generated_sample", 5)
	require.True(t, ok)
	require.Equal(t, "/tmp/5.png", point.FilePath)
	require.Equal(t, "step=5", point.Caption)

	_, ok = store.ResolveAt("media/generated_sample", 0)
	require.False(t, ok)
}
