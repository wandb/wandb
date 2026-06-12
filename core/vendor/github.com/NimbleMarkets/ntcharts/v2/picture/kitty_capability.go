package picture

import (
	"fmt"
	"os"
	"sync"
	"sync/atomic"
	"time"

	tea "charm.land/bubbletea/v2"
	uv "github.com/charmbracelet/ultraviolet"
)

// KittyCapability reports whether the host terminal supports the Kitty
// graphics protocol. The state is process-wide — terminal support is a
// property of the tty, not of any individual Model — and shared by every
// picture.Model, chartpicture.Model, heatpicture.Model, and
// pictureurl.Model in the program.
type KittyCapability int8

const (
	// KittyCapabilityUnknown is the default state, before the probe has
	// completed. Toggle into Kitty is BLOCKED in this state — both
	// Unknown and Unsupported keep Kitty escapes off the wire, so a
	// non-Kitty terminal never sees garbage. Kitty terminals typically
	// resolve to Supported within a few milliseconds, after which
	// Toggle works normally.
	KittyCapabilityUnknown KittyCapability = iota

	// KittyCapabilitySupported means the terminal answered the Kitty
	// query — Kitty graphics escapes will render correctly.
	KittyCapabilitySupported

	// KittyCapabilityUnsupported means the probe timed out without a
	// response. Toggle into Kitty mode no-ops to avoid emitting Kitty
	// escapes that would print as garbage.
	KittyCapabilityUnsupported
)

// kittyProbeID is the image ID used for the Kitty support probe.
// Chosen to be far above any sensible consumer-assigned ID so it can
// never collide with real images.
const kittyProbeID = 42069101

// kittyProbeTimeout is how long QueryKittySupport waits for a response
// before concluding the terminal does not support Kitty graphics.
// Kitty-supporting terminals typically respond well under 50ms; 250ms
// is generous enough to accommodate slow ssh paths.
const kittyProbeTimeout = 250 * time.Millisecond

var (
	kittyCap          atomic.Int32 // holds KittyCapability values
	kittyEnvSignalled atomic.Bool  // recorded result of the env preflight
	kittyQueryOnce    sync.Once
)

// KittyEnvSignalled reports whether the env preflight saw a positive
// indicator (TERM=xterm-{kitty,ghostty}, KITTY_*, GHOSTTY_*, WEZTERM_*,
// recognized TERM_PROGRAM) at the time QueryKittySupport ran. Useful
// alongside KittySupported() for diagnostics: if KittySupported() ==
// Unsupported AND KittyEnvSignalled() == true, the probe ran but no
// response arrived within the timeout — likely a real terminal-side
// or transport issue. If env wasn't signalled, the probe was skipped
// to avoid emitting bytes to a terminal that may not swallow APCs.
func KittyEnvSignalled() bool { return kittyEnvSignalled.Load() }

// KittySupported reports the current process-wide Kitty graphics
// capability. Returns KittyCapabilityUnknown until the probe started by
// QueryKittySupport resolves (typically <50ms after the first Init).
func KittySupported() KittyCapability {
	return KittyCapability(kittyCap.Load())
}

// ForceKittyCapability sets the process-wide Kitty graphics capability,
// bypassing terminal probing. **Typically used in tests** — production
// code should rely on QueryKittySupport batched from Model.Init. May
// also be useful in transports where auto-detection misfires (some tmux
// passthrough setups, terminal multiplexer chains) and the application
// has out-of-band knowledge of true terminal support.
func ForceKittyCapability(c KittyCapability) {
	kittyCap.Store(int32(c))
}

// kittyProbeTickMsg fires kittyProbeTimeout after QueryKittySupport
// runs; if the capability is still Unknown when Model.Update sees this,
// it concludes Kitty is unsupported.
type kittyProbeTickMsg struct{}

// QueryKittySupport returns a Cmd that probes terminal Kitty graphics
// support. The probe runs at most once per process via sync.Once;
// subsequent calls return nil. Multiple Models can safely batch this
// from their Init — only the first emission actually queries the
// terminal.
//
// Pre-flight env check: most well-behaved terminals silently swallow
// unknown APC sequences, but some non-Kitty terminals display the
// probe bytes as visible garbage. To avoid that, the probe is only
// sent when the process environment indicates a terminal known to
// support Kitty graphics (kitty, Ghostty, WezTerm, iTerm2, or an
// explicit TERM=xterm-kitty/xterm-ghostty). Terminals without a
// positive signal resolve immediately to KittyCapabilityUnsupported
// without sending anything to the wire. False negatives — Kitty-
// capable terminals whose env vars don't propagate (some ssh paths,
// custom builds) — can opt in via ForceKittyCapability.
//
// Two messages drive resolution when a probe is sent:
//   - uv.KittyGraphicsEvent with the probe's ID arrives if the terminal
//     supports the protocol; Model.Update sets the capability to
//     KittyCapabilitySupported.
//   - kittyProbeTickMsg fires after kittyProbeTimeout; if the
//     capability is still Unknown, Model.Update sets it to
//     KittyCapabilityUnsupported.
//
// Both messages are intercepted by Model.Update — consumers that
// forward every tea.Msg to Model.Update don't need to handle them.
func QueryKittySupport() tea.Cmd {
	var cmd tea.Cmd
	kittyQueryOnce.Do(func() {
		// If capability was already set (e.g., by ForceKittyCapability
		// before any Model's Init ran), respect that and skip the probe.
		if KittySupported() != KittyCapabilityUnknown {
			return
		}
		// If the environment doesn't indicate a Kitty-aware terminal,
		// don't send any bytes — go straight to Unsupported.
		if !kittyEnvSignal() {
			kittyEnvSignalled.Store(false)
			kittyCap.CompareAndSwap(int32(KittyCapabilityUnknown), int32(KittyCapabilityUnsupported))
			return
		}
		kittyEnvSignalled.Store(true)
		cmd = tea.Batch(
			tea.Raw(buildKittyQueryAPC(kittyProbeID)),
			tea.Tick(kittyProbeTimeout, func(time.Time) tea.Msg {
				return kittyProbeTickMsg{}
			}),
		)
	})
	return cmd
}

// kittyEnvSignal reports whether the process environment indicates a
// terminal known to support the Kitty graphics protocol. Used as the
// pre-flight gate by QueryKittySupport so probes don't go to terminals
// that may show the probe bytes as garbage.
//
// Recognized signals:
//   - KITTY_WINDOW_ID, KITTY_INSTALLATION_DIR (kitty itself)
//   - GHOSTTY_RESOURCES_DIR (Ghostty)
//   - WEZTERM_EXECUTABLE, WEZTERM_PANE (WezTerm)
//   - TERM=xterm-kitty, TERM=xterm-ghostty (explicit terminfo entries)
//   - TERM_PROGRAM=ghostty, WezTerm, iTerm.app (well-known terminal IDs)
//
// Anything else returns false; consumers can override via
// ForceKittyCapability if they have out-of-band knowledge.
func kittyEnvSignal() bool {
	if os.Getenv("KITTY_WINDOW_ID") != "" || os.Getenv("KITTY_INSTALLATION_DIR") != "" {
		return true
	}
	if os.Getenv("GHOSTTY_RESOURCES_DIR") != "" {
		return true
	}
	if os.Getenv("WEZTERM_EXECUTABLE") != "" || os.Getenv("WEZTERM_PANE") != "" {
		return true
	}
	switch os.Getenv("TERM") {
	case "xterm-kitty", "xterm-ghostty":
		return true
	}
	switch os.Getenv("TERM_PROGRAM") {
	case "ghostty", "WezTerm", "kitty", "iTerm.app":
		return true
	}
	return false
}

// buildKittyQueryAPC encodes a Kitty graphics query (a=q): a tiny 1×1
// transmit whose only purpose is to elicit a response. Kitty terminals
// reply with `\e_Gi=<id>;OK\e\\`; non-Kitty terminals don't reply.
// The payload "AAAA" is base64 of three zero bytes (one RGB pixel).
func buildKittyQueryAPC(id int) string {
	return fmt.Sprintf("\x1b_Ga=q,t=d,f=24,s=1,v=1,i=%d;AAAA\x1b\\", id)
}

// recordKittyResponse handles a uv.KittyGraphicsEvent. Any response
// carrying our probe's image ID proves the terminal speaks the protocol
// (even an error response — only a Kitty-aware terminal would have
// produced it).
//
// A real response is authoritative and overrides the timeout's
// pessimistic Unsupported conclusion: bubbletea's startup can deliver
// the kittyProbeTickMsg before draining the input event queue, so the
// timeout sometimes fires first even though the terminal responded
// immediately. Two CompareAndSwaps cover both starting states
// (Unknown after probe-but-no-tick, Unsupported after tick-but-late-
// response) without overriding a Forced(Supported) that's already set.
func recordKittyResponse(ev uv.KittyGraphicsEvent) {
	if ev.Options.ID != kittyProbeID {
		return
	}
	if !kittyCap.CompareAndSwap(int32(KittyCapabilityUnknown), int32(KittyCapabilitySupported)) {
		kittyCap.CompareAndSwap(int32(KittyCapabilityUnsupported), int32(KittyCapabilitySupported))
	}
}

// recordKittyTimeout marks Kitty unsupported if the probe window has
// elapsed without a response. Idempotent and a no-op if the capability
// was already resolved (by an earlier response or by ForceKittyCapability).
func recordKittyTimeout() {
	kittyCap.CompareAndSwap(int32(KittyCapabilityUnknown), int32(KittyCapabilityUnsupported))
}
