package sentry

import (
	"encoding/json"
	"net/url"
	"strings"
)

// defaultSensitiveTerms is the canonical list of case-insensitive,
// partial-match terms used for scrubbing.
//
// See https://develop.sentry.dev/sdk/foundations/client/data-collection/#sensitive-denylist
var defaultSensitiveTerms = []string{
	"auth",
	"bearer",
	"credentials",
	"csrf",
	"identity",
	"jwt",
	"key",
	"passwd",
	"password",
	"pwd",
	"saml",
	"secret",
	"session",
	"sid",
	"sso",
	"token",
	"xsrf",
}

// filteredValue is the replacement for sensitive values.
const filteredValue = "[Filtered]"

// filterKeyValues applies a KeyValueCollectionBehavior to a map of key-value
// pairs. Keys are always preserved and values are replaced with "[Filtered]".
//
// Returns nil when the mode is CollectionOff.
func (dc DataCollection) filterKeyValues(data map[string]string, behavior *KeyValueCollectionBehavior) map[string]string {
	if behavior == nil {
		behavior = &KeyValueCollectionBehavior{}
	}
	if behavior.Mode == CollectionOff {
		return nil
	}
	result := make(map[string]string, len(data))
	for k, v := range data {
		if dc.shouldFilterKey(k, behavior) {
			result[k] = filteredValue
		} else {
			result[k] = v
		}
	}
	return result
}

// FilterRequestHeaders applies the configured request-header collection behavior.
func (dc DataCollection) FilterRequestHeaders(headers map[string]string) map[string]string {
	var behavior *KeyValueCollectionBehavior
	if dc.HTTPHeaders != nil {
		behavior = dc.HTTPHeaders.Request
	}
	return dc.filterKeyValues(headers, behavior)
}

// FilterResponseHeaders applies the configured response-header collection behavior.
func (dc DataCollection) FilterResponseHeaders(headers map[string]string) map[string]string {
	var behavior *KeyValueCollectionBehavior
	if dc.HTTPHeaders != nil {
		behavior = dc.HTTPHeaders.Response
	}
	return dc.filterKeyValues(headers, behavior)
}

// CollectHTTPBody reports whether the given body type should be collected.
func (dc *DataCollection) CollectHTTPBody(bt BodyType) bool {
	if dc == nil || dc.HTTPBodies == nil {
		return true
	}
	for _, t := range dc.HTTPBodies {
		if t == bt {
			return true
		}
	}
	return false
}

// CollectCookies reports whether cookies should be collected.
func (dc *DataCollection) CollectCookies() bool {
	return dc == nil || dc.Cookies == nil || dc.Cookies.Mode != CollectionOff
}

// CollectQueryParams reports whether query parameters should be collected.
func (dc DataCollection) CollectQueryParams() bool {
	return dc.QueryParams == nil || dc.QueryParams.Mode != CollectionOff
}

// FilterQueryString applies the configured query-parameter collection behavior.
func (dc DataCollection) FilterQueryString(rawQuery string) string {
	if rawQuery == "" {
		return ""
	}
	values, _ := url.ParseQuery(rawQuery)
	return dc.filterURLValues(values, dc.QueryParams)
}

// FilterURL applies query-parameter filtering to u and returns its redacted string form.
func (dc DataCollection) FilterURL(u *url.URL) string {
	if u == nil {
		return ""
	}
	filtered := *u
	filtered.RawQuery = dc.FilterQueryString(u.RawQuery)
	return filtered.Redacted()
}

// FilterCookies applies the configured cookie collection behavior.
func (dc DataCollection) FilterCookies(values []string) string {
	parsed := parseKeyValueStrings(values, ';')
	if len(parsed) == 0 {
		return ""
	}
	filtered := dc.filterKeyValues(parsed, dc.Cookies)
	if len(filtered) == 0 {
		return ""
	}

	parts := make([]string, 0, len(filtered))
	for key, value := range filtered {
		parts = append(parts, key+"="+value)
	}
	return strings.Join(parts, "; ")
}

// FilterSetCookies applies the configured cookie collection behavior to
// Set-Cookie header values.
func (dc DataCollection) FilterSetCookies(values []string) string {
	filtered := make([]string, 0, len(values))
	for _, value := range values {
		if cookie := dc.filterSetCookie(value); cookie != "" {
			filtered = append(filtered, cookie)
		}
	}
	return strings.Join(filtered, ", ")
}

func (dc DataCollection) filterSetCookie(setCookie string) string {
	if !dc.CollectCookies() {
		return ""
	}
	parts := strings.Split(setCookie, ";")
	name, value, ok := strings.Cut(parts[0], "=")
	name = strings.TrimSpace(name)
	if !ok || name == "" {
		return ""
	}
	if dc.shouldFilterKey(name, dc.Cookies) {
		value = filteredValue
	}
	parts[0] = name + "=" + value

	for i := 1; i < len(parts); i++ {
		attribute, _, ok := strings.Cut(parts[i], "=")
		if !ok {
			continue
		}
		if name := strings.TrimSpace(attribute); name != "" && dc.shouldFilterKey(name, dc.Cookies) {
			parts[i] = attribute + "=" + filteredValue
		}
	}

	return strings.Join(parts, ";")
}

// FilterHTTPBody applies sensitive-key filtering to parseable HTTP body data.
// Opaque raw bodies are replaced entirely.
func (dc DataCollection) FilterHTTPBody(body []byte, contentType string) string {
	if len(body) == 0 {
		return ""
	}

	if strings.Contains(strings.ToLower(contentType), "application/json") || looksLikeJSON(body) {
		var value any
		if err := json.Unmarshal(body, &value); err == nil {
			filteredJSON := dc.filterJSONValue(value, nil)
			filtered, err := json.Marshal(filteredJSON)
			if err == nil {
				return string(filtered)
			}
		}
	}

	if strings.Contains(strings.ToLower(contentType), "application/x-www-form-urlencoded") {
		if values, err := url.ParseQuery(string(body)); err == nil {
			return dc.filterURLValues(values, nil)
		}
	}

	return filteredValue
}

func looksLikeJSON(body []byte) bool {
	trimmed := strings.TrimSpace(string(body))
	return strings.HasPrefix(trimmed, "{") || strings.HasPrefix(trimmed, "[")
}

func (dc DataCollection) filterURLValues(values url.Values, behavior *KeyValueCollectionBehavior) string {
	if behavior == nil {
		behavior = &KeyValueCollectionBehavior{}
	}
	if behavior.Mode == CollectionOff {
		return ""
	}
	for key := range values {
		if dc.shouldFilterKey(key, behavior) {
			values.Set(key, filteredValue)
		}
	}
	return strings.ReplaceAll(values.Encode(), url.QueryEscape(filteredValue), filteredValue)
}

func (dc DataCollection) filterJSONValue(value any, behavior *KeyValueCollectionBehavior) any {
	return dc.filterJSONNode(value, behavior, false)
}

// filterJSONNode recursively filters a decoded JSON value.
func (dc DataCollection) filterJSONNode(value any, behavior *KeyValueCollectionBehavior, keyed bool) any {
	if behavior != nil && behavior.Mode == CollectionOff {
		return nil
	}

	switch value := value.(type) {
	case map[string]any:
		filtered := make(map[string]any, len(value))
		for key, child := range value {
			if dc.shouldFilterKey(key, behavior) {
				filtered[key] = filteredValue
			} else {
				filtered[key] = dc.filterJSONNode(child, behavior, true)
			}
		}
		return filtered
	case []any:
		filtered := make([]any, len(value))
		for i, child := range value {
			filtered[i] = dc.filterJSONNode(child, behavior, keyed)
		}
		return filtered
	default:
		if !keyed {
			return filteredValue
		}
		return value
	}
}

// shouldFilterKey reports whether a key's value should be redacted under the
// given behavior. It combines the built-in sensitive terms with the behavior's
// user-provided terms.
func (dc DataCollection) shouldFilterKey(key string, behavior *KeyValueCollectionBehavior) bool {
	if behavior == nil {
		behavior = &KeyValueCollectionBehavior{}
	}

	sensitive := matchesDenyTerms(key, defaultSensitiveTerms) || matchesDenyTerms(key, dc.sensitiveTerms)

	switch behavior.Mode {
	case CollectionOff:
		return true
	case CollectionAllowList:
		return sensitive || !matchesDenyTerms(key, behavior.Terms)
	default:
		return sensitive || matchesDenyTerms(key, behavior.Terms)
	}
}

// matchesDenyTerms reports whether the key (case-insensitive) contains any of
// the given terms as a substring.
func matchesDenyTerms(key string, terms []string) bool {
	lower := strings.ToLower(key)
	for _, term := range terms {
		if strings.Contains(lower, strings.ToLower(term)) {
			return true
		}
	}
	return false
}

// parseKeyValueStrings splits strings like "a=1; b=2" into a map.
// Malformed parts without '=' and parts with empty keys are skipped.
func parseKeyValueStrings(values []string, separator rune) map[string]string {
	result := make(map[string]string)
	for _, value := range values {
		for _, part := range strings.Split(value, string(separator)) {
			part = strings.TrimSpace(part)
			if part == "" {
				continue
			}
			key, value, ok := strings.Cut(part, "=")
			if !ok || strings.TrimSpace(key) == "" {
				continue
			}
			result[key] = value
		}
	}
	return result
}
