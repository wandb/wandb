package runsyncstate_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/runsyncstate"
)

func TestMemoryStore_GetOrInitStartingStep_PersistsValue(t *testing.T) {
	store := runsyncstate.InMemory()

	value1, err := store.GetOrInitStartState(runsyncstate.StartState{
		StartStep:    1,
		StartRuntime: time.Millisecond,
	})
	require.NoError(t, err)
	value2, err := store.GetOrInitStartState(runsyncstate.StartState{
		StartStep:    2,
		StartRuntime: 2 * time.Millisecond,
	})
	require.NoError(t, err)

	assert.EqualValues(t, runsyncstate.StartState{
		StartStep:    1,
		StartRuntime: time.Millisecond,
	}, value1)
	assert.EqualValues(t, runsyncstate.StartState{
		StartStep:    1,
		StartRuntime: time.Millisecond,
	}, value2)
}
