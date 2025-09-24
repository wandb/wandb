package runhistoryreader

import "fmt"

// HistoryReader downloads and reads an exisiting run's logged metrics.
type HistoryReader struct {
	entity  string
	project string
	runId   string
}

// New returns a new HistoryReader.
func New(
	entity string,
	project string,
	runId string,
) *HistoryReader {
	return &HistoryReader{
		entity:  entity,
		project: project,
		runId:   runId,
	}
}

// GetHistorySteps gets all history rows for the given keys
// that fall between minStep and maxStep.
func (h *HistoryReader) GetHistorySteps(
	keys []string,
	minStep int64,
	maxStep int64,
) error {
	// TODO: Implement
	return fmt.Errorf("not implemented")
}
