package agent

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/ctrlplanedev/cli/internal/options"
	"github.com/ctrlplanedev/cli/internal/ptysession"
	client "github.com/ctrlplanedev/cli/internal/websocket"
	"github.com/ctrlplanedev/cli/pkg/payloads"
	"github.com/gorilla/websocket"
)

func WithMetadata(metadata map[string]string) func(*Agent) {
	return func(a *Agent) {
		a.metadata = metadata
	}
}

type Agent struct {
	headers    http.Header
	client     *client.Client
	serverURL  string
	agentName  string
	StopSignal chan struct{}
	metadata   map[string]string
	manager    *ptysession.Manager
}

func WithHeader(key string, value string) func(*Agent) {
	return func(a *Agent) {
		a.headers.Set(key, value)
	}
}

func NewAgent(serverURL, agentName string, opts ...func(*Agent)) *Agent {
	headers := make(http.Header)
	headers.Set("User-Agent", "ctrlplane-cli")
	headers.Set("X-Agent-Name", agentName)
	agent := &Agent{
		headers:    headers,
		serverURL:  serverURL,
		agentName:  agentName,
		StopSignal: make(chan struct{}),
		metadata:   make(map[string]string),
		manager:    ptysession.GetManager(),
	}
	for _, opt := range opts {
		opt(agent)
	}
	return agent
}

// Connect establishes a websocket connection to the server, sets up message
// handlers, starts read/write pumps, initializes heartbeat routine, and starts
// the session cleaner. It returns an error if the connection fails.
func (a *Agent) Connect() error {
	conn, _, err := websocket.DefaultDialer.Dial(a.serverURL, a.headers)
	if err != nil {
		return err
	}

	a.client = client.NewClient(conn,
		client.WithMessageHandler(a.handleMessage),
		client.WithCloseHandler(a.handleClose),
	)

	go a.client.ReadPump()
	go a.client.WritePump()

	go a.heartbeatRoutine()
	go a.handleConnect()

	a.manager.StartSessionCleaner(5 * time.Minute)

	return nil
}

func (a *Agent) handleMessage(message []byte) error {
	// First try to unmarshal as a generic message to determine type
	var genericMsg struct {
		Type string `json:"type"`
	}
	if err := json.Unmarshal(message, &genericMsg); err != nil {
		return fmt.Errorf("failed to parse message type: %v", err)
	}

	switch genericMsg.Type {
	case string(payloads.SessionInputJsonTypeSessionInput):
		var input payloads.SessionInputJson
		if err := json.Unmarshal(message, &input); err != nil {
			return fmt.Errorf("failed to parse session input: %v", err)
		}

		session, exists := a.manager.GetSession(input.SessionId)
		if !exists {
			return fmt.Errorf("session %s not found", input.SessionId)
		}

		// Send input data to session's stdin
		session.Stdin <- []byte(input.Data)

	case string(payloads.SessionCreateJsonTypeSessionCreate):
		var create payloads.SessionCreateJson
		if err := json.Unmarshal(message, &create); err != nil {
			return fmt.Errorf("failed to parse session create: %v", err)
		}

		_, err := a.CreateSession(
			ptysession.WithSize(create.Rows, create.Cols),
			ptysession.WithID(*create.SessionId),
			ptysession.WithShell(create.Shell),
			ptysession.AsUser(create.Username),
		)
		if err != nil {
			return fmt.Errorf("failed to create session: %v", err)
		}

	default:
		return fmt.Errorf("unsupported message type: %s", genericMsg.Type)
	}

	return nil
}

func (a *Agent) handleConnect() {
	log.Printf("Agent %s connected to server", a.agentName)

	connectPayload := payloads.AgentConnectJson{
		Type:     payloads.AgentConnectJsonTypeAgentConnect,
		Name:     a.agentName,
		Config:   map[string]interface{}{},
		Metadata: a.metadata,
	}

	data, err := json.Marshal(connectPayload)
	if err != nil {
		log.Printf("Error marshaling connect payload: %v", err)
		return
	}

	a.client.Send(data)
}

func (a *Agent) handleClose() {
	log.Printf("Agent %s disconnected from server", a.agentName)
	a.Stop()
	os.Exit(1)
}

func (a *Agent) heartbeatRoutine() {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			heartbeat := payloads.AgentHeartbeatJson{
				Type:      payloads.AgentHeartbeatJsonTypeClientHeartbeat,
				Timestamp: []time.Time{time.Now()}[0],
			}

			data, err := json.Marshal(heartbeat)
			if err != nil {
				log.Printf("Error marshaling heartbeat: %v", err)
				continue
			}

			a.client.Send(data)

		case <-a.StopSignal:
			return
		}
	}
}

func (a *Agent) Stop() {
	// Clean up any active sessions
	manager := ptysession.GetManager()
	log.Printf("Stopping %d sessions", len(manager.ListSessions()))
	for _, id := range manager.ListSessions() {
		if session, exists := manager.GetSession(id); exists {
			session.CancelFunc()
			manager.RemoveSession(id)
		}
	}

	close(a.StopSignal)
}

func (a *Agent) CreateSession(opts ...options.Option) (*ptysession.Session, error) {
	session, err := ptysession.StartSession(opts...)
	if err != nil {
		return nil, err
	}
	go session.HandleIO()

	// Start goroutine to listen for session stdout and send over websocket
	go func() {
		for {
			select {
			case data := <-session.Stdout:
				output := payloads.SessionOutputJson{
					Type:      payloads.SessionOutputJsonTypeSessionOutput,
					SessionId: session.ID,
					Data:      string(data),
				}

				// Marshal and send over websocket
				if jsonData, err := json.Marshal(output); err == nil {
					a.client.Send(jsonData)
				} else {
					log.Printf("Error marshaling session output: %v", err)
				}

			case <-session.Ctx.Done():
				return
			}
		}
	}()

	return session, nil
}
