package agent

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"runtime"
	"strconv"
	"time"

	"github.com/creack/pty"
	"github.com/ctrlplanedev/cli/internal/options"
	"github.com/ctrlplanedev/cli/internal/ptysession"
	client "github.com/ctrlplanedev/cli/internal/websocket"
	"github.com/ctrlplanedev/cli/pkg/payloads"
	"github.com/gorilla/websocket"
	"github.com/spf13/viper"
)

func GetSessionProxyURL(sessionId string) string {
	url := viper.GetString("proxy.sessionUrl")
	if url == "" {
		url = "/api/v1/resources/proxy/session"
	}
	return url + "/" + sessionId
}

func GetControllerProxyURL() string {
	url := viper.GetString("proxy.controllerUrl")
	if url == "" {
		url = "/api/v1/resources/proxy/controller"
	}
	return url
}

type Agent struct {
	headers             http.Header
	client              *client.Client
	serverURL           string
	agentName           string
	StopSignal          chan struct{}
	metadata            map[string]string
	associatedResources []string
	manager             *ptysession.Manager
}

func NewAgent(serverURL, agentName string, opts ...func(*Agent)) *Agent {
	headers := make(http.Header)
	headers.Set("User-Agent", "ctrlplane-cli")
	headers.Set("X-Agent-Name", agentName)
	agent := &Agent{
		headers:             headers,
		serverURL:           serverURL,
		agentName:           agentName,
		StopSignal:          make(chan struct{}),
		metadata:            make(map[string]string),
		manager:             ptysession.GetManager(),
		associatedResources: []string{},
	}
	for _, opt := range opts {
		opt(agent)
	}

	// Print agent headers for debugging
	for key, values := range agent.headers {
		if key != "X-Api-Key" {
			for _, value := range values {
				log.Printf("Header %s: %s", key, value)
			}
		}
	}
	return agent
}

// Connect establishes a websocket connection to the server, sets up message
// handlers, starts read/write pumps, initializes heartbeat routine, and starts
// the session cleaner. It returns an error if the connection fails.
func (a *Agent) Connect() error {
	conn, _, err := websocket.DefaultDialer.Dial(a.serverURL+GetControllerProxyURL(), a.headers)
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
		if err := create.UnmarshalJSON(message); err != nil {
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

	case string(payloads.SessionResizeJsonTypeSessionResize):
		var resize payloads.SessionResizeJson
		if err := resize.UnmarshalJSON(message); err != nil {
			return fmt.Errorf("failed to parse session resize: %v", err)
		}

		if session, exists := a.manager.GetSession(resize.SessionId); exists {
			log.Printf("Resizing session %s to (%dx%d)", resize.SessionId, resize.Rows, resize.Cols)
			session.SetSize(&pty.Winsize{
				Rows: resize.Rows,
				Cols: resize.Cols,
			})
		}
	default:
		return fmt.Errorf("unsupported message type: %s", genericMsg.Type)
	}

	return nil
}

func (a *Agent) handleConnect() {
	log.Printf("Agent %s connected to server", a.agentName)

	connectPayload := payloads.AgentConnectJson{
		Type:                payloads.AgentConnectJsonTypeAgentConnect,
		Name:                a.agentName,
		Config:              map[string]interface{}{},
		Metadata:            a.metadata,
		AssociatedResources: a.associatedResources,
	}

	var memStats runtime.MemStats
	runtime.ReadMemStats(&memStats)
	connectPayload.Metadata["go/memstats/totalalloc"] = strconv.FormatUint(memStats.TotalAlloc, 10)
	connectPayload.Metadata["go/memstats/sys"] = strconv.FormatUint(memStats.Sys, 10)
	connectPayload.Metadata["runtime/os"] = runtime.GOOS
	connectPayload.Metadata["runtime/arch"] = runtime.GOARCH
	connectPayload.Metadata["go/version"] = runtime.Version()
	connectPayload.Metadata["go/compiler"] = runtime.Compiler
	connectPayload.Metadata["go/numcpu"] = strconv.Itoa(runtime.NumCPU())

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
			log.Printf("Sending heartbeat to proxy")
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
	url := a.serverURL + GetSessionProxyURL(id)
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

	a.manager.AddSession(id, session)

	return session, nil
}
