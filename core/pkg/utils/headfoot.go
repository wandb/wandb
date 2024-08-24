package utils

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	resetFormat = "\033[0m"

	colorBrightBlue = "\033[1;34m"

	colorBrightMagenta = "\033[1;35m"

	colorBlue = "\033[34m"

	colorYellow = "\033[33m"

	bold = "\033[1m"
)

func format(str string, color string) string {
	return fmt.Sprintf("%v%v%v", color, str, resetFormat)
}

// This is used by the go wandb client to print the header and footer of the run
func PrintHeadFoot(run *spb.RunRecord, settings *spb.Settings, footer bool) {
	if run == nil {
		return
	}

	appURL := strings.Replace(settings.GetBaseUrl().GetValue(), "//api.", "//", 1)
	url := fmt.Sprintf("%v/%v/%v/runs/%v", appURL, run.Entity, run.Project, run.RunId)

	fmt.Printf("%v: 🚀 View run %v at: %v\n",
		format("wandb", colorBrightBlue),
		format(run.DisplayName, colorYellow),
		format(url, colorBlue),
	)

	if footer {
		currentDir, err := os.Getwd()
		if err != nil {
			return
		}
		logDir := settings.GetLogDir().GetValue()
		relLogDir, err := filepath.Rel(currentDir, logDir)
		if err != nil {
			return
		}
		fmt.Printf("%v: Find logs at: %v\n",
			format("wandb", colorBrightBlue),
			format(relLogDir, colorBrightMagenta),
		)
	}
}

func PrintFooterOnline(run *spb.RunRecord, settings *spb.Settings) {
	if run == nil {
		return
	}

	appURL := strings.Replace(settings.GetBaseUrl().GetValue(), "//api.", "//", 1)
	url := fmt.Sprintf("%v/%v/%v/runs/%v", appURL, run.Entity, run.Project, run.RunId)

	fmt.Printf("%v: 🚀 View run %v at: %v\n",
		format("wandb", colorBrightBlue),
		format(run.DisplayName, colorYellow),
		format(url, colorBlue),
	)

	currentDir, err := os.Getwd()
	if err != nil {
		return
	}
	logDir := settings.GetLogDir().GetValue()
	relLogDir, err := filepath.Rel(currentDir, logDir)
	if err != nil {
		return
	}
	fmt.Printf("%v: Find logs at: %v\n",
		format("wandb", colorBrightBlue),
		format(relLogDir, colorBrightMagenta),
	)
}

func PrintFooterOffline(settings *spb.Settings) {
	fmt.Printf("%v:\n", format("wandb", colorBrightBlue))
	fmt.Printf("%v: You can sync this run to the cloud by running:\n",
		format("wandb", colorBrightBlue),
	)

	sync := fmt.Sprintf("wandb sync %v", settings.GetSyncDir().GetValue())
	fmt.Printf("%v: %v\n",
		format("wandb", colorBrightBlue),
		format(sync, bold),
	)

	currentDir, err := os.Getwd()
	if err != nil {
		return
	}
	logDir := settings.GetLogDir().GetValue()
	relLogDir, err := filepath.Rel(currentDir, logDir)
	if err != nil {
		return
	}
	fmt.Printf("%v: Find logs at: %v\n",
		format("wandb", colorBrightBlue),
		format(relLogDir, colorBrightMagenta),
	)
}
