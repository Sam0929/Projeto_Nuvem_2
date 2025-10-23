#!/bin/bash
set -e

echo "Iniciando provisionamento da VM..."

# Atualiza pacotes
sudo apt-get update -y
sudo apt-get upgrade -y

echo "Instalando dependências..."
sudo apt-get install -y python3 python3-pip mysql-server util-linux systemd psmisc  # psmisc traz o pgrep
pip3 install flask mysql-connector-python psutil python-dotenv

echo "Instalando programas auxiliares..."
sudo apt-get install -y stress

# Diretório do projeto Flask
PROJECT_DIR="/home/vagrant/web-server"
cd $PROJECT_DIR

echo "Instalando dependências do projeto..."
pip install -r requirements.txt || true

echo "Configurando MySQL..."
sudo systemctl start mysql
sudo systemctl enable mysql

DB_NAME="ambientesdb"
DB_USER="flaskuser"
DB_PASS="12345"

sudo mysql -e "CREATE DATABASE IF NOT EXISTS ${DB_NAME};"
sudo mysql -e "CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASS}';"
sudo mysql -e "GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'localhost';"
sudo mysql -e "FLUSH PRIVILEGES;"

# Cria tabela ambientes (corrigida com cgroup_path)
sudo mysql -u${DB_USER} -p${DB_PASS} ${DB_NAME} <<EOF
CREATE TABLE IF NOT EXISTS ambientes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome VARCHAR(100),
    comando TEXT,
    caminho_script VARCHAR(255),
    cpu_limit FLOAT,
    mem_limit_mb INT,
    pid INT,
    cgroup_path VARCHAR(255),
    status ENUM('em_execucao','terminado','erro'),
    log_path VARCHAR(255),
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
EOF

# Cria o arquivo .env se não existir
if [ ! -f "$PROJECT_DIR/.env" ]; then
cat <<EOF > $PROJECT_DIR/.env
DB_HOST=localhost
DB_USER=${DB_USER}
DB_PASS=${DB_PASS}
DB_NAME=${DB_NAME}
EOF
fi

# Ajusta permissões e sudoers
sudo chown -R vagrant:vagrant $PROJECT_DIR
echo "vagrant ALL=(ALL) NOPASSWD: /usr/bin/unshare, /bin/bash, /bin/mkdir, /usr/bin/rmdir, /usr/bin/tee, /usr/bin/pgrep, /usr/bin/kill" | sudo tee /etc/sudoers.d/vagrant-cgroups
sudo chmod 440 /etc/sudoers.d/vagrant-cgroups

echo "Configurando Flask para iniciar automaticamente via systemd..."

# Serviço systemd
cat <<EOF | sudo tee /etc/systemd/system/flask-app.service
[Unit]
Description=Flask App
After=network.target mysql.service

[Service]
User=vagrant
WorkingDirectory=$PROJECT_DIR
Environment="FLASK_APP=app.py"
Environment="FLASK_ENV=development"
ExecStart=/usr/bin/python3 -m flask run --host=0.0.0.0 --port=5000
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable flask-app
sudo systemctl restart flask-app

echo "✅ Provisionamento concluído! Flask rodando em http://localhost:5000"
