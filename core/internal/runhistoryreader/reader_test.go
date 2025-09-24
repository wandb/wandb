package runhistoryreader

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestHistoryReader_GetHistorySteps(t *testing.T) {
	reader := New("test-entity", "test-project", "test-run-id")

	err := reader.GetHistorySteps([]string{"metric1"}, 0, 10)
	assert.Error(t, err)
}
