//! Port of `core/internal/leet/remote.go` (`ParseRemoteURL`), plus the
//! `RemoteRunParams` struct that Go declares in `run.go` (homed here so the
//! data layer owns the type it produces).
//!
//! Go parses with `net/url`. This module reimplements, std-only, the subset
//! of `url.Parse` that `ParseRemoteURL` observes: fragment/query stripping,
//! scheme extraction, authority (userinfo/host/port) parsing, and path
//! percent-unescaping — including the error CONDITIONS of each stage. Error
//! text mirrors Go closely but is not guaranteed byte-identical (per the
//! porting contract only the triggering conditions must match).
//!
//! The expected values in the `net_url_parity_*` tests below were generated
//! by running the Go implementation (`net/url` + `ParseRemoteURL`) on the
//! same inputs.

/// RemoteRunParams identifies a run stored on a W&B server.
///
/// PARITY: Go declares this struct in `run.go`; it is defined here because
/// `leet-data` is the crate that produces it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RemoteRunParams {
    /// BaseURL is the W&B API base URL (e.g. https://api.wandb.ai).
    pub base_url: String,
    pub entity: String,
    pub project: String,
    pub run_id: String,
}

/// A `net/url`-style parse error; the message mirrors Go's inner error text.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("{0}")]
pub struct UrlError(pub(crate) String);

/// Errors returned by [`parse_remote_url`].
///
/// One variant per `return nil, fmt.Errorf(...)` site in Go's
/// `ParseRemoteURL`.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum ParseRemoteUrlError {
    /// Go: `fmt.Errorf("invalid remote URL %q: %w", s, err)` wrapping the
    /// `*url.Error` (whose text is `parse "<url>": <msg>`).
    #[error("invalid remote URL {url:?}: parse {url:?}: {source}")]
    InvalidUrl { url: String, source: UrlError },
    /// Go: `remote URL must use http(s), got %q`.
    #[error("remote URL must use http(s), got {0:?}")]
    WrongScheme(String),
    /// Go: `remote URL is missing host: %q`.
    #[error("remote URL is missing host: {0:?}")]
    MissingHost(String),
    /// Go: `remote URL must be https://<host>/<entity>/<project>/runs/<run-id>, got %q`.
    #[error("remote URL must be https://<host>/<entity>/<project>/runs/<run-id>, got {0:?}")]
    BadShape(String),
}

/// ParseRemoteURL parses a W&B run URL into RemoteRunParams.
///
/// Accepted shapes:
///
/// ```text
/// https://<host>/<entity>/<project>/<run-id>
/// https://<host>/<entity>/<project>/runs/<run-id>
/// ```
///
/// The host is used as-is; canonicalization (e.g. wandb.ai -> api.wandb.ai)
/// is the launcher's responsibility.
pub fn parse_remote_url(s: &str) -> Result<RemoteRunParams, ParseRemoteUrlError> {
    let u = url_parse(s).map_err(|source| ParseRemoteUrlError::InvalidUrl {
        url: s.to_string(),
        source,
    })?;
    if u.scheme != "http" && u.scheme != "https" {
        return Err(ParseRemoteUrlError::WrongScheme(s.to_string()));
    }
    if u.host.is_empty() {
        return Err(ParseRemoteUrlError::MissingHost(s.to_string()));
    }

    // Go: strings.Split(strings.Trim(u.Path, "/"), "/").
    // PARITY: u.Path is the percent-DECODED path (an escaped %2F splits like
    // a literal slash), exactly as in Go.
    let mut parts: Vec<&str> = u.path.trim_matches('/').split('/').collect();
    if parts.len() == 4 && parts[2] == "runs" {
        parts = vec![parts[0], parts[1], parts[3]];
    }
    if parts.len() != 3 || parts[0].is_empty() || parts[1].is_empty() || parts[2].is_empty() {
        return Err(ParseRemoteUrlError::BadShape(s.to_string()));
    }

    Ok(RemoteRunParams {
        base_url: format!("{}://{}", u.scheme, u.host),
        entity: parts[0].to_string(),
        project: parts[1].to_string(),
        run_id: parts[2].to_string(),
    })
}

// --- Minimal std-only replica of Go net/url parsing (the subset
// --- ParseRemoteURL observes). Structure follows net/url's url.go.

/// The fields of Go's `url.URL` that `ParseRemoteURL` reads.
struct Url {
    scheme: String,
    /// Decoded host, including any `:port` (userinfo is stripped).
    host: String,
    /// Decoded path (Go's `u.Path`).
    path: String,
}

/// Percent-encoding contexts (Go net/url `encoding`); only the modes this
/// subset needs.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Encoding {
    Path,
    Host,
    Zone,
    UserPassword,
    Fragment,
}

/// Go `url.Parse`: cut off `#fragment`, parse the rest, then validate the
/// fragment's escapes (`setFragment` unescapes and can error).
fn url_parse(raw_url: &str) -> Result<Url, UrlError> {
    // strings.Cut(rawURL, "#")
    let (rest, frag) = match raw_url.find('#') {
        Some(i) => (&raw_url[..i], &raw_url[i + 1..]),
        None => (raw_url, ""),
    };
    let url = parse_inner(rest)?;
    if !frag.is_empty() {
        unescape(frag, Encoding::Fragment)?;
    }
    Ok(url)
}

/// Go net/url `parse(rawURL, viaRequest=false)`, minus fields
/// `ParseRemoteURL` never reads (Opaque, User, RawQuery, ForceQuery,
/// OmitHost, RawPath).
fn parse_inner(raw_url: &str) -> Result<Url, UrlError> {
    if string_contains_ctl_byte(raw_url) {
        return Err(UrlError(
            "net/url: invalid control character in URL".to_string(),
        ));
    }
    // PARITY: Go special-cases rawURL == "*" (u.Path = "*"); the generic path
    // below yields the same observable result for ParseRemoteURL (empty
    // scheme -> scheme error), so it is not replicated.

    // Split off possible leading "http:", "mailto:", etc.
    let (scheme, rest) = get_scheme(raw_url)?;
    let scheme = scheme.to_ascii_lowercase();

    // Split off ?query. Go's ForceQuery special case (lone trailing '?')
    // leaves the same `rest`, so a plain cut at the first '?' is equivalent.
    // RawQuery is kept un-decoded in Go and thus never errors.
    let rest = match rest.find('?') {
        Some(i) => &rest[..i],
        None => rest,
    };

    if !rest.starts_with('/') {
        if !scheme.is_empty() {
            // We consider rootless paths per RFC 3986 as opaque (u.Opaque);
            // Host and Path stay empty.
            return Ok(Url {
                scheme,
                host: String::new(),
                path: String::new(),
            });
        }
        // Avoid confusion with malformed schemes, like cache_object:foo/bar:
        // the first path segment of a relative URL cannot contain a colon.
        let segment = rest.split('/').next().unwrap_or("");
        if segment.contains(':') {
            return Err(UrlError(
                "first path segment in URL cannot contain colon".to_string(),
            ));
        }
    }

    let mut host = String::new();
    let mut rest = rest;
    if (!scheme.is_empty() || !rest.starts_with("///")) && rest.starts_with("//") {
        let mut authority = &rest[2..];
        rest = "";
        if let Some(i) = authority.find('/') {
            rest = &authority[i..];
            authority = &authority[..i];
        }
        host = parse_authority(authority)?;
    }

    // setPath: u.Path holds the percent-decoded path.
    let path = bytes_to_string(unescape(rest, Encoding::Path)?);
    Ok(Url { scheme, host, path })
}

/// Go net/url `getScheme`.
fn get_scheme(raw_url: &str) -> Result<(&str, &str), UrlError> {
    let b = raw_url.as_bytes();
    for (i, &c) in b.iter().enumerate() {
        if c.is_ascii_alphabetic() {
            // do nothing
        } else if c.is_ascii_digit() || c == b'+' || c == b'-' || c == b'.' {
            if i == 0 {
                return Ok(("", raw_url));
            }
        } else if c == b':' {
            if i == 0 {
                return Err(UrlError("missing protocol scheme".to_string()));
            }
            return Ok((&raw_url[..i], &raw_url[i + 1..]));
        } else {
            // we have encountered an invalid character,
            // so there is no valid scheme
            return Ok(("", raw_url));
        }
    }
    Ok(("", raw_url))
}

/// Go net/url `parseAuthority`, returning only the host (`ParseRemoteURL`
/// never reads u.User, but the userinfo's error conditions must hold).
fn parse_authority(authority: &str) -> Result<String, UrlError> {
    let Some(i) = authority.rfind('@') else {
        return parse_host(authority);
    };
    let host = parse_host(&authority[i + 1..])?;
    let userinfo = &authority[..i];
    if !valid_userinfo(userinfo) {
        return Err(UrlError("net/url: invalid userinfo".to_string()));
    }
    // Unescape for validation only; the decoded userinfo is unused.
    match userinfo.find(':') {
        Some(j) => {
            unescape(&userinfo[..j], Encoding::UserPassword)?;
            unescape(&userinfo[j + 1..], Encoding::UserPassword)?;
        }
        None => {
            unescape(userinfo, Encoding::UserPassword)?;
        }
    }
    Ok(host)
}

/// Go net/url `parseHost`: IP-literals in brackets (with RFC 6874 `%25`
/// zones), `:port` validation, and host unescaping.
fn parse_host(host: &str) -> Result<String, UrlError> {
    if host.starts_with('[') {
        // Parse an IP-Literal in RFC 3986 and RFC 6874.
        // E.g., "[fe80::1]", "[fe80::1%25en0]", "[fe80::1]:80".
        let Some(i) = host.rfind(']') else {
            return Err(UrlError("missing ']' in host".to_string()));
        };
        let colon_port = &host[i + 1..];
        if !valid_optional_port(colon_port) {
            return Err(UrlError(format!("invalid port {colon_port:?} after host")));
        }
        // RFC 6874: %25 introduces the zone identifier, which may use
        // %-encoding freely (Go restricts it to bytes valid in hosts).
        if let Some(zone) = host[..i].find("%25") {
            let mut out = unescape(&host[..zone], Encoding::Host)?;
            out.extend(unescape(&host[zone..i], Encoding::Zone)?);
            out.extend(unescape(&host[i..], Encoding::Host)?);
            return Ok(bytes_to_string(out));
        }
    } else if let Some(i) = host.rfind(':') {
        let colon_port = &host[i..];
        if !valid_optional_port(colon_port) {
            return Err(UrlError(format!("invalid port {colon_port:?} after host")));
        }
    }
    Ok(bytes_to_string(unescape(host, Encoding::Host)?))
}

/// Go net/url `validOptionalPort`: empty, or ':' followed by digits only.
fn valid_optional_port(port: &str) -> bool {
    if port.is_empty() {
        return true;
    }
    let b = port.as_bytes();
    if b[0] != b':' {
        return false;
    }
    b[1..].iter().all(u8::is_ascii_digit)
}

/// Go net/url `validUserinfo` (RFC 3986 userinfo charset, plus '%' and '@').
fn valid_userinfo(s: &str) -> bool {
    s.chars().all(|r| {
        r.is_ascii_alphanumeric()
            || matches!(
                r,
                '-' | '.'
                    | '_'
                    | ':'
                    | '~'
                    | '!'
                    | '$'
                    | '&'
                    | '\''
                    | '('
                    | ')'
                    | '*'
                    | '+'
                    | ','
                    | ';'
                    | '='
                    | '%'
                    | '@'
            )
    })
}

/// Go net/url `shouldEscape(c, encodeHost)` (the only mode this subset
/// queries; `encodeZone` shares the same table for the bytes checked here).
fn should_escape_host(c: u8) -> bool {
    !(c.is_ascii_alphanumeric()
        || matches!(
            c,
            // §3.2.2 Host allows sub-delims plus ':', '[', ']', '<', '>', '"'.
            b'!' | b'$'
                | b'&'
                | b'\''
                | b'('
                | b')'
                | b'*'
                | b'+'
                | b','
                | b';'
                | b'='
                | b':'
                | b'['
                | b']'
                | b'<'
                | b'>'
                | b'"'
                // §2.3 Unreserved characters (mark).
                | b'-'
                | b'_'
                | b'.'
                | b'~'
        ))
}

/// Go net/url `unescape(s, mode)`: validates `%XX` escapes (and, for
/// host/zone, the raw characters), then percent-decodes.
///
/// Returns bytes: Go strings are raw bytes and escapes may decode to
/// non-UTF-8; see [`bytes_to_string`].
fn unescape(s: &str, mode: Encoding) -> Result<Vec<u8>, UrlError> {
    let b = s.as_bytes();
    // Count %, check that they're well-formed.
    let mut n = 0usize;
    let mut i = 0usize;
    while i < b.len() {
        match b[i] {
            b'%' => {
                n += 1;
                if i + 2 >= b.len()
                    || !b[i + 1].is_ascii_hexdigit()
                    || !b[i + 2].is_ascii_hexdigit()
                {
                    let end = (i + 3).min(b.len());
                    let bad = String::from_utf8_lossy(&b[i..end]);
                    return Err(UrlError(format!("invalid URL escape {bad:?}")));
                }
                // In the host component %-encoding can only be used for
                // non-ASCII bytes, except %25 (RFC 6874).
                if mode == Encoding::Host && unhex(b[i + 1]) < 8 && &s[i..i + 3] != "%25" {
                    return Err(UrlError(format!("invalid URL escape {:?}", &s[i..i + 3])));
                }
                if mode == Encoding::Zone {
                    // Zone identifiers may escape only bytes that are valid
                    // host bytes unescaped (plus ' ' — Windows puts spaces
                    // here), except %25.
                    let v = (unhex(b[i + 1]) << 4) | unhex(b[i + 2]);
                    if &s[i..i + 3] != "%25" && v != b' ' && should_escape_host(v) {
                        return Err(UrlError(format!("invalid URL escape {:?}", &s[i..i + 3])));
                    }
                }
                i += 3;
            }
            // Go tracks '+' only for encodeQueryComponent (never used here);
            // it passes through everywhere else.
            b'+' => i += 1,
            c => {
                if matches!(mode, Encoding::Host | Encoding::Zone)
                    && c < 0x80
                    && should_escape_host(c)
                {
                    return Err(UrlError(format!(
                        "net/url: invalid character {:?} in host name",
                        (c as char).to_string()
                    )));
                }
                i += 1;
            }
        }
    }

    if n == 0 {
        return Ok(b.to_vec());
    }

    let mut t = Vec::with_capacity(b.len() - 2 * n);
    let mut i = 0usize;
    while i < b.len() {
        if b[i] == b'%' {
            t.push((unhex(b[i + 1]) << 4) | unhex(b[i + 2]));
            i += 3;
        } else {
            t.push(b[i]);
            i += 1;
        }
    }
    Ok(t)
}

/// Go net/url `unhex`.
fn unhex(c: u8) -> u8 {
    match c {
        b'0'..=b'9' => c - b'0',
        b'a'..=b'f' => c - b'a' + 10,
        b'A'..=b'F' => c - b'A' + 10,
        _ => 0,
    }
}

/// Go `stringContainsCTLByte`.
fn string_contains_ctl_byte(s: &str) -> bool {
    s.bytes().any(|b| b < b' ' || b == 0x7f)
}

/// PARITY: Go strings carry raw bytes, so percent-escapes decoding to
/// invalid UTF-8 pass through verbatim; Rust Strings must be UTF-8, so such
/// bytes become U+FFFD. No accepted URL shape is affected ('/' never occurs
/// inside a multi-byte sequence, so splitting is unchanged).
fn bytes_to_string(b: Vec<u8>) -> String {
    match String::from_utf8(b) {
        Ok(s) => s,
        Err(e) => String::from_utf8_lossy(e.as_bytes()).into_owned(),
    }
}

#[cfg(test)]
mod tests {
    use pretty_assertions::assert_eq;

    use super::*;

    fn params(base_url: &str, entity: &str, project: &str, run_id: &str) -> RemoteRunParams {
        RemoteRunParams {
            base_url: base_url.to_string(),
            entity: entity.to_string(),
            project: project.to_string(),
            run_id: run_id.to_string(),
        }
    }

    // TestParseRemoteURL
    #[test]
    fn test_parse_remote_url() {
        let tests: &[(&str, &str, RemoteRunParams)] = &[
            (
                "run URL with runs segment",
                "https://wandb.ai/my-entity/my-project/runs/abc123",
                params("https://wandb.ai", "my-entity", "my-project", "abc123"),
            ),
            (
                "run URL without runs segment",
                "https://api.wandb.ai/my-entity/my-project/abc123",
                params("https://api.wandb.ai", "my-entity", "my-project", "abc123"),
            ),
            (
                "entity named runs",
                "https://wandb.ai/runs/my-project/runs/abc123",
                params("https://wandb.ai", "runs", "my-project", "abc123"),
            ),
            (
                "trailing slash",
                "http://localhost:8080/my-entity/my-project/runs/abc123/",
                params("http://localhost:8080", "my-entity", "my-project", "abc123"),
            ),
        ];
        for (name, url, want) in tests {
            let got = parse_remote_url(url)
                .unwrap_or_else(|err| panic!("{name}: unexpected error: {err}"));
            assert_eq!(&got, want, "{name}");
        }
    }

    // TestParseRemoteURL_Errors
    #[test]
    fn test_parse_remote_url_errors() {
        let urls = [
            "ftp://wandb.ai/entity/project/runs/abc123",
            "wandb.ai/entity/project/runs/abc123",
            "https:///entity/project/runs/abc123",
            "https://wandb.ai/entity/project",
            "https://wandb.ai/entity/project/sweeps/abc123",
            "https://wandb.ai/entity/project/runs/abc123/extra",
            "https://wandb.ai",
        ];
        for url in urls {
            assert!(parse_remote_url(url).is_err(), "{url}: expected an error");
        }
    }

    // Extra (Rust-side only): success cases pinned against Go net/url +
    // ParseRemoteURL output (oracle run recorded in the module docs).
    #[test]
    fn net_url_parity_success() {
        let tests: &[(&str, RemoteRunParams)] = &[
            // Scheme is lowercased; host case is preserved.
            (
                "HTTPS://WandB.ai/e/p/runs/r",
                params("https://WandB.ai", "e", "p", "r"),
            ),
            (
                "HtTp://wandb.ai/e/p/runs/r",
                params("http://wandb.ai", "e", "p", "r"),
            ),
            // Userinfo is dropped from Host.
            (
                "https://user:pass@wandb.ai/e/p/runs/r",
                params("https://wandb.ai", "e", "p", "r"),
            ),
            (
                "https://@wandb.ai/e/p/runs/r",
                params("https://wandb.ai", "e", "p", "r"),
            ),
            // Numeric port survives in Host.
            (
                "https://wandb.ai:8080/e/p/runs/r",
                params("https://wandb.ai:8080", "e", "p", "r"),
            ),
            // Query and fragment are stripped.
            (
                "https://wandb.ai/e/p/runs/r?workspace=user",
                params("https://wandb.ai", "e", "p", "r"),
            ),
            (
                "https://wandb.ai/e/p/runs/r#panel",
                params("https://wandb.ai", "e", "p", "r"),
            ),
            // RawQuery is never unescaped, so bad escapes there are fine.
            (
                "https://wandb.ai/e/p/runs/r?%zz",
                params("https://wandb.ai", "e", "p", "r"),
            ),
            // Path percent-escapes decode into the parts.
            (
                "https://wandb.ai/my%20entity/p/runs/r",
                params("https://wandb.ai", "my entity", "p", "r"),
            ),
            // Leading double slash is eaten by strings.Trim.
            (
                "https://wandb.ai//e/p/runs/r",
                params("https://wandb.ai", "e", "p", "r"),
            ),
            // Trailing slash after a 3-segment path.
            (
                "https://wandb.ai/e/p/r/",
                params("https://wandb.ai", "e", "p", "r"),
            ),
            // Quirk: "/e/p/runs/" trims to 3 parts, so the run ID is "runs".
            (
                "https://wandb.ai/e/p/runs/",
                params("https://wandb.ai", "e", "p", "runs"),
            ),
            // Quirk: every segment named "runs".
            (
                "https://wandb.ai/runs/runs/runs/runs",
                params("https://wandb.ai", "runs", "runs", "runs"),
            ),
            // Bracketed IPv6 host with port.
            (
                "http://[::1]:8080/e/p/runs/r",
                params("http://[::1]:8080", "e", "p", "r"),
            ),
        ];
        for (url, want) in tests {
            let got = parse_remote_url(url)
                .unwrap_or_else(|err| panic!("{url}: unexpected error: {err}"));
            assert_eq!(&got, want, "{url}");
        }
    }

    // Extra (Rust-side only): error kinds pinned against Go net/url +
    // ParseRemoteURL (which Go check fires for each input).
    #[test]
    fn net_url_parity_errors() {
        #[derive(Debug, Clone, Copy)]
        enum Kind {
            InvalidUrl,
            WrongScheme,
            MissingHost,
            BadShape,
        }

        let tests: &[(&str, Kind, &str)] = &[
            // url.Parse errors (Go wraps them as "invalid remote URL ...").
            (
                "https://wandb.ai:notaport/e/p/runs/r",
                Kind::InvalidUrl,
                "invalid port",
            ),
            (
                "http://[::1/e/p/runs/r",
                Kind::InvalidUrl,
                "missing ']' in host",
            ),
            (
                "https://wan db.ai/e/p/runs/r",
                Kind::InvalidUrl,
                "invalid character in host name",
            ),
            (
                "https://wandb%2Eai/e/p/runs/r",
                Kind::InvalidUrl,
                "host cannot %-encode ASCII bytes",
            ),
            (
                "https://wandb.ai/e/p/runs/r%zz",
                Kind::InvalidUrl,
                "invalid URL escape in path",
            ),
            (
                "https://wandb.ai/e/p/runs/r#%zz",
                Kind::InvalidUrl,
                "invalid URL escape in fragment",
            ),
            (
                "https://us er@wandb.ai/e/p/runs/r",
                Kind::InvalidUrl,
                "invalid userinfo",
            ),
            (
                "://wandb.ai/e/p/runs/r",
                Kind::InvalidUrl,
                "missing protocol scheme",
            ),
            (
                "\u{1}https://wandb.ai/e/p/runs/r",
                Kind::InvalidUrl,
                "invalid control character in URL",
            ),
            // Scheme check ("wandb.ai:8080" parses as the scheme!).
            (
                "wandb.ai:8080/e/p/runs/r",
                Kind::WrongScheme,
                "colon-in-host without scheme parses as scheme wandb.ai",
            ),
            // Missing host (rootless/opaque forms).
            ("https:/e/p/runs/r", Kind::MissingHost, "path-only, no //"),
            (
                "https:e/p/runs/r",
                Kind::MissingHost,
                "opaque rootless path",
            ),
            // Shape errors.
            (
                "https://wandb.ai/e%2Fx/p/runs/r",
                Kind::BadShape,
                "decoded %2F splits the entity into two segments",
            ),
            (
                "https://wandb.ai/e//runs/r",
                Kind::BadShape,
                "empty project segment",
            ),
            (
                "https://wandb.ai/e/p//r",
                Kind::BadShape,
                "empty segment before run id",
            ),
            (
                "https://wandb.ai/e/p/RUNS/r",
                Kind::BadShape,
                "the runs segment is case-sensitive",
            ),
        ];
        for (url, want_kind, note) in tests {
            let err = parse_remote_url(url)
                .err()
                .unwrap_or_else(|| panic!("{url}: expected an error ({note})"));
            let matched = match want_kind {
                Kind::InvalidUrl => matches!(err, ParseRemoteUrlError::InvalidUrl { .. }),
                Kind::WrongScheme => matches!(err, ParseRemoteUrlError::WrongScheme(_)),
                Kind::MissingHost => matches!(err, ParseRemoteUrlError::MissingHost(_)),
                Kind::BadShape => matches!(err, ParseRemoteUrlError::BadShape(_)),
            };
            assert!(matched, "{url}: wrong error kind ({note}): {err:?}");
        }
    }
}
