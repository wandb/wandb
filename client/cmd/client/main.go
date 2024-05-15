package main

import "C"
import (
	"fmt"

	"github.com/wandb/wandb/client/pkg/session"
)

//export Init
func Init(corePath *C.char, runId *C.char) {

	params := &session.SessionParams{
		CorePath: C.GoString(corePath),
	}
	s := session.New(params)
	s.Start()

	run := s.NewRun(C.GoString(runId))

	fmt.Println("Run ID: ", run.GetId())
}

func main() {}
