package server

import (
    // "flag"
    // "io"
    // "google.golang.org/protobuf/reflect/protoreflect"

//    "context"
    "fmt"
    "os"
    "net/http"
    "github.com/wandb/wandb/nexus/service"

    "github.com/Khan/genqlient/graphql"
    log "github.com/sirupsen/logrus"
)


func (ns *Stream) senderInit() {
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

}

func (ns *Stream) networkSendRecord(record *service.Record) {
    fmt.Println("SEND", record)
/*
    ctx := context.Background()
    // resp, err := Viewer(ctx, ns.graphqlClient)
    // fmt.Println(resp, err)
    resp, err := UpsertBucket(
	    ctx, ns.graphqlClient,
        /*
	    id string,
	    name string,
	    project string,
	    entity string,
	    groupName string,
	    description string,
	    displayName string,
	    notes string,
	    commit string,
	    config string,
	    host string,
	    debug bool,
	    program string,
	    repo string,
	    jobType string,
	    state string,
	    sweep string,
	    tags []string,
	    summaryMetrics string,
    )
    fmt.Println(resp, err)
        */
    // (*UpsertBucketResponse, error) {
}

func (ns *Stream) sender() {
    ns.wg.Add(1)
    defer ns.wg.Done()

    log.Debug("SENDER: OPEN")
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
    log.Debug("SENDER: FIN")
}
