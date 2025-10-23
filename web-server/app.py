import os
import subprocess
import psutil
import mysql.connector
import time
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from dotenv import load_dotenv

# --- Configuração Inicial ---
load_dotenv()
app = Flask(__name__)
app.secret_key = os.urandom(24)

BASE_DIR = "/home/vagrant/web-server/ambientes"
CGROUP_BASE = "/sys/fs/cgroup"
os.makedirs(BASE_DIR, exist_ok=True)

DB_CONFIG = {
    'host': 'localhost',
    'user': 'flaskuser',
    'password': '12345',
    'database': 'ambientesdb'
}

# --- Página Inicial ---
@app.route('/')
def index():
    db = mysql.connector.connect(**DB_CONFIG)
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM ambientes ORDER BY criado_em DESC")
    ambientes = cursor.fetchall()
    cursor.close(); db.close()

    for amb in ambientes:
        pid = amb['pid']
        if pid and psutil.pid_exists(pid):
            try:
                p = psutil.Process(pid)
                amb['cpu'] = p.cpu_percent(interval=0.1)
                amb['mem'] = p.memory_info().rss // (1024 * 1024)
                amb['status'] = 'em_execucao'
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                amb['status'] = 'terminado'
                amb['cpu'] = amb['mem'] = 0
        else:
            amb['status'] = 'terminado'
            amb['cpu'] = amb['mem'] = 0

    return render_template('index.html', ambientes=ambientes)

# --- API de Status ---
@app.route('/api/status')
def api_status():
    db = mysql.connector.connect(**DB_CONFIG)
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT nome, pid, status FROM ambientes")
    ambientes = cursor.fetchall()
    cursor.close(); db.close()

    data = []
    for amb in ambientes:
        pid = amb['pid']
        nome = amb['nome']
        status = 'terminado'
        cpu = mem = 0

        if pid and psutil.pid_exists(pid):
            try:
                p = psutil.Process(pid)
                status = 'em_execucao'
                cpu = p.cpu_percent(interval=0.1)
                mem = p.memory_info().rss // (1024 * 1024)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                status = 'terminado'

        data.append({'nome': nome, 'status': status, 'cpu': cpu, 'mem': mem})

    return jsonify(data)

# --- Criar novo ambiente ---
@app.route('/criar', methods=['GET', 'POST'])
def criar():
    if request.method == 'POST':
        nome = request.form['nome']
        comando = request.form['comando'].strip()
        cpu = int(request.form['cpu'])
        mem = int(request.form['mem'])
        script = request.files.get('script')

        if not comando and not script:
            flash("❌ Informe um comando ou envie um script!", "danger")
            return redirect(url_for('criar'))

        dir_amb = os.path.join(BASE_DIR, nome)
        os.makedirs(dir_amb, exist_ok=True)
        log_path = os.path.join(dir_amb, "output.log")

        # Se for script enviado, salva e usa ele
        if script and script.filename:
            script_path = os.path.join(dir_amb, script.filename)
            script.save(script_path)
            exec_cmd = f"bash {script_path}"
        else:
            exec_cmd = comando

        # Executa comando de forma segura com unshare e captura PID corretamente
        shell_cmd = (
            f"sudo unshare -m --mount-proc bash -c "
            f"\"setsid bash -c '{exec_cmd} > {log_path} 2>&1 &' "
            f"&& sleep 0.2 && pgrep -n $(basename {exec_cmd.split()[0]})\""
        )

        process = subprocess.Popen(["bash", "-c", shell_cmd],
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()

        pid_str = stdout.decode().strip()
        if not pid_str.isdigit():
            flash(f"❌ Falha ao obter PID. Saída: {pid_str or stderr.decode().strip()}", "danger")
            return redirect(url_for('index'))

        pid = int(pid_str)
        grupo = f"env_{nome.replace(' ', '_')}_{int(time.time())}"
        cgroup_path = os.path.join(CGROUP_BASE, grupo)

        # Cria o cgroup e aplica limites
        subprocess.run(["sudo", "mkdir", "-p", cgroup_path])
        subprocess.run(["sudo", "bash", "-c", f"echo {pid} > {cgroup_path}/cgroup.procs"])
        subprocess.run(["sudo", "bash", "-c", f"echo '{int(cpu * 1000)} 100000' > {cgroup_path}/cpu.max"])
        subprocess.run(["sudo", "bash", "-c", f"echo '{mem * 1024 * 1024}' > {cgroup_path}/memory.max"])

        # Salva no banco
        try:
            db = mysql.connector.connect(**DB_CONFIG)
            cursor = db.cursor()
            cursor.execute("""
                INSERT INTO ambientes (nome, comando, cpu_limit, mem_limit_mb, pid, cgroup_path, status, log_path)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (nome, comando, cpu, mem, pid, cgroup_path, 'em_execucao', log_path))
            db.commit()
            cursor.close(); db.close()
        except Exception as e:
            flash(f"Erro ao salvar no banco: {e}", "danger")

        flash(f"✅ Ambiente '{nome}' criado com sucesso! (PID {pid})", "success")
        return redirect(url_for('index'))

    return render_template('criar_ambiente.html')

# --- Visualizar Log ---
@app.route('/log/<nome>')
def log(nome):
    log_path = os.path.join(BASE_DIR, nome, "output.log")
    conteudo = open(log_path).read() if os.path.exists(log_path) else "Log não encontrado."
    return f"<pre>{conteudo}</pre>"

@app.route('/terminar/<int:id>')
def terminar(id):
    db = mysql.connector.connect(**DB_CONFIG)

    try:
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT nome, pid, cgroup_path FROM ambientes WHERE id=%s", (id,))
        amb = cursor.fetchone()
        cursor.close()

        if amb:
            cgroup_path = amb['cgroup_path']

            # Mata todos os processos no cgroup
            if os.path.exists(cgroup_path):
                subprocess.run(
                    ["sudo", "bash", "-c", f"echo 1 > {cgroup_path}/cgroup.kill"],
                    check=False
                )
                subprocess.run(
                    ["sudo", "bash", "-c", f"rmdir --ignore-fail-on-non-empty {cgroup_path}"],
                    check=False
                )

            # Atualiza o status no banco
            cursor_upd = db.cursor()
            cursor_upd.execute(
                "UPDATE ambientes SET status='terminado' WHERE id=%s", (id,)
            )
            db.commit()
            cursor_upd.close()

            flash(f"🛑 Ambiente '{amb['nome']}' encerrado com sucesso via cgroup.kill.", "info")
        else:
            flash("❌ Ambiente não encontrado.", "danger")

    except Exception as e:
        flash(f"❌ Erro ao encerrar: {e}", "danger")

    finally:
        db.close()

    return redirect(url_for('index'))



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
