package shared

import (
	"fmt"
	"strings"

	"github.com/wandb/wandb/nexus/pkg/service"
)

func PrintHeadFoot(run *service.RunRecord, settings *service.Settings) {
	if run == nil {
		return
	}
	colorReset := "\033[0m"
	colorBrightBlue := "\033[1;34m"
	colorBlue := "\033[34m"
	colorYellow := "\033[33m"

	appURL := strings.Replace(settings.GetBaseUrl().GetValue(), "//api.", "//", 1)
	url := fmt.Sprintf("%v/%v/%v/runs/%v", appURL, run.Entity, run.Project, run.RunId)
	fmt.Printf("%vwandb%v: 🚀 View run %v%v%v at: %v%v%v\n", colorBrightBlue, colorReset, colorYellow, run.DisplayName, colorReset, colorBlue, url, colorReset)
}
