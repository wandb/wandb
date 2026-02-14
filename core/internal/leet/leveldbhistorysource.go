package leet

import (
	"errors"
	"fmt"
	"io"
	"strconv"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// LevelDBHistorySource handles reading records from a W&B LevelDB-style transaction log (.wandb file).
type LevelDBHistorySource struct {
	runPath string

	// store is a W&B LevelDB-style transaction log that may be actively written.
	store *LiveStore
	// exitSeen is true if the exit record has been seen.
	exitSeen bool
	// exitCode is the exit code of the run if the exit record has been seen.
	exitCode int32
}

func NewLevelDBHistorySource(
	runPath string,
	logger *observability.CoreLogger,
) (*LevelDBHistorySource, error) {
	store, err := NewLiveStore(runPath, logger)
	if err != nil {
		return nil, err
	}
	return &LevelDBHistorySource{
		runPath: runPath,
		store:   store,
	}, nil
}

// InitializeLevelDBHistorySource returns a tea.Cmd that initializes a
// LevelDBHistorySource for the given run path.
func InitializeLevelDBHistorySource(
	runPath string,
	logger *observability.CoreLogger,
) tea.Cmd {
	return func() tea.Msg {
		source, err := NewLevelDBHistorySource(runPath, logger)
		if err != nil {
			return ErrorMsg{
				Err: fmt.Errorf(
					"leveldbhistory: failed to create live store: %v",
					err,
				),
			}
		}

		return InitMsg{Source: source}
	}
}

// Read implements HistorySource.Read.
func (hs *LevelDBHistorySource) Read(
	chunkSize int,
	maxTimePerChunk time.Duration,
) (tea.Msg, error) {
	if hs == nil {
		return func() tea.Msg { return nil }, nil
	}

	if hs.store == nil {
		return ChunkedBatchMsg{
			Msgs:    []tea.Msg{},
			HasMore: false,
		}, nil
	}

	var msgs []tea.Msg
	var histories []HistoryMsg
	var summaries []SummaryMsg
	recordCount := 0
	startTime := time.Now()
	var err error

	for recordCount < chunkSize && time.Since(startTime) < maxTimePerChunk {
		record, readErr := hs.store.Read()
		if readErr != nil {
			if errors.Is(readErr, io.EOF) {
				if hs.exitSeen {
					err = io.EOF
				} else {
					err = nil
				}
			} else {
				err = readErr
			}
			break
		}
		if record == nil {
			continue
		}

		// Handle exit record first to avoid double FileComplete.
		if exit, ok := record.RecordType.(*spb.Record_Exit); ok && exit.Exit != nil {
			hs.exitSeen = true
			hs.exitCode = exit.Exit.GetExitCode()
			break
		}

		if msg := hs.recordToMsg(record); msg != nil {
			switch m := msg.(type) {
			case HistoryMsg:
				histories = append(histories, m)
			case SummaryMsg:
				summaries = append(summaries, m)
			default:
				msgs = append(msgs, msg)
			}
			recordCount++
		}
	}

	if len(histories) > 0 {
		msgs = append(msgs, concatenateHistory(histories, hs.runPath))
	}
	if len(summaries) > 0 {
		msgs = append(msgs, concatenateSummary(summaries, hs.runPath))
	}

	if hs.exitSeen {
		msgs = append(msgs, FileCompleteMsg{ExitCode: hs.exitCode})
	}

	// Determine if there's more to read,
	// i.e. whether we have records and didn't hit EOF, there might be more.
	hasMore := !hs.exitSeen && recordCount > 0

	return ChunkedBatchMsg{
		Msgs:     msgs,
		HasMore:  hasMore,
		Progress: recordCount,
	}, err
}

// recordToMsg converts a record to the appropriate message type.
func (hs *LevelDBHistorySource) recordToMsg(record *spb.Record) tea.Msg {
	switch rec := record.RecordType.(type) {
	case *spb.Record_Run:
		return RunMsg{
			RunPath:     hs.runPath,
			ID:          rec.Run.GetRunId(),
			DisplayName: rec.Run.GetDisplayName(),
			Project:     rec.Run.GetProject(),
			Config:      rec.Run.GetConfig(),
		}
	case *spb.Record_History:
		return ParseHistory(hs.runPath, rec.History)
	case *spb.Record_Stats:
		return ParseStats(hs.runPath, rec.Stats)
	case *spb.Record_Summary:
		return SummaryMsg{RunPath: hs.runPath, Summary: []*spb.SummaryRecord{rec.Summary}}
	case *spb.Record_Environment:
		return SystemInfoMsg{RunPath: hs.runPath, Record: rec.Environment}
	default:
		return nil
	}
}

func (hs *LevelDBHistorySource) Close() {
	if hs.store != nil {
		hs.store.Close()
	}
}

// ParseHistory extracts metrics from a history record.
func ParseHistory(runPath string, history *spb.HistoryRecord) tea.Msg {
	if history == nil {
		return nil
	}
	var step int
	values := make(map[string]float64, len(history.GetItem()))

	for _, item := range history.GetItem() {
		key := strings.Join(item.GetNestedKey(), ".")
		if key == "" {
			key = item.GetKey()
		}
		if key == "" {
			continue
		}

		v := item.ValueJson
		if n := len(v); n >= 2 && v[0] == '"' && v[n-1] == '"' {
			v = v[1 : n-1]
		}

		if key == "_step" {
			if s, err := strconv.Atoi(v); err == nil {
				step = s
			}
			continue
		}
		if strings.HasPrefix(key, "_") {
			continue
		}
		if val, err := strconv.ParseFloat(v, 64); err == nil {
			values[key] = val
		}
	}

	if len(values) == 0 {
		return nil
	}

	x := []float64{float64(step)}
	metrics := make(map[string]MetricData, len(values))
	for k, y := range values {
		metrics[k] = MetricData{X: x, Y: []float64{y}}
	}
	return HistoryMsg{RunPath: runPath, Metrics: metrics}
}

// ParseStats extracts metrics from a stats record.
func ParseStats(runPath string, stats *spb.StatsRecord) tea.Msg {
	if stats == nil {
		return nil
	}

	metrics := make(map[string]float64, len(stats.Item))
	var timestamp int64

	if stats.Timestamp != nil {
		timestamp = stats.Timestamp.Seconds
	}

	for _, item := range stats.Item {
		if item == nil {
			continue
		}

		v := item.ValueJson
		if n := len(v); n >= 2 && v[0] == '"' && v[n-1] == '"' {
			v = v[1 : n-1]
		}
		if value, err := strconv.ParseFloat(v, 64); err == nil {
			metrics[item.Key] = value
		}
	}

	if len(metrics) > 0 {
		return StatsMsg{RunPath: runPath, Timestamp: timestamp, Metrics: metrics}
	}
	return nil
}
