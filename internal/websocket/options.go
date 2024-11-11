package websocket

import "github.com/ctrlplanedev/cli/internal/options"

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

// WithReadPump starts the read pump for the client
func WithReadPump() options.Option {
	return options.NewOptionFunc(func(v interface{}) {
		c := v.(*Client)
		go c.ReadPump()
	})
}

// WithWritePump starts the write pump for the client
func WithWritePump() options.Option {
	return options.NewOptionFunc(func(v interface{}) {
		c := v.(*Client)
		go c.WritePump()
	})
}
