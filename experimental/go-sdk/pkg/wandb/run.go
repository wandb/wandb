package wandb

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"

	"github.com/wandb/wandb/experimental/go-sdk/internal/connection"
	"github.com/wandb/wandb/experimental/go-sdk/internal/interfaces"
	"github.com/wandb/wandb/experimental/go-sdk/pkg/runconfig"
	"github.com/wandb/wandb/experimental/go-sdk/pkg/settings"
)

type color string

const (
	resetFormat = "\033[0m"

	BrightBlue color = "\033[1;34m"

	Blue color = "\033[34m"

	Yellow color = "\033[33m"

	BrightMagenta color = "\033[1;35m"
)

func format(str string, color color) string {
	return fmt.Sprintf("%v%v%v", color, str, resetFormat)
}

type runParams struct {
	config    *runconfig.Config
	telemetry *spb.TelemetryRecord
	settings  *settings.Settings
	conn      *connection.Connection
}

type Run struct {
	// ctx is the context for the run
	ctx            context.Context
	settings       *settings.Settings
	config         *runconfig.Config
	interfaces     interfaces.IRun
	partialHistory map[string]interface{}
}

// newRun creates a new run with the given settings and responders.
func newRun(ctx context.Context, params *runParams) *Run {

	return &Run{
		ctx:      ctx,
		settings: params.settings,
		interfaces: interfaces.IRun{
			Conn:     params.conn,
			StreamID: params.settings.RunID,
		},
		config:         params.config,
		partialHistory: make(map[string]interface{}),
	}
}

func (r *Run) start() {
	if err := os.MkdirAll(r.settings.GetLogDir(), os.ModePerm); err != nil {
		slog.Error("error creating log dir", "err", err)
	}
	if err := os.MkdirAll(r.settings.GetFilesDir(), os.ModePerm); err != nil {
		slog.Error("error creating files dir", "err", err)
	}

	r.interfaces.Start()

	// send the init message
	r.interfaces.InformInit(r.settings)

	// deliver the run record
	result := r.interfaces.DeliverRunRecord(r.settings, r.config).Wait()
	r.settings.FromSettings(&settings.Settings{
		Entity:  result.GetRunResult().GetRun().GetEntity(),
		RunName: result.GetRunResult().GetRun().GetDisplayName(),
	})
	result = r.interfaces.DeliverRunStartRequest(r.settings).Wait()
	// print the header
	r.printRunURL()
}

func (r *Run) Log(data map[string]any, commit bool) {
	for k, v := range data {
		r.partialHistory[k] = v
	}
	if commit {
		r.interfaces.PublishPartialHistory(r.partialHistory)
		r.partialHistory = make(map[string]any)
	}
}

func (r *Run) Finish() {
	_ = r.interfaces.DeliverExitRecord().Wait()

	_ = r.interfaces.DeliverShutdownRecord().Wait()

	r.interfaces.InformFinish(r.settings)

	r.interfaces.Close()
	// print the footer
	r.printRunURL()
	r.printLogDir()
}

func (r *Run) printRunURL() {
	fmt.Printf("%v: 🚀 View run %v at: %v\n",
		format("wandb", BrightBlue),
		format(r.settings.RunName, Yellow),
		format(r.settings.GetRunURL(), Blue),
	)
}

func (r *Run) printLogDir() {
	logDir := r.settings.GetLogDir()
	cwd, err := os.Getwd()
	if err != nil {
		slog.Error("error getting current working directory", "err", err)
	} else {
		logDir, err = filepath.Rel(cwd, r.settings.GetLogDir())
		if err != nil {
			slog.Error("error getting relative log dir", "err", err)
		}
	}
	fmt.Printf("%v: Find logs at: %v\n",
		format("wandb", BrightBlue),
		format(logDir, BrightMagenta),
	)
}
