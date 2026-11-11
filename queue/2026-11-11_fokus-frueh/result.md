## BUILD FAILED

```
Traceback (most recent call last):
  File "/home/runner/work/ekkkrtrrrp/ekkkrtrrrp/eilblick/main.py", line 340, in cmd_run
    return _cmd_run(args)
           ^^^^^^^^^^^^^^
  File "/home/runner/work/ekkkrtrrrp/ekkkrtrrrp/eilblick/main.py", line 366, in _cmd_run
    plan = editor.load_plan(d / "plan.json")
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/ekkkrtrrrp/ekkkrtrrrp/eilblick/editor.py", line 218, in load_plan
    return json.loads(Path(path).read_text(encoding="utf-8"))
                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.12.16/x64/lib/python3.12/pathlib.py", line 1027, in read_text
    with self.open(mode='r', encoding=encoding, errors=errors) as f:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.12.16/x64/lib/python3.12/pathlib.py", line 1013, in open
    return io.open(self, mode, buffering, encoding, errors, newline)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
FileNotFoundError: [Errno 2] No such file or directory: '/home/runner/work/ekkkrtrrrp/ekkkrtrrrp/queue/2026-11-11_fokus-frueh/plan.json'

```
