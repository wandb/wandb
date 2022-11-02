package main 

import (
    "flag"
    "fmt"
    "github.com/wandb/wandb/nexus/server"
)

func main() {
    fmt.Println("hello")
    portFilename := flag.String("port-filename", "portfile.txt", "filename")    
    pid := flag.Int("pid", 0, "pid")    
    debug := flag.Bool("debug", false, "debug")
    serveSock := flag.Bool("serve-sock", false, "debug")
    serveGrpc := flag.Bool("serve-grpc", false, "debug")
    flag.Parse()
    fmt.Println("got", *portFilename, *pid, *debug, *serveSock, *serveGrpc)

    server.WandbService(*portFilename)
}
