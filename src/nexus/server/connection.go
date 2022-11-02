package server

import (
    // "flag"
    "context"
    "fmt"
    // "io"
    "log"
    "net"
    "bufio"
    "bytes"
    "encoding/binary"
    "google.golang.org/protobuf/proto"
    // "google.golang.org/protobuf/reflect/protoreflect"
    "github.com/wandb/wandb/nexus/service"
)

// import "wandb.ai/wandb/wbserver/wandb_internal":

type Stream struct {
    conn net.Conn
    exit chan struct{}
    done chan bool
    process chan service.ServerRequest
    respond chan service.ServerResponse
    writer chan service.Record
    ctx context.Context
    server *NexusServer
    shutdown bool
}

type Header struct {
    Magic      uint8
    DataLength uint32
}

type Tokenizer struct {
    data []byte
    exit chan struct{}
    done chan bool
    header Header
    headerLength int
    headerValid bool
}

func check(e error) {
    if e != nil {
        panic(e)
    }
}

func (x *Tokenizer) split(data []byte, atEOF bool) (retAdvance int, retToken []byte, retErr error) {
    if x.headerLength == 0 {
        x.headerLength = binary.Size(x.header)
    }

    retAdvance = 0

    // parse header
    if !x.headerValid {
        if len(data) < x.headerLength {
            return
        }
        buf := bytes.NewReader(data)
        err := binary.Read(buf, binary.LittleEndian, &x.header)
        if err != nil {
            log.Fatal(err)
        }
        // fmt.Println("head", x.header, x.headerLength)
        if x.header.Magic != uint8('W') {
             log.Fatal("badness")
        }
        x.headerValid = true
        retAdvance += x.headerLength
        data = data[retAdvance:]
    }

    // fmt.Println("gotdata", len(data))
    // check if we have the full amount of data
    if len(data) < int(x.header.DataLength) {
        return
    }

    retAdvance += int(x.header.DataLength)
    retToken = data[:x.header.DataLength]
    x.headerValid = false
    return
}

type NexusConn struct {
    conn net.Conn
    stream Stream
    server *NexusServer
}

func (nc *NexusConn) init() {
    exit := make(chan struct{})
    done := make(chan bool, 1)
    process := make(chan service.ServerRequest)
    respond := make(chan service.ServerResponse)
    writer := make(chan service.Record)
    ctx := context.Background()
    stream := Stream{exit: exit, done: done, process: process, respond: respond, writer: writer, ctx: ctx, server: nc.server, conn: nc.conn}
    nc.stream = stream
}

func (nc *NexusConn) reader() {
    scanner := bufio.NewScanner(nc.stream.conn)
    tokenizer := Tokenizer{exit: nc.stream.exit, done: nc.stream.done}

    scanner.Split(tokenizer.split)
    for scanner.Scan() {
        // fmt.Printf("%q ", scanner.Text())
        msg := &service.ServerRequest{}
        err := proto.Unmarshal(scanner.Bytes(), msg)
        if err != nil {
            log.Fatal("unmarshaling error: ", err)
        }
        // fmt.Println("gotmsg")
        nc.stream.process <- *msg
        // fmt.Println("data2 ", msg)
    }
    fmt.Println("SOCKETREADER: DONE")
    nc.stream.done <- true
}

func (nc *NexusConn) writer() {
    for {
        select {
        case msg := <-nc.stream.respond:
            respondServerResponse(nc.stream, &msg)
        case <-nc.stream.done:
            fmt.Println("PROCESS: DONE")
            return
        }
    }
}

func (nc *NexusConn) process() {
    for {
        select {
        case msg := <-nc.stream.process:
            handleServerRequest(&nc.stream, msg)
        case <-nc.stream.done:
            fmt.Println("PROCESS: DONE")
            return
        }
    }
}

func (nc *NexusConn) wait() {
    fmt.Println("WAIT1")
    for {
        select {
        case <- nc.stream.done:
            fmt.Println("WAIT done")
            return
        case <-nc.stream.ctx.Done():
            fmt.Println("WAIT ctx done")
			return
        }
    }
    fmt.Println("WAIT2")
}

func handleConnection(serverState *NexusServer, conn net.Conn) {
    defer func() {
        conn.Close()
    }()

    connection := NexusConn{conn: conn, server: serverState}

    connection.init()
    go connection.reader()
    go connection.writer()
    go connection.process()
    connection.wait()

    fmt.Println("WAIT3 done handle con")
}
