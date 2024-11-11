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

const (
	ControllerURL = "/api/v1/target/proxy/controller"
	SessionURL    = "/api/v1/target/proxy/session"
)

type Agent struct {
	headers    http.Header
	client     *client.Client
	serverURL  string
	agentName  string
	StopSignal chan struct{}
	metadata   map[string]string
	manager    *ptysession.Manager
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
	conn, _, err := websocket.DefaultDialer.Dial(a.serverURL + ControllerURL, a.headers)
	if err != nil {
		return err
	}

	a.client = client.NewClient(conn,
		client.WithMessageHandler(a.handleMessage),
		client.WithCloseHandler(a.handleClose),
		client.WithReadPump(),
		client.WithWritePump(),
	)

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
	case string(payloads.SessionCreateJsonTypeSessionCreate):
		var create payloads.SessionCreateJson
		if err := json.Unmarshal(message, &create); err != nil {
			return fmt.Errorf("failed to parse session create: %v", err)
		}

		_, err := a.CreateSession(
			create.SessionId,
			ptysession.WithSize(create.Rows, create.Cols),
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

func (a *Agent) CreateSession(id string, opts ...options.Option) (*ptysession.Session, error) {
	url := a.serverURL + SessionURL + "/" + id
	conn, _, err := websocket.DefaultDialer.Dial(url, a.headers)
	if err != nil {
		return nil, err
	}

	session, err := ptysession.StartSession(opts...)
	if err != nil {
		return nil, err
	}
	go session.HandleIO()

	handleMessages := func(message []byte) error {
		session.Stdin <- message
		return nil
	}
	ws := client.NewClient(conn, client.WithMessageHandler(handleMessages))
	go ws.ReadPump()
	go ws.WritePump()
	go func() {
		for {
			select {
			case data := <-session.Stdout:
				ws.Send(data)
			case <-session.Ctx.Done():
				ws.Close()
				return
			}
		}
	}()

	return session, nil
}
