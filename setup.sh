#!/bin/bash

# --- Carregar Variáveis de Ambiente ---
ENV_FILE="/var/www/html/.env"
if [ -f "$ENV_FILE" ]; then
    echo ">>> Carregando configurações do arquivo .env..."
    export $(grep -v '^#' "$ENV_FILE" | sed 's/\r$//' | awk '/=/ {print $1}')
else
    echo ">>> ATENÇÃO: Arquivo .env não encontrado. Usando valores padrão."
    DB_HOST="localhost"
    DB_NAME="projeto_so"
    DB_USER="webuser"
    DB_PASS="password123"
fi

# --- Atualizar Pacotes ---
echo ">>> Atualizando lista de pacotes..."
sudo apt-get update -y

# --- Instalar Software Essencial ---
echo ">>> Instalando Apache, MySQL, Python3, Pip e Git..."
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    apache2 \
    mysql-server \
    python3 \
    python3-pip \
    git

# --- Instalar bibliotecas Python ---
echo ">>> Instalando Flask, MySQL Connector e python-dotenv para Python..."
sudo pip3 install Flask mysql-connector-python python-dotenv

# --- Configurar Banco de Dados MySQL ---
echo ">>> Configurando o banco de dados MySQL com as variáveis de ambiente..."
sudo mysql -e "CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\`;"
sudo mysql -e "CREATE USER IF NOT EXISTS '${DB_USER}'@'${DB_HOST}' IDENTIFIED BY '${DB_PASS}';"
sudo mysql -e "GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'${DB_HOST}';"
sudo mysql -e "FLUSH PRIVILEGES;"

# --- Criar a tabela de ambientes ---
echo ">>> Criando a tabela 'ambientes' no banco de dados..."
sudo mysql -u root ${DB_NAME} <<EOF
CREATE TABLE IF NOT EXISTS ambientes (
  id INT AUTO_INCREMENT PRIMARY KEY,
  nome VARCHAR(255) NOT NULL,
  comando TEXT NOT NULL,
  cpu_limit VARCHAR(50),
  mem_limit VARCHAR(50),
  status ENUM('CRIADO', 'EXECUTANDO', 'CONCLUIDO', 'ERRO') DEFAULT 'CRIADO',
  output_file VARCHAR(255),
  pid INT NULL,
  data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
EOF

# --- Configurar permissões ---
echo ">>> Configurando permissões sudo para o usuário vagrant (cgroups v2)..."
echo "vagrant ALL=(ALL) NOPASSWD: /bin/kill, /usr/bin/unshare, /bin/mkdir /sys/fs/cgroup/*, /bin/rmdir /sys/fs/cgroup/*, /usr/bin/tee /sys/fs/cgroup/*/*, /bin/bash /tmp/launcher_*.sh" | sudo tee /etc/sudoers.d/vagrant-cgroups-v2

# --- Finalização ---
echo ">>> Provisionamento concluído com sucesso!"
echo ">>> Para iniciar a aplicação, acesse a VM com 'vagrant ssh' e execute:"
echo ">>> cd /var/www/html"
echo ">>> flask run --host=0.0.0.0"