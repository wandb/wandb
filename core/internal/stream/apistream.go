package stream

import (
	"net/http"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// ApiStream is a Stream that is used to send records to the server,
// which originate from the W&B SDK's public API.
type ApiStream struct {
	StreamID string

	dispatcher    *Dispatcher
	graphqlClient graphql.Client
	httpClient    *http.Client
	inChan        chan *spb.Record
	logger        *observability.CoreLogger
	settings      *settings.Settings
}

// NewApiStream creates a new ApiStream.
func NewApiStream(
	streamID string,
	settings *settings.Settings,
	logger *observability.CoreLogger,
	graphqlClient graphql.Client,
	httpClient *http.Client,
) *ApiStream {
	return &ApiStream{
		StreamID: streamID,

		dispatcher:    NewDispatcher(logger),
		graphqlClient: graphqlClient,
		httpClient:    httpClient,
		inChan:        make(chan *spb.Record),
		logger:        logger,
		settings:      settings,
	}
}

// Start implements Stream.Start.
func (s *ApiStream) Start() {
	s.logger.Info("api stream: starting")
	// TODO: implement an api handler
}

// HandleRecord implements Stream.HandleRecord.
func (s *ApiStream) HandleRecord(record *spb.Record) {
	s.inChan <- record
}

// GetSettings implements Stream.GetSettings.
func (s *ApiStream) GetSettings() *settings.Settings {
	return s.settings
}

// AddResponders implements Stream.AddResponders.
func (s *ApiStream) AddResponders(entries ...ResponderEntry) {
	s.dispatcher.AddResponders(entries...)
}

// Close implements Stream.Close.
func (s *ApiStream) Close() {
}

// FinishAndClose implements Stream.FinishAndClose.
func (s *ApiStream) FinishAndClose(exitCode int32) {
	s.Close()
}
