package server

import (
    "fmt"
    "os"
    "log"
    "net"
)

func writePortfile(portfile string) {
    // TODO
    // GRPC_TOKEN = "grpc="
    // SOCK_TOKEN = "sock="
    // EOF_TOKEN = "EOF"
    //            data = []
    //            if self._grpc_port:
    //                data.append(f"{self.GRPC_TOKEN}{self._grpc_port}")
    //            if self._sock_port:
    //                data.append(f"{self.SOCK_TOKEN}{self._sock_port}")
    //            data.append(self.EOF_TOKEN)
    //            port_str = "\n".join(data)
    //            written = f.write(port_str)

    tmpfile := fmt.Sprintf("%s.tmp")
    f, err := os.Create(tmpfile)
    check(err)
    defer f.Close()

    _, err = f.WriteString(fmt.Sprintf("sock=%d\n", 9999))
    check(err)
    _, err = f.WriteString("EOF")
    check(err)
    f.Sync()
    f.Close()

    err = os.Rename(tmpfile, portfile)
    check(err)
}

type NexusServer struct {
    shutdown bool
    listen net.Listener
}

func tcp_server(portfile string) {
    addr := "localhost:9999"
    listen, err := net.Listen("tcp", addr)
    if err != nil {
        log.Fatalln(err)
    }
    defer listen.Close()

    serverState := NexusServer{listen: listen}

    writePortfile(portfile)

    log.Println("Server is running on:", addr)

    for {
        conn, err := listen.Accept()
        if err != nil {
            if serverState.shutdown {
                log.Println("shutting down...")
                break
            }
            log.Println("Failed to accept conn.", err)
            // sleep so we dont have a busy loop
            continue
        }

        go handleConnection(&serverState, conn)
    }
}

func wb_service(portfile string) {
    tcp_server(portfile)
}

func WandbService(portFilename string) {
    wb_service(portFilename)
}
