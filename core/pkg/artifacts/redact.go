package artifacts

import (
	"regexp"
	"strings"
)

// urlInText matches an http(s) URL embedded in error text. It stops at
// whitespace and quotes, which is how Go's *url.Error delimits the URL.
var urlInText = regexp.MustCompile(`https?://[^\s"'<>]+`)

// redactURLs replaces the query parameter values of every URL in text with
// "REDACTED". Upload URLs are signed and Go's request errors include the full
// URL, so error text can carry parameters such as X-Amz-Signature.
func redactURLs(text string) string {
	return urlInText.ReplaceAllStringFunc(text, func(link string) string {
		base, query, hasQuery := strings.Cut(link, "?")
		if !hasQuery {
			return link
		}
		params := strings.Split(query, "&")
		for i, param := range params {
			key, _, _ := strings.Cut(param, "=")
			params[i] = key + "=REDACTED"
		}
		return base + "?" + strings.Join(params, "&")
	})
}
