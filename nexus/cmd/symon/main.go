package main

import "github.com/wandb/wandb/nexus/pkg/monitor"

func main() {
	smm := monitor.NewSystemMonitorService()

	smm.Start()
}
