package runsyncstate_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/runsyncstate"
)

func TestSyncStateStore_GetOrInitStartingStep_PersistsFirstValue(t *testing.T) {
	wandbFile := filepath.Join(t.TempDir(), "run-xyz.wandb")
	store := runsyncstate.NewSyncStateStore(wandbFile)

	step, err := store.GetOrInitStartingStep(5)
	require.NoError(t, err)
	assert.EqualValues(t, 5, step)

	// A second call should reuse the initialized value, regardless of the
	// passed-in value.
	step, err = store.GetOrInitStartingStep(999)
	require.NoError(t, err)
	assert.EqualValues(t, 5, step)
}

func TestSyncStateStore_GetOrInitStartingStep_PersistsAcrossStores(t *testing.T) {
	wandbFile := filepath.Join(t.TempDir(), "run-xyz.wandb")

	_, err := runsyncstate.NewSyncStateStore(wandbFile).GetOrInitStartingStep(7)
	require.NoError(t, err)

	// A fresh store instance should read the previously initialized value.
	step, err := runsyncstate.NewSyncStateStore(wandbFile).GetOrInitStartingStep(42)
	require.NoError(t, err)
	assert.EqualValues(t, 7, step)
}

func TestSyncStateStore_GetOrInitStartingStep_HandlesMissingStartingStep(t *testing.T) {
	wandbFile := filepath.Join(t.TempDir(), "run-xyz.wandb")

	// Simulate a pre-existing sync state file that's valid JSON but
	// doesn't set starting_step. This should behave like an uninitialized
	// file.
	require.NoError(t,
		os.WriteFile(wandbFile+".syncstate", []byte("{}"), 0666))

	step, err := runsyncstate.NewSyncStateStore(wandbFile).GetOrInitStartingStep(5)
	require.NoError(t, err)
	assert.EqualValues(t, 5, step)

	// The value should now be persisted for subsequent calls.
	step, err = runsyncstate.NewSyncStateStore(wandbFile).GetOrInitStartingStep(999)
	require.NoError(t, err)
	assert.EqualValues(t, 5, step)
}
