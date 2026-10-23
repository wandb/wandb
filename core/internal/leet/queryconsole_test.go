package leet_test

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"testing"
	"testing/synctest"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func outputRecord(line string, stderr bool, at time.Time) *spb.Record {
	rec := &spb.OutputRawRecord{OutputType: spb.OutputRawRecord_STDOUT, Line: line}
	if stderr {
		rec.OutputType = spb.OutputRawRecord_STDERR
	}
	if !at.IsZero() {
		rec.Timestamp = timestamppb.New(at)
	}
	return &spb.Record{RecordType: &spb.Record_OutputRaw{OutputRaw: rec}}
}

func queryConsole(t *testing.T, path string, q leet.ConsoleQuery) map[string]any {
	t.Helper()
	var out bytes.Buffer
	require.NoError(t, leet.QueryConsole("", path, "", q, &out))
	var obj map[string]any
	require.NoError(t, json.Unmarshal(out.Bytes(), &obj), out.String())
	return obj
}

func TestQueryConsole_GrepThenLast(t *testing.T) {
	at := time.Date(2026, 9, 23, 12, 0, 0, 0, time.UTC)
	path := writeWandbFile(t,
		&spb.Record{RecordType: &spb.Record_Run{Run: &spb.RunRecord{RunId: "abc123"}}},
		outputRecord("\x1b[32mepoch \x1b]8;;https://x\x1b\\1\x1b]8;;\x1b\\\x1b[0m\n", false, at),
		outputRecord("loss is nan\n", true, at),
		outputRecord("epoch 2\n", false, at),
		outputRecord("epoch 3\n", false, time.Time{}),
		&spb.Record{RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{ExitCode: 0}}},
	)

	all := queryConsole(t, path, leet.ConsoleQuery{})
	assert.Equal(t, "leet.console/1", all["schema"])
	assert.Equal(t, "finished", all["state"])
	assert.EqualValues(t, 4, all["total_lines"])
	assert.EqualValues(t, 4, all["matched_lines"])
	assert.Equal(t, false, all["truncated"])
	assert.Nil(t, all["next_cursor"])
	lines := all["lines"].([]any)
	require.Len(t, lines, 4)
	assert.Equal(t, map[string]any{
		"number": 0.0, "timestamp": "2026-09-23T12:00:00Z",
		"level": "", "label": "", "content": "epoch 1",
	}, lines[0])
	assert.Equal(t, "error", lines[1].(map[string]any)["level"])
	assert.Nil(t, lines[3].(map[string]any)["timestamp"])

	cut := queryConsole(t, path, leet.ConsoleQuery{Grep: "^epoch", Last: 2})
	assert.EqualValues(t, 3, cut["matched_lines"])
	assert.Equal(t, true, cut["truncated"])
	assert.Equal(t, false, cut["has_more"])
	lines = cut["lines"].([]any)
	require.Len(t, lines, 2)
	assert.EqualValues(t, 2, lines[0].(map[string]any)["number"])
	assert.Equal(t, "epoch 3", lines[1].(map[string]any)["content"])

	for _, cursor := range []string{
		`{"v":1,"n":-1,"f":"abc123"}`,
		`{"v":1,"n":99,"f":"abc123"}`,
		`{"v":1,"n":1,"f":"other"}`,
		`{"v":2,"n":1,"f":"abc123"}`,
	} {
		after := base64.RawURLEncoding.EncodeToString([]byte(cursor))
		err := leet.QueryConsole("", path, "", leet.ConsoleQuery{After: after}, io.Discard)
		var qerr *leet.QueryError
		require.ErrorAs(t, err, &qerr, cursor)
		assert.Equal(t, "bad_request", qerr.Code, cursor)
	}
}

func TestQueryConsole_SinceDurationBeforeTheLastWrite(t *testing.T) {
	at := time.Date(2026, 9, 23, 12, 0, 0, 0, time.UTC)
	path := writeWandbFile(t,
		outputRecord("old\n", false, at),
		outputRecord("mid\n", false, at.Add(30*time.Second)),
		outputRecord("no clock\n", false, time.Time{}),
		outputRecord("no clock\n", false, time.Time{}),
		outputRecord("new\n", false, at.Add(time.Minute)),
		&spb.Record{RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{ExitCode: 0}}},
	)
	require.NoError(t, os.Chtimes(path, at.Add(time.Minute), at.Add(time.Minute)))

	out := queryConsole(t, path, leet.ConsoleQuery{Since: "30s"})
	lines := out["lines"].([]any)
	require.Len(t, lines, 4)
	assert.Equal(t, "mid", lines[0].(map[string]any)["content"])
	assert.EqualValues(t, 4, out["matched_lines"])
	assert.Equal(t, []any{"2 lines have no timestamp and were kept"}, out["warnings"])

	out = queryConsole(t, path, leet.ConsoleQuery{Since: "2026-09-23T12:01:00Z"})
	require.Len(t, out["lines"], 3)
}

func TestQueryConsole_AfterThenFollowRewrittenLine(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		path := filepath.Join(t.TempDir(), "run-live.wandb")
		w, err := transactionlog.OpenWriter(path)
		require.NoError(t, err)
		require.NoError(t, w.Write(&spb.Record{
			RecordType: &spb.Record_Run{Run: &spb.RunRecord{RunId: "live"}},
		}))
		for _, line := range []string{"a\n", "b\n", "c\n"} {
			require.NoError(t, w.Write(outputRecord(line, false, time.Time{})))
		}
		require.NoError(t, w.Flush())

		first := queryConsole(t, path, leet.ConsoleQuery{Limit: 2})
		require.Len(t, first["lines"], 2)
		assert.EqualValues(t, 3, first["matched_lines"])
		assert.Equal(t, true, first["has_more"])
		assert.Equal(t, "running", first["state"])
		tail := queryConsole(t, path, leet.ConsoleQuery{Last: 1})
		assert.Equal(t, false, tail["has_more"])
		assert.NotNil(t, tail["next_cursor"])

		var out bytes.Buffer
		done := make(chan error, 1)
		go func() {
			done <- leet.QueryConsole("", path, "", leet.ConsoleQuery{
				After: first["next_cursor"].(string), Follow: true,
			}, &out)
		}()
		synctest.Wait()

		require.NoError(t, w.Write(outputRecord("10%", true, time.Time{})))
		require.NoError(t, w.Write(outputRecord("d\n", false, time.Time{})))
		require.NoError(t, w.Flush())
		time.Sleep(2 * time.Second)
		synctest.Wait()
		require.NoError(t, w.Write(outputRecord("\r20%", true, time.Time{})))
		require.NoError(t, w.Flush())
		time.Sleep(2 * time.Second)
		synctest.Wait()
		require.NoError(t, w.Write(&spb.Record{
			RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{ExitCode: 0}},
		}))
		require.NoError(t, w.Close())
		require.NoError(t, <-done)

		objects := consoleObjects(t, out.Bytes())
		require.Len(t, objects, 4)
		var contents [][][2]any
		for _, obj := range objects[:3] {
			var lines [][2]any
			for _, line := range obj["lines"].([]any) {
				line := line.(map[string]any)
				lines = append(lines, [2]any{line["number"], line["content"]})
			}
			contents = append(contents, lines)
		}
		assert.Equal(t, [][][2]any{
			{{2.0, "c"}}, {{3.0, "10%"}, {4.0, "d"}}, {{3.0, "20%"}},
		}, contents)
		assert.Equal(t, []any{}, objects[3]["lines"])
		assert.Equal(t, "finished", objects[3]["state"])
		assert.EqualValues(t, 0, objects[3]["exit_code"])
		assert.Equal(t, false, objects[3]["has_more"])
		assert.Nil(t, objects[3]["next_cursor"])
	})
}

func TestQueryConsole_FollowDrainsPagesAfterExit(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		path := filepath.Join(t.TempDir(), "run-live.wandb")
		w, err := transactionlog.OpenWriter(path)
		require.NoError(t, err)
		require.NoError(t, w.Write(&spb.Record{
			RecordType: &spb.Record_Run{Run: &spb.RunRecord{RunId: "live"}},
		}))
		require.NoError(t, w.Write(outputRecord("a\n", false, time.Time{})))
		require.NoError(t, w.Flush())

		var out bytes.Buffer
		done := make(chan error, 1)
		go func() {
			done <- leet.QueryConsole("", path, "",
				leet.ConsoleQuery{Limit: 2, Follow: true}, &out)
		}()
		synctest.Wait()

		for _, line := range []string{"b\n", "c\n", "d\n", "e\n", "f\n"} {
			require.NoError(t, w.Write(outputRecord(line, false, time.Time{})))
		}
		require.NoError(t, w.Write(&spb.Record{
			RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{ExitCode: 0}},
		}))
		require.NoError(t, w.Close())
		require.NoError(t, <-done)

		objects := consoleObjects(t, out.Bytes())
		require.Len(t, objects, 4)
		var numbers []any
		for _, obj := range objects {
			for _, line := range obj["lines"].([]any) {
				numbers = append(numbers, line.(map[string]any)["number"])
			}
		}
		assert.Equal(t, []any{0.0, 1.0, 2.0, 3.0, 4.0, 5.0}, numbers)
		assert.Equal(t, true, objects[2]["has_more"])
		last := objects[3]
		assert.Equal(t, "finished", last["state"])
		assert.Equal(t, false, last["has_more"])
		assert.Nil(t, last["next_cursor"])
	})
}

// consoleObjects parses the objects QueryConsole wrote, one per line.
func consoleObjects(t *testing.T, b []byte) []map[string]any {
	t.Helper()
	var objects []map[string]any
	for line := range bytes.Lines(b) {
		var obj map[string]any
		require.NoError(t, json.Unmarshal(line, &obj), string(line))
		objects = append(objects, obj)
	}
	return objects
}
