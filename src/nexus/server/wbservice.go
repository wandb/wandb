package server

import (
    // "flag"
    "context"
    "fmt"
    "os"
    // "io"
    "log"
    "net"
    "bufio"
    "bytes"
    "encoding/binary"
    "google.golang.org/protobuf/proto"
    // "google.golang.org/protobuf/reflect/protoreflect"
    "github.com/wandb/wandb/nexus/service"
    "github.com/golang/leveldb/record"
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
    server *ServerState
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


func socketReader(stream Stream) {
    scanner := bufio.NewScanner(stream.conn)
    tokenizer := Tokenizer{exit: stream.exit, done: stream.done}

    scanner.Split(tokenizer.split)
    for scanner.Scan() {
        // fmt.Printf("%q ", scanner.Text())
        msg := &service.ServerRequest{}
        err := proto.Unmarshal(scanner.Bytes(), msg)
        if err != nil {
            log.Fatal("unmarshaling error: ", err)
        }
        // fmt.Println("gotmsg")
        stream.process <- *msg
        // fmt.Println("data2 ", msg)
    }
    fmt.Println("SOCKETREADER: DONE")
    stream.done <- true
}

func respondServerResponse(stream Stream, msg *service.ServerResponse) {
    // fmt.Println("respond")
    out, err := proto.Marshal(msg)
    check(err)
    // fmt.Println("respond", len(out), out)

    writer := bufio.NewWriter(stream.conn)

    header := Header{Magic: byte('W')}
    header.DataLength = uint32(len(out))

    err = binary.Write(writer, binary.LittleEndian, &header)
    check(err)

    _, err = writer.Write(out)
    check(err)

    err = writer.Flush()
    check(err)
}

func socketWriter(stream Stream) {
    for {
        select {
        case msg := <-stream.respond:
            respondServerResponse(stream, &msg)
        case <-stream.done:
            fmt.Println("PROCESS: DONE")
            return
        }
    }
}

func handleInformInit(stream Stream, msg *service.ServerInformInitRequest) {
    fmt.Println("PROCESS: INIT")
}

func handleInformStart(stream Stream, msg *service.ServerInformStartRequest) {
    fmt.Println("PROCESS: START")
}

func handleInformFinish(stream Stream, msg *service.ServerInformFinishRequest) {
    fmt.Println("PROCESS: FIN")
}

func handleCommunicate(stream Stream, msg *service.Record) {
    ref := msg.ProtoReflect()
    desc := ref.Descriptor()
    num := ref.WhichOneof(desc.Oneofs().ByName("record_type")).Number()
    fmt.Printf("PROCESS: COMMUNICATE %d\n", num)
    
    switch x := msg.RecordType.(type) {
    case *service.Record_Request:
        // fmt.Println("reqgot:", x)
        handleRequest(stream, msg, x.Request)
    case nil:
        // The field is not set.
        panic("bad2rec")
    default:
        bad := fmt.Sprintf("REC UNKNOWN type %T", x)
        panic(bad)
    }
}

func handleRun(stream Stream, rec *service.Record, run *service.RunRecord) {
    runResult := &service.RunUpdateResult{Run: run}
    result := &service.Result{
        ResultType: &service.Result_RunResult{runResult},
        Control: rec.Control,
        Uuid: rec.Uuid,
    }
    resp := &service.ServerResponse{
        ServerResponseType: &service.ServerResponse_ResultCommunicate{result},
    }
    stream.respond <-*resp
}

func handleRunExit(stream Stream, rec *service.Record, runExit *service.RunExitRecord) {
    runExitResult := &service.RunExitResult{}
    result := &service.Result{
        ResultType: &service.Result_ExitResult{runExitResult},
        Control: rec.Control,
        Uuid: rec.Uuid,
    }
    resp := &service.ServerResponse{
        ServerResponseType: &service.ServerResponse_ResultCommunicate{result},
    }
    stream.respond <-*resp
}

func handleRequest(stream Stream, rec *service.Record, req *service.Request) {
    response := &service.Response{}
    result := &service.Result{
        ResultType: &service.Result_Response{response},
        Control: rec.Control,
        Uuid: rec.Uuid,
    }
    resp := &service.ServerResponse{
        ServerResponseType: &service.ServerResponse_ResultCommunicate{result},
    }
    stream.respond <-*resp
}

func handlePublish(stream Stream, msg *service.Record) {
    ref := msg.ProtoReflect()
    desc := ref.Descriptor()
    num := ref.WhichOneof(desc.Oneofs().ByName("record_type")).Number()
    fmt.Printf("PROCESS: PUBLISH %d\n", num)

    stream.writer <-*msg

    switch x := msg.RecordType.(type) {
    case *service.Record_Header:
        // fmt.Println("headgot:", x)
    case *service.Record_Request:
        // fmt.Println("reqgot:", x)
        handleRequest(stream, msg, x.Request)
    case *service.Record_Summary:
        // fmt.Println("sumgot:", x)
    case *service.Record_Run:
        // fmt.Println("rungot:", x)
        handleRun(stream, msg, x.Run)
    case *service.Record_History:
        // fmt.Println("histgot:", x)
    case *service.Record_Telemetry:
        // fmt.Println("telgot:", x)
    case *service.Record_OutputRaw:
        // fmt.Println("outgot:", x)
    case *service.Record_Exit:
        // fmt.Println("exitgot:", x)
        handleRunExit(stream, msg, x.Exit)
    case nil:
        // The field is not set.
        panic("bad2rec")
    default:
        bad := fmt.Sprintf("REC UNKNOWN type %T", x)
        panic(bad)
    }
}

func handleInformTeardown(stream Stream, msg *service.ServerInformTeardownRequest) {
    fmt.Println("PROCESS: TEARDOWN")
    stream.done <-true
    _, cancelCtx := context.WithCancel(stream.ctx)

    fmt.Println("PROCESS: TEARDOWN *****1")
    cancelCtx()
    fmt.Println("PROCESS: TEARDOWN *****2")
    // TODO: remove this?
    //os.Exit(1)

    stream.server.shutdown = true
    stream.server.listen.Close()
}

func handleLogWriter(stream Stream, msg service.Record) {
}

func handleServerRequest(stream Stream, msg service.ServerRequest) {
    switch x := msg.ServerRequestType.(type) {
    case *service.ServerRequest_InformInit:
        handleInformInit(stream, x.InformInit)
    case *service.ServerRequest_InformStart:
        handleInformStart(stream, x.InformStart)
    case *service.ServerRequest_InformFinish:
        handleInformFinish(stream, x.InformFinish)
    case *service.ServerRequest_RecordPublish:
        handlePublish(stream, x.RecordPublish)
    case *service.ServerRequest_RecordCommunicate:
        handleCommunicate(stream, x.RecordCommunicate)
    case *service.ServerRequest_InformTeardown:
        handleInformTeardown(stream, x.InformTeardown)
    case nil:
        // The field is not set.
        panic("bad2")
    default:
        bad := fmt.Sprintf("UNKNOWN type %T", x)
        panic(bad)
    }
}

func doProcess(stream Stream) {
    for {
        select {
        case msg := <-stream.process:
            handleServerRequest(stream, msg)
        case <-stream.done:
            fmt.Println("PROCESS: DONE")
            return
        }
    }
}

/*
func write(w io.Writer, ss []string) error {
    records := record.NewWriter(w)
    for _, s := range ss {
        rec, err := records.Next()
        if err != nil {
            return err
        }
        if _, err := rec.Write([]byte(s)), err != nil {
            return err
        }
    }
    return records.Close()
}


LEVELDBLOG_HEADER_IDENT = ":W&B"
LEVELDBLOG_HEADER_MAGIC = (
    0xBEE1  # zlib.crc32(bytes("Weights & Biases", 'iso8859-1')) & 0xffff
)
LEVELDBLOG_HEADER_VERSION = 0
        ident, magic, version = struct.unpack("<4sHB", header)

*/
func logHeader(f *os.File) {
    type logHeader struct {
        ident [4]byte
        magic uint16
        version byte
    }
    buf := new(bytes.Buffer)
    ident := [4]byte{byte(':'), byte('W'), byte('&'), byte('B')} 
    head := logHeader{ident: ident, magic: 0xBEE1, version: 1}
    err := binary.Write(buf, binary.LittleEndian, &head)
    check(err)
    f.Write(buf.Bytes())
}

func logWriter(stream Stream) {
    f, err := os.Create("run-data.wandb")
    check(err)
    defer f.Close()

    logHeader(f)

    records := record.NewWriter(f)

    for done := false; !done; {
        select {
        case msg := <-stream.writer:
            fmt.Println("write")
            handleLogWriter(stream, msg)

            rec, err := records.Next()
            check(err)

            out, err := proto.Marshal(&msg)
            check(err)

            _, err = rec.Write(out)
            check(err)
        case <-stream.done:
            fmt.Println("WRITER: DONE")
            done = true
            break
        }
    }
    fmt.Println("WRITER: CLOSE")
    records.Close()
    fmt.Println("WRITER: FIN")
}

func waitDone(stream Stream) {
    fmt.Println("WAIT1")
    for {
        select {
        case <- stream.done:
            fmt.Println("WAIT done")
            return
        case <-stream.ctx.Done():
            fmt.Println("WAIT ctx done")
			return
        }
    }
    fmt.Println("WAIT2")
}

func handle_connection(serverState *ServerState, conn net.Conn) {
    defer func() {
        conn.Close()
    }()

    exit := make(chan struct{})
    done := make(chan bool, 1)
    process := make(chan service.ServerRequest)
    respond := make(chan service.ServerResponse)
    writer := make(chan service.Record)
    ctx := context.Background()
    stream := Stream{conn: conn, exit: exit, done: done, process: process, respond: respond, writer: writer, ctx: ctx, server: serverState}
    
    go socketReader(stream)
    go socketWriter(stream)
    go doProcess(stream)
    go logWriter(stream)
    waitDone(stream)
    fmt.Println("WAIT3 done handle con")
    //os.Exit(0)
}

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

type ServerState struct {
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

    serverState := ServerState{listen: listen}

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

        go handle_connection(&serverState, conn)
    }
}

func wb_service(portfile string) {
    tcp_server(portfile)
}

func WandbService(portFilename string) {
    wb_service(portFilename)
}
