@echo off
rem Sets the language of the scripts: variable L (ru or en) and the message variables of tools\msg.<L>.bat.
rem Order: TRS_LANG in .env, otherwise the language of Windows. Call from the project folder:  call tools\lang.bat
chcp 65001 >nul
set "L="
if exist ".env" for /f "tokens=2 delims==" %%a in ('findstr /b "TRS_LANG=" .env 2^>nul') do set "L=%%a"
if not "%L%"=="ru" if not "%L%"=="en" (
  set "L=en"
  for /f %%c in ('powershell -NoProfile -Command "(Get-Culture).TwoLetterISOLanguageName"') do if /i "%%c"=="ru" set "L=ru"
)
call tools\msg.%L%.bat
