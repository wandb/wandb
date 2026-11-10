package runreader_test

import (
	"context"
	"fmt"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runreader"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestConsole_PartialLinesAndRewrites(t *testing.T) {
	console := runreader.NewConsole()
	at := time.Date(2026, 1, 1, 12, 0, 0, 0, time.UTC)
	console.Process(outputRecord("epoch ", false, at).GetOutputRaw())
	console.Process(outputRecord("care", true, at.Add(time.Second)).GetOutputRaw())
	console.Process(outputRecord("1\nprogress 10%", false, at.Add(2*time.Second)).GetOutputRaw())
	console.Process(outputRecord("ful\n", true, at.Add(3*time.Second)).GetOutputRaw())
	assert.Equal(t, []runreader.ConsoleLine{
		{Time: at, Content: "epoch 1"},
		{Time: at.Add(time.Second), Stderr: true, Content: "careful"},
		{Time: at.Add(2 * time.Second), Content: "progress 10%"},
	}, console.Lines())

	console.Process(
		outputRecord(
			"\rprogress 20%\n\x1b[A\rprogress 30%",
			false,
			at.Add(4*time.Second),
		).GetOutputRaw(),
	)
	assert.Equal(t, []runreader.ConsoleLine{
		{Time: at, Content: "epoch 1"},
		{Time: at.Add(time.Second), Stderr: true, Content: "careful"},
		{Time: at.Add(2 * time.Second), Content: "progress 30%"},
	}, console.Lines())
}

func TestConsole_LinesScrolledWithinRecord(t *testing.T) {
	console := runreader.NewConsole()
	var text strings.Builder
	for i := range 150 {
		fmt.Fprintf(&text, "line %03d\n", i)
	}
	console.Process(&spb.OutputRawRecord{Line: text.String()})
	require.Len(t, console.Lines(), 150)
	for i, line := range console.Lines() {
		assert.Equal(t, fmt.Sprintf("line %03d", i), line.Content)
	}

	console.Process(&spb.OutputRawRecord{Line: "\x1b[A\rupdated!"})
	assert.Equal(t, "line 000", console.Lines()[0].Content)
	assert.Equal(t, "updated!", console.Lines()[149].Content)
}

func TestConsole_LoggerLinesInterleaveWithPartialOutput(t *testing.T) {
	console := runreader.NewConsole()
	at := time.Date(2026, 1, 1, 12, 0, 0, 0, time.UTC)
	console.Process(outputRecord("part", false, at).GetOutputRaw())
	console.ProcessLogger(&spb.OutputLoggerRecord{Line: "\nlogged \t\n\n"})
	console.Process(outputRecord("err", true, at.Add(time.Second)).GetOutputRaw())
	console.Process(outputRecord("ial\n", false, at.Add(2*time.Second)).GetOutputRaw())
	console.ProcessLogger(&spb.OutputLoggerRecord{Line: "literal\rtext\x1b[A"})
	console.Process(outputRecord("or\n", true, at.Add(3*time.Second)).GetOutputRaw())
	console.ProcessLogger(&spb.OutputLoggerRecord{Line: "\n"})
	assert.Equal(t, []runreader.ConsoleLine{
		{Time: at, Content: "partial"},
		{},
		{Content: "logged \t"},
		{},
		{Time: at.Add(time.Second), Stderr: true, Content: "error"},
		{Content: "literal\rtext\x1b[A"},
		{},
	}, console.Lines())
}

func TestRun_LoggerOutput(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run-abc.wandb")
	writeLog(t, path, runRecord("abc", nil), &spb.Record{
		RecordType: &spb.Record_OutputLogger{OutputLogger: &spb.OutputLoggerRecord{
			Line: "custom logger message\n",
		}},
	})
	run, err := runreader.Open(path, observability.NewNoOpLogger())
	require.NoError(t, err)
	defer run.Close()
	require.NoError(t, run.Update(context.Background()))
	assert.Equal(t, []runreader.ConsoleLine{{Content: "custom logger message"}}, run.Console())
}

func BenchmarkConsole_Process(b *testing.B) {
	record := &spb.OutputRawRecord{Line: strings.Repeat("x", 4096) + "\n"}
	b.SetBytes(256 * int64(len(record.Line)))
	b.ReportAllocs()
	for b.Loop() {
		console := runreader.NewConsole()
		for range 256 {
			console.Process(record)
		}
	}
}
