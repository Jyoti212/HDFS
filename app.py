
from flask import (
    Flask, request, send_file, redirect,
    render_template_string, abort, flash, url_for
)
from werkzeug.utils import secure_filename
import subprocess
import os
import tempfile
import re

HDFS = "/opt/hadoop/bin/hdfs"
DIR = "/cloud"

app = Flask(__name__)
app.secret_key = "mini-hdfs-local-demo-change-me"
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024


def run(*args):
    """Run an HDFS command and report errors instead of hiding them."""
    result = subprocess.run(
        [HDFS, *args],
        capture_output=True,
        text=True,
        timeout=60
    )
    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(error or "HDFS command failed.")
    return result.stdout.strip()


def human(value):
    n = float(value)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


CSS = """
*{box-sizing:border-box}
body{margin:0;font-family:'Segoe UI',Arial,sans-serif;background:#f1f5f9;color:#0f172a}
header{background:linear-gradient(135deg,#1e3a8a,#2563eb);color:#fff;padding:28px 40px}
header h1{margin:0;font-size:26px}
header p{margin:6px 0 0;opacity:.85;font-size:14px}
main{max-width:1020px;margin:-24px auto 40px;padding:0 20px}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:20px}
.card,.panel{background:#fff;border-radius:12px;box-shadow:0 2px 10px #0f172a14;padding:20px}
.card .label{font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.05em}
.card .value{font-size:28px;font-weight:700;margin-top:6px;color:#1e3a8a}
.panel{margin-bottom:20px}
.panel h3{margin:0 0 14px;font-size:16px}
.upload{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
input[type=file]{flex:1;padding:10px;border:2px dashed #93c5fd;border-radius:8px;background:#eff6ff}
button,.btn{background:#2563eb;color:white;border:0;padding:10px 20px;border-radius:8px;font-size:14px;cursor:pointer;text-decoration:none;display:inline-block}
button:hover,.btn:hover{background:#1d4ed8}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;color:#64748b;font-size:12px;text-transform:uppercase;padding:10px;border-bottom:2px solid #e2e8f0}
td{padding:12px 10px;border-bottom:1px solid #e2e8f0;overflow-wrap:anywhere}
tr:hover td{background:#f8fafc}
.act a{margin-right:5px;padding:5px 9px;border-radius:6px;font-size:13px;text-decoration:none;display:inline-block}
.dl{background:#dcfce7;color:#166534}
.bl{background:#dbeafe;color:#1e40af}
.rm{background:#fee2e2;color:#991b1b}
.empty{text-align:center;color:#94a3b8;padding:30px}
.pill{background:#dbeafe;color:#1e40af;padding:3px 10px;border-radius:999px;font-size:12px}
pre{background:#0f172a;color:#e2e8f0;padding:16px;border-radius:8px;overflow:auto;font-size:12px;white-space:pre-wrap}
.notice{padding:12px 16px;border-radius:8px;margin-bottom:16px;background:#dbeafe;color:#1e40af;overflow-wrap:anywhere}
.error{background:#fee2e2;color:#991b1b}
details{margin-top:10px}
summary{cursor:pointer;color:#2563eb}
@media(max-width:640px){.cards{grid-template-columns:1fr}header{padding:24px 20px}}
"""

HOME = """
<div class="cards">
  <div class="card"><div class="label">Files stored</div>
    <div class="value">{{ files|length }}</div></div>
  <div class="card"><div class="label">Total size</div>
    <div class="value">{{ total }}</div></div>
  <div class="card"><div class="label">Live DataNodes</div>
    <div class="value">{{ nodes }}</div></div>
</div>
<div class="panel"><h3>Upload a file</h3>
  <form class="upload" method="post" action="/upload" enctype="multipart/form-data">
    <input type="file" name="f" required>
    <button type="submit">Upload to HDFS</button>
  </form>
</div>
<div class="panel"><h3>Files in the cloud</h3>
{% if files %}
<table><tr><th>Name</th><th>Size</th><th>Modified</th><th>Actions</th></tr>
{% for f in files %}
<tr>
  <td>{{ f.name }}</td><td>{{ f.size }}</td><td>{{ f.date }}</td>
  <td class="act">
    <a class="dl" href="{{ url_for('download', name=f.name) }}">Download</a>
    <a class="bl" href="{{ url_for('info', name=f.name) }}">Block info</a>
    <form method="post" action="{{ url_for('delete', name=f.name) }}"
          style="display:inline"
          onsubmit="return confirm('Delete this file?')">
      <button class="rm" type="submit">Delete</button>
    </form>
  </td>
</tr>
{% endfor %}
</table>
{% else %}
<div class="empty">No files yet. Upload one above.</div>
{% endif %}
</div>
"""

INFO = """
<div class="panel"><h3>Block details: {{ name }}</h3>
<div class="cards">
  <div class="card"><div class="label">File size</div>
    <div class="value">{{ size }}</div></div>
  <div class="card"><div class="label">Blocks</div>
    <div class="value">{{ blocks|length }}</div></div>
  <div class="card"><div class="label">Replication</div>
    <div class="value">{{ repl }}</div></div>
</div>
{% if blocks %}
<table><tr><th>#</th><th>Block ID</th><th>Size</th><th>DataNodes</th></tr>
{% for b in blocks %}
<tr><td>{{ b.i }}</td><td>{{ b.id }}</td><td>{{ b.size }}</td>
<td>{% for d in b.nodes %}<span class="pill">{{ d }}</span> {% endfor %}</td></tr>
{% endfor %}
</table>
{% else %}
<p>No block entries were parsed. Check the raw fsck output below.</p>
{% endif %}
<details><summary>Raw fsck output</summary><pre>{{ raw }}</pre></details>
<p><a class="btn" href="/">Back to files</a></p></div>
"""


def page(body, **context):
    return render_template_string(
        """<!doctype html><html><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Mini HDFS Cloud</title><style>""" + CSS + """</style>
        </head><body><header><h1>&#9729; Mini HDFS Cloud</h1>
        <p>Software as a Service on Hadoop Distributed File System</p>
        </header><main>
        {% for category, message in get_flashed_messages(with_categories=true) %}
          <div class="notice {{ 'error' if category == 'error' else '' }}">
            {{ message }}
          </div>
        {% endfor %}
        """ + body + """</main></body></html>""",
        **context
    )


def safe_name(name):
    name = secure_filename(name or "")
    if not name or name in (".", ".."):
        abort(400, description="Invalid filename.")
    return name


@app.route("/")
def home():
    try:
        # Ensure the HDFS destination directory exists.
        run("dfs", "-mkdir", "-p", DIR)

        output = run("dfs", "-ls", DIR)
        files = []
        total_bytes = 0

        for line in output.splitlines():
            parts = line.split()
            # HDFS listing: permissions repl owner group size date time path
            if len(parts) >= 8 and parts[0].startswith("-"):
                try:
                    size_bytes = int(parts[4])
                except ValueError:
                    continue

                path = parts[-1]
                files.append({
                    "name": os.path.basename(path.rstrip("/")),
                    "size": human(size_bytes),
                    "date": parts[5] + " " + parts[6]
                })
                total_bytes += size_bytes

        # Sort names consistently.
        files.sort(key=lambda item: item["name"].lower())

        report = run("dfsadmin", "-report")
        match = re.search(r"Live datanodes\s*\((\d+)\)", report, re.I)
        nodes = match.group(1) if match else "0"

        return page(
            HOME, files=files,
            total=human(total_bytes),
            nodes=nodes
        )

    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        return page(
            '<div class="panel"><h3>HDFS connection error</h3>'
            '<p>Flask is running, but it could not read HDFS.</p>'
            '<pre>{{ error }}</pre></div>',
            error=str(exc)
        ), 500


@app.route("/upload", methods=["POST"])
def upload():
    f = request.files.get("f")
    if not f or not f.filename:
        flash("Please choose a file first.", "error")
        return redirect("/")

    name = safe_name(f.filename)
    tmp_path = None

    try:
        fd, tmp_path = tempfile.mkstemp(prefix="hdfs_upload_")
        with os.fdopen(fd, "wb") as temp_file:
            f.save(temp_file)

        # -put -f overwrites a same-named file if it already exists.
        run("dfs", "-put", "-f", tmp_path, f"{DIR}/{name}")

        # Verify that HDFS can see the uploaded file.
        run("dfs", "-test", "-e", f"{DIR}/{name}")

        flash(f"Successfully uploaded '{name}' to HDFS.", "success")

    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        flash(f"Upload failed: {exc}", "error")

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

    return redirect("/")


@app.route("/download/<name>")
def download(name):
    name = safe_name(name)
    tmp_path = None

    try:
        fd, tmp_path = tempfile.mkstemp(prefix="hdfs_download_")
        os.close(fd)
        os.remove(tmp_path)

        run("dfs", "-get", f"{DIR}/{name}", tmp_path)

        if not os.path.isfile(tmp_path):
            raise RuntimeError("HDFS download did not create a local file.")

        response = send_file(
            tmp_path, as_attachment=True, download_name=name
        )
        response.call_on_close(
            lambda: os.path.exists(tmp_path) and os.remove(tmp_path)
        )
        return response

    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
        return page(
            '<div class="panel"><h3>Download failed</h3>'
            '<pre>{{ error }}</pre><a class="btn" href="/">Back</a></div>',
            error=str(exc)
        ), 500


@app.route("/delete/<name>", methods=["POST"])
def delete(name):
    name = safe_name(name)
    try:
        run("dfs", "-rm", f"{DIR}/{name}")
        flash(f"Deleted '{name}' from HDFS.", "success")
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        flash(f"Delete failed: {exc}", "error")
    return redirect("/")


@app.route("/info/<name>")
def info(name):
    name = safe_name(name)

    try:
        raw = run(
            "fsck", f"{DIR}/{name}",
            "-files", "-blocks", "-locations"
        )

        size = "Unknown"
        repl = "Unknown"
        blocks = []

        for line in raw.splitlines():
            if "bytes, " in line and "replication=" in line:
                size_match = re.search(r"(\d+) bytes", line)
                repl_match = re.search(r"replication=(\d+)", line)
                if size_match:
                    size = human(size_match.group(1))
                if repl_match:
                    repl = repl_match.group(1)

            # Block formats vary between Hadoop versions.
            if "blk_" in line and "len=" in line:
                block_match = re.search(r"(blk_\d+)", line)
                length_match = re.search(r"len=(\d+)", line)
                if block_match:
                    node_matches = re.findall(
                        r"/([\d.]+):(\d+)", line
                    )
                    blocks.append({
                        "i": len(blocks) + 1,
                        "id": block_match.group(1),
                        "size": human(length_match.group(1))
                            if length_match else "Unknown",
                        "nodes": [
                            f"{host}:{port}"
                            for host, port in node_matches
                        ]
                    })

        return page(
            INFO, name=name, size=size, repl=repl,
            blocks=blocks, raw=raw
        )

    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        return page(
            '<div class="panel"><h3>Block information failed</h3>'
            '<pre>{{ error }}</pre><a class="btn" href="/">Back</a></div>',
            error=str(exc)
        ), 500


@app.errorhandler(413)
def too_large(_error):
    return page(
        '<div class="panel"><h3>File too large</h3>'
        '<p>The maximum upload size is 100 MB.</p>'
        '<a class="btn" href="/">Back</a></div>'
    ), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
