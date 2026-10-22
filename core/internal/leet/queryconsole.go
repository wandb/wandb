package leet

import (
	"cmp"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"github.com/charmbracelet/x/ansi"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	// defaultConsoleLast is how many of the last matching lines
	// QueryConsole returns unless told otherwise.
	defaultConsoleLast = 200

	// defaultConsoleLimit is how many lines QueryConsole returns per page
	// unless told otherwise.
	defaultConsoleLimit = 1000
)

// ConsoleQuery selects the console lines of a run for QueryConsole.
type ConsoleQuery struct {
	Last int    `json:"last"`
	Grep string `json:"grep"`
	// Since keeps the lines logged at or after an RFC 3339 time, or within
	// a duration of the file's last write for a run that is not running
	// and of now for a live one. A line redrawn in place keeps the time it
	// was first written.
	Since       string        `json:"since"`
	Limit       int           `json:"limit"`
	After       string        `json:"after"`
	Follow      bool          `json:"follow"`
	IdleTimeout time.Duration `json:"idle_timeout"`
}

// consoleCursor is where a page of console lines ended, for the call that
// continues after it: the number of the next line.
type consoleCursor struct {
	Version int    `json:"v"`
	Next    int    `json:"n"`
	RunID   string `json:"f"`
}

// QueryConsole writes the console output of a run as one JSON object with
// the schema leet.console/1: of the lines that q.Grep and q.Since select,
// the last q.Last, or with q.Limit or q.After a page of q.Limit from the
// start or from the cursor q.After. With q.Follow it keeps writing one
// object per poll with the new lines, and the lines rewritten in place,
// until the run exits or its file goes q.IdleTimeout without a write.
//
// The run is runFile when given, else the run in wandbDir that run names,
// else the newest run in wandbDir, as resolveQueryRun decides.
func QueryConsole(wandbDir, runFile, run string, q ConsoleQuery, w io.Writer) error {
	s := &consoleScan{console: NewRunConsoleLogs()}
	if err := s.parse(q); err != nil {
		return err
	}
	path, err := resolveQueryRun(wandbDir, runFile, run)
	if err != nil {
		return err
	}
	if s.path, err = filepath.Abs(path); err != nil {
		return err
	}
	s.reader, err = transactionlog.OpenReader(s.path, observability.NewNoOpLogger())
	if err != nil {
		return err
	}
	defer s.reader.Close()

	if err := s.scan(); err != nil {
		return err
	}
	from, err := s.start(q.After)
	if err != nil {
		return err
	}
	last, limit := cmp.Or(q.Last, defaultConsoleLast), cmp.Or(q.Limit, defaultConsoleLimit)
	if q.After != "" || q.Limit > 0 {
		last = 0
	}
	if s.sinceAgo > 0 {
		stat, err := os.Stat(s.path)
		if err != nil {
			return err
		}
		end := time.Now()
		if runState(s.exit, s.run != nil, stat.ModTime()) != RunStateRunning {
			end = stat.ModTime()
		}
		s.since = end.Add(-s.sinceAgo)
	}
	if !s.since.IsZero() {
		untimed := 0
		for _, line := range s.console.lines {
			if line.Timestamp.IsZero() {
				untimed++
			}
		}
		if untimed > 0 {
			s.warnings = append(s.warnings,
				fmt.Sprintf("%d lines have no timestamp and were kept", untimed))
		}
	}

	s.console.dirtyFrom = len(s.console.lines)
	lines, matched, truncated, next := s.page(from, last, limit)
	hasMore := last == 0 && truncated
	if err := s.writeObject(w, lines, matched, truncated, hasMore, next, nil); err != nil {
		return err
	}
	return s.follow(w, q, limit, matched, next, hasMore)
}

// consoleScan assembles the console output of one run for QueryConsole.
type consoleScan struct {
	path   string
	reader *transactionlog.Reader

	grep *regexp.Regexp
	// since is the earliest time of a line to return, or zero.
	since time.Time
	// sinceAgo is q.Since as a duration, resolved once the file was read:
	// against now while the run runs, else against the modification time
	// of its file.
	sinceAgo time.Duration

	console *RunConsoleLogs
	// seen is the content of every line below the number the last object
	// ended at, as of that object, for rewritten to compare against.
	seen     []string
	run      *spb.RunRecord
	exit     *spb.RunExitRecord
	warnings []string
}

// start returns the number of the line to page from: 0, or the line the
// cursor after says.
func (s *consoleScan) start(after string) (int, error) {
	if after == "" {
		return 0, nil
	}
	var c consoleCursor
	if err := decodeCursor(after, &c); err != nil {
		return 0, err
	}
	switch {
	case c.Version != 1:
		return 0, badRequest("after: unsupported cursor version")
	case c.RunID != s.run.GetRunId(), c.Next < 0, c.Next > len(s.console.lines):
		return 0, badRequest("after: the cursor is from another run or an older file")
	}
	return c.Next, nil
}

// follow writes one object per poll with the lines from number next on
// and the lines rewritten in place, until the run exits or its file goes
// q.IdleTimeout without a write. It returns at once unless q.Follow.
func (s *consoleScan) follow(
	w io.Writer,
	q ConsoleQuery,
	limit, matched, next int,
	hasMore bool,
) error {
	var lines []any
	var truncated bool
	for q.Follow && (s.exit == nil || hasMore) {
		if !hasMore {
			idle, err := awaitWrite(s.reader, s.path, q.IdleTimeout)
			if err != nil {
				return err
			}
			if idle > 0 {
				return s.writeObject(w, []any{}, matched, false, true, next,
					[]string{fmt.Sprintf("no writes for %v", idle.Round(time.Second))})
			}
			if err := s.scan(); err != nil {
				return err
			}
		}
		rewritten := s.rewritten(next)
		lines, matched, truncated, next = s.page(next, 0, limit)
		lines = append(rewritten, lines...)
		hasMore = truncated
		if len(lines) > 0 || s.exit != nil {
			if err := s.writeObject(w, lines, matched, truncated, hasMore, next, nil); err != nil {
				return err
			}
		}
	}
	return nil
}

// parse checks the query's numbers, compiles q.Grep and parses q.Since.
func (s *consoleScan) parse(q ConsoleQuery) error {
	if q.Last < 0 || q.Limit < 0 || q.IdleTimeout < 0 {
		return badRequest("last, limit and idle_timeout must be >= 0")
	}
	var err error
	if q.Grep != "" {
		if s.grep, err = regexp.Compile(q.Grep); err != nil {
			return badRequest("grep: %v", err)
		}
	}
	s.since, s.sinceAgo, err = parseSince(q.Since)
	return err
}

// scan reads records up to the end of the file, assembling console lines.
func (s *consoleScan) scan() error {
	for {
		record, err := readRecord(s.reader)
		switch {
		case errors.Is(err, io.EOF), errors.Is(err, io.ErrUnexpectedEOF):
			return nil
		case errors.Is(err, errCorruptSkipped):
			s.warnings = append(s.warnings, err.Error())
			continue
		case err != nil:
			return err
		}
		switch rec := record.RecordType.(type) {
		case *spb.Record_Run:
			if s.run == nil {
				s.run = rec.Run
			}
		case *spb.Record_OutputRaw:
			msg := parseOutputRaw(s.path, rec.OutputRaw).(ConsoleLogMsg)
			s.console.ProcessRaw(msg.Text, msg.IsStderr, msg.Time)
		case *spb.Record_Exit:
			s.exit = rec.Exit
		}
	}
}

// selects reports whether the query's --since and --grep keep line i.
func (s *consoleScan) selects(i int) bool {
	line := s.console.lines[i]
	if !s.since.IsZero() && !line.Timestamp.IsZero() && line.Timestamp.Before(s.since) {
		return false
	}
	return s.grep == nil || s.grep.MatchString(ansi.Strip(line.Content))
}

// page returns the lines from number from on that the query selects, in
// JSON form: the last `last` of them when last > 0, else the first `limit`.
// It also returns how many lines of the whole log the query selects,
// whether it left out any of the lines from `from` on, and the number of
// the line after the returned ones, up to which it records s.seen.
func (s *consoleScan) page(from, last, limit int) ([]any, int, bool, int) {
	all := s.console.lines
	var idx []int
	matched := 0
	for i := range all {
		if !s.selects(i) {
			continue
		}
		matched++
		if i >= from {
			idx = append(idx, i)
		}
	}
	n, next := len(idx), len(all)
	if last > 0 {
		idx = idx[max(n-last, 0):]
	} else if n > limit {
		idx = idx[:limit]
		next = idx[limit-1] + 1
	}
	lines := make([]any, 0, len(idx))
	for _, i := range idx {
		lines = append(lines, consoleLineJSON(i, all[i]))
	}
	for _, line := range all[len(s.seen):next] {
		s.seen = append(s.seen, line.Content)
	}
	return lines, matched, n > len(lines), next
}

// rewritten returns, in JSON form, the lines below number next whose
// content changed since the last object and that the query selects.
func (s *consoleScan) rewritten(next int) []any {
	all := s.console.lines
	var lines []any
	for i := s.console.dirtyFrom; i < next; i++ {
		if all[i].Content == s.seen[i] {
			continue
		}
		s.seen[i] = all[i].Content
		if s.selects(i) {
			lines = append(lines, consoleLineJSON(i, all[i]))
		}
	}
	s.console.dirtyFrom = len(all)
	return lines
}

func (s *consoleScan) writeObject(
	w io.Writer,
	lines []any,
	matched int,
	truncated, hasMore bool,
	next int,
	warnings []string,
) error {
	stat, err := os.Stat(s.path)
	if err != nil {
		return err
	}
	out := map[string]any{
		"schema": "leet.console/1",
		"source": querySource(s.path, s.run.GetEntity(), s.run.GetProject(), s.run.GetRunId()),
		"state": strings.ToLower(
			runState(s.exit, s.run != nil, stat.ModTime()).String(),
		),
		"exit_code":     nil,
		"run_id":        orNil(s.run.GetRunId()),
		"total_lines":   len(s.console.lines),
		"matched_lines": matched,
		"lines":         lines,
		"truncated":     truncated,
		"has_more":      hasMore,
		"next_cursor":   nil,
		"warnings":      append(append([]string{}, s.warnings...), warnings...),
	}
	if s.exit != nil {
		out["exit_code"] = s.exit.GetExitCode()
	}
	if s.exit == nil || hasMore {
		out["next_cursor"] = encodeCursor(consoleCursor{
			Version: 1, Next: next, RunID: s.run.GetRunId(),
		})
	}
	s.warnings = nil
	return encodeJSON(w, out, "")
}

// consoleLineJSON returns line, the number-th assembled console line of a
// run, in the line shape of leet.console/1.
func consoleLineJSON(number int, line ConsoleLogLine) map[string]any {
	level := ""
	if line.IsStderr {
		level = "error"
	}
	return map[string]any{
		"number":    number,
		"timestamp": rfc3339OrNil(line.Timestamp),
		"level":     level,
		"label":     "",
		"content":   ansi.Strip(line.Content),
	}
}
