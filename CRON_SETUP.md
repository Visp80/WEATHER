# Запуск через Cron / Task Scheduler

Інструкція для автоматичного запуску скрипта погоди за розкладом.

## Linux / macOS (Cron)

### 1. Відкрийте crontab редактор

```bash
crontab -e
```

### 2. Додайте рядок для запуску

Приклади:

```bash
# Кожний день о 08:00 ранку
0 8 * * * cd /path/to/weather && python weather.py --quiet

# Кожні 30 хвилин
*/30 * * * * cd /path/to/weather && python weather.py --no-notify --quiet

# Кожні 3 години
0 */3 * * * cd /path/to/weather && python weather.py --json >> weather_log.txt 2>&1

# Тільки в робочі дні о 09:00
0 9 * * 1-5 cd /path/to/weather && python weather.py --quiet

# 4 рази в день (08:00, 12:00, 17:00, 21:00)
0 8,12,17,21 * * * cd /path/to/weather && python weather.py --quiet
```

### 3. Пояснення параметрів cron

```
┌─────────────── хвилина (0–59)
│ ┌───────────── година (0–23)
│ │ ┌─────────── день місяця (1–31)
│ │ │ ┌───────── місяць (1–12)
│ │ │ │ ┌─────── день тижня (0–6, 0=неділя)
│ │ │ │ │
│ │ │ │ │
* * * * * команда
```

### 4. Рекомендовані комбінації параметрів

- `--quiet` — мінімальний вивід (підходить для cron)
- `--no-notify` — вимкнути Telegram
- `--json >> weather_log.txt` — зберігати результат в лог-файл
- `2>&1` — перенаправляти помилки в той же файл

### 5. Перевірка налаштування

```bash
# Переглянути поточні завдання
crontab -l

# Переглянути логи cron
grep CRON /var/log/syslog

# На macOS
log stream --predicate 'process == "cron"'
```

### 6. Приклад з логуванням

```bash
# Запис вивіду в лог
0 8 * * * cd /path/to/weather && python weather.py --quiet >> ~/weather.log 2>&1

# Запис JSON в лог з часовою міткою
0 */2 * * * cd /path/to/weather && echo "$(date)" >> ~/weather_json.log && python weather.py --json >> ~/weather_json.log 2>&1
```

## Windows (Task Scheduler)

### 1. Відкрийте Task Scheduler

- Натисніть `Win + R`
- Введіть `taskschd.msc`
- Натисніть Enter

### 2. Створіть нове завдання

- Натисніть **Create Task** (справа)
- Введіть ім'я: `Weather Script`
- Виберіть **Run with highest privileges** (опційно)

### 3. Вкладка Triggers (Спусковані)

- Натисніть **New**
- **Begin the task:** On a schedule
- **Settings:**
  - Daily (кожний день) або Hourly (щогодини)
  - Виберіть час (наприклад, 08:00)
  - Натисніть OK

### 4. Вкладка Actions (Дії)

- Натисніть **New**
- **Action:** Start a program
- **Program:** `python` (або повний шлях, наприклад: `C:\Python39\python.exe`)
- **Arguments:** `weather.py --quiet`
- **Start in:** `C:\path\to\weather` (папка зі скриптом)

Приклад:

```
Program: C:\Python39\python.exe
Arguments: weather.py --quiet
Start in: C:\Users\YourUser\weather
```

### 5. Вкладка Conditions (Умови)

- Виберіть **Start the task only if the computer is on AC power** (опційно)
- Виберіть **Wake the computer to run this task** (опційно)

### 6. Вкладка Settings (Налаштування)

- **If the task fails, restart after:** 5 minutes
- **If the task is still running after:** 1 hour (припинити завдання)
- Натисніть **OK**

### 7. Перевірка

- Знайдіть завдання в Task Scheduler
- Натисніть **Run** для тесту
- Переглядайте історію в закладці **History**

## Приклади налаштування

### Сценарій 1: Щоденна погода зранку

**Linux/macOS:**
```bash
0 8 * * * cd /home/user/weather && python weather.py --quiet
```

**Windows:**
- Program: `C:\Python39\python.exe`
- Arguments: `weather.py --quiet`
- Trigger: Daily at 08:00

---

### Сценарій 2: Повідомлення в Telegram кожні 3 години

**Linux/macOS:**
```bash
0 */3 * * * cd /home/user/weather && python weather.py
```

**Windows:**
- Program: `C:\Python39\python.exe`
- Arguments: `weather.py`
- Trigger: Every 3 hours

---

### Сценарій 3: Логування погоди кожні 30 хвилин

**Linux/macOS:**
```bash
*/30 * * * * cd /home/user/weather && python weather.py --json >> ~/weather_log.txt 2>&1
```

**Windows:**
- Program: `C:\Python39\python.exe`
- Arguments: `weather.py --json`
- Start in: `C:\Users\YourUser\weather`
- Redirect output to file using Task Scheduler

---

### Сценарій 4: Розклад для шкільника

**Прогноз перед школою і після**

**Linux/macOS:**
```bash
0 7 * * 1-5 cd /home/user/weather && python weather.py --quiet  # Перед школою о 07:00
0 15 * * 1-5 cd /home/user/weather && python weather.py --quiet # По закінченню о 15:00
```

**Windows:** Створіть два окремі Task Scheduler завдання

---

## Корисні поради

1. **Тестування перед запуском в cron**
   ```bash
   # Запустіть вручну, щоб перевірити
   python weather.py --quiet
   ```

2. **Журнальні файли**
   ```bash
   # Записувати логи
   0 8 * * * cd /path/to/weather && python weather.py >> /var/log/weather.log 2>&1
   
   # Переглядати логи
   tail -f /var/log/weather.log
   ```

3. **Змінні оточення для cron**
   ```bash
   # Якщо потрібен PATH або інші змінні
   0 8 * * * . $HOME/.bashrc; cd /path/to/weather && python weather.py
   ```

4. **Виправлення проблем**
   - Перевірте, що Python встановлений і доступний через PATH
   - Переконайтеся, що файл `config.json` має правильні координати
   - Переконайтеся, що Telegram налаштований (якщо потрібні сповіщення)
   - Перевірте логи для деталей помилок

5. **Відключення завдання**
   - Linux/macOS: видаліть рядок з `crontab -e`
   - Windows: натисніть right-click на завдання → Disable

## Інтеграція з системою повідомлень

Якщо хочете отримувати сповіщення також від самої системи:

**Linux (з libnotify):**
```bash
0 8 * * * cd /path/to/weather && python weather.py --quiet && notify-send "Погода оновлена"
```

**macOS (з osascript):**
```bash
0 8 * * * cd /path/to/weather && python weather.py --quiet && osascript -e 'display notification "Погода оновлена"'
```

**Windows (з PowerShell):**
```powershell
# У Task Scheduler як скрипт PowerShell
C:\Python39\python.exe C:\Users\YourUser\weather\weather.py --quiet
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
```
