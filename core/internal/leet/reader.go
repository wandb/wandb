package leet

import (
	"io"
	"os"
	"strconv"
	"strings"
	"sync"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/wandb/wandb/core/internal/runconfig"
	"github.com/wandb/wandb/core/internal/runenvironment"
	"github.com/wandb/wandb/core/internal/runsummary"
	"github.com/wandb/wandb/core/internal/stream"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// ProcessedData holds pre-processed data ready for UI consumption
type ProcessedData struct {
	HistoryByStep map[int]map[string]float64
	RunInfo       *RunMsg
	SummaryData   *runsummary.RunSummary
	Environment   *runenvironment.RunEnvironment
	Config        *runconfig.RunConfig
	Stats         []StatsMsg
	ExitCode      int32
	FileComplete  bool
}

// WandbReader handles reading records from a .wandb file.
type WandbReader struct {
	store          *stream.Store
	exitSeen       bool
	exitCode       int32
	lastGoodOffset int64
}

// NewWandbReader creates a new wandb file reader.
func NewWandbReader(runPath string) (*WandbReader, error) {
	store := stream.NewStore(runPath)
	err := store.Open(os.O_RDONLY)
	if err != nil {
		return nil, err
	}

	initialOffset := store.GetCurrentOffset()

	return &WandbReader{
		store:          store,
		exitSeen:       false,
		lastGoodOffset: initialOffset,
	}, nil
}

// ReadAllDataOptimized reads all data in parallel and returns processed data
func (r *WandbReader) ReadAllDataOptimized() (*ProcessedData, error) {
	records, err := r.collectAllRecords()
	if err != nil {
		return nil, err
	}

	return r.processRecords(records), nil
}

// collectAllRecords reads all records from the store
func (r *WandbReader) collectAllRecords() ([]*spb.Record, error) {
	records := make([]*spb.Record, 0, 10000)

	for {
		currentOffset := r.store.GetCurrentOffset()
		record, err := r.store.Read()

		if err != nil {
			if err == io.EOF {
				break
			}
			// Try to recover from read errors
			if r.lastGoodOffset >= 0 && currentOffset >= 0 {
				if seekErr := r.store.SeekToOffset(r.lastGoodOffset); seekErr != nil {
					r.store.Recover()
				}
			} else {
				r.store.Recover()
			}
			continue
		}

		if currentOffset >= 0 {
			r.lastGoodOffset = currentOffset
		}
		records = append(records, record)
	}

	return records, nil
}

// processRecords processes records using multiple workers
func (r *WandbReader) processRecords(records []*spb.Record) *ProcessedData {
	data := &ProcessedData{
		HistoryByStep: make(map[int]map[string]float64),
		Stats:         make([]StatsMsg, 0),
		Config:        runconfig.New(),
		SummaryData:   runsummary.New(),
	}

	// Use worker pool for history records
	const numWorkers = 4
	var wg sync.WaitGroup
	recordChan := make(chan *spb.Record, 100)
	resultChan := make(chan map[int]map[string]float64, numWorkers)

	// Start workers
	for i := 0; i < numWorkers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			localHistory := make(map[int]map[string]float64)

			for record := range recordChan {
				if hist, ok := record.RecordType.(*spb.Record_History); ok {
					step, metrics := r.parseHistoryRecord(hist.History)
					if len(metrics) > 0 {
						if localHistory[step] == nil {
							localHistory[step] = make(map[string]float64)
						}
						for k, v := range metrics {
							localHistory[step][k] = v
						}
					}
				}
			}

			resultChan <- localHistory
		}()
	}

	// Process non-history records synchronously and send history to workers
	go func() {
		for _, record := range records {
			switch rec := record.RecordType.(type) {
			case *spb.Record_History:
				recordChan <- record

			case *spb.Record_Run:
				if data.RunInfo == nil {
					data.RunInfo = &RunMsg{
						ID:          rec.Run.RunId,
						DisplayName: rec.Run.DisplayName,
						Project:     rec.Run.Project,
						Config:      rec.Run.Config,
					}
				}
				if rec.Run.Config != nil {
					onError := func(err error) {
						// Log error but continue
					}
					data.Config.ApplyChangeRecord(rec.Run.Config, onError)
				}

			case *spb.Record_Summary:
				for _, update := range rec.Summary.Update {
					data.SummaryData.SetFromRecord(update)
				}
				for _, remove := range rec.Summary.Remove {
					data.SummaryData.RemoveFromRecord(remove)
				}

			case *spb.Record_Environment:
				if data.Environment == nil {
					data.Environment = runenvironment.New(rec.Environment.GetWriterId())
				}
				data.Environment.ProcessRecord(rec.Environment)

			case *spb.Record_Stats:
				if statsMsg := r.parseStatsRecord(rec.Stats); statsMsg != nil {
					data.Stats = append(data.Stats, *statsMsg)
				}

			case *spb.Record_Exit:
				r.exitSeen = true
				r.exitCode = rec.Exit.ExitCode
				data.ExitCode = rec.Exit.ExitCode
				data.FileComplete = true
			}
		}
		close(recordChan)
	}()

	// Collect results from workers
	go func() {
		wg.Wait()
		close(resultChan)
	}()

	// Merge worker results
	var mu sync.Mutex
	for localHistory := range resultChan {
		mu.Lock()
		for step, metrics := range localHistory {
			if data.HistoryByStep[step] == nil {
				data.HistoryByStep[step] = make(map[string]float64)
			}
			for k, v := range metrics {
				data.HistoryByStep[step][k] = v
			}
		}
		mu.Unlock()
	}

	return data
}

// parseHistoryRecord extracts step and metrics from a history record
func (r *WandbReader) parseHistoryRecord(history *spb.HistoryRecord) (int, map[string]float64) {
	metrics := make(map[string]float64)
	var step int

	for _, item := range history.Item {
		key := strings.Join(item.NestedKey, ".")
		if key == "_step" {
			if val, err := strconv.Atoi(strings.Trim(item.ValueJson, `"`)); err == nil {
				step = val
			}
			continue
		}

		if strings.HasPrefix(key, "_") {
			continue
		}

		valueStr := strings.Trim(item.ValueJson, `"`)
		if value, err := strconv.ParseFloat(valueStr, 64); err == nil {
			metrics[key] = value
		}
	}

	return step, metrics
}

// parseStatsRecord extracts metrics from a stats record
func (r *WandbReader) parseStatsRecord(stats *spb.StatsRecord) *StatsMsg {
	metrics := make(map[string]float64)
	var timestamp int64

	if stats.Timestamp != nil {
		timestamp = stats.Timestamp.Seconds
	}

	for _, item := range stats.Item {
		valueStr := strings.Trim(item.ValueJson, `"`)
		if value, err := strconv.ParseFloat(valueStr, 64); err == nil {
			metrics[item.Key] = value
		}
	}

	if len(metrics) > 0 {
		return &StatsMsg{Timestamp: timestamp, Metrics: metrics}
	}
	return nil
}

// ReadNext reads the next record for live monitoring
func (r *WandbReader) ReadNext() (tea.Msg, error) {
	currentOffset := r.store.GetCurrentOffset()

	record, err := r.store.Read()
	if err != nil {
		if err == io.EOF {
			if r.exitSeen {
				return FileCompleteMsg{ExitCode: r.exitCode}, io.EOF
			}
			if r.lastGoodOffset >= 0 && currentOffset >= 0 {
				if seekErr := r.store.SeekToOffset(r.lastGoodOffset); seekErr == nil {
					return nil, err
				}
			}
			r.store.Recover()
		} else {
			if r.lastGoodOffset >= 0 && currentOffset >= 0 {
				if seekErr := r.store.SeekToOffset(r.lastGoodOffset); seekErr != nil {
					r.store.Recover()
				}
			} else {
				r.store.Recover()
			}
		}
		return nil, err
	}

	if currentOffset >= 0 {
		r.lastGoodOffset = currentOffset
	}

	// Convert record to appropriate message type
	switch rec := record.RecordType.(type) {
	case *spb.Record_Run:
		return RunMsg{
			ID:          rec.Run.RunId,
			DisplayName: rec.Run.DisplayName,
			Project:     rec.Run.Project,
			Config:      rec.Run.Config,
		}, nil

	case *spb.Record_History:
		step, metrics := r.parseHistoryRecord(rec.History)
		if len(metrics) > 0 {
			return HistoryMsg{Metrics: metrics, Step: step}, nil
		}

	case *spb.Record_Stats:
		if statsMsg := r.parseStatsRecord(rec.Stats); statsMsg != nil {
			return *statsMsg, nil
		}

	case *spb.Record_Summary:
		return SummaryMsg{Summary: rec.Summary}, nil

	case *spb.Record_Environment:
		return SystemInfoMsg{Record: rec.Environment}, nil

	case *spb.Record_Exit:
		r.exitSeen = true
		r.exitCode = rec.Exit.ExitCode
		return FileCompleteMsg{ExitCode: r.exitCode}, nil
	}

	return nil, nil
}

// Close closes the reader.
func (r *WandbReader) Close() error {
	if r.store != nil {
		return r.store.Close()
	}
	return nil
}
