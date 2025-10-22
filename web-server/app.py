from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import mysql.connector
import subprocess
import os
import tempfile
import textwrap
import time
import shlex
import atexit
from dotenv import load_dotenv

# --- Configuração Inicial ---
load_dotenv()
app = Flask(__name__)
app.secret_key = os.urandom(24)

DB_CONFIG = {
    'host': os.getenv('DB_HOST'), 'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASS'), 'database': os.getenv('DB_NAME')
}
OUTPUTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'outputs')
CGROUP_BASE_PATH = "/sys/fs/cgroup"
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts')

if not os.path.isdir(OUTPUTS_DIR):
    os.makedirs(OUTPUTS_DIR, exist_ok=True)

# --- Gestor de Ciclo de Vida dos Ambientes ---
active_environments = set()

def cleanup_on_exit():
    """Função a ser executada quando a aplicação Flask termina."""
    print("\n--- A desligar a aplicação. A limpar ambientes ativos... ---")
    conn = get_db_connection()
    if conn and active_environments:
        cursor = conn.cursor(dictionary=True)
        for cgroup_name in tuple(active_environments):
            try:
                cursor.execute("SELECT * FROM ambientes WHERE cgroup_name = %s", (cgroup_name,))
                ambiente = cursor.fetchone()
                if ambiente:
                    print(f"A limpar ambiente '{ambiente['nome']}' (PID: {ambiente['pid_bash']})...")
                    subprocess.run(['sudo', '/bin/kill', '-9', str(ambiente['pid_bash'])], stderr=subprocess.DEVNULL)
                    
                    cursor.execute("SELECT cgroup_name FROM programas WHERE ambiente_id=%s", (ambiente['id'],))
                    programas = cursor.fetchall()
                    for prog in programas:
                        prog_path = os.path.join(CGROUP_BASE_PATH, cgroup_name, prog['cgroup_name'])
                        subprocess.run(['sudo', '/bin/rmdir', prog_path], stderr=subprocess.DEVNULL)
                    
                    anchor_path = os.path.join(CGROUP_BASE_PATH, cgroup_name, 'anchor')
                    subprocess.run(['sudo', '/bin/rmdir', anchor_path], stderr=subprocess.DEVNULL)
                    env_path = os.path.join(CGROUP_BASE_PATH, cgroup_name)
                    subprocess.run(['sudo', '/bin/rmdir', env_path], stderr=subprocess.DEVNULL)
            except Exception as e:
                print(f"Erro ao limpar {cgroup_name}: {e}")
        cursor.close()
        conn.close()
    print("--- Limpeza concluída. Adeus! ---")

atexit.register(cleanup_on_exit)

# --- Funções de Base de Dados ---
def get_db_connection():
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except mysql.connector.Error as err:
        print(f"Erro de DB: {err}")
        return None

# --- Rotas Principais ---
@app.route('/')
def index():
    conn, cursor = None, None
    try:
        conn = get_db_connection()
        if not conn:
            flash("Erro crítico: Não foi possível conectar à base de dados.", "error")
            return render_template('index.html', ambientes=[])
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM ambientes ORDER BY data_criacao DESC")
        ambientes = cursor.fetchall()
        global active_environments
        active_environments = {amb['cgroup_name'] for amb in ambientes}
        return render_template('index.html', ambientes=ambientes)
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

@app.route('/ambiente/<int:ambiente_id>')
def view_ambiente(ambiente_id):
    conn, cursor = None, None
    try:
        conn = get_db_connection()
        if not conn:
            flash("Erro crítico: Não foi possível conectar à base de dados.", "error")
            return redirect(url_for('index'))
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM ambientes WHERE id = %s", (ambiente_id,))
        ambiente = cursor.fetchone()
        if not ambiente:
            flash(f"Ambiente com ID {ambiente_id} não encontrado.", "error")
            return redirect(url_for('index'))
        cursor.execute("SELECT * FROM programas WHERE ambiente_id = %s ORDER BY data_criacao DESC", (ambiente_id,))
        programas = cursor.fetchall()
        return render_template('ambiente.html', ambiente=ambiente, programas=programas)
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

# --- Rotas de Ação: Ambientes ---
@app.route('/criar_ambiente', methods=['POST'])
def criar_ambiente():
    nome = request.form['nome']
    cgroup_name = f"env_{nome.replace(' ', '_')}_{int(time.time())}"
    cgroup_path = os.path.join(CGROUP_BASE_PATH, cgroup_name)
    pid_file_path = f"/tmp/{cgroup_name}.pid"
    conn, cursor = None, None
    try:
        subprocess.run(['sudo', '/bin/mkdir', cgroup_path], check=True) #criando cgroup
        delegation_cmd = f"echo '+cpu +memory' > {os.path.join(cgroup_path, 'cgroup.subtree_control')}" #delegando recursos
        subprocess.run(['sudo', '/bin/bash', '-c', delegation_cmd], check=True) #aplicando delegação

        anchor_cgroup_path = os.path.join(cgroup_path, 'anchor')
        subprocess.run(['sudo', '/bin/mkdir', anchor_cgroup_path], check=True)

        script_path = os.path.join(SCRIPTS_DIR, 'create_environment.sh') #caminho do script
        subprocess.Popen(['sudo', '/bin/bash', script_path, pid_file_path]) #executando script em background
        pid_bash = None
        for _ in range(5):  #tentar obter o PID durante 1 segundo
            if os.path.exists(pid_file_path):
                with open(pid_file_path, 'r') as f:
                    content = f.read().strip()
                    if content:
                        pid_bash = int(content)
                        break
            time.sleep(0.2)
        if not pid_bash:
            raise FileNotFoundError("Não foi possível obter o PID do ambiente a tempo.")
        
        subprocess.run(['sudo', '/bin/rm', pid_file_path], check=True) #removendo ficheiro temporário
        move_pid_cmd = f"echo {pid_bash} > {os.path.join(anchor_cgroup_path, 'cgroup.procs')}" #movendo PID para o cgroup
        subprocess.run(['sudo', '/bin/bash', '-c', move_pid_cmd], check=True)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO ambientes (nome, pid_bash, cgroup_name) VALUES (%s, %s, %s)", (nome, pid_bash, cgroup_name))
        conn.commit()
        active_environments.add(cgroup_name)
        flash(f"Ambiente '{nome}' criado com sucesso.", "success")

    except (subprocess.CalledProcessError, FileNotFoundError, mysql.connector.Error) as e:
        flash(f"Erro ao criar ambiente: {e}", "error")
        if os.path.exists(cgroup_path):
            if 'anchor_cgroup_path' in locals() and os.path.exists(anchor_cgroup_path):
                subprocess.run(['sudo', '/bin/rmdir', anchor_cgroup_path], stderr=subprocess.DEVNULL)
            subprocess.run(['sudo', '/bin/rmdir', cgroup_path], stderr=subprocess.DEVNULL)
        if os.path.exists(pid_file_path):
             subprocess.run(['sudo', '/bin/rm', pid_file_path], stderr=subprocess.DEVNULL)
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()

    return redirect(url_for('index'))

@app.route('/ambiente/<int:ambiente_id>/lancar_programa', methods=['POST'])
def lancar_programa(ambiente_id):
    conn, cursor = None, None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT pid_bash, cgroup_name FROM ambientes WHERE id = %s", (ambiente_id,))
        ambiente = cursor.fetchone()
        
        nome = request.form['nome']
        comando = request.form['comando']
        cpu_limit = int(request.form.get('cpu_limit') or 0)
        mem_limit = int(request.form.get('mem_limit') or 0)
        
        prog_cgroup_name = f"prog_{nome.replace(' ', '_')}_{int(time.time())}"
        prog_cgroup_path = os.path.join(CGROUP_BASE_PATH, ambiente['cgroup_name'], prog_cgroup_name)

        subprocess.run(['sudo', '/bin/mkdir', prog_cgroup_path], check=True)  #criando cgroup do programa
        
        if cpu_limit > 0:
            quota = int(100000 * (cpu_limit / 100.0))
            cmd = f"echo '{quota} 100000' > {os.path.join(prog_cgroup_path, 'cpu.max')}"
            subprocess.run(['sudo', '/bin/bash', '-c', cmd], check=True)
        if mem_limit > 0:
            cmd = f"echo {mem_limit * 1024 * 1024} > {os.path.join(prog_cgroup_path, 'memory.max')}"
            subprocess.run(['sudo', '/bin/bash', '-c', cmd], check=True)

        output_file = os.path.join(OUTPUTS_DIR, f"{prog_cgroup_name}.log")
        script_path = os.path.join(SCRIPTS_DIR, 'launch_program.sh')
        
        # FIX: Executar o script com sudo para garantir permissões internas
        result = subprocess.run(
            [
                'sudo', '/bin/bash', script_path,
                str(ambiente['pid_bash']),
                prog_cgroup_path,
                output_file,
                comando
            ],
            check=True, capture_output=True, text=True
        )
        pid = int(result.stdout.strip())

        cursor.execute(
            "INSERT INTO programas (ambiente_id, nome, comando, pid, cgroup_name) VALUES (%s, %s, %s, %s, %s)",
            (ambiente_id, nome, comando, pid, prog_cgroup_name)
        )
        conn.commit()
        flash(f"Programa '{nome}' lançado com sucesso no ambiente.", "success")

    except (subprocess.CalledProcessError, mysql.connector.Error) as e:
        flash(f"Erro ao lançar programa: {e}", "error")
        if 'prog_cgroup_path' in locals() and os.path.exists(prog_cgroup_path):
            subprocess.run(['sudo', '/bin/rmdir', prog_cgroup_path], stderr=subprocess.DEVNULL)
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
            
    return redirect(url_for('view_ambiente', ambiente_id=ambiente_id))

# --- Restante do ficheiro (terminar_ambiente, terminar_programa, api_stats) permanece igual ---

@app.route('/ambiente/<int:ambiente_id>/terminar', methods=['POST'])
def terminar_ambiente(ambiente_id):
    conn, cursor = None, None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM ambientes WHERE id = %s", (ambiente_id,))
        ambiente = cursor.fetchone()
        
        if ambiente:
            active_environments.discard(ambiente['cgroup_name'])
            subprocess.run(['sudo', '/bin/kill', '-9', str(ambiente['pid_bash'])], stderr=subprocess.DEVNULL)
            
            cursor.execute("SELECT cgroup_name FROM programas WHERE ambiente_id=%s", (ambiente_id,))
            programas = cursor.fetchall()
            for prog in programas:
                prog_cgroup_path = os.path.join(CGROUP_BASE_PATH, ambiente['cgroup_name'], prog['cgroup_name'])
                subprocess.run(['sudo', '/bin/rmdir', prog_cgroup_path], stderr=subprocess.DEVNULL)
            
            anchor_cgroup_path = os.path.join(CGROUP_BASE_PATH, ambiente['cgroup_name'], 'anchor')
            subprocess.run(['sudo', '/bin/rmdir', anchor_cgroup_path], stderr=subprocess.DEVNULL)
            subprocess.run(['sudo', '/bin/rmdir', os.path.join(CGROUP_BASE_PATH, ambiente['cgroup_name'])], stderr=subprocess.DEVNULL)
            
            cursor.execute("DELETE FROM ambientes WHERE id = %s", (ambiente_id,))
            conn.commit()
            flash(f"Ambiente '{ambiente['nome']}' e todos os seus programas foram terminados.", "success")
    except (subprocess.CalledProcessError, mysql.connector.Error) as e:
        flash(f"Erro ao terminar ambiente: {e}", "warning")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
            
    return redirect(url_for('index'))

@app.route('/programa/<int:programa_id>/terminar', methods=['POST'])
def terminar_programa(programa_id):
    conn, cursor = None, None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT p.*, a.cgroup_name as env_cgroup FROM programas p JOIN ambientes a ON p.ambiente_id = a.id WHERE p.id = %s", (programa_id,))
        programa = cursor.fetchone()
        
        ambiente_id = programa['ambiente_id']

        if programa:
            subprocess.run(['sudo', '/bin/kill', '-9', str(programa['pid'])], stderr=subprocess.DEVNULL)
            prog_cgroup_path = os.path.join(CGROUP_BASE_PATH, programa['env_cgroup'], programa['cgroup_name'])
            subprocess.run(['sudo', '/bin/rmdir', prog_cgroup_path], stderr=subprocess.DEVNULL)
            
            cursor.execute("DELETE FROM programas WHERE id = %s", (programa_id,))
            conn.commit()
            flash(f"Programa '{programa['nome']}' terminado.", "success")
    except (subprocess.CalledProcessError, mysql.connector.Error, TypeError) as e:
        flash(f"Erro ao terminar programa: {e}", "warning")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
    return redirect(url_for('view_ambiente', ambiente_id=ambiente_id if 'ambiente_id' in locals() else 1))

def read_cgroup_file(path):
    try:
        result = subprocess.run(['sudo', '/bin/cat', path], check=True, capture_output=True, text=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None

@app.route('/api/stats')
def api_stats():
    conn, cursor = None, None
    stats = {}
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT p.id, p.status, p.cgroup_name, a.cgroup_name as env_cgroup FROM programas p JOIN ambientes a ON p.ambiente_id = a.id WHERE p.status = 'EXECUTANDO'")
        programas = cursor.fetchall()
        
        for prog in programas:
            full_cgroup_path = os.path.join(CGROUP_BASE_PATH, prog['env_cgroup'], prog['cgroup_name'])
            
            try:
                mem_current_str = read_cgroup_file(os.path.join(full_cgroup_path, 'memory.current'))
                mem_bytes = int(mem_current_str) if mem_current_str else 0
                mem_mb = round(mem_bytes / (1024 * 1024), 2)
                
                cpu_stat_content = read_cgroup_file(os.path.join(full_cgroup_path, 'cpu.stat'))
                cpu_usage_us = 0
                if cpu_stat_content:
                    for line in cpu_stat_content.splitlines():
                        if line.startswith('usage_usec'):
                            cpu_usage_us = int(line.split()[1])
                            break
                
                stats[prog['id']] = { "mem_mb": mem_mb, "cpu_usage_us": cpu_usage_us, "status": "Online" }

            except (FileNotFoundError, IndexError, ValueError):
                stats[prog['id']] = {"status": "Offline"}
                cursor.execute("UPDATE programas SET status = 'CONCLUIDO' WHERE id = %s", (prog['id'],))
                conn.commit()
                if os.path.exists(full_cgroup_path):
                    subprocess.run(['sudo', '/bin/rmdir', full_cgroup_path], stderr=subprocess.DEVNULL)
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
    return jsonify(stats)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

