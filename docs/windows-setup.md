# Настройка TiGames на Windows с нуля

Руководство рассчитано на Windows 11 x64 с доступом в интернет. Все команды
выполняются вручную: отдельных файлов установочных скриптов нет.

Рекомендуемый маршрут для TiGames — **WSL2 + Ubuntu 24.04**. В Linux Cairo
и Poppler устанавливаются через `apt`; Python и зависимости проекта ведёт uv.
Если WSL использовать нельзя, в конце приведён отдельный маршрут для Windows.
Выберите один маршрут и создавайте окружение `.venv` в соответствующей системе.

Проверка свежего клона, установки зависимостей и пяти тестов выполнена на macOS.
Команды Windows/WSL сверены с документацией поставщиков, но полный прогон
на чистой Windows или WSL пока не выполнен. ARM64 этим руководством не проверен.

## Что будет установлено

| Компонент | Где | Назначение |
| --- | --- | --- |
| WinGet | Windows | Установка и обслуживание программ Windows |
| Git for Windows | Windows | Git в PowerShell и интеграция настольного приложения |
| ChatGPT desktop с Codex | Windows | Работа агента с проектом и фотографиями |
| WSL2 и Ubuntu 24.04 | Windows / Linux | Среда исполнения Python-конвейера |
| Git, curl, Cairo, Poppler | Ubuntu | Клонирование, установка uv, создание и проверка PNG/PDF |
| uv и Python 3.13 | Ubuntu | Изолированное окружение и зависимости по `uv.lock` |

Для запуска тестов и обработки готового контурного рисунка вход в ChatGPT
не требуется. Для стадии «фото → контуры» нужен агент с доступным инструментом
генерации/редактирования изображений. Сам `build.py` принимает контурный рисунок.

## 1. Проверить или установить WinGet

Откройте **PowerShell** и выполните:

```powershell
winget --version
```

Если версия выведена, переходите к шагу 2. Если команда не найдена,
установите или обновите **App Installer / «Установщик приложений»** от Microsoft
через [Microsoft Store](https://apps.microsoft.com/detail/9nblggh4nns1).
Затем откройте новое окно PowerShell и повторите проверку.

Если App Installer уже установлен, но ещё не зарегистрирован после первого
входа в Windows, выполните в PowerShell своей учётной записи:

```powershell
Add-AppxPackage -RegisterByFamilyName -MainPackage Microsoft.DesktopAppInstaller_8wekyb3d8bbwe
```

При отсутствии Microsoft Store можно воспользоваться модулем Microsoft:
откройте **Windows PowerShell от имени администратора**, выполните команды
ниже, затем закройте это окно и проверьте `winget --version` в новом обычном окне.
Подтвердите запросы установки провайдера NuGet или доверия к PSGallery, если они появятся.

```powershell
Install-PackageProvider -Name NuGet -Force
Install-Module -Name Microsoft.WinGet.Client -Force -Repository PSGallery
Repair-WinGetPackageManager -AllUsers
```

Источник: [установка WinGet и восстановление через PowerShell](https://learn.microsoft.com/en-us/windows/package-manager/winget/).
При ограничениях корпоративной политики потребуется доступ к разрешённым источникам пакетов.

## 2. Установить Git for Windows и настольное приложение

В обычном **PowerShell**:

```powershell
winget install --id Git.Git -e --source winget
winget install --id 9PLM9XGG6VKS -s msstore
```

Вторая команда устанавливает настольное приложение ChatGPT с Codex по
идентификатору из [официальной инструкции OpenAI](https://learn.chatgpt.com/docs/app/windows).
После установки запустите приложение и войдите в свой аккаунт.

Git for Windows работает из PowerShell и `cmd`; отдельный MSYS2 для него
устанавливать не нужно. В составе Git есть компоненты MSYS2 для shell-функций,
но ими управляет установщик Git. Источники:
[установка Git](https://git-scm.com/install/windows),
[устройство Git for Windows](https://gitforwindows.org/requirements.html).

Откройте новое окно PowerShell и проверьте:

```powershell
git --version
```

Если Git уже установлен и доступен, повторная установка не нужна.
Windows Git и Git внутри Ubuntu — две отдельные установки для своих сред.

## 3. Установить WSL2 и Ubuntu

Откройте **PowerShell от имени администратора**:

```powershell
wsl --install -d Ubuntu-24.04
```

Перезагрузите компьютер, если установщик этого потребует. Запустите Ubuntu
и создайте Linux-пользователя с паролем. При вводе пароля символы не отображаются.

В **PowerShell** проверьте установленный дистрибутив:

```powershell
wsl --list --verbose
```

У `Ubuntu-24.04` в столбце `VERSION` должно быть `2`. Если указано `1`:

```powershell
wsl --set-version Ubuntu-24.04 2
```

Если Ubuntu уже установлена под другим именем, используйте имя из списка.
Для установки WSL2 нужна поддержка виртуализации; если Windows сообщает,
что она отключена, следуйте [официальной инструкции WSL](https://learn.microsoft.com/en-us/windows/wsl/install).

## 4. Установить системные пакеты и uv в Ubuntu

Далее работайте в терминале **Ubuntu**, не в PowerShell и не в Git Bash:

```bash
sudo apt update
sudo apt upgrade
sudo apt install git curl ca-certificates libcairo2 poppler-utils
```

`libcairo2` нужен для создания PNG/PDF. `poppler-utils` предоставляет
`pdftoppm` и `pdfinfo` для проверки PDF. Зависимости установит `apt`.
См. [пакет Poppler в Ubuntu](https://packages.ubuntu.com/noble/poppler-utils).

Установите uv официальным установщиком для Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Закройте и снова откройте терминал Ubuntu, чтобы подхватился `PATH`, затем:

```bash
uv --version
git --version
pdftoppm -v
```

Источник: [установка uv](https://docs.astral.sh/uv/getting-started/installation/).
Установленный в Windows uv не требуется для этого маршрута.

## 5. Клонировать проект и установить Python-зависимости

В **Ubuntu**:

```bash
mkdir -p ~/projects
cd ~/projects
git clone https://github.com/progmonster/tigames.git
cd tigames
uv python install 3.13
uv sync --locked
```

Python 3.13 задан в `.python-version` и `pyproject.toml`; отдельно скачивать
его установщик не нужно. uv создаст `.venv` и установит зависимости из `uv.lock`.
Ключ `--locked` проверяет согласованность зависимостей без изменения lock-файла.
Источники: [управление Python](https://docs.astral.sh/uv/guides/install-python/),
[окружения проектов uv](https://docs.astral.sh/uv/guides/projects/).

Держите клон внутри Linux, например `/home/<user>/projects/tigames`.
Это рекомендуемое расположение для Linux-инструментов под WSL:
[файловые системы Windows и Linux](https://learn.microsoft.com/en-us/windows/wsl/filesystems).
Windows-окружение `.venv` нельзя переиспользовать в Linux и наоборот.

## 6. Проверить окружение, тесты и сборку примера

В корне клона в **Ubuntu**:

```bash
uv run --locked python --version
uv run --locked python -c "import sys; print(sys.executable)"
uv run --locked python -c "import cairocffi; print(cairocffi.cairo_version_string())"
uv run --locked python -m unittest discover -s tests -v
```

Ожидаются Python 3.13, интерпретатор из `<проект>/.venv/bin/python`, версия
Cairo и успешное завершение тестов с `OK`. Сейчас в наборе пять тестов,
включая создание SVG/PNG/PDF, размеры рамки и прозрачность отверстий.

Проверьте сборку из рисунка, включённого в репозиторий:

```bash
uv run --locked python .agents/skills/photo-to-hexagon/scripts/build.py --lineart examples/technic-reference/approved-lineart.png --size-mm 34 --measure across-vertices --output-dir outputs/setup-check-34mm
```

Результат: `model-outline.svg`, `model-outline.png`, `sheet-a4.pdf` и
`manifest.json` в `outputs/setup-check-34mm/`. Здесь **34 мм — большая
диагональ внешней рамки**, включая обводку. Повторный запуск требует нового
имени каталога результата.

Отрисуйте итоговый PDF и проверьте страницу:

```bash
pdfinfo outputs/setup-check-34mm/sheet-a4.pdf
pdftoppm -r 150 -png -singlefile outputs/setup-check-34mm/sheet-a4.pdf outputs/setup-check-34mm/work/pdf-check
explorer.exe .
```

В Проводнике откройте PDF, `work/pdf-check.png` и `check-blue.png`.
Проверьте книжный A4, квадратные карточки, пунктирные линии разрезания,
целые рамки и прозрачные отверстия модели на цветной подложке.
Для печати: **100% / «Фактический размер»**, без «Вписать в страницу».

## 7. Подключить проект и проверить навык в приложении

В настольном приложении откройте **Settings → Agent environment → WSL**
и полностью перезапустите приложение. Терминал можно также переключить на WSL;
выбор оболочки терминала сам по себе не переключает среду агента.

Добавьте проект через **Add new project / Ctrl+O**. В адресной строке выбора
папки введите `\\wsl$\`, выберите `Ubuntu-24.04` и каталог
`home\<user>\projects\tigames`. Настройка среды и открытие WSL-проекта описаны
в [документации OpenAI](https://learn.chatgpt.com/docs/app/windows).

В новом чате проекта введите `$photo-to-hexagon` и проверьте наличие навыка
в списке. В качестве проверки можно попросить:

> Найди локальный навык photo-to-hexagon, назови путь к его SKILL.md
> и проверь доступность Python, Cairo и pdftoppm в текущей среде.

Ожидаемый путь: `.agents/skills/photo-to-hexagon/SKILL.md` внутри этого клона.
Это обычный каталог. Глобально устанавливать навык не нужно. Если он не появился,
перезапустите приложение и откройте новый чат именно в проекте `tigames`.
См. [локальное обнаружение навыков](https://learn.chatgpt.com/docs/build-skills).

Для полной работы по фотографии проверьте доступность инструмента генерации
изображений в текущем приложении и режиме. Наличие навыка и успешные Python-тесты
сами по себе не подтверждают доступность этого инструмента.

## 8. Обновление и удаление

Обновляйте компоненты тем менеджером, которым они установлены.

В **PowerShell** для программ Windows:

```powershell
winget upgrade --id Git.Git -e --source winget
winget upgrade --id 9PLM9XGG6VKS -s msstore
wsl --update
```

В **Ubuntu** для системных пакетов и uv, установленного официальным установщиком:

```bash
sudo apt update
sudo apt upgrade
uv self update
```

В корне проекта в **Ubuntu**:

```bash
git pull --ff-only
uv sync --locked
uv run --locked python -m unittest discover -s tests -v
```

`git pull --ff-only` выполняйте при сохранённых локальных изменениях.
`uv sync --locked` восстанавливает версии проекта; обновление самих библиотек
требует отдельного изменения и проверки `uv.lock`.

Если программы Windows больше не нужны другим проектам, удаление выполняется
через `winget uninstall --id Git.Git -e` и
`winget uninstall --id 9PLM9XGG6VKS -s msstore`. Linux-пакеты удаляются через
`sudo apt remove poppler-utils libcairo2`; проверьте список зависимых пакетов
перед подтверждением. Для удаления управляемого uv Python есть
`uv python uninstall 3.13`; используйте его, когда среда больше не нужна.
Сам uv, установленный standalone-установщиком, удаляется по
[инструкции uv](https://docs.astral.sh/uv/getting-started/installation/#uninstallation).

Перед удалением дистрибутива WSL сохраните нужные файлы: `outputs/`
исключён из Git и не восстановится при клонировании.

## Альтернатива: Windows без WSL, с MSYS2

Этот маршрут использует Windows Python и нативный режим агента. После шагов
1–2 вместо установки WSL выполните следующее. Проект храните на диске Windows,
например в `C:\Users\<user>\projects\tigames`.

### A. Установить uv и MSYS2

В **PowerShell**:

```powershell
winget install --id astral-sh.uv -e --source winget
winget install --id MSYS2.MSYS2 -e --source winget
```

Далее предполагается стандартный каталог MSYS2 `C:\msys64`.
Если установлен другой путь, подставьте его в команды настройки DLL.

### B. Установить Cairo и Poppler

Откройте из меню «Пуск» терминал **MSYS2 UCRT64**, выполните:

```bash
pacman -Syu
```

Если обновление просит закрыть терминалы, подтвердите, снова откройте
MSYS2 UCRT64 и повторите `pacman -Syu`, затем:

```bash
pacman -S --needed mingw-w64-ucrt-x86_64-cairo mingw-w64-ucrt-x86_64-poppler
```

Обновление самой среды MSYS2 и её пакетов выполняется через `pacman`,
а не переустановкой через WinGet. Источники:
[обновление MSYS2](https://www.msys2.org/docs/updating/),
[Cairo](https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-cairo),
[Poppler](https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-poppler).

### C. Настроить DLL и команды в PowerShell

Откройте новое обычное окно **PowerShell**:

```powershell
$env:CAIROCFFI_DLL_DIRECTORIES = 'C:\msys64\ucrt64\bin'
$env:Path = "C:\msys64\ucrt64\bin;$env:Path"
Test-Path 'C:\msys64\ucrt64\bin\libcairo-2.dll'
pdftoppm -v
uv --version
```

Ожидаются `True` и версии утилит. Переменные в этом блоке действуют только
в текущем PowerShell. Для постоянной работы откройте в Windows
«Изменение переменных среды текущего пользователя» и сохраните:

- переменную `CAIROCFFI_DLL_DIRECTORIES` со значением `C:\msys64\ucrt64\bin`;
- отдельную строку `C:\msys64\ucrt64\bin` в пользовательском `Path`,
  сохранив существующие строки.

После этого полностью закройте и заново откройте терминалы и настольное
приложение. Для Python 3.13 и DLL используйте одну архитектуру x64.
Источник: [загрузка Cairo DLL на Windows](https://doc.courtbouillon.org/cairocffi/stable/overview.html#importing).

### D. Клонировать и проверить проект

В **PowerShell** перейдите в выбранную родительскую папку проектов:

```powershell
git clone https://github.com/progmonster/tigames.git
cd tigames
uv python install 3.13
uv sync --locked
uv run --locked python -c "import cairocffi; print(cairocffi.cairo_version_string())"
uv run --locked python -m unittest discover -s tests -v
```

Затем выполните команды сборки и отрисовки PDF из шага 6: однострочные
команды `uv run`, `pdfinfo` и `pdftoppm` подходят и для PowerShell.
Для открытия папки вместо `explorer.exe .` также можно использовать `Invoke-Item .`.
Интерпретатор здесь находится в `.venv\Scripts\python.exe`.

В приложении выберите **Agent environment → Windows native**, перезапустите
его, добавьте Windows-каталог проекта и проверьте навык, как в шаге 7.

В этом маршруте uv обновляется командой
`winget upgrade --id astral-sh.uv -e --source winget`, удаляется через
`winget uninstall --id astral-sh.uv -e`. Системные пакеты MSYS2 обновляются
командой `pacman -Syu`; удаление выбранных пакетов —
`pacman -R mingw-w64-ucrt-x86_64-poppler mingw-w64-ucrt-x86_64-cairo`.
Если pacman сообщает о зависимостях других пакетов, сначала проверьте их использование.

## Если проверка не прошла

| Симптом | Что проверить |
| --- | --- |
| `winget`, `git`, `uv` не найдены | Установка завершилась; открыто новое окно терминала; выбран нужный Windows/Ubuntu терминал |
| `No module named ...` | Команда запущена из корня проекта через `uv run --locked`; выполнен `uv sync --locked` |
| Ошибка загрузки Cairo | В Ubuntu установлен `libcairo2`; в Windows доступны x64 DLL и `CAIROCFFI_DLL_DIRECTORIES` |
| `pdftoppm` не найден | В Ubuntu установлен `poppler-utils`; в Windows настроен путь к MSYS2 UCRT64 |
| Агент использует PowerShell вместо Linux | Выбрана среда агента WSL, приложение перезапущено; одной смены терминала недостаточно |
| Навык не виден | Открыт нужный проект, существует `.agents/skills/photo-to-hexagon/SKILL.md`; начат новый чат |
| Нет инструмента генерации изображений | Нужен доступ к такому инструменту в приложении; тесты Python и работа с готовым рисунком доступны отдельно |
