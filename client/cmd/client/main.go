package main

import "C"
import (
	"fmt"

	"github.com/wandb/wandb/client/pkg/session"
)

// TODO: support multiple sessions
var s *session.Session

//export Init
func Init(corePath *C.char, runId *C.char) {

	params := &session.SessionParams{
		CorePath: C.GoString(corePath),
	}
	s = session.New(params)
	s.Start()

	run := s.NewRun(C.GoString(runId))

	fmt.Println("Run ID: ", run.GetId())
}

//export Finish
func Finish() {
	fmt.Println("Finishing session")
	s.Close()
}

func main() {}
