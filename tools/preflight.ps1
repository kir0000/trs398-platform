# Checks of the computer before the start (called from start.bat): Windows, virtualization, WSL 2, Docker Desktop, disk, port.
# Проверка компьютера перед запуском (вызывается из start.bat).
# Exit code / код выхода: 0 = ready, 1 = a problem (the reason and what to do are printed / причина и что делать выведены).
# -Lang ru|en   language of the messages / язык сообщений;  -NonInteractive  asks nothing;
# -Simulate virt | wsl | docker | docker-stopped | port   shows the messages of a problem without having it.
param([switch]$NonInteractive, [string]$Simulate = '', [string]$Lang = 'ru')
$ErrorActionPreference = 'SilentlyContinue'
$script:problems = 0
if ($Lang -ne 'en') { $Lang = 'ru' }

$T = @{
  ru = @{
    title = 'Проверка компьютера перед запуском программы'
    yn = '(д/н)'
    win_ok = 'Windows (сборка {0})'
    win_old = 'Windows слишком старая (сборка {0}). Нужна Windows 10 версии 22H2 или Windows 11.'
    win_old_h = 'Обновите систему: Параметры → Обновление и безопасность.'
    virt_ok = 'Виртуализация включена'
    virt_bad = 'Виртуализация выключена в BIOS/UEFI, Docker без неё не запустится.'
    virt_h1 = 'При включении компьютера нажмите Del, F2 или F10, найдите Intel Virtualization Technology (VT-x)'
    virt_h2 = 'или у AMD «SVM Mode», поставьте Enabled, сохраните и перезагрузитесь. На рабочем компьютере больницы это делает ИТ-отдел.'
    virt_unk = 'Не удалось подтвердить работу виртуализации (возможно, WSL ещё не установлена или не перезагружена).'
    virt_unk_h = 'Если дальше будет ошибка, проверьте: Диспетчер задач → Производительность → ЦП → «Виртуализация: Включено».'
    wsl_ok = 'WSL 2 установлена'
    wsl_bad = 'WSL 2 не установлена. Она нужна Docker Desktop.'
    wsl_ask = 'Установить WSL сейчас? Откроется окно администратора, потом нужна перезагрузка'
    wsl_done = 'Готово. Нажмите Enter и ПЕРЕЗАГРУЗИТЕ компьютер'
    wsl_reboot = 'Перезагрузите компьютер и запустите start.bat снова.'
    wsl_h1 = 'Откройте PowerShell от имени администратора (правый щелчок по «Пуск» → Терминал (Администратор)),'
    wsl_h2 = 'выполните  wsl --install --no-distribution  затем перезагрузите компьютер.'
    dk_ok = 'Docker Desktop установлен'
    dk_bad = 'Docker Desktop не установлен.'
    dk_h1 = 'Скачайте https://www.docker.com/products/docker-desktop/ , установите (галочка «Use WSL 2»), перезагрузите компьютер.'
    dk_h2 = 'Подробно: docs\INSTALL.md'
    dk_open = 'Открыть страницу загрузки в браузере?'
    run_ok = 'Docker запущен (Engine running)'
    run_warn = 'Docker Desktop не запущен.'
    run_ask = 'Запустить Docker Desktop и подождать до 3 минут?'
    run_wait = 'ждём запуска'
    run_ok2 = 'Docker запущен'
    run_bad = 'Docker не запущен.'
    run_h1 = 'Запустите Docker Desktop из меню «Пуск». При первом запуске примите лицензию (регистрацию можно пропустить: Skip).'
    run_h2 = 'Дождитесь, пока внизу слева появится «Engine running», и запустите start.bat снова.'
    disk_ok = 'Свободно на диске {0}: {1} ГБ'
    disk_warn = 'На диске {0}: свободно только {1} ГБ (желательно от 10 ГБ).'
    disk_bad = 'На диске {0}: свободно {1} ГБ, этого не хватит для сборки. Освободите место.'
    sync_warn = 'Папка находится в облачной синхронизации (OneDrive, Яндекс.Диск и т.п.): она может портить файлы базы и кода.'
    sync_h = 'Надёжнее перенести программу в обычную папку, например C:\trs398 (без русских букв в пути).'
    port_docker = 'Порт {0} занят Docker (программа уже запущена или перезапускается)'
    port_bad = 'Порт {0} уже занят программой «{1}».'
    port_h = 'Освободите порт или в файле .env добавьте строку  APP_PORT=8080  (адрес станет http://localhost:8080).'
    port_ok = 'Порт {0} свободен'
    fail = 'Исправьте отмеченные [ХХХ] пункты и запустите start.bat снова.'
    ready = 'Всё готово к запуску.'
  }
  en = @{
    title = 'Checking the computer before starting the program'
    yn = '(y/n)'
    win_ok = 'Windows (build {0})'
    win_old = 'Windows is too old (build {0}). Windows 10 version 22H2 or Windows 11 is required.'
    win_old_h = 'Update the system: Settings > Update and security.'
    virt_ok = 'Virtualization is on'
    virt_bad = 'Virtualization is off in the BIOS/UEFI; Docker will not start without it.'
    virt_h1 = 'When the computer starts press Del, F2 or F10, find Intel Virtualization Technology (VT-x)'
    virt_h2 = 'or, on AMD, "SVM Mode", set Enabled, save and restart. On a hospital work computer the IT department does this.'
    virt_unk = 'Could not confirm that virtualization works (maybe WSL is not installed yet or not restarted).'
    virt_unk_h = 'If an error follows, check: Task Manager > Performance > CPU > "Virtualization: Enabled".'
    wsl_ok = 'WSL 2 is installed'
    wsl_bad = 'WSL 2 is not installed. Docker Desktop needs it.'
    wsl_ask = 'Install WSL now? An administrator window opens, then a restart is needed'
    wsl_done = 'Done. Press Enter and RESTART the computer'
    wsl_reboot = 'Restart the computer and run start.bat again.'
    wsl_h1 = 'Open PowerShell as administrator (right-click Start > Terminal (Admin)),'
    wsl_h2 = 'run  wsl --install --no-distribution  then restart the computer.'
    dk_ok = 'Docker Desktop is installed'
    dk_bad = 'Docker Desktop is not installed.'
    dk_h1 = 'Download https://www.docker.com/products/docker-desktop/ , install it (keep "Use WSL 2" ticked), restart the computer.'
    dk_h2 = 'Details: docs\INSTALL.en.md'
    dk_open = 'Open the download page in the browser?'
    run_ok = 'Docker is running (Engine running)'
    run_warn = 'Docker Desktop is not running.'
    run_ask = 'Start Docker Desktop and wait up to 3 minutes?'
    run_wait = 'waiting for it to start'
    run_ok2 = 'Docker is running'
    run_bad = 'Docker is not running.'
    run_h1 = 'Start Docker Desktop from the Start menu. At the first start accept the licence (you can skip the sign-in: Skip).'
    run_h2 = 'Wait until "Engine running" appears at the bottom left, then run start.bat again.'
    disk_ok = 'Free space on drive {0}: {1} GB'
    disk_warn = 'Drive {0}: only {1} GB free (10 GB or more is recommended).'
    disk_bad = 'Drive {0}: {1} GB free, which is not enough for the build. Free some space.'
    sync_warn = 'The folder is inside a cloud sync (OneDrive, Yandex.Disk, etc.): it may damage the database and code files.'
    sync_h = 'It is safer to move the program to an ordinary folder, for example C:\trs398 (no non-Latin letters in the path).'
    port_docker = 'Port {0} is held by Docker (the program is already running or restarting)'
    port_bad = 'Port {0} is already used by the program "{1}".'
    port_h = 'Free the port or add the line  APP_PORT=8080  to the file .env (the address becomes http://localhost:8080).'
    port_ok = 'Port {0} is free'
    fail = 'Fix the items marked [XXX] and run start.bat again.'
    ready = 'Everything is ready to start.'
  }
}

function M($key, $a0 = $null, $a1 = $null) { ($T[$Lang][$key]) -f $a0, $a1 }
function Ok($t)   { Write-Host "  [ OK ]  $t" -ForegroundColor Green }
function Warn($t) { Write-Host "  [ ! ]   $t" -ForegroundColor Yellow }
function Bad($t)  { $mark = if ($Lang -eq 'en') { '[XXX]' } else { '[ХХХ]' }; Write-Host "  $mark   $t" -ForegroundColor Red; $script:problems++ }
function Hint($t) { Write-Host "          $t" -ForegroundColor Gray }
function Ask($q)  {
    if ($NonInteractive) { return $false }
    $a = Read-Host ("          {0} {1}" -f $q, (M 'yn'))
    return ($a -match '^(д|да|y|yes)$')
}
function Done($code) { exit $code }

Write-Host ''
Write-Host (M 'title') -ForegroundColor Cyan
Write-Host ''

# 1. Windows
$build = [Environment]::OSVersion.Version.Build
if ($build -ge 19045) { Ok (M 'win_ok' $build) }
else { Bad (M 'win_old' $build); Hint (M 'win_old_h') }

# 2. Virtualization
$cs  = Get-CimInstance Win32_ComputerSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$hv  = [bool]$cs.HypervisorPresent
$fw  = $cpu.VirtualizationFirmwareEnabled
if ($Simulate -eq 'virt') { $hv = $false; $fw = $false }
if ($hv) { Ok (M 'virt_ok') }
elseif ($fw -eq $false) { Bad (M 'virt_bad'); Hint (M 'virt_h1'); Hint (M 'virt_h2') }
else { Warn (M 'virt_unk'); Hint (M 'virt_unk_h') }

# 3. WSL 2
$wslInstalled = $false
if ($Simulate -ne 'wsl') {
    $wsl = Get-Command wsl.exe
    if ($wsl) {
        & wsl.exe --version *> $null
        if ($LASTEXITCODE -eq 0) { $wslInstalled = $true }
        else { & wsl.exe --status *> $null; if ($LASTEXITCODE -eq 0) { $wslInstalled = $true } }
    }
}
if ($wslInstalled) { Ok (M 'wsl_ok') }
else {
    Bad (M 'wsl_bad')
    if (Ask (M 'wsl_ask')) {
        $done = M 'wsl_done'
        Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile', '-Command',
            "wsl --install --no-distribution; Write-Host ''; Read-Host '$done'"
        Write-Host ''
        Write-Host ('  ' + (M 'wsl_reboot')) -ForegroundColor Yellow
        Done 1
    }
    else { Hint (M 'wsl_h1'); Hint (M 'wsl_h2') }
}

# 4. Docker Desktop installed?
$dockerCmd = Get-Command docker.exe
if ($Simulate -eq 'docker') { $dockerCmd = $null }
$exe = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
if ($dockerCmd -or (Test-Path $exe)) { Ok (M 'dk_ok') }
else {
    Bad (M 'dk_bad'); Hint (M 'dk_h1'); Hint (M 'dk_h2')
    if (Ask (M 'dk_open')) { Start-Process 'https://www.docker.com/products/docker-desktop/' }
}

# 5. Docker running?
if ($dockerCmd -or (Test-Path $exe)) {
    $running = $false
    if ($Simulate -ne 'docker-stopped') { & docker.exe info *> $null; $running = ($LASTEXITCODE -eq 0) }
    if ($running) { Ok (M 'run_ok') }
    else {
        Warn (M 'run_warn')
        if ((Test-Path $exe) -and (Ask (M 'run_ask'))) {
            Start-Process $exe
            Write-Host -NoNewline ('          ' + (M 'run_wait'))
            for ($i = 0; $i -lt 60 -and -not $running; $i++) {
                Start-Sleep -Seconds 3
                Write-Host -NoNewline '.'
                & docker.exe info *> $null
                $running = ($LASTEXITCODE -eq 0)
            }
            Write-Host ''
        }
        if ($running) { Ok (M 'run_ok2') }
        else { Bad (M 'run_bad'); Hint (M 'run_h1'); Hint (M 'run_h2') }
    }
}

# 6. Disk space
$drive = (Get-Location).Drive
if ($drive) {
    $free = [math]::Round((Get-PSDrive $drive.Name).Free / 1GB, 1)
    if ($free -ge 10) { Ok (M 'disk_ok' $drive.Name $free) }
    elseif ($free -ge 3) { Warn (M 'disk_warn' $drive.Name $free) }
    else { Bad (M 'disk_bad' $drive.Name $free) }
}

# 7. A folder inside a cloud sync (this already caused file conflicts)
if ($PWD.Path -match 'OneDrive|Yandex|Яндекс|Dropbox|Google Drive') { Warn (M 'sync_warn'); Hint (M 'sync_h') }

# 8. Port
$port = 8000
if (Test-Path '.env') {
    $line = Get-Content '.env' | Where-Object { $_ -match '^APP_PORT=\d+' } | Select-Object -First 1
    if ($line) { $port = [int]($line -replace '^APP_PORT=', '') }
}
$listen = Get-NetTCPConnection -LocalPort $port -State Listen | Select-Object -First 1
if ($Simulate -eq 'port') { $listen = [pscustomobject]@{ OwningProcess = $PID } }
if ($listen) {
    $name = (Get-Process -Id $listen.OwningProcess).ProcessName
    if ($name -match 'docker|wslrelay|vpnkit|com\.docker') { Ok (M 'port_docker' $port) }
    else { Bad (M 'port_bad' $port $name); Hint (M 'port_h') }
}
else { Ok (M 'port_ok' $port) }

Write-Host ''
if ($script:problems -gt 0) {
    Write-Host ('  ' + (M 'fail')) -ForegroundColor Red
    Write-Host ''
    Done 1
}
Write-Host ('  ' + (M 'ready')) -ForegroundColor Green
Write-Host ''
Done 0
