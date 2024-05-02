package utils

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/wandb/wandb/core/pkg/service"
)

func PrintHeadFoot(run *service.RunRecord, settings *service.Settings, footer bool) {
	if run == nil {
		return
	}
	colorReset := "\033[0m"
	colorBrightBlue := "\033[1;34m"
	colorBrightMagenta := "\033[1;35m"
	colorBlue := "\033[34m"
	colorYellow := "\033[33m"

	appURL := strings.Replace(settings.GetBaseUrl().GetValue(), "//api.", "//", 1)
	url := fmt.Sprintf("%v/%v/%v/runs/%v", appURL, run.Entity, run.Project, run.RunId)
	fmt.Printf("%vwandb%v: 🚀 View run %v%v%v at: %v%v%v\n", colorBrightBlue, colorReset, colorYellow, run.DisplayName, colorReset, colorBlue, url, colorReset)
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
		fmt.Printf("%vwandb%v: Find logs at: %v%v%v\n",
			colorBrightBlue, colorReset, colorBrightMagenta, relLogDir, colorReset)
	}
}
