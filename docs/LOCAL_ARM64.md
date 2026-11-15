# Текущая машина — local-arm64

Выполняет агент в этой папке. Не подменять результаты отчётами Intel Mac.

```sh
.venv/bin/python tools/doctor.py --machine local-arm64
.venv/bin/python tools/doctor.py --machine local-arm64 --probe-bluetooth
```

Вторая команда вызывает системные API и может вызвать запрос доступа к Bluetooth.
Если процесс завершается системой, отчёт сохраняет код завершения.
Точный текст ошибки можно посмотреть отдельным запуском, не публикуя его без проверки:

```sh
.venv/bin/python tools/doctor.py --internal-probe classic
.venv/bin/python tools/doctor.py --internal-probe ble
```

`ModuleNotFoundError` означает отсутствие зависимости, а не поломку Bluetooth.
`controller_present` и `powered_on` — только предварительные признаки.
