package server

import (
    // "flag"
    "context"
    // "io"
    "net"
    "bufio"
    "bytes"
    "encoding/binary"
    "google.golang.org/protobuf/proto"
    // "google.golang.org/protobuf/reflect/protoreflect"
    "github.com/wandb/wandb/nexus/service"
    log "github.com/sirupsen/logrus"
)

// import "wandb.ai/wandb/wbserver/wandb_internal":

type Header struct {
    Magic      uint8
    DataLength uint32
}

type Tokenizer struct {
    data []byte
    header Header
    headerLength int
    headerValid bool
}

type NexusConn struct {
    conn net.Conn
    server *NexusServer
    done chan bool
    ctx context.Context

    mux map[string]*Stream
    processChan chan service.ServerRequest
    respondChan chan service.ServerResponse
}

func (nc *NexusConn) init() {
    process := make(chan service.ServerRequest)
    respond := make(chan service.ServerResponse)
    nc.processChan = process
    nc.respondChan = respond
    nc.done = make(chan bool)
    nc.ctx = context.Background()
    nc.mux = make(map[string]*Stream)
    // writer := make(chan service.Record)
    // stream := Stream{exit: exit, done: done, process: process, respond: respond, writer: writer, ctx: ctx, server: nc.server}
    // stream := Stream{exit: exit, done: done, process: process, respond: respond, ctx: ctx, server: nc.server}
    // nc.stream = stream
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

/*
    resp := &service.ServerResponse{
        ServerResponseType: &service.ServerResponse_ResultCommunicate{result},
    }
*/

func respondServerResponse(nc *NexusConn, msg *service.ServerResponse) {
    // fmt.Println("respond")
    out, err := proto.Marshal(msg)
    check(err)
    // fmt.Println("respond", len(out), out)

    writer := bufio.NewWriter(nc.conn)

    header := Header{Magic: byte('W')}
    header.DataLength = uint32(len(out))

    err = binary.Write(writer, binary.LittleEndian, &header)
    check(err)

    _, err = writer.Write(out)
    check(err)

    err = writer.Flush()
    check(err)
}

func (nc *NexusConn) reader() {
    scanner := bufio.NewScanner(nc.conn)
    tokenizer := Tokenizer{}

    scanner.Split(tokenizer.split)
    for scanner.Scan() {
        // fmt.Printf("%q ", scanner.Text())
        msg := &service.ServerRequest{}
        err := proto.Unmarshal(scanner.Bytes(), msg)
        if err != nil {
            log.Fatal("unmarshaling error: ", err)
        }
        // fmt.Println("gotmsg")
        nc.processChan <- *msg
        // fmt.Println("data2 ", msg)
    }
    log.Debug("SOCKETREADER: DONE")
    nc.done <- true
}

func (nc *NexusConn) writer() {
    for {
        select {
        case msg := <-nc.respondChan:
            respondServerResponse(nc, &msg)
        case <-nc.done:
            log.Debug("PROCESS: DONE")
            return
        }
    }
}

func (nc *NexusConn) process() {
    for {
        select {
        case msg := <-nc.processChan:
            handleServerRequest(nc, msg)
        case <-nc.done:
            log.Debug("PROCESS: DONE")
            return
        }
    }
}

func (nc *NexusConn) RespondServerResponse(serverResponse *service.ServerResponse) {
    nc.respondChan <-*serverResponse
}

func (nc *NexusConn) wait() {
    log.Debug("WAIT1")
    for {
        select {
        case <- nc.done:
            log.Debug("WAIT done")
            return
        case <-nc.ctx.Done():
            log.Debug("WAIT ctx done")
			return
        }
    }
    log.Debug("WAIT2")
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

    log.Debug("WAIT3 done handle con")
}
