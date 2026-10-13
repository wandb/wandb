package provenance

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
)

type Redactor struct{ key []byte }

func NewRedactor(key []byte) *Redactor { return &Redactor{key: append([]byte(nil), key...)} }

func (r *Redactor) Pseudonym(kind, raw string) (string, bool) {
	if len(r.key) == 0 || raw == "" {
		return "", false
	}
	mac := hmac.New(sha256.New, r.key)
	_, _ = mac.Write([]byte(kind + "\x00" + raw))
	return kind + "_" + hex.EncodeToString(mac.Sum(nil)[:12]), true
}
