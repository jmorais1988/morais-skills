import socket, json, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
def run(code, timeout=300):
    s=socket.socket(); s.settimeout(timeout); s.connect(('localhost',9876))
    s.sendall(json.dumps({"type":"execute","code":code,"strict_json":False}).encode()+b"\0")
    buf=b''
    while b"\0" not in buf:
        c=s.recv(1<<20)
        if not c: break
        buf+=c
    s.close()
    return json.loads(buf.split(b"\0")[0].decode())
if __name__=="__main__":
    code=open(sys.argv[1]).read() if len(sys.argv)>1 else sys.stdin.read()
    r=run(code)
    if r.get("stdout"): print(r["stdout"])
    if r.get("stderr"): print("STDERR:",r["stderr"])
    if r.get("status")!="ok": print("ERROR:",r.get("message"))
    elif r.get("result") is not None: print(json.dumps(r["result"],indent=1)[:20000])
