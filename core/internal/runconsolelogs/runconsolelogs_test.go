package runconsolelogs_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/filestreamtest"
	"github.com/wandb/wandb/core/internal/paths"
	. "github.com/wandb/wandb/core/internal/runconsolelogs"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/sparselist"
	"github.com/wandb/wandb/core/pkg/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

func TestFileStreamUpdates(t *testing.T) {
	settings := settings.From(&spb.Settings{
		FilesDir: wrapperspb.String(t.TempDir()),
	})
	fileStream := filestreamtest.NewFakeFileStream()
	outputFile, _ := paths.Relative("output.log")
	sender := New(Params{
		ConsoleOutputFile: *outputFile,
		Settings:          settings,
		Logger:            observability.NewNoOpLogger(),
		ExtraWork:         runworktest.New(),
		FileStreamOrNil:   fileStream,
		GetNow: func() time.Time {
			return time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
		},
	})

	sender.StreamLogs(&spb.OutputRawRecord{Line: "line1\n"})
	sender.StreamLogs(&spb.OutputRawRecord{Line: "line2\n"})
	sender.StreamLogs(&spb.OutputRawRecord{Line: "\x1b[Aline2 - modified\n"})
	sender.Finish()

	request := fileStream.GetRequest(settings)
	assert.Equal(t,
		[]sparselist.Run[string]{
			{Start: 0, Items: []string{
				"ERROR 2024-01-01T00:00:00.000000 line1",
				"ERROR 2024-01-01T00:00:00.000000 line2 - modified",
			}},
		},
		request.ConsoleLines.ToRuns())
}
