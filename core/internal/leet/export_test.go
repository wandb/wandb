package leet

import (
	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/runhistoryreader/parquet/ffi"
)

// NewRemoteClientsForTest returns remote clients around a GraphQL client,
// without loading the parquet dylib.
func NewRemoteClientsForTest(client graphql.Client) *remoteClients {
	return &remoteClients{graphql: client, arrow: &ffi.RustArrowWrapper{}}
}

// The remote queries over given clients.
var (
	ListRemoteRunsWith     = listRemoteRuns
	QueryRemoteSummaryWith = queryRemoteSummary
	QueryRemoteConsoleWith = queryRemoteConsole
	QueryRemoteHistoryWith = queryRemoteHistory
	QueryRemoteSystemWith  = queryRemoteSystem
)
