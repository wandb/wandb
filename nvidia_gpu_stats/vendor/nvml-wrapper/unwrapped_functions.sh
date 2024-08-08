#!/bin/bash

# Writes all unwrapped function names to `unwrapped_functions.txt`. This can
# help discover functions to work on wrapping.
#
# `ripgrep` must be installed and available. `cargo install ripgrep`

all_functions=$(rg 'pub unsafe fn (\w+)' -oNr '$1' ../nvml-wrapper-sys/src/bindings.rs | sort)
readarray -t all_functions_arr <<< "$all_functions"

output=""
versioned_output=""

for name in "${all_functions_arr[@]}"
do
    if [[ $name = "new" ]]
    then
        continue
    fi

    # filter out function names that appear in the wrapper source
    if ! rg -U "lib[ \n]*\.${name}[ \n]*\." -q src/* ;
    then
        # some functions are versioned in the format {name}_v{x}
        #
        # this gets {name} only for every function name
        unversioned_name=$(echo "${name}" | cut -d "_" -f 1)

        # take this unversioned function name (does not end in _vx) and look
        # for any function with the same name in the wrapper source (may or may
        # not end in _vx).
        #
        # if we find anything here we know this function is part of a series of
        # versioned functions. Output it separately.
        if rg -U "lib[ \n]*\.${unversioned_name}(_v.)?[ \n]*\." -q src/* ;
        then
            versioned_output+="${name}"
            versioned_output+=$'\n'
        else
            output+="${name}"
            output+=$'\n'
        fi
    fi
done

# heredoc to write multi-line string to file
cat > unwrapped_functions.txt <<- EndOfMessage
$output
the following functions are part of a series of versioned functions, at least one
of which appears in the wrapper source code.

this means some version is already wrapped and the listed names are either
newer versions to be wrapped or older versions that could be wrapped behind the
legacy-functions feature.

$versioned_output
EndOfMessage
