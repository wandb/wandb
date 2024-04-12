package main

import (
   "C"
   "fmt"
)

//export pbSessionSetup
func pbSessionSetup() {
    fmt.Println("setup")
}

//export pbSessionTeardown
func pbSessionTeardown() {
    fmt.Println("teardown")
}

//export pbRunStart
func pbRunStart() {
    fmt.Println("run start")
}

//export pbRunLog
func pbRunLog() {
    fmt.Println("run log")
}

//export pbRunFinish
func pbRunFinish() {
    fmt.Println("run finish")
}
