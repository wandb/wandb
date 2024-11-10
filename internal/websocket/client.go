package websocket

import (
	"log"

	"github.com/ctrlplanedev/cli/internal/options"
	"github.com/gorilla/websocket"
)

// MessageHandler is a function that processes a websocket message
type MessageHandler func([]byte) error

// Client represents a WebSocket client connection
type Client struct {
	conn           *websocket.Conn
	send           chan []byte
	messageHandler MessageHandler
	closeHandler   func()
	connectHandler func()
}

// WithMessageHandler sets the message handler for the client
func WithMessageHandler(handler MessageHandler) options.Option {
	return options.NewOptionFunc(func(v interface{}) {
		c := v.(*Client)
		c.messageHandler = handler
	})
}

// WithCloseHandler sets the close handler for the client
func WithCloseHandler(handler func()) options.Option {
	return options.NewOptionFunc(func(v interface{}) {
		c := v.(*Client)
		c.closeHandler = handler
	})
}

// WithConnectHandler sets the connect handler for the client
func WithConnectHandler(handler func()) options.Option {
	return options.NewOptionFunc(func(v interface{}) {
		c := v.(*Client)
		c.connectHandler = handler
	})
}

// NewClient creates a new WebSocket client
func NewClient(conn *websocket.Conn, opts ...options.Option) *Client {
	c := &Client{
		conn:           conn,
		send:           make(chan []byte, 1024),
		messageHandler: func([]byte) error { return nil }, // Default no-op handler
		closeHandler:   func() {},                         // Default no-op handler
		connectHandler: func() {},                         // Default no-op handler
	}

	log.Printf("New client created")

	for _, opt := range opts {
		opt.Apply(c)
	}

	if c.connectHandler != nil {
		c.connectHandler()
	}

	return c
}

// ReadPump pumps messages from the WebSocket connection to the hub.
func (c *Client) ReadPump() {
	defer func() {
		if c.closeHandler != nil {
			c.closeHandler()
		}
		c.conn.Close()
	}()

	for {
		_, message, err := c.conn.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseAbnormalClosure) {
				log.Printf("error: %v", err)
			}
			break
		}

		// Handle received message using the message handler
		if err := c.messageHandler(message); err != nil {
			log.Printf("error handling message: %v", err)
		}
	}
}

// WritePump pumps messages from the hub to the WebSocket connection.
func (c *Client) WritePump() {
	defer func() {
		c.conn.Close()
	}()

	//lint:ignore S1000 suppose to run in a go routine
	for {
		select {
		case message, ok := <-c.send:
			log.Printf("Sending message to channel: %s, ok: %v", string(message), ok)
			if !ok {
				// Channel was closed
				c.conn.WriteMessage(websocket.CloseMessage, []byte{})
				return
			}

			w, err := c.conn.NextWriter(websocket.TextMessage)
			if err != nil {
				return
			}
			w.Write(message)

			if err := w.Close(); err != nil {
				return
			}
		}
	}
}

// Send sends a message to the client
func (c *Client) Send(message []byte) {
	select {
	case c.send <- message:
		// Message sent successfully
	default:
		// Channel is full or closed, handle gracefully
		log.Printf("Failed to send message: channel full or closed")
		c.conn.Close()
	}
}

// Example usage:
/*
func ExampleClient() {
	// Connect to WebSocket server
	conn, _, err := websocket.DefaultDialer.Dial("ws://localhost:8080/ws", nil)
	if err != nil {
		log.Fatal("dial:", err)
	}

	// Create a new client with custom message handler
	client := NewClient(conn,
		WithMessageHandler(func(message []byte) error {
			log.Printf("Received message: %s", message)
			return nil
		}),
		WithConnectHandler(func() {
			log.Println("Connected to server")
		}),
		WithCloseHandler(func() {
			log.Println("Connection closed")
		}),
	)

	// Start the read and write pumps in separate goroutines
	go client.ReadPump()
	go client.WritePump()

	// Send a message
	client.Send([]byte("Hello server!"))
}
*/
