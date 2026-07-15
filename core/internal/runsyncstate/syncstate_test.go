package runsyncstate_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/runsyncstate"
)

func TestEnsureExists_CreatesEmptyFile(t *testing.T) {
	transactionLog := filepath.Join(t.TempDir(), "run-xyz.wandb")

	require.NoError(t, runsyncstate.EnsureExists(transactionLog))

	data, err := os.ReadFile(transactionLog + ".syncstate")
	require.NoError(t, err)
	assert.Equal(t, "{}", string(data))
}

func TestEnsureExists_IsIdempotent(t *testing.T) {
	transactionLog := filepath.Join(t.TempDir(), "run-xyz.wandb")

	require.NoError(t, runsyncstate.EnsureExists(transactionLog))
	require.NoError(t, runsyncstate.EnsureExists(transactionLog))

	step, err := runsyncstate.File(transactionLog).GetOrInitStartingStep(3)
	require.NoError(t, err)
	assert.EqualValues(t, 3, step)
}

func TestSyncStateStore_GetOrInitStartingStep_PersistsFirstValue(t *testing.T) {
	wandbFile := filepath.Join(t.TempDir(), "run-xyz.wandb")
	store := runsyncstate.File(wandbFile)

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

	_, err := runsyncstate.File(wandbFile).GetOrInitStartingStep(7)
	require.NoError(t, err)

	// A fresh store instance should read the previously initialized value.
	step, err := runsyncstate.File(wandbFile).GetOrInitStartingStep(42)
	require.NoError(t, err)
	assert.EqualValues(t, 7, step)
}

func TestSyncStateStore_GetOrInitStartingStep_HandlesMissingStartingStep(t *testing.T) {
	wandbFile := filepath.Join(t.TempDir(), "run-xyz.wandb")

	// Simulate a pre-existing sync state file that's valid JSON but
	// doesn't set starting_step. This should behave like an uninitialized
	// file.
	require.NoError(t,
		os.WriteFile(wandbFile+".syncstate", []byte("{}"), 0o666))

	step, err := runsyncstate.File(wandbFile).GetOrInitStartingStep(5)
	require.NoError(t, err)
	assert.EqualValues(t, 5, step)

	// The value should now be persisted for subsequent calls.
	step, err = runsyncstate.File(wandbFile).GetOrInitStartingStep(999)
	require.NoError(t, err)
	assert.EqualValues(t, 5, step)
}
