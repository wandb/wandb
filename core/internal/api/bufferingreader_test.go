package api_test

import (
	"io"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/api"
)

func TestReadsSource(t *testing.T) {
	reader := api.NewBufferingReader(strings.NewReader("abc"))

	result, err := io.ReadAll(reader)

	require.NoError(t, err)
	assert.Equal(t, "abc", string(result))
}

func TestReconstructsSource(t *testing.T) {
	reader := api.NewBufferingReader(strings.NewReader("my text"))

	readerFirstBytes := make([]byte, 2)
	n, err := reader.Read(readerFirstBytes)
	require.NoError(t, err)
	require.Equal(t, 2, n)

	reconstructedReader := reader.Reconstruct()
	reconstructedBytes, _ := io.ReadAll(reconstructedReader)

	assert.Equal(t, "my", string(readerFirstBytes))
	assert.Equal(t, "my text", string(reconstructedBytes))
}
