package main

import "C"
import (
	"fmt"

	"github.com/wandb/wandb/client/pkg/client"
)

//export Init
func Init(runId *C.char) {
	// fmt.Printf("Hello, %s!\n", C.GoString(name))
	session := client.NewSession()
	run := session.NewRun(C.GoString(runId))

	fmt.Println("Run ID: ", run.GetId())
}

func main() {}
