#!/bin/bash

# --- Carregar Variáveis de Ambiente ---
ENV_FILE="/var/www/html/.env"
if [ -f "$ENV_FILE" ]; then
    export $(grep -v '^#' "$ENV_FILE" | sed 's/\r$//' | awk '/=/ {print $1}')
else
    DB_NAME="projeto_so"
    DB_USER="webuser"
    DB_PASS="password123"
fi

# --- Instalação de Pacotes ---
echo ">>> Atualizando e instalando pacotes essenciais..."
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    mysql-server \
    python3 \
    python3-pip \
    git \
    util-linux # Fornece o comando 'nsenter'

# --- Instalação de bibliotecas Python ---
echo ">>> Instalando bibliotecas Python..."
sudo pip3 install Flask mysql-connector-python python-dotenv

# --- Configuração do Banco de Dados MySQL ---
echo ">>> Configurando o banco de dados e as novas tabelas..."
sudo mysql -e "CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\`;"
sudo mysql -e "CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASS}';"
sudo mysql -e "GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'localhost';"
sudo mysql -e "FLUSH PRIVILEGES;"

# --- Criação das novas tabelas ---
echo ">>> Removendo a tabela antiga e criando as novas: 'ambientes' e 'programas'..."
sudo mysql -u root ${DB_NAME} <<EOF
DROP TABLE IF EXISTS ambientes;
DROP TABLE IF EXISTS programas;

CREATE TABLE ambientes (
  id INT AUTO_INCREMENT PRIMARY KEY,
  nome VARCHAR(255) NOT NULL UNIQUE,
  pid_bash INT NOT NULL,
  cgroup_name VARCHAR(255) NOT NULL,
  data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE programas (
  id INT AUTO_INCREMENT PRIMARY KEY,
  ambiente_id INT NOT NULL,
  nome VARCHAR(255) NOT NULL,
  comando TEXT NOT NULL,
  pid INT NOT NULL,
  cgroup_name VARCHAR(255) NOT NULL,
  status ENUM('EXECUTANDO', 'CONCLUIDO', 'ERRO') DEFAULT 'EXECUTANDO',
  data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (ambiente_id) REFERENCES ambientes(id) ON DELETE CASCADE
);
EOF

# --- Configuração de Permissões Sudo (cgroups v2) ---
echo ">>> Configurando permissões sudo para a nova arquitetura..."
# Remove permissões antigas se existirem para evitar conflitos
sudo rm -f /etc/sudoers.d/vagrant-permissions

# Adiciona as permissões necessárias para a nova lógica
# tee é usado para escrever em ficheiros de sistema (cgroup.procs)
# nsenter é usado para entrar nos namespaces de um ambiente existente
# rm é adicionado para permitir a remoção do ficheiro de PID temporário
echo "vagrant ALL=(ALL) NOPASSWD: /bin/mkdir, /bin/rmdir, /bin/rm, /usr/bin/tee, /usr/bin/nsenter, /bin/kill" | sudo tee /etc/sudoers.d/vagrant-permissions

echo ">>> Configurando permissões nos scripts..."
sudo chmod +x /var/www/html/scripts/*.sh

# --- Finalização ---
echo ">>> Provisionamento concluído com sucesso!"
echo ">>> Para iniciar a aplicação, acesse a VM com 'vagrant ssh' e execute:"
echo ">>> cd /var/www/html"
echo ">>> flask run --host=0.0.0.0"