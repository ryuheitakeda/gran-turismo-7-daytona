#!/usr/bin/env python3

# Web page with GT7 live telemetry and the credits gt7-daytona.sh has earned
# Usage: gt7-web.py [serve|start|stop|status]
#
# Listens on the Tailscale address only (WEB_ADDRESS, default `tailscale ip -4`)
# and WEB_PORT (default 8077). Reads the log and the telemetry file that
# gt7-daytona.sh writes; it never talks to the Playstation itself.

import datetime
import glob
import http.server
import json
import os
import re
import signal
import subprocess
import sys
import time

HOME = os.path.expanduser('~')
LOG_FILE = os.environ.get('LOG_FILE', os.path.join(HOME, 'gt7-daytona.log'))
CACHE = os.environ.get('XDG_CACHE_HOME', os.path.join(HOME, '.cache'))
LOCK_FILE = os.environ.get('LOCK_FILE', os.path.join(CACHE, 'gt7-daytona.lock'))
PID_FILE = os.path.join(CACHE, 'gt7-web.pid')
STOP_FILE = os.environ.get('STOP_FILE', os.path.join(CACHE, 'gt7-daytona.stop-after-race'))
SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gt7-daytona.sh')
WEB_LOG = os.path.join(HOME, 'gt7-web.log')
WEB_PORT = int(os.environ.get('WEB_PORT', '8077'))
RUNTIME = os.environ.get('XDG_RUNTIME_DIR', '/run/user/%d' % os.getuid())

FIELDS = ('time', 'on_track', 'paused', 'loading', 'lap', 'laps', 'speed', 'position',
          'best', 'last', 'gear', 'throttle', 'brake', 'rpm', 'steer')
LINE = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (.*)$')


def telemetry():
    paths = [os.path.join(RUNTIME, 'gt7-telemetry.state'), '/tmp/gt7-telemetry.state']
    paths += glob.glob(os.path.join(RUNTIME, 'gt7-telemetry.[0-9]*'))
    paths = [p for p in paths if os.path.exists(p)]
    if not paths:
        return None
    path = max(paths, key=os.path.getmtime)
    try:
        values = [int(v) for v in open(path).read().split()]
    except (OSError, ValueError):
        return None
    t = dict(zip(FIELDS, values))
    t['age'] = time.time() - t.get('time', 0)
    return t


def script_running():
    try:
        pid = int(open(LOCK_FILE).read().split()[0])
        cmdline = open('/proc/%d/cmdline' % pid, 'rb').read()
    except (OSError, ValueError, IndexError):
        return False
    return b'gt7-daytona.sh' in cmdline


def earnings():
    """Count races in the log; only dated lines (YYYY-MM-DD HH:MM:SS) are used."""
    sessions = []
    try:
        lines = open(LOG_FILE, errors='replace').read().splitlines()
    except OSError:
        lines = []
    for line in lines:
        m = LINE.match(line)
        if not m:
            continue
        when = datetime.datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S')
        text = m.group(2).strip()
        if text.startswith('Started:'):
            prize = re.search(r'RACE_PRIZE=(\d+)', text)
            sessions.append({'start': when, 'end': when, 'prize': int(prize.group(1)) if prize else 0,
                             'races': []})
        elif sessions:
            sessions[-1]['end'] = when
            if text.startswith('Race ending'):
                position = re.search(r'\(P(\d+)', text)
                sessions[-1]['races'].append((when, int(position.group(1)) if position else None))
    now = datetime.datetime.now()
    if sessions and script_running():
        sessions[-1]['end'] = now

    def summary(selected, since=None):
        seconds = races = wins = credits = 0
        for s in selected:
            start = max(s['start'], since) if since else s['start']
            if s['end'] > start:
                seconds += (s['end'] - start).total_seconds()
            for when, position in s['races']:
                if since and when < since:
                    continue
                races += 1
                if position == 1:
                    wins += 1
                    credits += s['prize']
        per_hour = credits / (seconds / 3600) if seconds >= 60 else 0
        return {'races': races, 'wins': wins, 'credits': credits, 'hours': seconds / 3600,
                'per_hour': per_hour}

    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today = [s for s in sessions if s['end'] >= midnight]
    return {
        'session': summary(sessions[-1:]),
        'today': summary(today, midnight),
        'session_start': sessions[-1]['start'].strftime('%m/%d %H:%M') if sessions else None,
        'log': [line for line in lines[-8:]],
    }


def state():
    return {'telemetry': telemetry(), 'running': script_running(),
            'stop_after_race': os.path.exists(STOP_FILE), **earnings()}


ACTIONS = {'start': ['start'], 'stop-after-race': ['stop-after-race'],
           'cancel-stop': ['cancel-stop'], 'emergency-stop': ['stop']}


def run_script(action):
    result = subprocess.run([SCRIPT] + ACTIONS[action], capture_output=True, text=True, timeout=15)
    return {'ok': result.returncode == 0, 'output': (result.stdout + result.stderr).strip()}


PAGE = '''<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GT7 Daytona</title>
<style>
:root { --bg: #f4f5f7; --card: #fff; --text: #1d2330; --muted: #6b7385; --line: #e3e6ec;
  --accent: #d6402b; --ok: #1f8a4c; --warn: #b7791f; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #11141a; --card: #1a1f28; --text: #e8ebf1; --muted: #8d95a7; --line: #2a303c;
    --accent: #ff6b55; --ok: #4cc884; --warn: #e6b450; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.5 system-ui, -apple-system, "Hiragino Sans", "Noto Sans JP", sans-serif; }
main { max-width: 960px; margin: 0 auto; padding: 16px; }
header { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 16px; }
h1 { font-size: 20px; margin: 0; }
h2 { font-size: 13px; font-weight: 600; color: var(--muted); margin: 0 0 12px; letter-spacing: .04em; }
.badge { padding: 4px 10px; border-radius: 999px; font-size: 13px; font-weight: 600; background: var(--line); }
.badge.ok { background: color-mix(in srgb, var(--ok) 18%, transparent); color: var(--ok); }
.badge.warn { background: color-mix(in srgb, var(--warn) 20%, transparent); color: var(--warn); }
.grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 16px; }
.big { font-size: 44px; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1.1; }
.unit { font-size: 15px; color: var(--muted); font-weight: 500; margin-left: 4px; }
.stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 12px; }
.stat .v { font-size: 20px; font-weight: 650; font-variant-numeric: tabular-nums; }
.stat .k { font-size: 12px; color: var(--muted); }
.bar { height: 8px; border-radius: 4px; background: var(--line); overflow: hidden; margin-top: 4px; }
.bar > div { height: 100%; background: var(--accent); width: 0; transition: width .2s; }
.bar.brake > div { background: var(--muted); }
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
td { padding: 6px 0; border-bottom: 1px solid var(--line); }
td:last-child { text-align: right; font-weight: 600; }
tr:last-child td { border-bottom: 0; }
pre { margin: 0; font: 12px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace; white-space: pre-wrap;
  word-break: break-all; color: var(--muted); }
.note { font-size: 12px; color: var(--muted); margin-top: 8px; }
.controls { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.controls button { flex: 1 1 140px; min-height: 48px; border-radius: 10px; border: 1px solid var(--line);
  background: var(--card); color: var(--text); font: inherit; font-weight: 650; cursor: pointer; }
.controls button:disabled { opacity: .4; cursor: default; }
.controls .start { border-color: var(--ok); color: var(--ok); }
.controls .danger { background: var(--accent); border-color: var(--accent); color: #fff; }
#message { font-size: 13px; color: var(--muted); min-height: 1.5em; margin: -4px 0 12px; }
</style>
</head>
<body>
<main>
<header><h1>GT7 Daytona</h1><span id="status" class="badge">読み込み中</span></header>
<div class="controls">
  <button id="start" class="start" onclick="act('start')">開始</button>
  <button id="stop-after-race" onclick="toggleStop()">このレースで停止</button>
  <button id="emergency" class="danger" onclick="act('emergency-stop')">緊急停止</button>
</div>
<div id="message"></div>
<div class="grid">
  <section class="card">
    <h2>ライブテレメトリー</h2>
    <div><span class="big" id="speed">–</span><span class="unit">km/h</span></div>
    <div class="stats">
      <div class="stat"><div class="v" id="lap">–</div><div class="k">周回</div></div>
      <div class="stat"><div class="v" id="position">–</div><div class="k">順位</div></div>
      <div class="stat"><div class="v" id="gear">–</div><div class="k">ギア</div></div>
      <div class="stat"><div class="v" id="best">–</div><div class="k">ベストラップ</div></div>
      <div class="stat"><div class="v" id="last">–</div><div class="k">前周</div></div>
      <div class="stat"><div class="v" id="rpm">–</div><div class="k">回転数</div></div>
    </div>
    <div class="stats">
      <div class="stat" style="grid-column: span 3"><div class="k">アクセル</div><div class="bar"><div id="throttle"></div></div>
      <div class="k" style="margin-top:8px">ブレーキ</div><div class="bar brake"><div id="brake"></div></div></div>
    </div>
  </section>
  <section class="card">
    <h2>稼ぎ</h2>
    <div><span class="big" id="per_hour">–</span><span class="unit">Cr / 時間</span></div>
    <table>
      <tr><td>今回の起動から（<span id="since">–</span>）</td><td id="session_credits">–</td></tr>
      <tr><td>レース数 / 1位</td><td id="session_races">–</td></tr>
      <tr><td>経過時間</td><td id="session_hours">–</td></tr>
      <tr><td>今日</td><td id="today_credits">–</td></tr>
      <tr><td>今日のレース数 / 1位</td><td id="today_races">–</td></tr>
      <tr><td>今日の 1時間あたり</td><td id="today_per_hour">–</td></tr>
    </table>
    <p class="note">1位で終えたレースを、1レースあたりの賞金（1位＋クリーンレースボーナス）で数えた推定値です。</p>
  </section>
  <section class="card" style="grid-column: 1 / -1">
    <h2>ログ</h2>
    <pre id="log"></pre>
  </section>
</div>
</main>
<script>
const $ = id => document.getElementById(id);
let stopPlanned = false;
async function act(action) {
  if (action === 'start' && !confirm('GT7 のカーソルが「スタート」にあることを確認しましたか？')) return;
  $('message').textContent = '実行中…';
  try {
    const r = await (await fetch('api/' + action, {method: 'POST', headers: {'X-GT7-Control': '1'}})).json();
    $('message').textContent = r.output || (r.ok ? '完了' : '失敗');
  } catch (e) { $('message').textContent = '失敗: ' + e; }
  update();
}
const toggleStop = () => act(stopPlanned ? 'cancel-stop' : 'stop-after-race');
const fmt = n => Math.round(n).toLocaleString('ja-JP');
const lapTime = ms => ms > 0 ? `${Math.floor(ms / 60000)}:${((ms % 60000) / 1000).toFixed(3).padStart(6, '0')}` : '–';
const hours = h => `${Math.floor(h)}時間${String(Math.round((h % 1) * 60)).padStart(2, '0')}分`;
async function update() {
  let s;
  try { s = await (await fetch('api', {cache: 'no-store'})).json(); }
  catch (e) { $('status').textContent = 'サーバーに接続できません'; $('status').className = 'badge warn'; return; }
  const t = s.telemetry && s.telemetry.age < 3 ? s.telemetry : null;
  let label = s.running ? '動作中' : '停止中', cls = s.running ? 'ok' : 'warn';
  if (t) label += t.paused ? '・ポーズ中' : t.on_track ? (t.lap > t.laps ? '・ゴール後' : '・レース中') : '・メニュー';
  else label += '・テレメトリーなし';
  if (s.running && s.stop_after_race) label += '・このレースで停止予定';
  $('status').textContent = label; $('status').className = 'badge ' + cls;
  stopPlanned = s.stop_after_race;
  $('start').disabled = s.running;
  $('stop-after-race').disabled = !s.running;
  $('stop-after-race').textContent = stopPlanned ? '停止予定を取り消す' : 'このレースで停止';
  $('emergency').disabled = !s.running;
  $('speed').textContent = t ? t.speed : '–';
  $('lap').textContent = t && t.laps ? `${Math.min(t.lap, t.laps)} / ${t.laps}` : '–';
  $('position').textContent = t && t.position > 0 ? `${t.position}位` : '–';
  $('gear').textContent = t && 'gear' in t ? (t.gear || 'N') : '–';
  $('best').textContent = t ? lapTime(t.best) : '–';
  $('last').textContent = t ? lapTime(t.last) : '–';
  $('rpm').textContent = t && 'rpm' in t ? fmt(t.rpm) : '–';
  $('throttle').style.width = t && 'throttle' in t ? `${t.throttle / 2.55}%` : 0;
  $('brake').style.width = t && 'brake' in t ? `${t.brake / 2.55}%` : 0;
  const a = s.session, d = s.today;
  $('per_hour').textContent = fmt(a.per_hour);
  $('since').textContent = s.session_start || '–';
  $('session_credits').textContent = `${fmt(a.credits)} Cr`;
  $('session_races').textContent = `${a.races} / ${a.wins}`;
  $('session_hours').textContent = hours(a.hours);
  $('today_credits').textContent = `${fmt(d.credits)} Cr`;
  $('today_races').textContent = `${d.races} / ${d.wins}`;
  $('today_per_hour').textContent = `${fmt(d.per_hour)} Cr`;
  $('log').textContent = s.log.join('\\n');
}
update(); setInterval(update, 1000);
</script>
</body>
</html>
'''


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split('?')[0] == '/api':
            body, kind = json.dumps(state()).encode(), 'application/json'
        elif self.path.split('?')[0] == '/':
            body, kind = PAGE.encode(), 'text/html; charset=utf-8'
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        # a custom header can't be sent cross-site without a CORS preflight, which
        # this server never allows, so other web pages can't press these buttons
        action = self.path.split('?')[0].removeprefix('/api/')
        if self.headers.get('X-GT7-Control') != '1' or action not in ACTIONS:
            self.send_error(403)
            return
        body = json.dumps(run_script(action)).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def address():
    if os.environ.get('WEB_ADDRESS'):
        return os.environ['WEB_ADDRESS']
    out = subprocess.run(['tailscale', 'ip', '-4'], capture_output=True, text=True).stdout.split()
    if not out:
        sys.exit('No Tailscale address (is tailscale up?). Set WEB_ADDRESS to choose one.')
    return out[0]


def web_pid():
    try:
        pid = int(open(PID_FILE).read())
        if b'gt7-web.py' in open('/proc/%d/cmdline' % pid, 'rb').read():
            return pid
    except (OSError, ValueError):
        pass
    return None


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else 'serve'
    if command == 'serve':
        host = address()
        server = http.server.ThreadingHTTPServer((host, WEB_PORT), Handler)
        os.makedirs(CACHE, exist_ok=True)
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
        print('Serving on http://%s:%d/' % (host, WEB_PORT), flush=True)
        server.serve_forever()
    elif command == 'start':
        if web_pid():
            sys.exit('Already running (pid %d)' % web_pid())
        with open(WEB_LOG, 'a') as log:
            subprocess.Popen([sys.executable, os.path.abspath(__file__), 'serve'], stdout=log,
                             stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
        time.sleep(1)
        print(open(WEB_LOG).read().splitlines()[-1])
    elif command == 'stop':
        pid = web_pid()
        if not pid:
            print('Not running')
            return
        os.kill(pid, signal.SIGTERM)
        print('Stopped')
    elif command == 'status':
        pid = web_pid()
        print('Running (pid %d)' % pid if pid else 'Not running')
    else:
        sys.exit('Usage: gt7-web.py [serve|start|stop|status]')


main()
