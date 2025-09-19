package runhistory

import (
	"testing"
)

func TestHistoryReader_GetHistorySteps(t *testing.T) {
	reader := New("test-entity", "test-project", "run-123")

	err := reader.GetHistorySteps([]string{"metric1"}, 0, 10)
	if err == nil {
		t.Errorf("expected error, got nil")
	}
}
