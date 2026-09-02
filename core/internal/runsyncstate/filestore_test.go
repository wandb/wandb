package runsyncstate_test

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/runsyncstate"
)

func TestFileStore_GetOrInitStartState_PersistsFirstValue(t *testing.T) {
	wandbFile := filepath.Join(t.TempDir(), "run-xyz.wandb")
	store := runsyncstate.File(wandbFile)

	state, err := store.GetOrInitStartState(runsyncstate.StartState{
		StartStep:    5,
		StartRuntime: 7 * time.Millisecond,
	})
	require.NoError(t, err)
	assert.EqualValues(t, 5, state.StartStep)
	assert.EqualValues(t, 7, state.StartRuntime.Milliseconds())

	// A second call should reuse the initialized value, regardless of the
	// passed-in value.
	state, err = store.GetOrInitStartState(runsyncstate.StartState{})
	require.NoError(t, err)
	assert.EqualValues(t, 5, state.StartStep)
	assert.EqualValues(t, 7*time.Millisecond, state.StartRuntime)
}

func TestFileStore_GetOrInitStartState_PersistsAcrossStores(t *testing.T) {
	wandbFile := filepath.Join(t.TempDir(), "run-xyz.wandb")

	_, err := runsyncstate.File(wandbFile).GetOrInitStartState(
		runsyncstate.StartState{
			StartStep:    7,
			StartRuntime: time.Minute,
		})
	require.NoError(t, err)

	// A fresh store instance should read the previously initialized value.
	state, err := runsyncstate.File(wandbFile).
		GetOrInitStartState(runsyncstate.StartState{})
	require.NoError(t, err)
	assert.EqualValues(t, 7, state.StartStep)
	assert.EqualValues(t, time.Minute, state.StartRuntime)
}

func TestFileStore_GetOrInitStartState_HandlesMissingStartState(t *testing.T) {
	// Simulate a pre-existing sync state file that's valid JSON but
	// doesn't set the start state. This should behave like an uninitialized
	// file.
	wandbFile := filepath.Join(t.TempDir(), "run-xyz.wandb")
	require.NoError(t,
		os.WriteFile(wandbFile+".syncstate", []byte("{}"), 0o666))

	state, err := runsyncstate.File(wandbFile).GetOrInitStartState(
		runsyncstate.StartState{
			StartStep:    5,
			StartRuntime: 4 * time.Hour,
		})
	require.NoError(t, err)
	assert.EqualValues(t, 5, state.StartStep)
	assert.EqualValues(t, 4*time.Hour, state.StartRuntime)

	// The value should now be persisted for subsequent calls.
	state, err = runsyncstate.File(wandbFile).
		GetOrInitStartState(runsyncstate.StartState{})
	require.NoError(t, err)
	assert.EqualValues(t, 5, state.StartStep)
	assert.EqualValues(t, 4*time.Hour, state.StartRuntime)
}
