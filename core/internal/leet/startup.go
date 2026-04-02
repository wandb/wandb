package leet

import (
	"flag"
	"fmt"
	"os"

	"github.com/wandb/wandb/core/internal/observability"
)

type StartupArgs struct {
	BaseURL          *string
	DisableAnalytics *bool
	EditConfig       *bool
	Entity           *string
	LogLevel         *int
	PprofAddr        *string
	Project          *string
	RunFile          *string
	RunId            *string
	Usage            func()
	WandbDir         string
}

func ParseStartupArgs(args []string) (*StartupArgs, error) {
	fs := flag.NewFlagSet("leet", flag.ContinueOnError)
	fs.SetOutput(os.Stderr)

	logLevel := fs.Int("log-level", 0,
		"Specifies the log level to use for logging. -4: debug, 0: info, 4: warn, 8: error.")
	disableAnalytics := fs.Bool("no-observability", false,
		"Disables observability features such as metrics and logging analytics.")
	runFile := fs.String("run-file", "",
		"Path to a .wandb file to open directly in single-run view.")
	pprofAddr := fs.String("pprof", "",
		"If set, serves /debug/pprof/* on this address (e.g. 127.0.0.1:6060).")
	editConfig := fs.Bool("config", false, "Open config editor.")

	// Remote runs flags
	baseUrl := fs.String(
		"base-url",
		"",
		"Specifies the base URL of the W&B server for querying remote runs.",
	)
	entity := fs.String(
		"entity",
		"",
		"Specifies the entity who owns the run.",
	)
	project := fs.String(
		"project",
		"",
		"Specifies the project the remote run belongs to.",
	)
	runId := fs.String(
		"run-id",
		"",
		"Specifies the run ID of the remote run.",
	)

	fs.Usage = func() {
		fmt.Fprintf(os.Stderr, `wandb-core leet - Lightweight Experiment Exploration Tool
			A terminal UI for viewing your W&B runs locally.

			Usage:
			  wandb-core leet [flags] <wandb-file/wandb-run-path>

			Arguments:
			  <wandb-file> Path to the .wandb file of a W&B run or a W&B run path.
					Example:
					  /path/to/.wandb/run-20250731_170606-iazb7i1k/run-iazb7i1k.wandb
				If

			Options:
			  -h, --help         Show this help message
			Flags:
		`)
		fs.PrintDefaults()
	}

	if err := fs.Parse(args); err != nil {
		return nil, err
	}

	return &StartupArgs{
		BaseURL:          baseUrl,
		DisableAnalytics: disableAnalytics,
		EditConfig:       editConfig,
		Entity:           entity,
		LogLevel:         logLevel,
		PprofAddr:        pprofAddr,
		Project:          project,
		RunFile:          runFile,
		RunId:            runId,
		Usage:            fs.Usage,
		WandbDir:         fs.Arg(0),
	}, nil
}

func CreateModelParams(
	startupArgs *StartupArgs,
	logger *observability.CoreLogger,
) *ModelParams {
	var wandbDir string
	var runParams *RunParams
	if startupArgs.BaseURL != nil && *startupArgs.BaseURL != "" {
		logger.Debug("remote run because base URL is set")
		runParams = &RunParams{
			RemoteRunParams: &RemoteRunParams{
				BaseURL: *startupArgs.BaseURL,
				Entity:  *startupArgs.Entity,
				Project: *startupArgs.Project,
				RunId:   *startupArgs.RunId,
			},
		}
	} else {
		wandbDir = startupArgs.WandbDir

		if *startupArgs.RunFile != "" {
			runParams = &RunParams{
				LocalRunParams: &LocalRunParams{
					RunFile: *startupArgs.RunFile,
				},
			}
		}
	}

	return &ModelParams{
		WandbDir:  wandbDir,
		RunParams: runParams,
		Logger:    logger,
	}
}
