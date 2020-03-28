def write_key(settings, key):
    if not key:
        return

    # Normal API keys are 40-character hex strings. Onprem API keys have a
    # variable-length prefix, a dash, then the 40-char string.
    prefix, suffix = key.split('-') if '-' in key else ('', key)

    if len(suffix) == 40:
        write_netrc(settings.base_url, "user", key)
        return
    raise ValueError("API key must be 40 characters long, yours was %s" % len(key))

