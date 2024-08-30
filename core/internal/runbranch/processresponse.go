package runbranch

import (
	"encoding/json"
	"errors"
	"fmt"

	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/filestream"
)

func processConfigResume(config *string) (map[string]any, error) {
	if config == nil {
		return nil, errors.New("no config found")
	}
	return processConfig(config)
}

func processConfig(config *string) (map[string]any, error) {
	// If we are unable to parse the config, we should fail if resume is set to
	// must for any other case of resume status, it is fine to ignore it
	cfgVal, err := simplejsonext.UnmarshalString(*config)
	if err != nil {
		return nil, fmt.Errorf("failed to unmarshal config: %s", err)
	}

	var cfg map[string]any
	switch x := cfgVal.(type) {
	case nil: // OK, cfg is nil
	case map[string]any:
		cfg = x
	default:
		return nil, fmt.Errorf(
			"got type %T for %s",
			x, *config,
		)
	}

	result := make(map[string]any)
	for key, value := range cfg {
		valueDict, ok := value.(map[string]any)
		if !ok {
			return nil, fmt.Errorf("unexpected type %T for %s", value, key)
		} else if val, ok := valueDict["value"]; ok {
			result[key] = val
		}
	}
	return result, nil

}

// processSummary extracts the summary metrics from the data we get from the server
func processSummary(summary *string) (map[string]any, error) {
	if summary == nil {
		return nil, errors.New("no summary metrics found in resume response")
	}

	// If we are unable to parse the summary, we should fail if resume is set to
	// must for any other case of resume status, it is fine to ignore it
	summaryVal, err := simplejsonext.UnmarshalString(*summary)
	if err != nil {
		return nil, err
	}

	switch x := summaryVal.(type) {
	case nil: // OK, summary is nil
		return nil, nil
	case map[string]any:
		return x, nil
	default:
		return nil, fmt.Errorf("unexpected type %T for %s", x, *summary)
	}
}

// processEventsTail extracts the last event from the events tail we get from the server
// these are the system metric events
func processEventsTail(events *string) (map[string]any, error) {
	if events == nil {
		return nil, errors.New("no events tail found")
	}

	// Since we just expect a list of strings, we unmarshal using the
	// standard JSON library.
	var eventsTail []string
	if err := json.Unmarshal([]byte(*events), &eventsTail); err != nil {
		return nil, err
	}

	// if we don't have any events, we have nothing to process
	if len(eventsTail) == 0 {
		return nil, nil
	}

	// We only care about the last event in the list
	eventTail, err := simplejsonext.UnmarshalObjectString(eventsTail[len(eventsTail)-1])
	if err != nil {
		return nil, err
	}

	return eventTail, nil
}

func processHistory(history *string) (map[string]any, error) {
	if history == nil {
		return nil, errors.New("no history tail found")
	}

	// Since we just expect a list of strings, we unmarshal using the
	// standard JSON library.
	var histories []string
	if err := json.Unmarshal([]byte(*history), &histories); err != nil {
		return nil, err
	}

	if len(histories) == 0 {
		return nil, nil
	}

	historyTail, err := simplejsonext.UnmarshalObjectString(histories[len(histories)-1])

	if err != nil {
		return nil, err
	}

	return historyTail, nil
}

func extractRuntime(runtime any) float64 {
	switch x := runtime.(type) {
	case int64:
		return float64(x)
	case float64:
		return x
	}
	return 0
}

func processAllOffsets(history, events, logs *int) (filestream.FileStreamOffsetMap, error) {
	filestreamOffset := make(filestream.FileStreamOffsetMap)

	if history != nil {
		filestreamOffset[filestream.HistoryChunk] = *history
	} else {
		return nil, errors.New("no history line count found")
	}

	if events != nil {
		filestreamOffset[filestream.EventsChunk] = *events
	} else {
		return nil, errors.New("no events line count found")
	}

	if logs != nil {
		filestreamOffset[filestream.OutputChunk] = *logs
	} else {
		return nil, errors.New("no log line count found")
	}

	return filestreamOffset, nil
}
