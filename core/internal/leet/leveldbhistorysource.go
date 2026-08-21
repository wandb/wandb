package leet

import (
	"encoding/json"
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
	// fileCompleteEmitted is true after the terminal FileCompleteMsg has been emitted.
	fileCompleteEmitted bool
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
	if hs.exitSeen && hs.fileCompleteEmitted {
		return ChunkedBatchMsg{
			Msgs:    []tea.Msg{},
			HasMore: false,
		}, io.EOF
	}

	var msgs []tea.Msg
	var summaries []SummaryMsg
	var history historyAccumulator
	scannedCount := 0
	startTime := time.Now()
	var err error

	for scannedCount < chunkSize && time.Since(startTime) < maxTimePerChunk {
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
		scannedCount++

		// Handle exit record first to avoid double FileComplete.
		if exit, ok := record.RecordType.(*spb.Record_Exit); ok && exit.Exit != nil {
			hs.exitSeen = true
			hs.exitCode = exit.Exit.GetExitCode()
			break
		}

		// History records are by far the most common; accumulate them
		// directly into per-metric series for the whole chunk instead of
		// allocating a message per record.
		if h, ok := record.RecordType.(*spb.Record_History); ok {
			history.addRecord(hs.runPath, h.History)
			continue
		}

		if msg := hs.recordToMsg(record); msg != nil {
			switch m := msg.(type) {
			case SummaryMsg:
				summaries = append(summaries, m)
			default:
				msgs = append(msgs, msg)
			}
		}
	}

	if msg, ok := history.toMsg(hs.runPath); ok {
		msgs = append(msgs, msg)
	}
	if len(summaries) > 0 {
		msgs = append(msgs, concatenateSummary(summaries, hs.runPath))
	}

	if hs.exitSeen && !hs.fileCompleteEmitted {
		msgs = append(msgs, FileCompleteMsg{ExitCode: hs.exitCode})
		hs.fileCompleteEmitted = true
	}

	// Determine if there's more to read,
	// i.e. whether we have records and didn't hit EOF, there might be more.
	hasMore := !hs.exitSeen && scannedCount > 0

	return ChunkedBatchMsg{
		Msgs:     msgs,
		HasMore:  hasMore,
		Progress: scannedCount,
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
			Notes:       rec.Run.GetNotes(),
			Tags:        slices.Clone(rec.Run.GetTags()),
			Config:      rec.Run.GetConfig(),
		}
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

// historyAccumulator merges history records into per-metric series.
//
// The boot loader feeds it up to a full chunk of records, so it appends
// samples directly into growing slices instead of allocating a message per
// record. The scratch map is reused across records to keep per-record
// allocations at zero once warm.
type historyAccumulator struct {
	metrics map[string]*MetricData
	media   map[string][]MediaPoint

	// scratch holds one record's samples until the record's final step is
	// known (a "_step" item may appear after metric items).
	scratch map[string]float64
}

// addRecord folds one history record into the accumulator.
func (acc *historyAccumulator) addRecord(runPath string, history *spb.HistoryRecord) {
	if history == nil {
		return
	}

	step := int(history.GetStep().GetNum())
	if acc.scratch == nil {
		acc.scratch = make(map[string]float64)
	} else {
		clear(acc.scratch)
	}
	var mediaFieldsByKey map[string]map[string]string

	for _, item := range history.GetItem() {
		if item == nil {
			continue
		}

		if mediaKey, field, ok := historyMediaField(item); ok {
			fields := mediaFieldsByKey[mediaKey]
			if fields == nil {
				fields = make(map[string]string)
				if mediaFieldsByKey == nil {
					mediaFieldsByKey = make(map[string]map[string]string)
				}
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
			acc.scratch[key] = val
		}
	}

	if len(acc.scratch) > 0 && acc.metrics == nil {
		acc.metrics = make(map[string]*MetricData)
	}
	x := float64(step)
	for k, y := range acc.scratch {
		md := acc.metrics[k]
		if md == nil {
			md = &MetricData{}
			acc.metrics[k] = md
		}
		md.X = append(md.X, x)
		md.Y = append(md.Y, y)
	}

	for key, points := range parseHistoryMedia(runPath, step, mediaFieldsByKey) {
		if acc.media == nil {
			acc.media = make(map[string][]MediaPoint)
		}
		acc.media[key] = append(acc.media[key], points...)
	}
}

// toMsg returns the accumulated batch as a HistoryMsg.
// ok is false when no metrics or media were accumulated.
func (acc *historyAccumulator) toMsg(runPath string) (HistoryMsg, bool) {
	if len(acc.metrics) == 0 && len(acc.media) == 0 {
		return HistoryMsg{}, false
	}

	msg := HistoryMsg{RunPath: runPath}
	if len(acc.metrics) > 0 {
		msg.Metrics = make(map[string]MetricData, len(acc.metrics))
		for k, md := range acc.metrics {
			msg.Metrics[k] = *md
		}
	}
	if len(acc.media) > 0 {
		msg.Media = acc.media
	}
	return msg, true
}

// ParseHistory extracts metrics and media from a history record.
func ParseHistory(runPath string, history *spb.HistoryRecord) tea.Msg {
	var acc historyAccumulator
	acc.addRecord(runPath, history)
	msg, ok := acc.toMsg(runPath)
	if !ok {
		return nil
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

// parseHistoryMedia builds media series from the per-key media fields of a
// history record.
func parseHistoryMedia(
	runPath string,
	step int,
	mediaFieldsByKey map[string]map[string]string,
) map[string][]MediaPoint {
	if len(mediaFieldsByKey) == 0 {
		return nil
	}
	media := make(map[string][]MediaPoint)
	for mediaKey, fields := range mediaFieldsByKey {
		switch fields["_type"] {
		case "image-file":
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
		case "images/separated":
			// A list of wandb.Image logged under one key: fan each image
			// out into its own "key[i]" series so every image gets a tile.
			captions := parseJSONStringArray(fields["captions"])
			for i, relPath := range parseJSONStringArray(fields["filenames"]) {
				if relPath == "" {
					continue
				}
				point := MediaPoint{
					X:            float64(step),
					FilePath:     resolveMediaPath(runPath, relPath),
					RelativePath: relPath,
					Format:       fields["format"],
					Width:        parseHistoryInt(fields["width"]),
					Height:       parseHistoryInt(fields["height"]),
				}
				if i < len(captions) {
					point.Caption = captions[i]
				}
				indexedKey := fmt.Sprintf("%s[%d]", mediaKey, i)
				media[indexedKey] = append(media[indexedKey], point)
			}
		}
	}
	return media
}

// parseJSONStringArray decodes a JSON array of strings, returning nil on
// malformed input.
func parseJSONStringArray(v string) []string {
	var out []string
	if json.Unmarshal([]byte(v), &out) != nil {
		return nil
	}
	return out
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
	case "_type", "path", "caption", "format", "width", "height", "sha256", "size",
		"count", "filenames", "captions":
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
