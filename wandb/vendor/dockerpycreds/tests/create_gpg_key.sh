#!/usr/bin/sh
haveged
gpg --batch --gen-key <<-EOF
%echo Generating a standard key
Key-Type: DSA
Key-Length: 1024
Subkey-Type: ELG-E
Subkey-Length: 1024
Name-Real: Sakuya Izayoi
Name-Email: sakuya@gensokyo.jp
Expire-Date: 0
EOF