#!/bin/bash

# Este script agora é executado inteiramente como root pela aplicação Flask.

set -e # Termina o script se algum comando falhar

if [ "$#" -lt 4 ]; then
    echo "Usage: $0 <pid_ambiente> <caminho_cgroup_programa> <ficheiro_output> <comando...>" >&2
    exit 1
fi

ENV_PID="$1"
PROG_CGROUP_PATH="$2"
OUTPUT_FILE="$3"
shift 3
USER_CMD="$@"

REAL_PID_FILE=$(mktemp)

# O nsenter corre como root e entra nos namespaces do ambiente.
# O bash interno (também root) lança o comando do utilizador e captura o seu PID real.
INNER_CMD="nohup /bin/bash -c '$USER_CMD' > \"$OUTPUT_FILE\" 2>&1 & echo \$! > \"$REAL_PID_FILE\""
/usr/bin/nsenter -t "$ENV_PID" -a -- /bin/bash -c "$INNER_CMD"

# Espera robusta pelo ficheiro de PID
REAL_PID=""
for i in {1..5}; do
    if [ -s "$REAL_PID_FILE" ]; then
        REAL_PID=$(cat "$REAL_PID_FILE")
        break
    fi
    sleep 0.2
done

rm "$REAL_PID_FILE"

if ! [[ "$REAL_PID" =~ ^[0-9]+$ ]]; then
    echo "Erro: Não foi possível obter o PID do programa lançado." >&2
    exit 1
fi
# Adiciona o PID real ao cgroup do programa
echo "$REAL_PID" > "$PROG_CGROUP_PATH/cgroup.procs"

# Devolver o PID real para a aplicação Flask
echo "$REAL_PID"


