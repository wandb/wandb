package runsyncstate_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/runsyncstate"
)

func TestMemoryStore_GetOrInitStartingStep_PersistsValue(t *testing.T) {
	store := runsyncstate.InMemory()

	value1, err := store.GetOrInitStartingStep(1)
	require.NoError(t, err)
	value2, err := store.GetOrInitStartingStep(2)
	require.NoError(t, err)

	assert.EqualValues(t, 1, value1)
	assert.EqualValues(t, 1, value2)
}
