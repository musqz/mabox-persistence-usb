_mabox_persistence_usb() {
    local cur prev words cword
    _init_completion || return

    local commands="version doctor devices inspect write"
    local write_opts="--device --yes -y --force-unmount --persist-size --no-persist --force --skip-reinsert-check --no-verify --dry-run -h --help"

    case "${words[1]}" in
        devices)
            COMPREPLY=($(compgen -W "list" -- "$cur"))
            return
            ;;
        inspect)
            COMPREPLY=($(compgen -f -- "$cur"))
            return
            ;;
        write)
            if [[ "$prev" == "write" || "$cword" -eq 2 ]]; then
                COMPREPLY=($(compgen -f -- "$cur"))
            else
                COMPREPLY=($(compgen -W "$write_opts" -- "$cur"))
            fi
            return
            ;;
    esac

    if [[ "$cword" -eq 1 ]]; then
        COMPREPLY=($(compgen -W "$commands" -- "$cur"))
    fi
}
complete -F _mabox_persistence_usb mabox-persistence-usb
