"""Development-only login to the local SSH-tunnel preview without printing secrets."""
import getpass
import json
from pathlib import Path
import subprocess
import tempfile

import paramiko


def bridge(action, args):
    body = {"session": "research-data-center-v2", "action": action, "args": args}
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", prefix="rdc-auth-", delete=False) as handle:
        json.dump(body, handle, ensure_ascii=False)
        request_path = Path(handle.name)
    try:
        result = subprocess.run(["curl.exe", "-sS", "--max-time", "30", "-X", "POST",
                                 "http://127.0.0.1:10086/command", "-H", "Content-Type: application/json",
                                 "--data-binary", "@" + str(request_path)], capture_output=True, check=True)
        reply = json.loads(result.stdout)
        if not reply.get("ok"):
            raise RuntimeError("Browser command failed")
        return reply["data"]
    finally:
        request_path.unlink(missing_ok=True)


if __name__ == "__main__":
    current = bridge("evaluate", {"code": "location.origin"})
    if current.get("value") != "http://127.0.0.1:18765":
        raise RuntimeError("Select the exact local SSH-tunnel application tab first")
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.load_host_keys(str(Path.home() / ".ssh" / "known_hosts"))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        password = getpass.getpass("SSH password (hidden): ")
        client.connect("101.132.97.146", username="rmp", password=password, timeout=20,
                       look_for_keys=False, allow_agent=False)
        del password
        with client.open_sftp() as sftp:
            with sftp.open("/data/rmp/research-data-center/var/access-token") as handle:
                token = handle.read(4096).decode("utf-8").strip()
        code = "(async()=>{if(location.origin!==\"http://127.0.0.1:18765\")throw Error(\"Wrong origin\");const r=await fetch(\"/api/session\",{method:\"POST\",credentials:\"same-origin\",headers:{\"Content-Type\":\"application/json\"},body:JSON.stringify({token:" + json.dumps(token) + "})});return JSON.stringify({status:r.status,authenticated:(await r.json()).authenticated===true})})()"
        reply = bridge("evaluate", {"code": code})
        del token, code
        result = json.loads(reply["value"])
        assert result == {"status": 200, "authenticated": True}, "Browser session failed"
        print("Browser session authenticated through the local SSH tunnel.")
    finally:
        client.close()
