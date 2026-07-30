_toolbox_completion() {
    local current previous candidates
    current="${COMP_WORDS[COMP_CWORD]}"
    previous="${COMP_WORDS[COMP_CWORD-1]}"
    case "$previous" in
        -o|--output-dir)
            COMPREPLY=($(compgen -d -- "$current"))
            return
            ;;
    esac
    candidates="-h --help --version -m --manifest -o --output-dir"
    candidates="$candidates $(toolbox --completion-script-ids 2>/dev/null)"
    COMPREPLY=($(compgen -W "$candidates" -- "$current"))
}
complete -F _toolbox_completion toolbox
