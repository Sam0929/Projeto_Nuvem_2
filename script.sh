#!/bin/bash
# Exemplo de script para rodar dentro do ambiente isolado

echo "Iniciando teste no ambiente $(hostname)"
echo "PID do processo: $$"
echo "Início: $(date)"

# Teste de carga de CPU por 40 segundos
echo "Executando stress de CPU..."
stress -c 2 --timeout 40

# Teste de escrita em arquivo temporário
echo "Criando arquivo de teste..."
echo "Arquivo criado em $(date)" > /tmp/arquivo_teste.txt
ls -lh /tmp/arquivo_teste.txt

# Sleep apenas para manter o processo ativo
echo "Entrando em modo sleep por 20 segundos..."
sleep 20

echo "Encerrando script em $(date)"
echo "Teste concluído com sucesso!"