// Package leetmcp serves the wandb leet query verbs as the tools of an MCP
// server: one JSON-RPC 2.0 message per line on stdin and stdout.
package leetmcp

import (
	"bufio"
	"bytes"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"slices"
	"strings"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/version"
)

// supportedVersions are the MCP protocol versions the server speaks,
// newest first.
var supportedVersions = []string{"2026-07-28", "2025-11-25", "2025-06-18"}

// legacyVersions are the supported versions with an initialize handshake.
// The server answers initialize with the client's version when it is one
// of them and with the newest of them otherwise.
var legacyVersions = supportedVersions[1:]

// The JSON-RPC error codes the server replies with.
const (
	errParse              = -32700
	errInvalidRequest     = -32600
	errMethodNotFound     = -32601
	errInvalidParams      = -32602
	errResourceNotFound   = -32002
	errUnsupportedVersion = -32022
)

var (
	capabilities = map[string]any{"tools": map[string]any{}, "resources": map[string]any{}}
	serverInfo   = map[string]any{"name": "wandb", "version": version.Version}
)

// The LEET panel: the MCP App that renders the result of leet_view in a
// client that declared the extension io.modelcontextprotocol/ui.
const (
	panelURI      = "ui://leet/panel"
	panelMIMEType = "text/html;profile=mcp-app"
)

var panelMeta = map[string]any{"ui": map[string]any{"prefersBorder": true}}

// panelHTML is the panel's HTML, which draws the runs and charts it reads
// through leet_history calls that the client proxies to this server.
//
//go:embed panel.html
var panelHTML string

// server answers the requests of one client.
type server struct {
	// apps is whether the client declared in initialize that it renders
	// MCP Apps.
	apps bool
}

type request struct {
	ID     json.RawMessage `json:"id"`
	Method string          `json:"method"`
	Params json.RawMessage `json:"params"`
}

// params are the fields of a request's params the server reads.
type params struct {
	Meta struct {
		ProtocolVersion    string          `json:"io.modelcontextprotocol/protocolVersion"`
		ClientCapabilities json.RawMessage `json:"io.modelcontextprotocol/clientCapabilities"`
	} `json:"_meta"`
	ProtocolVersion string          `json:"protocolVersion"`
	Capabilities    json.RawMessage `json:"capabilities"`
	Name            string          `json:"name"`
	Arguments       json.RawMessage `json:"arguments"`
	URI             string          `json:"uri"`
}

type response struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id"`
	Result  any             `json:"result,omitempty"`
	Error   *rpcError       `json:"error,omitempty"`
}

type rpcError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
	Data    any    `json:"data,omitempty"`
}

// Serve answers the requests read from stdin on stdout until stdin ends,
// noting protocol errors on stderr.
func Serve(stdin io.Reader, stdout, stderr io.Writer) error {
	s := &server{}
	reader := bufio.NewReader(stdin)
	for {
		line, err := reader.ReadBytes('\n')
		if resp := s.respond(line); resp != nil {
			if resp.Error != nil {
				fmt.Fprintf(stderr, "wandb mcp: %s\n", resp.Error.Message)
			}
			if err := writeJSON(stdout, resp); err != nil {
				return err
			}
		}
		if errors.Is(err, io.EOF) {
			return nil
		}
		if err != nil {
			return err
		}
	}
}

// respond returns the response to one message, or nil for a blank line or
// a notification.
func (s *server) respond(line []byte) *response {
	line = bytes.TrimSpace(line)
	if len(line) == 0 {
		return nil
	}
	var req request
	err := json.Unmarshal(line, &req)
	var typeErr *json.UnmarshalTypeError
	switch {
	case err != nil && !errors.As(err, &typeErr):
		return invalid(errParse, "invalid JSON")
	case err != nil && typeErr.Field != "":
		resp := invalid(errInvalidRequest, typeErr.Field+" has the wrong type")
		resp.ID = req.ID
		return resp
	case err != nil, line[0] != '{':
		return invalid(errInvalidRequest, "request must be an object")
	case len(req.ID) == 0:
		return nil
	case strings.IndexByte("\"-0123456789", req.ID[0]) < 0:
		return invalid(errInvalidRequest, "id must be a string or a number")
	}
	slog.Debug("mcp: request", "method", req.Method, "id", string(req.ID))
	resp := &response{JSONRPC: "2.0", ID: req.ID}
	result, rpcErr := s.handle(&req)
	if rpcErr != nil {
		resp.Error = rpcErr
	} else {
		resp.Result = result
	}
	return resp
}

// invalid is the response to a message that is not a request, with no id.
func invalid(code int, message string) *response {
	return &response{JSONRPC: "2.0", Error: &rpcError{Code: code, Message: message}}
}

// handle answers one request. A request carrying the protocol version of
// the 2026-07-28 revision in its _meta gets that revision's result fields.
func (s *server) handle(req *request) (map[string]any, *rpcError) {
	if req.Method == "" {
		return nil, &rpcError{Code: errInvalidRequest, Message: "method is required"}
	}
	p, rpcErr := parseParams(req.Params)
	if rpcErr != nil {
		return nil, rpcErr
	}

	modern := p.Meta.ProtocolVersion != ""
	apps := s.apps || rendersApps(p.Meta.ClientCapabilities)
	var result map[string]any
	switch req.Method {
	case "initialize":
		s.apps = rendersApps(p.Capabilities)
		protocolVersion := legacyVersions[0]
		if slices.Contains(legacyVersions, p.ProtocolVersion) {
			protocolVersion = p.ProtocolVersion
		}
		result = map[string]any{
			"protocolVersion": protocolVersion,
			"capabilities":    capabilities,
			"serverInfo":      serverInfo,
		}
	case "server/discover":
		result = map[string]any{
			"supportedVersions": supportedVersions,
			"capabilities":      capabilities,
		}
		modern = true
	case "ping":
		result = map[string]any{}
	case "tools/list":
		result = ListTools(apps)
	case "tools/call":
		if result, rpcErr = callTool(p.Name, p.Arguments); rpcErr != nil {
			return nil, rpcErr
		}
	case "resources/list":
		result = map[string]any{"resources": panelResources(apps)}
	case "resources/templates/list":
		result = map[string]any{"resourceTemplates": []any{}}
	case "resources/read":
		if result, rpcErr = readResource(apps, modern, p.URI); rpcErr != nil {
			return nil, rpcErr
		}
	default:
		return nil, &rpcError{
			Code:    errMethodNotFound,
			Message: fmt.Sprintf("unknown method %q", req.Method),
		}
	}
	if modern {
		result["resultType"] = "complete"
		result["_meta"] = map[string]any{"io.modelcontextprotocol/serverInfo": serverInfo}
	}
	return result, nil
}

// parseParams decodes a request's params and checks its _meta: a request
// carrying a protocol version must carry one the server speaks and the
// client's capabilities.
func parseParams(raw json.RawMessage) (params, *rpcError) {
	var p params
	if len(raw) > 0 && !bytes.Equal(raw, []byte("null")) {
		if err := json.Unmarshal(raw, &p); err != nil {
			var typeErr *json.UnmarshalTypeError
			if errors.As(err, &typeErr) && typeErr.Field != "" {
				return p, &rpcError{
					Code:    errInvalidParams,
					Message: strings.ReplaceAll(typeErr.Field, "~1", "/") + " has the wrong type",
				}
			}
			return p, &rpcError{Code: errInvalidParams, Message: "params must be an object"}
		}
	}
	modern := p.Meta.ProtocolVersion != ""
	switch {
	case modern && !slices.Contains(supportedVersions, p.Meta.ProtocolVersion):
		return p, &rpcError{
			Code:    errUnsupportedVersion,
			Message: "unsupported protocol version",
			Data: map[string]any{
				"supported": supportedVersions,
				"requested": p.Meta.ProtocolVersion,
			},
		}
	case modern && len(p.Meta.ClientCapabilities) == 0:
		return p, &rpcError{
			Code:    errInvalidParams,
			Message: "_meta lacks io.modelcontextprotocol/clientCapabilities",
		}
	}
	return p, nil
}

// panelResources is the list of resources/list: the panel for a client
// that renders apps, else nothing.
func panelResources(apps bool) []any {
	if !apps {
		return []any{}
	}
	return []any{map[string]any{
		"uri":         panelURI,
		"name":        "leet_panel",
		"description": "Charts of the runs that leet_view listed.",
		"mimeType":    panelMIMEType,
		"_meta":       panelMeta,
	}}
}

// readResource answers resources/read: the panel's HTML for a client that
// renders apps, else Resource not found with the code of the client's
// protocol revision.
func readResource(apps, modern bool, uri string) (map[string]any, *rpcError) {
	if !apps || uri != panelURI {
		code := errResourceNotFound
		if modern {
			code = errInvalidParams
		}
		return nil, &rpcError{
			Code:    code,
			Message: "Resource not found",
			Data:    map[string]any{"uri": uri},
		}
	}
	return map[string]any{"contents": []any{map[string]any{
		"uri":      panelURI,
		"mimeType": panelMIMEType,
		"text":     panelHTML,
		"_meta":    panelMeta,
	}}}, nil
}

// rendersApps is whether a client's capabilities declare the MCP Apps
// extension for the panel's MIME type.
func rendersApps(capabilities json.RawMessage) bool {
	var c struct {
		Extensions struct {
			UI struct {
				MIMETypes []string `json:"mimeTypes"`
			} `json:"io.modelcontextprotocol/ui"`
		} `json:"extensions"`
	}
	_ = json.Unmarshal(capabilities, &c)
	return slices.Contains(c.Extensions.UI.MIMETypes, panelMIMEType)
}

// callTool runs a tool and returns its result: the tool's JSON object as
// text and as structuredContent, or with isError the leet.error/1 object.
func callTool(name string, args json.RawMessage) (map[string]any, *rpcError) {
	i := slices.IndexFunc(tools, func(t tool) bool { return t.name == name })
	if i < 0 {
		return nil, &rpcError{Code: errInvalidParams, Message: fmt.Sprintf("unknown tool %q", name)}
	}

	var out bytes.Buffer
	err := tools[i].run(args, &out)
	if err != nil {
		out.Reset()
		leet.WriteQueryError(&out, err)
	}
	text := strings.TrimSpace(out.String())
	var structured any
	dec := json.NewDecoder(strings.NewReader(text))
	dec.UseNumber()
	_ = dec.Decode(&structured)
	return map[string]any{
		"content":           []any{map[string]any{"type": "text", "text": text}},
		"structuredContent": structured,
		"isError":           err != nil,
	}, nil
}

// writeJSON writes v as one line of JSON.
func writeJSON(w io.Writer, v any) error {
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	return enc.Encode(v)
}
