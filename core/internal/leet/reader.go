package leet

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// WandbReader handles reading records from a W&B LevelDB-style transaction log (.wandb file).
type WandbReader struct {
	// store is a W&B LevelDB-style transaction log that may be actively written.
	store *LiveStore
	// exitSeen indicates whether an ExitRecord has been seen.
	exitSeen bool
	// exitCode is the ext code reported in the ExitRecord (if seen).
	exitCode int32
}

// NewWandbReader creates a new wandb file reader.
func NewWandbReader(runPath string) (*WandbReader, error) {
	_, err := os.Stat(runPath)
	if os.IsNotExist(err) {
		return nil, fmt.Errorf("reader: wandb file not found: %s", runPath)
	}

	store, err := NewLiveStore(runPath)
	if err != nil {
		return nil, fmt.Errorf("reader: failed to create live store: %v", err)
	}

	return &WandbReader{store: store}, nil
}

// ReadAllRecordsChunked reads all available records in chunks
// and forwards them for processing as batches.
func (r *WandbReader) ReadAllRecordsChunked() tea.Cmd {
	return func() tea.Msg {
		const chunkSize = 100                          // Process records in chunks
		const maxTimePerChunk = 100 * time.Millisecond // Increased time limit

		if r.store == nil {
			return ChunkedBatchMsg{Msgs: []tea.Msg{}, HasMore: false}
		}

		var msgs []tea.Msg
		recordCount := 0
		startTime := time.Now()
		hitEOF := false

		for recordCount < chunkSize && time.Since(startTime) < maxTimePerChunk {
			record, err := r.store.Read()
			if err != nil {
				break
			}

			if record == nil {
				continue
			}
			// Handle exit record first to avoid double FileComplete
			if exit, ok := record.RecordType.(*spb.Record_Exit); ok && exit.Exit != nil {
				r.exitSeen = true
				r.exitCode = exit.Exit.ExitCode
				msgs = append(msgs, FileCompleteMsg{ExitCode: r.exitCode})
				hitEOF = true // Treat as EOF
				break
			}
			// Non-exit record: convert and append
			if msg := recordToMsg(record); msg != nil {
				msgs = append(msgs, msg)
				recordCount++
			}
		}

		// Determine if there's more to read,
		// i.e. whether we have records and didn't hit EOF, there might be more.
		hasMore := !r.exitSeen && !hitEOF && recordCount > 0

		return ChunkedBatchMsg{
			Msgs:     msgs,
			HasMore:  hasMore,
			Progress: recordCount,
		}
	}
}

// ReadNext reads the next record for live monitoring.
func (r *WandbReader) ReadNext() (tea.Msg, error) {
	if r == nil || r.store == nil {
		return nil, io.EOF
	}

	// Try to read the next record
	record, err := r.store.Read()

	if err == io.EOF && !r.exitSeen {
		// We hit EOF, but the run isn't finished yet
		return nil, io.EOF
	}

	if err != nil && err != io.EOF {
		return nil, err
	}

	if err == io.EOF {
		if r.exitSeen {
			return FileCompleteMsg{ExitCode: r.exitCode}, io.EOF
		}
		return nil, io.EOF
	}

	// Check if this is an exit record
	if exit, ok := record.RecordType.(*spb.Record_Exit); ok {
		r.exitSeen = true
		r.exitCode = exit.Exit.ExitCode
		return FileCompleteMsg{ExitCode: r.exitCode}, nil
	}

	return recordToMsg(record), nil
}

// recordToMsg converts a record to the appropriate message type.
func recordToMsg(record *spb.Record) tea.Msg {
	if record == nil {
		return nil
	}

	switch rec := record.RecordType.(type) {
	case *spb.Record_Run:
		if rec.Run != nil {
			return RunMsg{
				ID:          rec.Run.RunId,
				DisplayName: rec.Run.DisplayName,
				Project:     rec.Run.Project,
				Config:      rec.Run.Config,
			}
		}
	case *spb.Record_History:
		if rec.History != nil {
			return ParseHistory(rec.History)
		}
	case *spb.Record_Stats:
		if rec.Stats != nil {
			return ParseStats(rec.Stats)
		}
	case *spb.Record_Summary:
		if rec.Summary != nil {
			return SummaryMsg{Summary: rec.Summary}
		}
	case *spb.Record_Environment:
		if rec.Environment != nil {
			return SystemInfoMsg{Record: rec.Environment}
		}
	case *spb.Record_Exit:
		if rec.Exit != nil {
			return FileCompleteMsg{ExitCode: rec.Exit.ExitCode}
		}
	}
	return nil
}

// ParseHistory extracts metrics from a history record.
func ParseHistory(history *spb.HistoryRecord) tea.Msg {
	if history == nil {
		return nil
	}

	metrics := make(map[string]float64)
	var step int

	for _, item := range history.Item {
		if item == nil {
			continue
		}

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

		if value, err := strconv.ParseFloat(strings.Trim(item.ValueJson, `"`), 64); err == nil {
			metrics[key] = value
		}
	}

	if len(metrics) > 0 {
		return HistoryMsg{Metrics: metrics, Step: step}
	}
	return nil
}

// ParseStats extracts metrics from a stats record.
func ParseStats(stats *spb.StatsRecord) tea.Msg {
	if stats == nil {
		return nil
	}

	metrics := make(map[string]float64)
	var timestamp int64

	if stats.Timestamp != nil {
		timestamp = stats.Timestamp.Seconds
	}

	for _, item := range stats.Item {
		if item == nil {
			continue
		}

		if value, err := strconv.ParseFloat(strings.Trim(item.ValueJson, `"`), 64); err == nil {
			metrics[item.Key] = value
		}
	}

	if len(metrics) > 0 {
		return StatsMsg{Timestamp: timestamp, Metrics: metrics}
	}
	return nil
}

// Close closes the reader.
func (r *WandbReader) Close() error {
	if r == nil {
		return nil
	}
	if r.store != nil {
		return r.store.Close()
	}
	return nil
}

// InitializeReader creates a command to initialize the wandb reader.
func InitializeReader(runPath string) tea.Cmd {
	return func() tea.Msg {
		reader, err := NewWandbReader(runPath)
		if err != nil {
			return ErrorMsg{Err: err}
		}
		return InitMsg{Reader: reader}
	}
}

// ReadAllRecordsChunked returns a command to read records in chunks for progressive loading.
func ReadAllRecordsChunked(reader *WandbReader) tea.Cmd {
	if reader == nil {
		// No reader available; no-op to keep Bubble Tea flow consistent.
		return func() tea.Msg { return nil }
	}
	return reader.ReadAllRecordsChunked()
}

// ReadAvailableRecords reads new records for live monitoring.
func ReadAvailableRecords(reader *WandbReader) tea.Cmd {
	// No reader? Nothing to do.
	if reader == nil {
		return func() tea.Msg { return nil }
	}

	return func() tea.Msg {
		var msgs []tea.Msg
		recordCount := 0

		// Read more per batch, but keep a small time budget to stay responsive.
		const maxRecordsPerBatch = 2000
		const maxBatchTime = 50 * time.Millisecond
		start := time.Now()

		for recordCount < maxRecordsPerBatch && time.Since(start) < maxBatchTime {
			msg, err := reader.ReadNext()
			if err == io.EOF {
				// No more records available right now.
				break
			}
			if err != nil {
				continue
			}
			if msg != nil {
				msgs = append(msgs, msg)
				recordCount++
			}
		}

		if len(msgs) > 0 {
			return BatchedRecordsMsg{Msgs: msgs}
		}
		// No new records found.
		return nil
	}
}

// findLatestRun looks for the latest-run symlink in wandb or .wandb directories.
//
// It respects the WANDB_DIR environment variable if set.
func findLatestRun() (string, error) {
	wandbDirs := []string{".wandb", "wandb"}

	if wandbDir := os.Getenv("WANDB_DIR"); wandbDir != "" {
		wandbDirs = []string{
			filepath.Join(wandbDir, ".wandb"),
			filepath.Join(wandbDir, "wandb"),
		}
	}

	for _, dir := range wandbDirs {
		if _, err := os.Stat(dir); err != nil {
			continue
		}
		latestRunPath := filepath.Join(dir, "latest-run")
		info, err := os.Lstat(latestRunPath)
		if err != nil || info.Mode()&os.ModeSymlink == 0 {
			continue
		}
		target, err := filepath.EvalSymlinks(latestRunPath)
		if err != nil {
			return "", fmt.Errorf("cannot resolve latest-run symlink in %s: %w", dir, err)
		}
		absTarget, err := filepath.Abs(target)
		if err != nil {
			return "", fmt.Errorf("cannot get absolute path for %s: %w", target, err)
		}
		targetInfo, err := os.Stat(absTarget)
		if err != nil {
			return "", fmt.Errorf("latest-run symlink target does not exist: %w", err)
		}
		if !targetInfo.IsDir() {
			return "", fmt.Errorf("latest-run symlink does not point to a directory")
		}
		return absTarget, nil
	}

	if wandbDir := os.Getenv("WANDB_DIR"); wandbDir != "" {
		return "", fmt.Errorf("no latest-run symlink found in %s/.wandb or %s/wandb", wandbDir, wandbDir)
	}
	return "", fmt.Errorf("no latest-run symlink found in ./.wandb or ./wandb")
}

// ResolveRunDirectory determines which run directory to use to look for .wandb file.
//
// If runPath is empty, it looks for the latest-run symlink.
// If runPath is provided, it resolves any symlinks and returns the absolute path.
func ResolveRunDirectory(runPath string) (string, error) {
	if runPath == "" {
		return findLatestRun()
	}

	// Check if it's a symlink
	if info, err := os.Lstat(runPath); err == nil && info.Mode()&os.ModeSymlink != 0 {
		resolved, err := filepath.EvalSymlinks(runPath)
		if err != nil {
			return "", fmt.Errorf("cannot resolve symlink %s: %w", runPath, err)
		}
		runPath = resolved
	}

	// Make it absolute
	absPath, err := filepath.Abs(runPath)
	if err != nil {
		return "", fmt.Errorf("cannot get absolute path for %s: %w", runPath, err)
	}

	return absPath, nil
}

// FindWandbFile searches for a .wandb file in the given directory.
func FindWandbFile(dir string) (string, error) {
	info, err := os.Stat(dir)
	if err != nil {
		return "", fmt.Errorf("cannot access directory: %w", err)
	}
	if !info.IsDir() {
		return "", fmt.Errorf("path is not a directory: %s", dir)
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		return "", fmt.Errorf("cannot read directory: %w", err)
	}
	var wandbFiles []string
	for _, e := range entries {
		if !e.IsDir() && strings.HasSuffix(e.Name(), ".wandb") {
			wandbFiles = append(wandbFiles, e.Name())
		}
	}
	if len(wandbFiles) == 0 {
		return "", fmt.Errorf("no .wandb file found in directory: %s", dir)
	}
	if len(wandbFiles) > 1 {
		return "", fmt.Errorf("multiple .wandb files found in directory: %s", dir)
	}
	return filepath.Join(dir, wandbFiles[0]), nil
}
