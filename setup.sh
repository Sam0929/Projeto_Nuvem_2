#!/bin/bash

# --- Carregar Variáveis de Ambiente ---
ENV_FILE="/var/www/html/.env"
if [ -f "$ENV_FILE" ]; then
    # O comando 'export' precisa do caminho completo, não apenas do nome da variável
    export $(grep -v '^#' "$ENV_FILE" | sed 's/\r$//' | awk '/=/ {print $1 "=" $2}')
else
    # Variáveis de fallback (só para o provisionamento do MySQL)
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
    util-linux \
    # [NOVO] Pacotes para o Servidor Web Apache e WSGI
    apache2 \
    libapache2-mod-wsgi-py3 

# --- Instalação de bibliotecas Python ---
echo ">>> Instalando bibliotecas Python..."
# [NOVO] Adicionando 'python-dotenv' para garantir que as credenciais do DB funcionem no Flask
sudo pip3 install Flask mysql-connector-python python-dotenv

# --- Configuração do Banco de Dados MySQL (NÃO PRECISA MUDAR) ---
echo ">>> Configurando o banco de dados e as novas tabelas..."
sudo mysql -e "CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\`;"
sudo mysql -e "CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASS}';"
sudo mysql -e "GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'localhost';"
sudo mysql -e "FLUSH PRIVILEGES;"

# --- Criação das novas tabelas (NÃO PRECISA MUDAR) ---
echo ">>> Removendo a tabela antiga e criando as novas: 'ambientes' e 'programas'..."
sudo mysql -u root ${DB_NAME} <<EOF
DROP TABLE IF EXISTS ambientes;
DROP TABLE IF EXISTS programas;
# ... (restante da criação de tabelas)
EOF

# --- Configuração do Apache e WSGI [BLOCO NOVO] ---
echo ">>> Configurando o Apache para servir a aplicação Flask com mod_wsgi..."

# 1. Habilita o módulo WSGI
sudo a2enmod wsgi

# 2. Configura o Apache para ouvir na porta 5000 (necessário devido ao Vagrantfile)
# O | sudo tee -a é uma forma de adicionar texto a um arquivo de sistema via script.
echo "Listen 5000" | sudo tee -a /etc/apache2/ports.conf > /dev/null

# 3. Copia o arquivo de configuração do VirtualHost para o diretório de sites
# Assumimos que 'flaskapp.conf' está na sua pasta 'web-server' e sincronizado com '/var/www/html'
sudo cp /var/www/html/flaskapp.conf /etc/apache2/sites-available/

# 4. Habilita o novo site e desabilita o site padrão (para evitar conflitos de porta)
sudo a2ensite flaskapp
sudo a2dissite 000-default.conf

# 5. Define permissões para o Apache (www-data) acessar os arquivos sincronizados
sudo chown -R vagrant:www-data /var/www/html
sudo chmod -R 775 /var/www/html

# --- Permissões Sudo e Scripts (NÃO PRECISA MUDAR) ---
echo ">>> Configurando permissões sudo para a nova arquitetura..."
# ... (o restante das permissões)
# ...

# --- Finalização ---
echo ">>> Provisionamento concluído com sucesso! O Apache foi iniciado e está servindo a aplicação Flask."
# [NOVO] Inicia/Reinicia o Apache para aplicar todas as configurações e garantir que ele suba.
sudo systemctl restart apache2

echo ">>> Sua aplicação está acessível via navegador em: http://localhost:8080"