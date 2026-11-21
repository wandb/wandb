package main

import (
	"errors"
	"flag"
	"fmt"
	"os"
	"slices"

	tea "charm.land/bubbletea/v2"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

var leetComputeCommands = []*leetCommand{
	{
		name:      "compute usage",
		args:      "[<scope-url>]",
		short:     "Print compute usage for a W&B scope as JSON",
		mode:      "compute_usage",
		script:    true,
		bindFlags: bindLeetComputeUsageFlags,
		validate:  validateLeetComputeUsageOptions,
		run:       runLeetComputeUsage,
	},
	{
		name:      "compute drilldown",
		args:      "[<run-url>]",
		short:     "Print per-device metric series for a W&B run as JSON",
		mode:      "compute_drilldown",
		script:    true,
		bindFlags: bindLeetComputeDrilldownFlags,
		validate:  validateLeetComputeDrilldownOptions,
		run:       runLeetComputeDrilldown,
	},
}

func parseLeetComputeArgs(
	parent *leetCommand, args []string,
) (*leetCommand, *leetOptions, error) {
	if len(args) > 0 && slices.Contains([]string{"-h", "-help", "--help"}, args[0]) {
		fmt.Fprint(os.Stderr, "Read compute usage and per-device metrics as JSON.\n\n"+
			"Usage:\n  wandb-core leet compute <command> [flags] [<url>]\n\nCommands:\n")
		for _, cmd := range leetComputeCommands {
			fmt.Fprintf(os.Stderr, "  %s\n", cmd.name)
		}
		return parent, nil, flag.ErrHelp
	}
	if len(args) > 0 {
		for _, cmd := range leetComputeCommands {
			if cmd.name == "compute "+args[0] {
				return parseLeetCommandArgs(cmd, args[1:])
			}
		}
	}
	return parent, nil, errors.New("compute requires usage or drilldown")
}

func bindLeetComputeUsageFlags(fs *flag.FlagSet, opts *leetOptions) {
	q := &opts.computeUsage
	fs.StringVar(&opts.remoteURL, "remote-url", "", "W&B organization, team, project or run URL.")
	fs.StringVar(&q.Period, "period", "30d", "YYYY-MM, inclusive YYYY-MM-DD:YYYY-MM-DD, or Nd.")
	fs.StringVar(
		&q.Basis,
		"basis",
		"physical",
		"GPU-hour basis: associated, physical or allocated.",
	)
	fs.Func(
		"group-by",
		"Comma-separated team,project,user,run,device,parent_device,device_model,day.",
		appendKeys(&q.GroupBy),
	)
	fs.StringVar(&q.User, "user", "", "Keep runs owned by this username.")
	fs.Func("tag", "Keep runs carrying this tag. Repeatable.", appendComputeValue(&q.Tags))
	fs.Func(
		"device-model",
		"Keep this device model. Repeatable.",
		appendComputeValue(&q.DeviceModels),
	)
	fs.Func("device-type", "Keep this device type. Repeatable.", appendComputeValue(&q.DeviceTypes))
	fs.BoolVar(&q.Compare, "compare", false, "Also query the preceding period.")
}

func bindLeetCompassFlags(fs *flag.FlagSet, opts *leetOptions) {
	fs.StringVar(&opts.remoteURL, "remote-url", "", "W&B organization, team or project URL.")
}

// runLeetCompass runs the Compute Compass view, steered by wandb leet
// session on the same URL.
func runLeetCompass(opts *leetOptions, logger *observability.CoreLogger) int {
	control, stop := serveLeetControl(opts.remoteURL, logger)
	defer stop()
	m, err := leet.NewCompass(opts.remoteRun, control)
	if err == nil {
		_, err = tea.NewProgram(m).Run()
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "Error:", err)
		return exitCodeErrorInternal
	}
	return exitCodeSuccess
}

func bindLeetComputeDrilldownFlags(fs *flag.FlagSet, opts *leetOptions) {
	q := &opts.computeDrilldown
	fs.StringVar(&opts.remoteURL, "remote-url", "", "W&B run URL.")
	fs.Func("fields", "Comma-separated typed record field paths. Required.", appendKeys(&q.Fields))
	fs.IntVar(&q.Bins, "bins", 200, "Number of equal time bins.")
	fs.StringVar(&q.Device, "device", "", "Keep this device UUID.")
	fs.StringVar(&q.Start, "start", "", "First sample time, as RFC3339.")
	fs.StringVar(&q.End, "end", "", "Last sample time, as RFC3339.")
}

func appendComputeValue(values *[]string) func(string) error {
	return func(value string) error {
		*values = append(*values, value)
		return nil
	}
}

func validateLeetComputeSource(opts *leetOptions) error {
	if opts.remoteURL != "" && opts.wandbDir != "" {
		return errors.New("a URL cannot be used with --remote-url")
	}
	if opts.remoteURL == "" {
		opts.remoteURL = opts.wandbDir
	}
	if opts.remoteURL == "" {
		return errors.New("a W&B URL is required")
	}
	return nil
}

func validateLeetComputeUsageOptions(opts *leetOptions) error {
	if err := validateLeetComputeSource(opts); err != nil {
		return err
	}
	var err error
	opts.remoteRun, err = leet.ParseRemoteScopeURL(opts.remoteURL)
	return err
}

func validateLeetComputeDrilldownOptions(opts *leetOptions) error {
	if err := validateLeetComputeSource(opts); err != nil {
		return err
	}
	var err error
	opts.remoteRun, err = leet.ParseRemoteURL(opts.remoteURL)
	if err != nil {
		return err
	}
	if opts.remoteRun.RunID == "" {
		return errors.New("a run URL is required")
	}
	return nil
}

func runLeetComputeUsage(opts *leetOptions, _ *observability.CoreLogger) int {
	return queryExit(leet.QueryComputeUsage(opts.remoteRun, opts.computeUsage, os.Stdout))
}

func runLeetComputeDrilldown(opts *leetOptions, _ *observability.CoreLogger) int {
	return queryExit(leet.QueryComputeDrilldown(opts.remoteRun, opts.computeDrilldown, os.Stdout))
}
