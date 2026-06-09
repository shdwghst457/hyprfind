#!/usr/bin/env fish
# Launch HyprFind without sourcing bash-only activate scripts.
set -l root (dirname (status --current-filename))
set -l py "$root/.venv/bin/python"
if not test -x $py
    set py (which python3)
end
exec $py -m hyprfind $argv
