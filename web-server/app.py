from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash
import mysql.connector
import subprocess
import os
import tempfile
import textwrap
from dotenv import load_dotenv

# Carrega as variáveis do arquivo .env para o ambiente do sistema
load_dotenv()

app = Flask(__name__)

app.secret_key = os.urandom(24) 

# --- Configuração ---
DB_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASS'),
    'database': os.getenv('DB_NAME')
}
OUTPUTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'outputs')
CGROUP_BASE_PATH = "/sys/fs/cgroup"

# Garante que o diretório de outputs exista
if not os.path.isdir(OUTPUTS_DIR):
    os.makedirs(OUTPUTS_DIR, exist_ok=True)

def get_db_connection():
    """Cria e retorna uma nova conexão com o banco de dados."""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except mysql.connector.Error as err:
        print(f"Erro ao conectar ao banco de dados: {err}")
        return None

def write_to_cgroup_file(group_name, file, value):
    
    path = os.path.join(CGROUP_BASE_PATH, group_name, file)
    command = ['/bin/bash', '-c', f"echo '{value}' | sudo /usr/bin/tee {path}"]
    subprocess.run(command, check=True)

@app.route('/', methods=['GET', 'POST'])
def index():
    conn = get_db_connection()
    if not conn:
        flash("Erro crítico: Não foi possível conectar ao banco de dados.", "error")
        return render_template('index.html', ambientes=[])

    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        unique_id = f"ambiente_{int(subprocess.time.time())}_{os.urandom(2).hex()}"
        cgroup_path = os.path.join(CGROUP_BASE_PATH, unique_id)
        
        try:
            nome = request.form['nome']
            comando = request.form['comando']
            cpu_limit_pct = int(request.form.get('cpu_limit') or 0)
            mem_limit_mb = int(request.form.get('mem_limit') or 0)

            output_file_name = f"{unique_id}.log"
            output_file_abs_path = os.path.join(OUTPUTS_DIR, output_file_name)
            
            # 1. Criar o diretório do cgroup
            subprocess.run(['sudo', '/bin/mkdir', cgroup_path], check=True)
            
            # 2. Definir os limites
            if cpu_limit_pct > 0:
                period_us = 100000
                quota_us = int(period_us * (cpu_limit_pct / 100.0))
                write_to_cgroup_file(unique_id, 'cpu.max', f"{quota_us} {period_us}")

            if mem_limit_mb > 0:
                mem_bytes = mem_limit_mb * 1024 * 1024
                write_to_cgroup_file(unique_id, 'memory.max', mem_bytes)

            escaped_comando = comando.replace('"', '\\"')

            # 3. Criar e executar o script lançador
            launcher_script_content = textwrap.dedent(f"""\
                #!/bin/bash
                unshare --fork --pid --mount-proc nohup bash -c "{escaped_comando}" > {output_file_abs_path} 2>&1 &
                PID=$!
                echo $PID > {cgroup_path}/cgroup.procs
                echo $PID
            """)
            
    
            with tempfile.NamedTemporaryFile(mode='w+', delete=False, prefix='launcher_', suffix='.sh', dir='/tmp') as launcher_file:
                launcher_file.write(launcher_script_content)
                launcher_script_path = launcher_file.name

            os.chmod(launcher_script_path, 0o755)

            # Executar o script com sudo e capturar a sua saída (que é o PID)
            result = subprocess.run(
                ['sudo', '/bin/bash', launcher_script_path],
                check=True, capture_output=True, text=True
            )
            actual_pid = int(result.stdout.strip())
            os.remove(launcher_script_path) # Limpar o script temporário

            # 4. Inserir na BD com o PID correto
            sql = """
                INSERT INTO ambientes (nome, comando, cpu_limit, mem_limit, status, output_file, pid)
                VALUES (%s, %s, %s, %s, 'EXECUTANDO', %s, %s)
            """
            cursor.execute(sql, (nome, comando, cpu_limit_pct, mem_limit_mb, output_file_name, actual_pid))
            conn.commit()

            flash(f"Ambiente '{nome}' criado e iniciado com sucesso (PID: {actual_pid})!", "success")

        except (subprocess.CalledProcessError, ValueError, mysql.connector.Error) as e:
            flash(f"Erro ao criar o ambiente: {e}", "error")
        
            if os.path.exists(cgroup_path):
                subprocess.run(['sudo', '/bin/rmdir', cgroup_path])
            if 'launcher_script_path' in locals() and os.path.exists(launcher_script_path):
                os.remove(launcher_script_path)
        
        return redirect(url_for('index'))


    cursor.execute("SELECT id, nome, status, pid, data_criacao, output_file FROM ambientes ORDER BY data_criacao DESC")
    ambientes = cursor.fetchall()
    
    for ambiente in ambientes:
        if ambiente['status'] == 'EXECUTANDO' and ambiente['pid']:
            try:
                subprocess.run(['/bin/kill', '-0', str(ambiente['pid'])], check=True, capture_output=True)
            except (subprocess.CalledProcessError, FileNotFoundError):
                ambiente['status'] = 'CONCLUIDO'
                cursor.execute("UPDATE ambientes SET status = 'CONCLUIDO' WHERE id = %s", (ambiente['id'],))
                conn.commit()

    cursor.close()
    conn.close()
    return render_template('index.html', ambientes=ambientes)


@app.route('/terminar/<int:id>')
def terminar(id):
    conn = get_db_connection()
    if not conn:
        flash("Erro de banco de dados ao tentar terminar o ambiente.", "error")
        return redirect(url_for('index'))

    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT pid, nome, output_file FROM ambientes WHERE id = %s", (id,))
    ambiente = cursor.fetchone()
    
    if ambiente:
        try:
            if ambiente['pid']:
                subprocess.run(['sudo', '/bin/kill', '-9', str(ambiente['pid'])], check=True, stderr=subprocess.DEVNULL)
            
            if ambiente['output_file']:
                cgroup_name = ambiente['output_file'].replace('.log', '')
                cgroup_path = os.path.join(CGROUP_BASE_PATH, cgroup_name)
                subprocess.run(['sudo', '/bin/rmdir', cgroup_path], check=True, stderr=subprocess.DEVNULL)

            cursor.execute("DELETE FROM ambientes WHERE id = %s", (id,))
            conn.commit()
            flash(f"Ambiente '{ambiente['nome']}' terminado e removido com sucesso.", "success")
        except (subprocess.CalledProcessError, mysql.connector.Error) as e:
            flash(f"O processo já não existia ou ocorreu um erro ao remover: {e}", "warning")
            cursor.execute("DELETE FROM ambientes WHERE id = %s", (id,))
            conn.commit()

    cursor.close()
    conn.close()
    return redirect(url_for('index'))


@app.route('/outputs/<path:filename>')
def serve_output(filename):
    #log
    return send_from_directory(OUTPUTS_DIR, filename, as_attachment=False)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

