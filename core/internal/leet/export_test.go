package leet

import "github.com/Khan/genqlient/graphql"

// NewRemoteClientsForTest returns remote clients around a GraphQL client.
func NewRemoteClientsForTest(client graphql.Client) *remoteClients {
	return &remoteClients{graphql: client}
}

// The remote queries over given clients.
var (
	ListRemoteRunsWith     = listRemoteRuns
	QueryRemoteSummaryWith = queryRemoteSummary
	QueryRemoteConsoleWith = queryRemoteConsole
)
