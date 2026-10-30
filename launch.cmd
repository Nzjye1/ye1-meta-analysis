@echo off
setlocal
if defined META_PYTHON (
  "%META_PYTHON%" -B "%~dp0candidate_entry.py" %*
) else (
  python -B "%~dp0candidate_entry.py" %*
)
exit /b %errorlevel%
