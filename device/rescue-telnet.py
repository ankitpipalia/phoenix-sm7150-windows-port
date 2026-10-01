#!/usr/bin/env python3
"""Run commands in the postmarketOS initramfs debug shell over telnet (busybox
telnetd), and move files to/from it over netcat. The rescue shell has no sshd;
this is how a host drives it.

  rescue-telnet.py run 'cmd1' 'cmd2' ...      run commands, print output
  rescue-telnet.py push LOCAL REMOTE          copy a host file to the phone
  rescue-telnet.py pull REMOTE LOCAL          copy a phone file to the host

HOST defaults to 172.16.42.1 (USB networking). A one-shot `nc -l` on the phone
serves one transfer; do not probe the port first, that consumes the listener.
"""
import socket
import subprocess
import sys
import time

HOST = __import__('os').environ.get('HOST', '172.16.42.1')
IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240


def _clean(sock, data):
    out, i = bytearray(), 0
    while i < len(data):
        b = data[i]
        if b == IAC and i + 1 < len(data):
            cmd = data[i + 1]
            if cmd in (DO, DONT, WILL, WONT) and i + 2 < len(data):
                sock.sendall(bytes([IAC, WONT if cmd in (DO, DONT) else DONT, data[i + 2]]))
                i += 3
                continue
            if cmd == SB:
                j = data.find(bytes([IAC, SE]), i)
                i = j + 2 if j >= 0 else len(data)
                continue
            i += 2
            continue
        out.append(b)
        i += 1
    return out.decode('utf-8', 'replace')


def _read_for(sock, seconds):
    sock.settimeout(0.5)
    end, buf = time.time() + seconds, ''
    while time.time() < end:
        try:
            d = sock.recv(65536)
            if not d:
                break
            buf += _clean(sock, d)
        except socket.timeout:
            pass
    return buf


def run(cmds):
    s = socket.create_connection((HOST, 23), timeout=10)
    print(_read_for(s, 3), end='')
    for cmd in cmds:
        marker = 'END-%d' % time.time_ns()
        s.sendall((cmd + '; echo ' + marker + '\n').encode())
        buf, end = '', time.time() + 180
        while marker not in buf.split('echo ' + marker)[-1] and time.time() < end:
            buf += _read_for(s, 1)
        print(buf.replace('echo ' + marker, '').replace(marker, '').strip())
    s.close()


def push(local, remote, port=5000):
    data = open(local, 'rb').read()
    import threading
    t = threading.Thread(target=run, args=([f'nc -l -p {port} > {remote}; echo recv-$(stat -c %s {remote})'],), daemon=True)
    t.start()
    time.sleep(7)
    s = socket.create_connection((HOST, port), timeout=10)
    s.sendall(data)
    s.shutdown(socket.SHUT_WR)
    s.close()
    print(f'pushed {len(data)} bytes to {remote}')
    t.join(timeout=10)


def pull(remote, local, port=5000):
    import threading
    t = threading.Thread(target=run, args=([f'nc -l -p {port} < {remote}; echo sent'],), daemon=True)
    t.start()
    time.sleep(7)
    out = subprocess.run(['nc', '-w', '30', HOST, str(port)], capture_output=True)
    open(local, 'wb').write(out.stdout)
    print(f'pulled {len(out.stdout)} bytes to {local}')
    t.join(timeout=10)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == 'run':
        run(sys.argv[2:])
    elif cmd == 'push':
        push(sys.argv[2], sys.argv[3])
    elif cmd == 'pull':
        pull(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
