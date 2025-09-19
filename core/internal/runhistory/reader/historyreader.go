package runhistory

import "fmt"

// HistoryReader handles reading run history for a given run.
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

// Gets all history rows for the given keys
// which fall between minStep and maxStep.
func (h *HistoryReader) GetHistorySteps(
	keys []string,
	minStep int64,
	maxStep int64,
) error {
	// TODO: Implement
	return fmt.Errorf("not implemented")
}
