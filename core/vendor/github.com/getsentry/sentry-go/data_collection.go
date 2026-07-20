package sentry

import "slices"

// CollectionMode controls how key-value data (headers, cookies, query params) is collected.
//
// Defaults to CollectionDenyList.
type CollectionMode int

const (
	// CollectionDenyList keeps all keys and filters denied values.
	CollectionDenyList CollectionMode = iota

	// CollectionOff disables collection of the category entirely.
	CollectionOff

	// CollectionAllowList keeps all keys and sends real values only for allowed keys.
	CollectionAllowList
)

// KeyValueCollectionBehavior configures how key-value data is collected and filtered.
type KeyValueCollectionBehavior struct {
	// Mode controls the collection strategy.
	Mode CollectionMode
	// Terms is a list of additional terms used by the active mode.
	Terms []string
}

// HeaderCollectionConfig configures how HTTP headers are collected for
// requests and responses independently.
type HeaderCollectionConfig struct {
	// Request configures collection of HTTP request headers.
	Request *KeyValueCollectionBehavior
	// Response configures collection of HTTP response headers.
	Response *KeyValueCollectionBehavior
}

// BodyType identifies a category of HTTP body to collect.
type BodyType string

const (
	// BodyIncomingRequest collects bodies from incoming HTTP requests
	// (server-side).
	BodyIncomingRequest BodyType = "incomingRequest"

	// BodyOutgoingRequest collects bodies from outgoing HTTP requests
	// (client-side).
	BodyOutgoingRequest BodyType = "outgoingRequest"

	// BodyIncomingResponse collects bodies from incoming HTTP responses
	// (client-side).
	BodyIncomingResponse BodyType = "incomingResponse"
)

// DataCollection configures what data the SDK collects automatically.
// All fields are optional. nil or zero-value fields use the documented
// defaults, which collect rich context for debugging while scrubbing sensitive
// values via a built-in denylist.
//
// See https://docs.sentry.io/platforms/go/configuration/options/#DataCollection
type DataCollection struct {
	// UserInfo controls automatic population of user.* fields from auto-instrumentation.
	//
	// This does NOT gate data explicitly set via Scope.SetUser(); that is
	// always attached. Defaults to true.
	UserInfo Option[bool]

	// Cookies configures collection of HTTP cookies.
	//
	// Defaults to using the built-in DenyList.
	Cookies *KeyValueCollectionBehavior

	// HTTPHeaders configures collection of HTTP request and response headers
	// independently.
	//
	// Defaults to both request and response using the built-in DenyList.
	HTTPHeaders *HeaderCollectionConfig

	// HTTPBodies controls which HTTP body types are collected.
	//
	// Defaults to collecting all valid body types.
	HTTPBodies []BodyType

	// QueryParams configures collection of URL query parameters.
	//
	// Defaults to using the built-in DenyList.
	QueryParams *KeyValueCollectionBehavior

	// sensitiveTerms is the deny-list used for built-in sensitive-key
	// scrubbing.
	sensitiveTerms []string
}

// cloneKeyValueCollectionBehavior returns a deep copy of b.
func cloneKeyValueCollectionBehavior(b *KeyValueCollectionBehavior) *KeyValueCollectionBehavior {
	if b == nil {
		return nil
	}
	cloned := &KeyValueCollectionBehavior{Mode: b.Mode}
	if b.Terms != nil {
		cloned.Terms = slices.Clone(b.Terms)
	}
	return cloned
}

// cloneHeaderCollectionConfig returns a deep copy of c.
func cloneHeaderCollectionConfig(c *HeaderCollectionConfig) *HeaderCollectionConfig {
	if c == nil {
		return nil
	}
	return &HeaderCollectionConfig{
		Request:  cloneKeyValueCollectionBehavior(c.Request),
		Response: cloneKeyValueCollectionBehavior(c.Response),
	}
}

// cloneDataCollection returns a deep copy of dc.
func cloneDataCollection(dc *DataCollection) *DataCollection {
	if dc == nil {
		return nil
	}
	cloned := &DataCollection{
		UserInfo:       dc.UserInfo,
		Cookies:        cloneKeyValueCollectionBehavior(dc.Cookies),
		HTTPHeaders:    cloneHeaderCollectionConfig(dc.HTTPHeaders),
		QueryParams:    cloneKeyValueCollectionBehavior(dc.QueryParams),
		sensitiveTerms: dc.sensitiveTerms,
	}
	if dc.HTTPBodies != nil {
		cloned.HTTPBodies = slices.Clone(dc.HTTPBodies)
	}
	return cloned
}

// allBodyTypes returns all valid body types.
func allBodyTypes() []BodyType {
	return []BodyType{
		BodyIncomingRequest,
		BodyOutgoingRequest,
		BodyIncomingResponse,
	}
}

// snapshotDataCollection builds a fully-populated DataCollection based on given options.
// It handles any unspecified values by applying the defaults. If the given opts are nil, this
// provides a best-effort snapshot to align with sendDefaultPII for backwards compatibility.
func snapshotDataCollection(opts *DataCollection, sendDefaultPII bool) DataCollection {
	if opts == nil {
		return legacyDataCollection(sendDefaultPII)
	}
	return resolveDataCollection(opts)
}

func resolveDataCollection(dc *DataCollection) DataCollection {
	var resolved DataCollection
	if cloned := cloneDataCollection(dc); cloned != nil {
		resolved = *cloned
	}

	if !resolved.UserInfo.IsSet {
		resolved.UserInfo = Set(true)
	}
	if resolved.Cookies == nil {
		resolved.Cookies = &KeyValueCollectionBehavior{}
	}
	if resolved.HTTPHeaders == nil {
		resolved.HTTPHeaders = &HeaderCollectionConfig{}
	}
	if resolved.HTTPHeaders.Request == nil {
		resolved.HTTPHeaders.Request = &KeyValueCollectionBehavior{}
	}
	if resolved.HTTPHeaders.Response == nil {
		resolved.HTTPHeaders.Response = &KeyValueCollectionBehavior{}
	}
	if resolved.HTTPBodies == nil {
		resolved.HTTPBodies = allBodyTypes()
	}
	if resolved.QueryParams == nil {
		resolved.QueryParams = &KeyValueCollectionBehavior{}
	}
	return resolved
}

func legacyDataCollection(sendDefaultPII bool) DataCollection {
	if sendDefaultPII {
		return resolveDataCollection(&DataCollection{
			UserInfo:    Set(true),
			Cookies:     &KeyValueCollectionBehavior{},
			HTTPHeaders: &HeaderCollectionConfig{Request: &KeyValueCollectionBehavior{}, Response: &KeyValueCollectionBehavior{}},
			HTTPBodies:  allBodyTypes(),
			QueryParams: &KeyValueCollectionBehavior{},
		})
	}

	return resolveDataCollection(&DataCollection{
		UserInfo:   Set(false),
		HTTPBodies: []BodyType{},
		Cookies:    &KeyValueCollectionBehavior{Mode: CollectionOff},
		HTTPHeaders: &HeaderCollectionConfig{
			Request:  &KeyValueCollectionBehavior{Mode: CollectionDenyList},
			Response: &KeyValueCollectionBehavior{Mode: CollectionDenyList},
		},
		QueryParams:    &KeyValueCollectionBehavior{Mode: CollectionDenyList},
		sensitiveTerms: extendedSensitiveTerms,
	})
}

// extendedSensitiveTerms are additional privacy terms that cover
// user-identifying data such as IP forwarding headers and user IDs. Used for
// backwards compatibility with SendDefaultPII=false.
var extendedSensitiveTerms = []string{
	"forwarded",
	"-ip",
	"remote-",
	"via",
	"-user",
}
