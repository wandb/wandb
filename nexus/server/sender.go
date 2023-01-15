package server

import (
	// "flag"
	// "io"
	// "google.golang.org/protobuf/reflect/protoreflect"
	"sync"

	"context"
	"encoding/base64"
	"fmt"
	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/nexus/service"
	"net/http"

	log "github.com/sirupsen/logrus"
)

type Sender struct {
	senderChan    chan *service.Record
	wg            *sync.WaitGroup
	graphqlClient graphql.Client
	respondResult func(result *service.Result)
	settings      *Settings
}

func NewSender(wg *sync.WaitGroup, respondResult func(result *service.Result), settings *Settings) *Sender {
	sender := Sender{
		senderChan:    make(chan *service.Record),
		wg:            wg,
		respondResult: respondResult,
		settings:      settings,
	}

	sender.wg.Add(1)
	go sender.senderGo()
	return &sender
}

func (sender *Sender) Stop() {
	close(sender.senderChan)
}

func (sender *Sender) SendRecord(rec *service.Record) {
	if sender.settings.Offline {
		return
	}
	sender.senderChan <- rec
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
	req.Header.Set("Authorization", "Basic "+basicAuth("api", t.key))
	req.Header.Set("User-Agent", "wandb-nexus")
	// req.Header.Set("X-WANDB-USERNAME", "jeff")
	// req.Header.Set("X-WANDB-USER-EMAIL", "jeff@wandb.com")
	return t.wrapped.RoundTrip(req)
}

func (sender *Sender) senderInit() {
	httpClient := http.Client{
		Transport: &authedTransport{
			key:     sender.settings.ApiKey,
			wrapped: http.DefaultTransport,
		},
	}
	url := fmt.Sprintf("%s/graphql", sender.settings.BaseURL)
	sender.graphqlClient = graphql.NewClient(url, &httpClient)
}

func (sender *Sender) sendNetworkStatusRequest(msg *service.NetworkStatusRequest) {
}

func (sender *Sender) sendRequest(msg *service.Record, req *service.Request) {
	switch x := req.RequestType.(type) {
	case *service.Request_NetworkStatus:
		sender.sendNetworkStatusRequest(x.NetworkStatus)
	default:
	}
}

func (sender *Sender) networkSendRecord(msg *service.Record) {
	switch x := msg.RecordType.(type) {
	case *service.Record_Run:
		// fmt.Println("rungot:", x)
		sender.networkSendRun(msg, x.Run)
	case *service.Record_Request:
		sender.sendRequest(msg, x.Request)
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
		nil,           // id
		&record.RunId, // name
		nil,           // project
		nil,           // entity
		nil,           // groupName
		nil,           // description
		nil,           // displayName
		nil,           // notes
		nil,           // commit
		nil,           // config
		nil,           // host
		nil,           // debug
		nil,           // program
		nil,           // repo
		nil,           // jobType
		nil,           // state
		nil,           // sweep
		tags,          // tags []string,
		nil,           // summaryMetrics
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
		Control:    msg.Control,
		Uuid:       msg.Uuid,
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
			sender.networkSendRecord(msg)
			// handleLogWriter(sender, msg)
		}
	}
	log.Debug("SENDER: FIN")
}
