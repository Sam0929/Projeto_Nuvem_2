#!/bin/bash

# Este script cria o processo âncora para um novo ambiente.
# Ele é desenhado para ser executado em segundo plano.

# Verifica se o argumento do ficheiro PID foi fornecido
if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <caminho_para_ficheiro_pid>"
    exit 1
fi

PID_FILE_PATH="$1"

# O 'unshare' cria os namespaces.
# O 'bash' interno escreve o seu próprio PID no ficheiro especificado.
# O 'exec sleep infinity' substitui o processo bash, mantendo o PID e os namespaces vivos.
/usr/bin/unshare --fork --pid --mount-proc --net \
    /bin/bash -c "echo \$\$ > \"$PID_FILE_PATH\"; exec sleep infinity"
