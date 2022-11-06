package server

import (
    // "flag"
    // "io"
    // "google.golang.org/protobuf/reflect/protoreflect"

    "github.com/wandb/wandb/nexus/service"

    log "github.com/sirupsen/logrus"
)

type FileStream struct {
    fstreamChan chan service.Record
}

func (ns *Stream) NewFileStream() (*FileStream) {
    fs := FileStream{}
    fs.fstreamChan = make(chan service.Record)
    return &fs
}

func (ns *Stream) fstreamStart() {
    ns.wg.Add(1)
    go ns.fstreamGo()
}

func (fs *FileStream) Stop() {
    close(fs.fstreamChan)
}

func (ns *Stream) fstreamInit() {
    /*
    key := os.Getenv("WANDB_API_KEY")
    if key == "" {
        err := fmt.Errorf("must set WANDB_API_KEY=<wandb api key>")
        panic(err)
        return
    }

    httpClient := http.Client{
        Transport: &authedTransport{
            key:     key,
            wrapped: http.DefaultTransport,
        },
    }

    ns.graphqlClient = graphql.NewClient("https://api.wandb.ai/graphql", &httpClient)
    */
}

func (ns *Stream) fstreamPush(fname string, data string) {
}

func (ns *Stream) fstreamGo() {
    defer ns.wg.Done()

    log.Debug("FSTREAM: OPEN")
/*
    ns.senderInit()
    for done := false; !done; {
        select {
        case msg, ok := <-ns.senderChan:
            if !ok {
                log.Debug("SENDER: NOMORE")
                done = true
                break
            }
            log.Debug("SENDER *******")
            log.WithFields(log.Fields{"record": msg}).Debug("SENDER: got msg")
            ns.networkSendRecord(&msg)
            // handleLogWriter(ns, msg)
        case <-ns.done:
            log.Debug("SENDER: DONE")
            done = true
            break
        }
    }
*/
    log.Debug("FSTREAM: FIN")
}
