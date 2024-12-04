package gowandb

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"sync"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/experimental/client-go/internal/connection"
	"github.com/wandb/wandb/experimental/client-go/internal/interfaces"
	"github.com/wandb/wandb/experimental/client-go/pkg/runconfig"
	"github.com/wandb/wandb/experimental/client-go/pkg/settings"
)

type Color string

const (
	resetFormat = "\033[0m"

	BrightBlue    Color = "\033[1;34m"
	Blue          Color = "\033[34m"
	Yellow        Color = "\033[33m"
	BrightMagenta Color = "\033[1;35m"
)

func format(text string, color Color) string {
	return fmt.Sprintf("%v%v%v", color, text, resetFormat)
}

type RunParams struct {
	Conn      *connection.Connection
	Config    *runconfig.Config
	Settings  *settings.SettingsWrap
	Telemetry *spb.TelemetryRecord
}
type Run struct {
	// ctx is the context for the run
	ctx            context.Context
	settings       *settings.SettingsWrap
	config         *runconfig.Config
	conn           *connection.Connection
	sock           *interfaces.SockInterface
	wg             sync.WaitGroup
	partialHistory History
	telemetry      *spb.TelemetryRecord
}

// NewRun creates a new run with the given settings and responders.
func NewRun(ctx context.Context, params RunParams) *Run {
	if params.Config == nil {
		params.Config = &runconfig.Config{}
	}

	run := &Run{
		ctx:      ctx,
		settings: params.Settings,
		conn:     params.Conn,
		sock: &interfaces.SockInterface{
			Conn:     params.Conn,
			StreamId: params.Settings.GetRunId().GetValue(),
		},
		wg:             sync.WaitGroup{},
		config:         params.Config,
		telemetry:      params.Telemetry,
		partialHistory: make(History),
	}
	return run
}

func (r *Run) Start() {
	if err := os.MkdirAll(r.settings.GetLogDir().GetValue(), os.ModePerm); err != nil {
		slog.Error("error creating log dir", "err", err)
	}
	if err := os.MkdirAll(r.settings.GetFilesDir().GetValue(), os.ModePerm); err != nil {
		slog.Error("error creating files dir", "err", err)
	}

	r.sock.Start()

	if err := r.sock.InformInit(r.settings); err != nil {
		slog.Error("error informing init", "err", err)
		return
	}

	handle, err := r.sock.DeliverRunRecord(r.settings, r.config, r.telemetry)
	if err != nil {
		slog.Error("error delivering run record", "err", err)
		return
	}
	result := handle.Wait()
	r.settings.Entity = wrapperspb.String(result.GetRunResult().GetRun().GetEntity())
	r.settings.RunName = wrapperspb.String(result.GetRunResult().GetRun().GetDisplayName())
	if err := r.sock.InformStart(r.settings); err != nil {
		slog.Error("error informing start", "err", err)
		return
	}

	handle, err = r.sock.DeliverRunStartRequest(r.settings)
	if err != nil {
		slog.Error("error delivering run start request", "err", err)
		return
	}
	handle.Wait()

	r.printRunURL()
}

func (r *Run) Log(data map[string]interface{}, commit bool) {
	for k, v := range data {
		r.partialHistory[k] = v
	}
	if !commit {
		return
	}

	if err := r.sock.PublishPartialHistory(r.partialHistory); err != nil {
		slog.Error("error publishing partial history", "err", err)
	}
	r.partialHistory = make(History)
}

func (r *Run) Finish() {
	handle, err := r.sock.DeliverExitRecord()
	if err != nil {
		slog.Error("error delivering exit record", "err", err)
		return
	}
	handle.Wait()

	handle, err = r.sock.DeliverShutdownRequest()
	if err != nil {
		slog.Error("error delivering shutdown request", "err", err)
		return
	}
	handle.Wait()
	if err := r.sock.InformFinish(); err != nil {
		slog.Error("error informing finish", "err", err)
		return
	}
	r.sock.Close()
	r.printRunURL()
	r.printLogDir()
}

func (r *Run) printRunURL() {
	url := fmt.Sprintf("%v/%v/%v/runs/%v",
		strings.Replace(r.settings.GetBaseUrl().GetValue(), "//api.", "//", 1),
		r.settings.GetEntity().GetValue(),
		r.settings.GetProject().GetValue(),
		r.settings.GetRunId().GetValue(),
	)

	fmt.Printf("%v: 🚀 View run %v at: %v\n",
		format("wandb", BrightBlue),
		format(r.settings.GetRunName().GetValue(), Yellow),
		format(url, Blue),
	)
}

func (r *Run) printLogDir() {

	logDir := r.settings.GetLogDir().GetValue()
	if cwd, err := os.Getwd(); err != nil {
		slog.Error("error getting current directory", "err", err)
	} else if relLogDir, err := filepath.Rel(cwd, logDir); err != nil {
		slog.Error("error getting relative log directory", "err", err)
	} else {
		logDir = relLogDir
	}

	fmt.Printf("%v: Find logs at: %v\n",
		format("wandb", BrightBlue),
		format(logDir, BrightMagenta),
	)

}
