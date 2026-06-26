package leet_test

import (
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestParseHistory_ImageFile(t *testing.T) {
	runPath := filepath.Join("tmp", "offline-run-123", "run-123.wandb")
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

func TestParseHistory_ImageFile_NormalizesRelativePathWithinFilesDir(t *testing.T) {
	runPath := filepath.Join("tmp", "offline-run-123", "run-123.wandb")
	relPath := filepath.Join("..", "outside", "generated_sample_7.png")

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{
			{NestedKey: []string{"_step"}, ValueJson: "7"},
			{NestedKey: []string{"media/generated_sample", "_type"}, ValueJson: `"image-file"`},
			{NestedKey: []string{"media/generated_sample", "path"}, ValueJson: `"` + relPath + `"`},
			{NestedKey: []string{"media/generated_sample", "format"}, ValueJson: `"png"`},
			{NestedKey: []string{"media/generated_sample", "width"}, ValueJson: "64"},
			{NestedKey: []string{"media/generated_sample", "height"}, ValueJson: "64"},
		},
	}

	msg, ok := leet.ParseHistory(runPath, history).(leet.HistoryMsg)
	require.True(t, ok)
	require.Contains(t, msg.Media, "media/generated_sample")
	require.Len(t, msg.Media["media/generated_sample"], 1)

	point := msg.Media["media/generated_sample"][0]
	require.Equal(
		t,
		filepath.Join(filepath.Dir(runPath), "files", "outside", "generated_sample_7.png"),
		point.FilePath,
	)
}

func TestParseHistory_ImagesSeparated(t *testing.T) {
	runPath := filepath.Join("tmp", "offline-run-123", "run-123.wandb")

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{
			{NestedKey: []string{"_step"}, ValueJson: "7"},
			{NestedKey: []string{"attention_maps", "_type"}, ValueJson: `"images/separated"`},
			{
				NestedKey: []string{"attention_maps", "filenames"},
				ValueJson: `["media/images/maps_7_0.png","media/images/maps_7_1.png"]`,
			},
			{NestedKey: []string{"attention_maps", "captions"}, ValueJson: `["head 0","head 1"]`},
			{NestedKey: []string{"attention_maps", "format"}, ValueJson: `"png"`},
			{NestedKey: []string{"attention_maps", "width"}, ValueJson: "64"},
			{NestedKey: []string{"attention_maps", "height"}, ValueJson: "64"},
			{NestedKey: []string{"attention_maps", "count"}, ValueJson: "2"},
		},
	}

	msg, ok := leet.ParseHistory(runPath, history).(leet.HistoryMsg)
	require.True(t, ok)
	require.Len(t, msg.Media, 2)
	require.Contains(t, msg.Media, "attention_maps[0]")
	require.Contains(t, msg.Media, "attention_maps[1]")

	point := msg.Media["attention_maps[1]"][0]
	require.Equal(t, 7.0, point.X)
	require.Equal(
		t,
		filepath.Join(filepath.Dir(runPath), "files", "media", "images", "maps_7_1.png"),
		point.FilePath,
	)
	require.Equal(t, "media/images/maps_7_1.png", point.RelativePath)
	require.Equal(t, "head 1", point.Caption)
	require.Equal(t, "png", point.Format)
	require.Equal(t, 64, point.Width)
	require.Equal(t, 64, point.Height)

	// Media metadata must not leak into scalar metrics.
	require.NotContains(t, msg.Metrics, "attention_maps.count")
}

func TestParseHistory_ImagesSeparated_NoCaptions(t *testing.T) {
	runPath := filepath.Join("tmp", "offline-run-123", "run-123.wandb")

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{
			{NestedKey: []string{"_step"}, ValueJson: "3"},
			{NestedKey: []string{"samples", "_type"}, ValueJson: `"images/separated"`},
			{NestedKey: []string{"samples", "filenames"}, ValueJson: `["media/images/s_3_0.png"]`},
			{NestedKey: []string{"samples", "format"}, ValueJson: `"png"`},
		},
	}

	msg, ok := leet.ParseHistory(runPath, history).(leet.HistoryMsg)
	require.True(t, ok)
	require.Len(t, msg.Media, 1)
	require.Contains(t, msg.Media, "samples[0]")
	require.Empty(t, msg.Media["samples[0]"][0].Caption)
}

func TestMediaStoreSeriesKeys_NaturalOrder(t *testing.T) {
	store := leet.NewMediaStore()
	for _, key := range []string{"maps[10]", "maps[2]", "maps[0]", "loss", "zmap"} {
		store.ProcessHistory(leet.HistoryMsg{
			Media: map[string][]leet.MediaPoint{key: {{X: 1, FilePath: "/img.png"}}},
		})
	}
	require.Equal(
		t,
		[]string{"loss", "maps[0]", "maps[2]", "maps[10]", "zmap"},
		store.SeriesKeys(),
	)
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

func TestMediaStoreProcessHistory_ReplacesExistingPointAtSameX(t *testing.T) {
	store := leet.NewMediaStore()

	require.True(t, store.ProcessHistory(leet.HistoryMsg{
		Media: map[string][]leet.MediaPoint{
			"media/generated_sample": {{
				X:        5,
				FilePath: filepath.Join("tmp", "old.png"),
				Caption:  "old",
			}},
		},
	}))

	require.True(t, store.ProcessHistory(leet.HistoryMsg{
		Media: map[string][]leet.MediaPoint{
			"media/generated_sample": {{
				X:        5,
				FilePath: filepath.Join("tmp", "new.png"),
				Caption:  "new",
			}},
		},
	}))

	point, ok := store.ResolveAt("media/generated_sample", 5)
	require.True(t, ok)
	require.Equal(t, filepath.Join("tmp", "new.png"), point.FilePath)
	require.Equal(t, "new", point.Caption)
	require.Equal(t, []float64{5}, store.SeriesXValues("media/generated_sample"))
}
