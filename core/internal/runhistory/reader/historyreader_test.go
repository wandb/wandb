package runhistory

import (
	"testing"
)

func TestHistoryReader_GetHistorySteps(t *testing.T) {
	reader := New("test-entity", "test-project", "test-run-id")

	err := reader.GetHistorySteps([]string{"metric1"}, 0, 10)
	if err == nil {
		t.Errorf("expected error, got nil")
	}
}
