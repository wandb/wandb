package leet

import (
	"cmp"
	"context"
	"os"
	"strings"
	"time"

	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/analytics"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/version"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// defaultTelemetryBaseURL receives telemetry when no W&B server is
// configured.
const defaultTelemetryBaseURL = "https://api.wandb.ai"

// TelemetryParams configures ConfigureTelemetry.
type TelemetryParams struct {
	// Disabled turns off telemetry for the whole process.
	Disabled bool

	// Mode is the launch mode: leet, config, inspect or symon.
	Mode string

	// Commit is the git commit the binary was built from.
	Commit string

	// BaseURL is the W&B server to upload telemetry to.
	// Empty means the public W&B API.
	BaseURL string
}

// ConfigureTelemetry builds the recorder that forwards leet telemetry to
// Datadog through the W&B OpenTelemetry proxy.
//
// Telemetry is uploaded, unauthenticated, to the given server so that
// dedicated instances ingest their own traffic. Servers without the proxy
// API reject the uploads, which are dropped quietly; construction never
// touches the network, so leet startup is not delayed.
//
// The returned function flushes pending records and stops uploads; call it
// on exit. The recorder is nil, and telemetry a no-op, when disabled.
func ConfigureTelemetry(
	params TelemetryParams,
) (*analytics.TelemetryRecorder, func()) {
	if params.Disabled {
		analytics.Disable()
		return nil, func() {}
	}

	baseURL := strings.TrimRight(
		cmp.Or(params.BaseURL, defaultTelemetryBaseURL),
		"/",
	)
	proxy := analytics.NewOpenTelemetryProxyUnchecked(
		context.Background(),
		settings.From(&spb.Settings{
			BaseUrl: wrapperspb.String(baseURL),
		}),
		"wandb-leet",
	)
	if proxy == nil {
		return nil, func() {}
	}

	highCardinalityAttributes := map[string]string{
		"commit":      params.Commit,
		"environment": version.Environment,
	}
	if hostname, err := os.Hostname(); err == nil {
		highCardinalityAttributes["hostname"] = hostname
	}
	if terminal := terminalName(); terminal != "" {
		highCardinalityAttributes["terminal"] = terminal
	}

	recorder := analytics.NewTelemetryRecorder(
		proxy,
		analytics.NewTelemetryContext(),
	).With(
		analytics.LowCardinalityAttributes{
			LeetMode:         params.Mode,
			ExecutionContext: detectExecutionContext(),
		},
		highCardinalityAttributes,
	)

	return recorder, func() {
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		_ = proxy.Shutdown(ctx)
	}
}

// detectExecutionContext classifies the environment leet runs in.
//
// The result is used as a metric attribute, so it must stay low-cardinality.
func detectExecutionContext() string {
	switch {
	case os.Getenv("KUBERNETES_SERVICE_HOST") != "":
		return "kubernetes"
	case fileExists("/.dockerenv") || fileExists("/run/.containerenv"):
		return "container"
	case os.Getenv("SLURM_JOB_ID") != "":
		return "slurm"
	case os.Getenv("CI") != "":
		return "ci"
	case os.Getenv("SSH_CONNECTION") != "" || os.Getenv("SSH_TTY") != "":
		return "ssh"
	default:
		return "local"
	}
}

func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

// terminalName identifies the terminal emulator, or the terminal type when
// the emulator does not advertise itself.
func terminalName() string {
	if termProgram := os.Getenv("TERM_PROGRAM"); termProgram != "" {
		return termProgram
	}
	return os.Getenv("TERM")
}
