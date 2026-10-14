package provenance

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"strconv"
	"strings"
)

type Redactor struct{ key []byte }

func NewRedactor(key []byte) *Redactor { return &Redactor{key: append([]byte(nil), key...)} }

func (r *Redactor) Pseudonym(kind, raw string) (string, bool) {
	if len(r.key) == 0 || raw == "" {
		return "", false
	}
	if kind == "pci" {
		raw = canonicalPCI(raw)
	}
	mac := hmac.New(sha256.New, r.key)
	_, _ = mac.Write([]byte(kind + "\x00" + raw))
	return kind + "_" + hex.EncodeToString(mac.Sum(nil)[:12]), true
}

// canonicalPCI returns the sysfs form (0000:3b:00.0) of an NVML or sysfs PCI address, or raw if it is not one.
func canonicalPCI(raw string) string {
	parts := strings.Split(strings.TrimSpace(raw), ":")
	if len(parts) == 2 {
		parts = append([]string{"0"}, parts...)
	}
	if len(parts) != 3 {
		return raw
	}
	slot, function, ok := strings.Cut(parts[2], ".")
	if !ok {
		return raw
	}
	var fields [4]uint64
	for i, field := range []struct {
		text string
		bits int
	}{{parts[0], 32}, {parts[1], 8}, {slot, 5}, {function, 3}} {
		value, err := strconv.ParseUint(field.text, 16, field.bits)
		if err != nil {
			return raw
		}
		fields[i] = value
	}
	return fmt.Sprintf("%04x:%02x:%02x.%x", fields[0], fields[1], fields[2], fields[3])
}
