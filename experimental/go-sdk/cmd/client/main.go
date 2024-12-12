package main

import (
	"os"

	"github.com/wandb/wandb/experimental/client-go/pkg/runconfig"
	"github.com/wandb/wandb/experimental/client-go/pkg/settings"
	"github.com/wandb/wandb/experimental/client-go/pkg/wandb"
)

func main() {
	os.Setenv("WANDB_TAGS", "tag1,tag2,tag3")
	os.Setenv("WANDB_NOTES", "bla bla")
	os.Setenv("WANDB_CONSOLE", "off")
	os.Setenv("WANDB_RESUME", "allow")

	run, err := wandb.Init(
		&wandb.RunParams{
			Config: &runconfig.Config{},
			Settings: &settings.Settings{
				RunProject: "test",
				RunGroup:   "test",
			},
		},
	)
	defer wandb.Teardown()

	defer run.Finish()
	if err != nil {
		panic(err)
	}

	run.Log(map[string]any{"x": 1}, true)
}
