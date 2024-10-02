package runbranch_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/runbranch"
)

func TestProto(t *testing.T) {
	timeNow := time.Now()
	r := &runbranch.RunParams{
		RunID:        "test",
		Project:      "test",
		Entity:       "test",
		DisplayName:  "test",
		StartTime:    timeNow,
		StorageID:    "test",
		SweepID:      "test",
		StartingStep: 10,
		Runtime:      20,
		Config: map[string]interface{}{
			"test": "test",
		},
		Summary: map[string]interface{}{
			"test": "test",
		},
		Tags: []string{"test", "test2"},
	}
	proto := r.Proto()
	assert.NotNil(t, proto)
	assert.Equal(t, r.RunID, proto.RunId)
	assert.Nil(t, proto.Tags)
	assert.Nil(t, proto.StartTime)
}

func TestMerge(t *testing.T) {
	timeNow := time.Now()
	r := &runbranch.RunParams{
		RunID:        "test",
		Project:      "test",
		Entity:       "test",
		DisplayName:  "test",
		StartTime:    timeNow,
		StorageID:    "test",
		SweepID:      "test",
		StartingStep: 10,
		Runtime:      20,
		Config: map[string]interface{}{
			"test": "test",
		},
		Summary: map[string]interface{}{
			"test": "test",
		},
		Tags: []string{"test", "test2"},
	}
	assert.Equal(t, r.Resumed, false)
	r2 := &runbranch.RunParams{
		RunID:        "test2",
		Project:      "test2",
		Entity:       "test2",
		DisplayName:  "test2",
		StartTime:    timeNow,
		StorageID:    "test2",
		SweepID:      "test2",
		StartingStep: 20,
		Runtime:      30,
		Config: map[string]interface{}{
			"test2": "test2",
		},
		Summary: map[string]interface{}{
			"test2": "test2",
		},
		Tags: []string{"test2", "test3"},
		FileStreamOffset: filestream.FileStreamOffsetMap{
			filestream.HistoryChunk: 10,
		},
		Resumed: true,
	}
	r.Merge(r2)
	assert.Equal(t, r.RunID, r2.RunID)
	assert.Equal(t, r.Project, r2.Project)
	assert.Equal(t, r.Entity, r2.Entity)
	assert.Equal(t, r.DisplayName, r2.DisplayName)
	assert.Equal(t, r.StartTime, r2.StartTime)
	assert.Equal(t, r.StorageID, r2.StorageID)
	assert.Equal(t, r.SweepID, r2.SweepID)
	assert.Equal(t, r.StartingStep, r2.StartingStep)
	assert.Equal(t, r.Runtime, r2.Runtime)
	assert.Equal(t, r.Config, map[string]any{
		"test":  "test",
		"test2": "test2",
	})
	assert.Equal(t, r.Summary, map[string]any{
		"test":  "test",
		"test2": "test2",
	})
	assert.Equal(t, r.Tags, r2.Tags)
	assert.Equal(t, r.Resumed, true)
}
