package server

import (
    // "flag"
    // "io"
    // "google.golang.org/protobuf/reflect/protoreflect"

    "context"
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

func (ns *Stream) networkSendRecord(msg *service.Record) {
    switch x := msg.RecordType.(type) {
    case *service.Record_Run:
        // fmt.Println("rungot:", x)
        ns.networkSendRun(msg, x.Run)
    case nil:
        // The field is not set.
        panic("bad2rec")
    default:
        bad := fmt.Sprintf("REC UNKNOWN type %T", x)
        panic(bad)
    }
}

func (ns *Stream) networkSendRun(msg *service.Record, record *service.RunRecord) {

    keepRun := *record

    // fmt.Println("SEND", record)
    ctx := context.Background()
    // resp, err := Viewer(ctx, ns.graphqlClient)
    // fmt.Println(resp, err)
    tags := []string{}
    resp, err := UpsertBucket(
	    ctx, ns.graphqlClient,
        nil, // id
        &record.RunId, // name
        nil, // project
	    nil, // entity
	    nil, // groupName
	    nil, // description
	    nil, // displayName
	    nil, // notes
	    nil, // commit
	    nil, // config
	    nil, // host
	    nil, // debug
	    nil, // program
	    nil, // repo
	    nil, // jobType
	    nil, // state
	    nil, // sweep
	    tags, // tags []string,
	    nil, // summaryMetrics
    )
    check(err)

    displayName := *resp.UpsertBucket.Bucket.DisplayName
    projectName := resp.UpsertBucket.Bucket.Project.Name
    entityName := resp.UpsertBucket.Bucket.Project.Entity.Name
    keepRun.DisplayName = displayName
    keepRun.Project = projectName
    keepRun.Entity = entityName

    // fmt.Println("RESP::", keepRun)

    // (*UpsertBucketResponse, error) {
    /*
	id *string,
	name *string,
	project *string,
	entity *string,
	groupName *string,
	description *string,
	displayName *string,
	notes *string,
	commit *string,
	config *string,
	host *string,
	debug *bool,
	program *string,
	repo *string,
	jobType *string,
	state *string,
	sweep *string,
	tags []string,
	summaryMetrics *string,
    */

    runResult := &service.RunUpdateResult{Run: &keepRun}
    result := &service.Result{
        ResultType: &service.Result_RunResult{runResult},
        Control: msg.Control,
        Uuid: msg.Uuid,
    }
    ns.respond <-*result
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
