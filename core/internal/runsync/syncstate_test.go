package runsync_test

import (
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/runsync"
)

func TestSyncStateStore_GetOrInitStartingStep_PersistsFirstValue(t *testing.T) {
	wandbFile := filepath.Join(t.TempDir(), "run-xyz.wandb")
	store := runsync.NewSyncStateStore(wandbFile)

	step, err := store.GetOrInitStartingStep(5)
	require.NoError(t, err)
	assert.EqualValues(t, 5, step)

	// A second call should reuse the persisted value, even though a
	// different value is passed in (as would happen on a re-sync, where
	// the live-computed value has since drifted).
	step, err = store.GetOrInitStartingStep(999)
	require.NoError(t, err)
	assert.EqualValues(t, 5, step)
}

func TestSyncStateStore_GetOrInitStartingStep_PersistsAcrossStores(t *testing.T) {
	wandbFile := filepath.Join(t.TempDir(), "run-xyz.wandb")

	_, err := runsync.NewSyncStateStore(wandbFile).GetOrInitStartingStep(7)
	require.NoError(t, err)

	// A fresh store instance (as would happen on a second `wandb sync`
	// invocation) should read the previously locked-in value.
	step, err := runsync.NewSyncStateStore(wandbFile).GetOrInitStartingStep(42)
	require.NoError(t, err)
	assert.EqualValues(t, 7, step)
}
