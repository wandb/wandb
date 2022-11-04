package server

import (
    // "flag"
    "fmt"
    "os"
    // "io"
    "bytes"
    "encoding/binary"
    "google.golang.org/protobuf/proto"
    // "google.golang.org/protobuf/reflect/protoreflect"
    "github.com/golang/leveldb/record"
)

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

func (ns *Stream) writer() {
    ns.wg.Add(1)
    f, err := os.Create("run-data.wandb")
    check(err)
    defer ns.wg.Done()
    defer f.Close()

    logHeader(f)

    records := record.NewWriter(f)

    fmt.Println("WRITER: OPEN")
    for done := false; !done; {
        select {
        case msg, ok := <-ns.writerChan:
            if !ok {
                fmt.Println("NOMORE")
                done = true
                break
            }
            fmt.Println("WRITE *******")
            // handleLogWriter(ns, msg)

            rec, err := records.Next()
            check(err)

            out, err := proto.Marshal(&msg)
            check(err)

            _, err = rec.Write(out)
            check(err)
        case <-ns.done:
            fmt.Println("WRITER: DONE")
            done = true
            break
        }
    }
    fmt.Println("WRITER: CLOSE")
    records.Close()
    fmt.Println("WRITER: FIN")
}
