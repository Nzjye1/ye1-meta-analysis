@echo off
setlocal
rem Official first-use bootstrap. Does not invoke PowerShell or edit policy/PATH.
if "%~1"=="" goto usage
set "RUNTIME=%~f1"
set "PROFILE=%~2"
set "ACTION=install"
if "%~4"=="prepare-python" set "ACTION=prepare-python"
if not "%~4"=="" if not "%~4"=="prepare-python" goto usage
if "%PROFILE%"=="" set "PROFILE=standard"
if /i "%PROFILE%"=="core" goto profile_ok
if /i "%PROFILE%"=="standard" goto profile_ok
if /i "%PROFILE%"=="docling" goto profile_ok
echo Unsupported profile. Use core, standard or docling.
exit /b 2
:profile_ok
if not "%~3"=="I_ACCEPT" goto usage
if exist "%RUNTIME%\.official-python-bootstrap" goto owned
if exist "%RUNTIME%" (
  echo Existing unowned target refused. Choose a fresh runtime directory.
  exit /b 2
)
mkdir "%RUNTIME%"
if errorlevel 1 exit /b 2
>"%RUNTIME%\.official-python-bootstrap" echo c66c6e75aba5cc0434541089127557010da2af9f6ef653abc14bdb694fdf3594
:owned
findstr /x /i "c66c6e75aba5cc0434541089127557010da2af9f6ef653abc14bdb694fdf3594" "%RUNTIME%\.official-python-bootstrap" >nul
if errorlevel 1 exit /b 2
where curl.exe >nul 2>nul
if errorlevel 1 goto missing_tools
where tar.exe >nul 2>nul
if errorlevel 1 goto missing_tools
where certutil.exe >nul 2>nul
if errorlevel 1 goto missing_tools
if not exist "%RUNTIME%\downloads" mkdir "%RUNTIME%\downloads"
set "PYZIP=%RUNTIME%\downloads\c66c6e75aba5cc0434541089127557010da2af9f6ef653abc14bdb694fdf3594_python-3.14.5-amd64.zip"
if exist "%PYZIP%" goto verify_zip
curl.exe --fail --location --proto "=https" --proto-redir "=https" --tlsv1.2 --retry 2 --output "%PYZIP%.part" "https://www.python.org/ftp/python/3.14.5/python-3.14.5-amd64.zip"
if errorlevel 1 goto failed
certutil.exe -hashfile "%PYZIP%.part" SHA256 | findstr /x /i "c66c6e75aba5cc0434541089127557010da2af9f6ef653abc14bdb694fdf3594" >nul
if errorlevel 1 goto failed
move "%PYZIP%.part" "%PYZIP%" >nul
if errorlevel 1 goto failed
:verify_zip
certutil.exe -hashfile "%PYZIP%" SHA256 | findstr /x /i "c66c6e75aba5cc0434541089127557010da2af9f6ef653abc14bdb694fdf3594" >nul
if errorlevel 1 goto failed
rem The installer host is separate from native\python, which it prepares.
rem Completion markers are written only after a successful full extraction.
set "BOOTBASE=%RUNTIME%\bootstrap\python-c66c6e75aba5cc0434541089127557010da2af9f6ef653abc14bdb694fdf3594"
set "BOOTATTEMPT=0"
:select_bootstrap
set "BOOTSTRAP=%BOOTBASE%"
if not "%BOOTATTEMPT%"=="0" set "BOOTSTRAP=%BOOTBASE%-attempt-%BOOTATTEMPT%"
if exist "%BOOTSTRAP%\.complete" (
  findstr /x /i "c66c6e75aba5cc0434541089127557010da2af9f6ef653abc14bdb694fdf3594" "%BOOTSTRAP%\.complete" >nul
  if errorlevel 1 goto failed
  if not exist "%BOOTSTRAP%\python.exe" goto failed
  goto install
)
if not exist "%BOOTSTRAP%" goto extract_bootstrap
echo Incomplete bootstrap preserved: "%BOOTSTRAP%"
set /a BOOTATTEMPT+=1 >nul
if %BOOTATTEMPT% GTR 16 goto failed
goto select_bootstrap
:extract_bootstrap
mkdir "%BOOTSTRAP%"
if errorlevel 1 goto failed
tar.exe -xf "%PYZIP%" -C "%BOOTSTRAP%"
if errorlevel 1 goto failed
>"%BOOTSTRAP%\.complete" echo c66c6e75aba5cc0434541089127557010da2af9f6ef653abc14bdb694fdf3594
:install
"%BOOTSTRAP%\python.exe" -I -B "%~dp0tools\online_setup.py" %ACTION% --root "%RUNTIME%" --profile "%PROFILE%" --allow-network --accept-third-party-terms
exit /b %errorlevel%
:missing_tools
echo This bootstrap requires allowed curl.exe, tar.exe and certutil.exe commands. Stop and report missing tools; no policy or system changes are made.
exit /b 2
:failed
echo Setup stopped. Keep the runtime directory, partial files and error. Do not change policy or switch launch methods after a denial.
exit /b 2
:usage
echo Usage: setup-online.cmd NEW_RUNTIME_DIRECTORY core^|standard^|docling I_ACCEPT
echo Maintainer regression only: append prepare-python to stop before R/packages. This does not produce READY.json.
echo First read INSTALL.md and THIRD-PARTY.md. I_ACCEPT confirms permission to install official dependencies and acceptance of applicable original terms.
echo standard preserves all statistical routes; docling additionally downloads optional PDF dependencies and models.
exit /b 2
