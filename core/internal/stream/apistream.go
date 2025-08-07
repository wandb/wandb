package stream

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"sync"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/randomid"
	"github.com/wandb/wandb/core/internal/sentry_ext"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type APIStreamParams struct {
	Settings   *settings.Settings
	Sentry     *sentry_ext.Client
	LoggerPath string
	LogLevel   slog.Level
}

type APIStream struct {
	// inChan is a channel of records to process.
	//
	// TODO?: use runWork instead?
	inChan chan *spb.Record

	// logger writes debug logs.
	logger *observability.CoreLogger

	// wg is the WaitGroup for the stream.
	wg sync.WaitGroup

	// settings is the settings for the stream.
	settings *settings.Settings

	// sender manages GraphQL and file transfer operations.
	sender *APISender

	// dispatcher manages responses to the client.
	dispatcher *Dispatcher

	// sentryClient is the client used to report errors to Sentry.
	sentryClient *sentry_ext.Client

	// ID is a unique ID for the stream.
	ID string
}

type APISender struct {
	// featureProvider checks server capabilities.
	featureProvider *featurechecker.ServerFeaturesCache

	// graphqlClient is used for GraphQL operations to the W&B backend.
	graphqlClient graphql.Client

	// fileTransferManager is the file uploader/downloader
	fileTransferManager filetransfer.FileTransferManager

	outChan chan *spb.Result
}

// Do processes incoming requests.
func (as APISender) Do(inChan <-chan *spb.Record) {
	for record := range inChan {
		fmt.Println("+++ GOT A RECORD TO PROCESS\n", record)

		// TODO: do the sanity check more elegantly
		switch record.RecordType.(type) {
		case *spb.Record_Request:
			switch x := record.GetRequest().RequestType.(type) {
			case *spb.Request_Api:
				as.sendAPIRequest(record, x.Api)
			default:
				// TODO?
			}
		default:
			// TODO?
		}
	}
}

// respond
func (as *APISender) respond(record *spb.Record, response *spb.Response) {
	result := &spb.Result{
		ResultType: &spb.Result_Response{Response: response},
		Control:    record.Control,
		Uuid:       record.Uuid,
	}
	as.outChan <- result
}

func (as APISender) sendAPIRequest(record *spb.Record, apiRequest *spb.APIRequest) {
	var valueJSON string
	switch apiRequest.RequestType.(type) {
	case *spb.APIRequest_Run:
		// TODO: handle ProjectId
		response, err := gql.RunWithProjectId(
			context.TODO(),
			as.graphqlClient,
			apiRequest.GetRun().Project,
			apiRequest.GetRun().Entity,
			apiRequest.GetRun().Name,
		)
		if err == nil {
			fmt.Printf("+++ LOOK MA, RESPONSE!\n %+v\n", response)
			jsonBytes, err := json.Marshal(response)
			if err == nil {
				valueJSON = string(jsonBytes)
			}
		}
	default:
		valueJSON = `{"lol":true}`
	}

	// TODO: make an actual response
	r := &spb.Response{
		ResponseType: &spb.Response_ApiResponse{
			ApiResponse: &spb.APIResponse{
				ValueJson: valueJSON,
			},
		},
	}
	as.respond(record, r)
}

func NewAPIStream(params APIStreamParams) *APIStream {
	loggerFile := streamLoggerFile(params.Settings)
	logger := streamLogger(
		loggerFile,
		params.Settings,
		params.Sentry,
		params.LogLevel,
	)

	id := randomid.GenerateUniqueID(32)

	peeker := &observability.Peeker{}
	backend := NewBackend(logger, params.Settings)
	graphqlClient := NewGraphQLClient(
		backend,
		params.Settings,
		peeker,
		id,
	)
	fileTransferStats := filetransfer.NewFileTransferStats()
	fileTransferManager := NewFileTransferManager(
		fileTransferStats,
		logger,
		params.Settings,
	)
	featureProvider := featurechecker.NewServerFeaturesCache(
		context.TODO(),
		graphqlClient,
		logger,
	)

	sender := &APISender{
		featureProvider:     featureProvider,
		graphqlClient:       graphqlClient,
		fileTransferManager: fileTransferManager,
		outChan:             make(chan *spb.Result, BufferSize),
	}

	return &APIStream{
		inChan:       make(chan *spb.Record, BufferSize),
		logger:       logger,
		sentryClient: params.Sentry,
		settings:     params.Settings,
		dispatcher:   NewDispatcher(logger),
		sender:       sender,
	}
}

// AddResponders adds the given responders to the stream's dispatcher.
func (s *APIStream) AddResponders(entries ...ResponderEntry) {
	s.dispatcher.AddResponders(entries...)
}

// UpdateSettings updates the stream's settings with the given settings.
func (s *APIStream) UpdateSettings(newSettings *settings.Settings) {
	s.settings = newSettings
}

// GetSettings returns the stream's settings.
func (s *APIStream) GetSettings() *settings.Settings {
	return s.settings
}

// Start starts sender and dispatcher.
func (s *APIStream) Start() {
	s.wg.Add(1)
	go func() {
		s.sender.Do(s.inChan)
		s.wg.Done()
	}()

	s.wg.Add(1)
	go func() {
		for result := range s.sender.outChan {
			s.dispatcher.handleRespond(result)
		}
		s.wg.Done()
	}()
}

func (s *APIStream) HandleRecord(record *spb.Record) {
	s.logger.Debug("handling record", "record", record.GetRecordType())

	s.inChan <- record
}

func (s *APIStream) Close() {}

func (s *APIStream) FinishAndClose(exitCode int32) {}
