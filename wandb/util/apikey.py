# -*- coding: utf-8 -*-
"""
apikey util.
"""

import os
import textwrap

import wandb
import stat


def write_netrc(host, entity, key):
    """Add our host and key to .netrc"""
    key_prefix, key_suffix = key.split('-', 1) if '-' in key else ('', key)
    if len(key_suffix) != 40:
        wandb.termlog('API-key must be exactly 40 characters long: {} ({} chars)'.format(key_suffix, len(key_suffix)))
        return None
    try:
        normalized_host = host.split("/")[-1].split(":")[0]
        wandb.termlog("Appending key for {} to your netrc file: {}".format(
            normalized_host, os.path.expanduser('~/.netrc')))
        machine_line = 'machine %s' % normalized_host
        path = os.path.expanduser('~/.netrc')
        orig_lines = None
        try:
            with open(path) as f:
                orig_lines = f.read().strip().split('\n')
        except (IOError, OSError) as e:
            pass
        with open(path, 'w') as f:
            if orig_lines:
                # delete this machine from the file if it's already there.
                skip = 0
                for line in orig_lines:
                    if machine_line in line:
                        skip = 2
                    elif skip:
                        skip -= 1
                    else:
                        f.write('%s\n' % line)
            f.write(textwrap.dedent("""\
            machine {host}
              login {entity}
              password {key}
            """).format(host=normalized_host, entity=entity, key=key))
        os.chmod(os.path.expanduser('~/.netrc'),
                 stat.S_IRUSR | stat.S_IWUSR)
        return True
    except IOError as e:
        wandb.termerror("Unable to read ~/.netrc")
        return None


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

