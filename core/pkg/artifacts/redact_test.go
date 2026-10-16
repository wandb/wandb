package artifacts

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestRedactURLs(t *testing.T) {
	tests := []struct {
		name string
		text string
		want string
	}{
		{
			name: "no URL",
			text: "ArtifactSaver.createArtifact: forced artifact failure",
			want: "ArtifactSaver.createArtifact: forced artifact failure",
		},
		{
			name: "URL without a query",
			text: `Put "https://storage.example.com/bucket/key": connection reset`,
			want: `Put "https://storage.example.com/bucket/key": connection reset`,
		},
		{
			name: "signed URL keeps host, path and parameter names",
			text: `Put "https://s3.example.com/bucket/key?X-Amz-Credential=AKIA%2F20260101` +
				`&X-Amz-Signature=abc123": EOF`,
			want: `Put "https://s3.example.com/bucket/key?X-Amz-Credential=REDACTED` +
				`&X-Amz-Signature=REDACTED": EOF`,
		},
		{
			name: "every URL is redacted",
			text: `Put "https://h/p?sig=one": EOF; retry of https://h/p?sig=one failed`,
			want: `Put "https://h/p?sig=REDACTED": EOF; retry of https://h/p?sig=REDACTED failed`,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			assert.Equal(t, tc.want, redactURLs(tc.text))
		})
	}
}
