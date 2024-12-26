default: (_build build_file)

set dotenv-load
set quiet
# respect variables set in .env file next to the present justfile
boulder := env_var_or_default('BOULDER', 'boulder')
boulder_args := env_var_or_default('BOULDER_ARGS', '')
boulder_profile := env_var_or_default('BOULDER_PROFILE', 'local-x86_64')
build_file := join(invocation_directory(), "stone.yaml")
local_repo := env_var_or_default('LOCAL_REPO', '${HOME}/.cache/local_repo/x86_64')

# Build the stone.yaml recipe using boulder
_build target:
    cd {{ invocation_directory() }}; {{boulder}} build {{boulder_args}} -u {{ if path_exists(target) == "true" { target } else { error("Missing stone.yaml file") } }} -p {{ boulder_profile }}

# Build stone.yaml from the current directory
build: (_build build_file)

# Chroot into target from stone.yaml recipe with boulder
_chroot target:
    cd {{ invocation_directory() }}; {{boulder}} {{boulder_args}} chroot {{ if path_exists(target) == "true" { target } else { error("Missing stone.yaml file") } }}

_bump target:
    cd {{ invocation_directory() }}; {{boulder}} {{boulder_args}} recipe bump
bump: (_bump build_file)

# Chroot into pkg from the current directory
chroot: (_chroot build_file)

# Clean up .stone files
_clean target:
    cd {{ invocation_directory() }}; rm -v *.stone || echo "No .stone file(s) found"

# Clean *.stone artefacts from the current directory
clean: (_clean build_file)

# Init git hooks
_init target:
    ln -sfv ../../tools/prepare-commit-msg.py $(git rev-parse --git-path hooks)/prepare-commit-msg
    ln -sfv ../../tools/pre-commit.py $(git rev-parse --git-path hooks)/pre-commit
init: (_init build_file)

[confirm('This will delete ALL .stones in your local repo -- continue?')]
_clean-local:
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ -d {{local_repo}} ]]; then
       rm -f {{local_repo}}/*.stone
    fi

# clean the LOCAL_REPO dir of .stones and reindex it
clean-local: ls-local && index-local
  just _clean-local

# create LOCAL_REPO dir if it doesn't exist
create-local:
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ ! -d {{local_repo}} ]]; then
       mkdir -pv {{local_repo}}
    fi

# index .stones in LOCAL_REPO (create it if it doesn't exist)
index-local: create-local
    cd {{ invocation_directory() }} && moss index {{local_repo}}

# list .stones in LOCAL_REPO (create it if it doesn't exist)
ls-local: create-local
    cd {{ invocation_directory() }} && ls -AFcghlot {{local_repo}}

# move .stones to LOCAL_REPO (create if it doesn't exist) and reindex it
mv-local: create-local
    cd {{ invocation_directory() }} && mv -v *.stone {{local_repo}}/ && moss index {{local_repo}}

# Check for upstream updates
updates:
    cd {{ invocation_directory() }} && ent check updates
