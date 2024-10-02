This directory contains SSL certs/keys that our tests use when exercising SSL functionality.

Here's how they were generated:

```bash
openssl req -x509 \
    -newkey rsa:2048 \
    -keyout localhost.key \
    -out localhost.crt \
    -days 9999 \
    -nodes \
    -subj "/C=US/ST=CA/L=San Francisco/O=Weights & Biases/OU=IT/CN=localhost" \
    -addext 'subjectAltName=IP:127.0.0.1'

mv localhost.crt $(openssl x509 -hash -noout -in localhost.crt).0
```

I don't really understand all that, but here are the most valuable things I learned in the process of coming up with ^that process:

- "Why do we need the `mv ...certificate hash???...`?

    TLDR: `requests` provides a way for the user to specify a directory full of trusted certificates for SSL to use. Each certificate file in that directory must be named based on its hash, or else OpenSSL (which requests uses under the hood) won't be able to find it. (I'd prefer to `ln -s localhost.cert ${HASH}.0` instead, but IME the symlink doesn't work robustly on Windows.)

    Details:

    - `requests` allows you to use an env var to point to a directory full of certificates. (Or a single certificate file; but the symlink is only relevant for directories.)
        - Docs: [`REQUESTS_CA_BUNDLE`](https://requests.readthedocs.io/en/latest/user/advanced/#ssl-cert-verification)
    - ...and [this Stack Overflow question](https://stackoverflow.com/questions/30059107/get-x509-certificate-hash-with-openssl-library) contains the incantation for getting that certificate hash.

    - `requests`' docs don't specify the required directory structure, but it uses urllib3 under the hood and [urllib3's docs](https://urllib3.readthedocs.io/en/stable/reference/urllib3.util.html#urllib3.util.ssl_wrap_socket) likewise indicate that the directory should be "as supported by OpenSSL’s -CApath flag".

- "Why do we need the `-addext` option to openssl?"

    `requests` requires that the SSL cert be signed for `localhost`. The `-addext` flag makes the cert valid for both `localhost` and `127.0.0.1`
