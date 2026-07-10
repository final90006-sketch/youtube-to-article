# -*- coding: utf-8 -*-
"""py 包一層跑 node 的 SR 引擎測試；無 node 則 SKIP（exit 0）。"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
JS = HERE / "test_sr_engine.js"


def main():
    node = shutil.which("node")
    if not node:
        print("SKIP: node not found")
        return 0
    r = subprocess.run([node, str(JS)], capture_output=True, text=True, encoding="utf-8")
    sys.stdout.write(r.stdout or "")
    sys.stderr.write(r.stderr or "")
    if r.returncode != 0 or "ALL PASS" not in (r.stdout or ""):
        print("SR engine node test FAILED")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
