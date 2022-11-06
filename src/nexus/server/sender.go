package server

import (
    // "flag"
    // "io"
    // "google.golang.org/protobuf/reflect/protoreflect"
    "sync"

    "context"
    "fmt"
    "os"
    "encoding/base64"
    "net/http"
    "github.com/wandb/wandb/nexus/service"
    "github.com/Khan/genqlient/graphql"

    log "github.com/sirupsen/logrus"
)


type Sender struct {
    senderChan chan service.Record
    wg *sync.WaitGroup
    graphqlClient graphql.Client
    respondResult func(result *service.Result)
}

func NewSender(wg *sync.WaitGroup, respondResult func(result *service.Result)) (*Sender) {
    sender := Sender{}
    sender.senderChan = make(chan service.Record)
    sender.respondResult = respondResult
    sender.wg = wg

    sender.wg.Add(1)
    go sender.senderGo()
    return &sender
}

func (sender *Sender) Stop() {
    close(sender.senderChan)
}

func (sender *Sender) SendRecord(rec *service.Record) {
    sender.senderChan <-*rec
}

type authedTransport struct {
	key     string
	wrapped http.RoundTripper
}

func basicAuth(username, password string) string {
  auth := username + ":" + password
  return base64.StdEncoding.EncodeToString([]byte(auth))
}

func (t *authedTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	// req.Header.Set("Authorization", "bearer "+t.key)
	req.Header.Set("Authorization", "Basic "+basicAuth("api", t.key))
	//req.Header.Set("Authorization", "api "+t.key)
    req.Header.Set("User-Agent", "wandb-nexus")
    // req.Header.Set("X-WANDB-USERNAME", "jeff")
    // req.Header.Set("X-WANDB-USER-EMAIL", "jeff@wandb.com")
	return t.wrapped.RoundTrip(req)
}

func (sender *Sender) senderInit() {
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

    sender.graphqlClient = graphql.NewClient("https://api.wandb.ai/graphql", &httpClient)

}

func (sender *Sender) networkSendRecord(msg *service.Record) {
    switch x := msg.RecordType.(type) {
    case *service.Record_Run:
        // fmt.Println("rungot:", x)
        sender.networkSendRun(msg, x.Run)
    case nil:
        // The field is not set.
        panic("bad2rec")
    default:
        bad := fmt.Sprintf("REC UNKNOWN type %T", x)
        panic(bad)
    }
}

func (sender *Sender) networkSendRun(msg *service.Record, record *service.RunRecord) {

    keepRun := *record

    // fmt.Println("SEND", record)
    ctx := context.Background()
    // resp, err := Viewer(ctx, sender.graphqlClient)
    // fmt.Println(resp, err)
    tags := []string{}
    resp, err := UpsertBucket(
	    ctx, sender.graphqlClient,
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
    sender.respondResult(result)
}

func (sender *Sender) senderGo() {
    defer sender.wg.Done()

    log.Debug("SENDER: OPEN")
    sender.senderInit()
    for done := false; !done; {
        select {
        case msg, ok := <-sender.senderChan:
            if !ok {
                log.Debug("SENDER: NOMORE")
                done = true
                break
            }
            log.Debug("SENDER *******")
            log.WithFields(log.Fields{"record": msg}).Debug("SENDER: got msg")
            sender.networkSendRecord(&msg)
            // handleLogWriter(sender, msg)
        }
    }
    log.Debug("SENDER: FIN")
}
