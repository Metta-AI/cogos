# Cogent shell prompt integration.
# Source this file in your .zshrc / .bashrc:
#   source /path/to/cogents.4/scripts/shell-prompt.sh
#
# Shows [cogent-name] in your prompt when a cogent is selected via .env.

_cogent_prompt_info() {
    local env_file
    env_file="$(git rev-parse --show-toplevel 2>/dev/null)/.env"
    [ -f "$env_file" ] || return
    local cogent
    cogent=$(grep -m1 '^COGENT=' "$env_file" 2>/dev/null | cut -d= -f2-)
    [ -n "$cogent" ] && printf '[%s] ' "$cogent"
}

if [ -n "$ZSH_VERSION" ]; then
    setopt PROMPT_SUBST
    PROMPT='$(_cogent_prompt_info)'"$PROMPT"
elif [ -n "$BASH_VERSION" ]; then
    PROMPT_COMMAND='__cogent_ps1=$(_cogent_prompt_info)'${PROMPT_COMMAND:+";$PROMPT_COMMAND"}
    PS1='${__cogent_ps1}'"$PS1"
fi
