# Вторая машина — peer-intel

Выполняет пользователь на MacBook Pro 2019. Репозиторий приватный: нужен доступ
к аккаунту ekermas или разрешение на чтение.

```sh
git clone https://github.com/ekermas/mac_sync.git
cd mac_sync
```

Открыть Terminal в клонированной папке проекта. Перед повторной проверкой:

```sh
git pull --ff-only
git rev-parse HEAD
uname -m
sw_vers
python3 --version
```

Ожидаем `x86_64`; macOS 26.7.1 нужно подтвердить выводом `sw_vers`.
Если Python отсутствует или старее 3.11, сначала установить нативный Python.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python tools/doctor.py --machine peer-intel
.venv/bin/python tools/doctor.py --machine peer-intel --probe-bluetooth
```

Если macOS запросит Bluetooth-доступ, разрешить его для запускающего приложения.
При отказе зафиксировать отказ; он не доказывает поломку транспорта.
Если установка зависимостей не удалась, всё равно запустить первую диагностику.

Вернуть в чат JSON из последнего отчёта `reports/peer-intel-*.json`, а при проблемах
установки — её ошибку. Пока соединение с первым Mac не требуется.
Не записывать успех передачи: CP001 её не выполняет.
