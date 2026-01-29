package leet

import (
	"errors"
	"fmt"
	"io"
	"slices"
	"strconv"
	"strings"
	"sync"
	"time"

	tea "charm.land/bubbletea/v2"

	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// LevelDBHistorySource handles reading records from a W&B LevelDB-style transaction log (.wandb file).
type LevelDBHistorySource struct {
	mu sync.Mutex

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
	hs.mu.Lock()
	defer hs.mu.Unlock()

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
		msgs = append(msgs, hs.concatenateHistory(histories))
	}
	if len(summaries) > 0 {
		msgs = append(msgs, hs.concatenateSummary(summaries))
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

// concatenateHistory merges a slice of HistoryMsg into a single HistoryMsg.
//
// Assumes that the history messages are ordered.
func (hs *LevelDBHistorySource) concatenateHistory(messages []HistoryMsg) HistoryMsg {
	h := HistoryMsg{
		RunPath: hs.runPath,
		Metrics: make(map[string]MetricData),
		Media:   make(map[string][]MediaPoint),
	}

	for _, msg := range messages {
		for metricName, data := range msg.Metrics {
			existing := h.Metrics[metricName]
			existing.X = append(existing.X, data.X...)
			existing.Y = append(existing.Y, data.Y...)
			h.Metrics[metricName] = existing
		}
		for mediaKey, points := range msg.Media {
			h.Media[mediaKey] = append(h.Media[mediaKey], points...)
		}
	}

	if len(h.Metrics) == 0 {
		h.Metrics = nil
	}
	if len(h.Media) == 0 {
		h.Media = nil
	}

	return h
}

// ConcatenateHistory merges a slice of SummaryMsg into a single SummaryMsg.
//
// Assumes that the summary messages are ordered.
func (hs *LevelDBHistorySource) concatenateSummary(messages []SummaryMsg) SummaryMsg {
	s := SummaryMsg{
		RunPath: hs.runPath,
		Summary: make([]*spb.SummaryRecord, 0),
	}

	for _, msg := range messages {
		s.Summary = append(s.Summary, msg.Summary...)
	}

	return s
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
			Notes:       rec.Run.GetNotes(),
			Tags:        slices.Clone(rec.Run.GetTags()),
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
	case *spb.Record_OutputRaw:
		return parseOutputRaw(hs.runPath, rec.OutputRaw)
	default:
		return nil
	}
}

func (hs *LevelDBHistorySource) Close() {
	hs.mu.Lock()
	defer hs.mu.Unlock()

	if hs.store != nil {
		hs.store.Close()
		hs.store = nil
	}
}

// ParseHistory extracts metrics and media from a history record.
func ParseHistory(runPath string, history *spb.HistoryRecord) tea.Msg {
	if history == nil {
		return nil
	}

	step := int(history.GetStep().GetNum())
	values := make(map[string]float64, len(history.GetItem()))
	mediaFieldsByKey := make(map[string]map[string]string)

	for _, item := range history.GetItem() {
		if item == nil {
			continue
		}

		if mediaKey, field, ok := historyMediaField(item); ok {
			fields := mediaFieldsByKey[mediaKey]
			if fields == nil {
				fields = make(map[string]string)
				mediaFieldsByKey[mediaKey] = fields
			}
			fields[field] = trimJSONString(item.ValueJson)
			continue
		}

		key := strings.Join(item.GetNestedKey(), ".")
		if key == "" {
			key = item.GetKey()
		}
		if key == "" {
			continue
		}

		v := trimJSONString(item.ValueJson)
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

	metrics := make(map[string]MetricData, len(values))
	if len(values) > 0 {
		x := []float64{float64(step)}
		for k, y := range values {
			metrics[k] = MetricData{X: x, Y: []float64{y}}
		}
	}

	media := make(map[string][]MediaPoint)
	for mediaKey, fields := range mediaFieldsByKey {
		if fields["_type"] != "image-file" {
			continue
		}
		relPath := fields["path"]
		if relPath == "" {
			continue
		}
		media[mediaKey] = append(media[mediaKey], MediaPoint{
			X:            float64(step),
			FilePath:     resolveMediaPath(runPath, relPath),
			RelativePath: relPath,
			Caption:      fields["caption"],
			Format:       fields["format"],
			Width:        parseHistoryInt(fields["width"]),
			Height:       parseHistoryInt(fields["height"]),
			SHA256:       fields["sha256"],
		})
	}

	if len(metrics) == 0 && len(media) == 0 {
		return nil
	}

	msg := HistoryMsg{RunPath: runPath}
	if len(metrics) > 0 {
		msg.Metrics = metrics
	}
	if len(media) > 0 {
		msg.Media = media
	}
	return msg
}

func trimJSONString(v string) string {
	if v == "" {
		return ""
	}
	if unquoted, err := strconv.Unquote(v); err == nil {
		return unquoted
	}
	return v
}

func parseHistoryInt(v string) int {
	i, err := strconv.Atoi(v)
	if err == nil {
		return i
	}
	return 0
}

func historyMediaField(item *spb.HistoryItem) (mediaKey, field string, ok bool) {
	parts := item.GetNestedKey()
	if len(parts) < 2 {
		return "", "", false
	}
	field = parts[len(parts)-1]
	switch field {
	case "_type", "path", "caption", "format", "width", "height", "sha256", "size":
	default:
		return "", "", false
	}
	mediaKey = strings.Join(parts[:len(parts)-1], ".")
	if mediaKey == "" {
		return "", "", false
	}
	return mediaKey, field, true
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

// parseOutputRaw extracts a ConsoleLogMsg from an OutputRawRecord.
func parseOutputRaw(runPath string, rec *spb.OutputRawRecord) tea.Msg {
	if rec == nil {
		return nil
	}

	var ts time.Time
	if rec.Timestamp != nil {
		ts = time.Unix(rec.Timestamp.Seconds, int64(rec.Timestamp.Nanos))
	}

	return ConsoleLogMsg{
		RunPath:  runPath,
		Text:     rec.Line,
		IsStderr: rec.OutputType == spb.OutputRawRecord_STDERR,
		Time:     ts,
	}
}
