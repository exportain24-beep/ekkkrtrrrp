## BUILD FAILED

```
Traceback (most recent call last):
  File "/home/runner/work/ekkkrtrrrp/ekkkrtrrrp/eilblick/main.py", line 340, in cmd_run
    return _cmd_run(args)
           ^^^^^^^^^^^^^^
  File "/home/runner/work/ekkkrtrrrp/ekkkrtrrrp/eilblick/main.py", line 369, in _cmd_run
    raise RuntimeError("plan invalid: " + "; ".join(errs))
RuntimeError: plan invalid: hook_voice: the shock itself, max 8 words (spoken within ~1.5 s); youtube_title too long: max 60 characters, keyword within the first 40 (Shorts truncate ~40); repeat: shares ['gespräche', 'ukraine', 'ukraine-gespräche'] with 'Der Tag in 45 Sekunden: Erste Einigung bei Ukraine-Gesprächen?' (2026-11-10 nacht) – pick a different story (max once per 24 h) or, only for a hard new fact, set "new_development" to that fact

```
