import os
import subprocess
import psutil
import mysql.connector
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from dotenv import load_dotenv

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


@app.route('/criar', methods=['GET', 'POST'])
def criar():
    if request.method == 'POST':
        nome = request.form['nome']
        comando = request.form['comando']
        cpu = int(request.form['cpu'])
        mem = int(request.form['mem'])
        script = request.files.get('script')

        dir_amb = os.path.join(BASE_DIR, nome)
        os.makedirs(dir_amb, exist_ok=True)
        log_path = os.path.join(dir_amb, "output.log")

        # Determina comando a executar
        if script and script.filename:
            script_path = os.path.join(dir_amb, script.filename)
            script.save(script_path)
            exec_cmd = f"bash {script_path}"
        else:
            if not comando.strip():
                flash("❌ É necessário informar um comando ou enviar um script!", "danger")
                return redirect(url_for('criar'))
            exec_cmd = comando

        # Novo comando funcional
        unshare_cmd = (
            f"sudo unshare -m --mount-proc bash -c "
            f"\"setsid bash -c '{exec_cmd} > {log_path} 2>&1 &' && pgrep -n $(basename {exec_cmd.split()[0]})\""
        )

        process = subprocess.Popen(["bash", "-c", unshare_cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()

        pid_str = stdout.decode().strip().splitlines()[-1] if stdout else ""
        erro_str = stderr.decode().strip()

        if not pid_str.isdigit():
            flash(f"❌ Falha ao criar ambiente: {erro_str or 'Não foi possível obter PID.'}", "danger")
            return redirect(url_for('index'))

        pid = int(pid_str)
        grupo = f"amb_{nome}"
        cgroup_path = os.path.join(CGROUP_BASE, grupo)

        # Cria o cgroup e aplica limites
        subprocess.run(["sudo", "mkdir", "-p", cgroup_path])
        subprocess.run(["sudo", "bash", "-c", f"echo {pid} > {cgroup_path}/cgroup.procs"])
        subprocess.run(["sudo", "bash", "-c", f"echo '{int(cpu*1000)} 100000' > {cgroup_path}/cpu.max"])
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


@app.route('/log/<nome>')
def log(nome):
    log_path = os.path.join(BASE_DIR, nome, "output.log")
    conteudo = open(log_path).read() if os.path.exists(log_path) else "Log não encontrado."
    return f"<pre>{conteudo}</pre>"


@app.route('/terminar/<nome>')
def terminar(nome):
    db = mysql.connector.connect(**DB_CONFIG)
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT pid, cgroup_path FROM ambientes WHERE nome=%s", (nome,))
    amb = cursor.fetchone()
    if amb:
        try:
            pid = amb['pid']
            if psutil.pid_exists(pid):
                subprocess.run(["sudo", "kill", "-9", str(pid)])
            if os.path.exists(amb['cgroup_path']):
                subprocess.run(["sudo", "rmdir", amb['cgroup_path']])
            cursor.execute("UPDATE ambientes SET status='terminado' WHERE nome=%s", (nome,))
            db.commit()
            flash(f"🛑 Ambiente '{nome}' encerrado.", "info")
        except Exception as e:
            flash(f"❌ Erro ao encerrar: {e}", "danger")
    cursor.close(); db.close()
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
