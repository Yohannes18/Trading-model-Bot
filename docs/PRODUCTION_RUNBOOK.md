# Quantara Production Runbook (Windows)

## 1) Pre-flight checks

- Run all commands from project root (for example `C:\Quantara`).
- Python virtual environment exists at `.venv`.
- Runtime folders exist: `data`, `logs`, `signals`, `cache`.
- `.env` is configured with production credentials and risk parameters.
- Dry run passes:

```powershell
.\.venv\Scripts\python.exe -m quantara.main --test
```

## 2) Install background startup (Task Scheduler)

Run PowerShell as Administrator:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\windows\install_task.ps1
```

This creates task `QuantaraEngine` to auto-start at boot and restart on failure.

## 3) Install log maintenance task

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\windows\install_log_cleanup_task.ps1
```

This creates daily task `QuantaraLogCleanup` to rotate old logs.

## 4) Health and readiness probes

- Liveness: `GET /livez`
- Readiness: `GET /readyz`
- Readiness alias: `GET /readiness`
- Runtime health: `GET /health`

Probe examples:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/livez
Invoke-RestMethod http://127.0.0.1:8000/readyz
Invoke-RestMethod http://127.0.0.1:8000/health
```

## 5) Runtime operations

Start task:

```powershell
Start-ScheduledTask -TaskName "QuantaraEngine"
```

Stop task:

```powershell
Stop-ScheduledTask -TaskName "QuantaraEngine"
```

View latest logs:

```powershell
Get-Content .\logs\quantara.log -Tail 100
```

## 6) Staged rollout recommendation

1. Validate with `--test`
2. Run shadow period
3. Start with small capital and reduced risk settings
4. Increase risk only after stable telemetry and trade outcomes

## 7) Incident rollback

- Stop engine task immediately:

```powershell
Stop-ScheduledTask -TaskName "QuantaraEngine"
```

- Reduce risk in `.env`
- Re-run one-cycle test
- Restart only when `/readyz` returns `READY`
