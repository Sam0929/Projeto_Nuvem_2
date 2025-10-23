import sys
import logging
import os

# O caminho para o diretório RAIZ da aplicação (onde está o app.py)
sys.path.insert(0, "/var/www/html")

# Importar o objeto Flask. 'app' é o nome da sua instância Flask no app.py
from app import app as application  

# Para log de erros
logging.basicConfig(stream=sys.stderr)