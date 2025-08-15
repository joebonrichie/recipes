#!/usr/bin/env bash
#
# SPDX-license: MPL-2.0
# SPDX-copyright: © AerynOS Developers 2025
#
# Remove outdated repos from installed systems
# Intended to be used as a trigger or systemd one-shot service script
# Depends on the 'moss' and 'yq' packages
#

add-unstable-repo () {
    moss repo add unstable https://cdn.aerynos.dev/unstable/x86_64/stone.index -p 0 -c "unstable package stream"
    moss repo enable unstable
}

add-disabled-volatile-repo () {
    moss repo add volatile https://build.aerynos.dev/volatile/x86_64/stone.index -p 10 -c "volatile package stream (for packagers and testing only)"
    moss repo disable volatile
}

delete-repo () {
    [[ -z "$1" ]] && return 0
    local repo="$1"

    moss repo remove "${repo}"
}

handle-repo () {
    [[ -z "$1" ]] && return 0
    local repo="$1"

    local repo_name="$(yq '. | keys[0]' < "${repo}")"
    local repo_uri="$(yq '.*.uri' < "${repo}")"
    echo ${repo}: ${repo_name} = ${repo_uri}

    # We want to get rid of outdated repos
    if [[ ${repo_uri} =~ dev.serpentos.com  ]] || \
       [[ ${repo_uri} =~ packages.aerynos.com ]] || \
       [[ "${repo_uri}" == "https://aerynos.dev/volatile/x86_64/stone.index" ]]
    then
        echo deleting ${repo_name} ...
        delete-repo "${repo_name}"
        # If the repo was outdated, we need to add the corresponding current repo
        if [[ "${repo_name}" == "unstable" ]]
        then
            # This can be added multiple times with no issue
            # -- it will simply override the existing repo definition
            echo adding current unstable repo ...
            add-unstable-repo
        fi
        if [[ "${repo_name}" == "volatile" ]]
        then
            # Tame as above, but note that this repo will be disabled by default
            # because we don't want users to inadvertently end up on the package
            # stream where the infra lands packages for testing etc.
            echo adding disabled volatile repo ...
            add-disabled-volatile-repo
        fi
    fi
}


main () {
    local arg="$1"
    # if these dirs exist, there's a high probability that this
    # system is one controlled by moss
    if [[ -d /.moss/ && -d /etc/moss/repo.d && -x /usr/bin/moss ]]
    then
        for repo in /etc/moss/repo.d/*.yaml
        do
            handle-repo "${repo}" || : # don't die on errors
        done
    fi
}

test () {
    echo -e "\nTest 1:\n"
    moss repo add volatile https://dev.serpentos.com/volatile/x86_64/stone.index -p0
    moss repo add unstable https://dev.serpentos.com/volatile/x86_64/stone.index -p10
    moss repo list

    main
    moss repo list
    echo -e "\nTest 1 done.\n"

    
    echo -e "\nTest 2:\n"
    moss repo add volatile https://dev.serpentos.com/volatile/x86_64/stone.index -p0
    moss repo add unstable https://packages.aerynos.com/volatile/x86_64/stone.index -p10
    moss repo list

    main
    moss repo list
    echo -e "\nTest 2 done.\n"

    echo -e "\nTest 3:\n"
    moss repo add volatile https://dev.serpentos.com/volatile/x86_64/stone.index -p0
    moss repo add unstable https://aerynos.dev/volatile/x86_64/stone.index -p10
    moss repo list

    main
    moss repo list
    echo -e "\nTest 3 done.\n"
}

echo before:
moss repo list

ARG="$1"
if [[ -n "${ARG}" && "${ARG}" == "test" ]]
then
   test
elif [[ -n "${ARG}" ]]
then
    echo "valid args are 'test' (to run tests) or no args (execute normally)"
else
    main
fi

echo after:
moss repo list

unset ARG
