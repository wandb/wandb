package server

import (
    "fmt"
    "io"
    "os"
    "net"
    log "github.com/sirupsen/logrus"
)

func InitLogging() {
    /*

    InfoLogger = log.New(file, "INFO: ", log.Ldate|log.Ltime|log.Lshortfile)
    WarningLogger = log.New(file, "WARNING: ", log.Ldate|log.Ltime|log.Lshortfile)
    ErrorLogger = log.New(file, "ERROR: ", log.Ldate|log.Ltime|log.Lshortfile)

    InfoLogger.Println("Starting the application...")
    InfoLogger.Println("Something noteworthy happened")
    WarningLogger.Println("There is something you should know about")
    ErrorLogger.Println("Something went wrong")
    */

    logFile, err := os.OpenFile("logs.txt", os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0666)
    if err != nil {
        log.Fatal(err)
    }

    logToConsole := false
    // logToConsole = true
    if logToConsole {
        mw := io.MultiWriter(os.Stderr, logFile)
        log.SetOutput(mw)
    } else {
        log.SetOutput(logFile)
    }

    log.SetFormatter(&log.JSONFormatter{})
    log.SetLevel(log.DebugLevel)
    /*
    log.Debug("Useful debugging information.")
    log.Info("Something noteworthy happened!")
    log.Warn("You should probably take a look at this.")
    log.Error("Something failed but I'm not quitting.")
    */
}

func writePortfile(portfile string, port int) {
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

    _, err = f.WriteString(fmt.Sprintf("sock=%d\n", port))
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
    addr := "localhost:0"
    listen, err := net.Listen("tcp", addr)
    if err != nil {
        log.Fatalln(err)
    }
    defer listen.Close()

    serverState := NexusServer{listen: listen}


    log.Println("Server is running on:", addr)
    port := listen.Addr().(*net.TCPAddr).Port
    log.Println("PORT", port)

    writePortfile(portfile, port)

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
