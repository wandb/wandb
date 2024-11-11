package websocket

import (
	"fmt"
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

// NewClient creates a new WebSocket client
func NewClient(conn *websocket.Conn, opts ...options.Option) *Client {
	c := &Client{
		conn:           conn,
		send:           make(chan []byte, 1024),
		messageHandler: func([]byte) error { return nil }, // Default no-op handler
		closeHandler:   func() {},                         // Default no-op handler
		connectHandler: func() {},                         // Default no-op handler
	}

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
			if !ok {
				fmt.Println("WritePump channel closed")
				// Channel was closed
				c.conn.WriteMessage(websocket.CloseMessage, []byte{})
				return
			}

			if err := c.conn.WriteMessage(websocket.BinaryMessage, message); err != nil {
				fmt.Println("WritePump error sending message: " + err.Error())
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

func (c *Client) Close() {
	c.conn.Close()
}
