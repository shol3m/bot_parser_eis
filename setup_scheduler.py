"""
Настройка автозапуска:
1. Windows Task Scheduler — daily_run.py каждый день в 8:00
2. Инструкция по запуску бота при старте системы

Запуск: python setup_scheduler.py
"""

import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.resolve()
PYTHON = sys.executable
DAILY_SCRIPT = PROJECT_DIR / "daily_run.py"
BOT_SCRIPT = PROJECT_DIR / "bot" / "bot.py"


def setup_daily_task():
    """Создаёт задачу в Task Scheduler: daily_run.py каждый день в 8:00."""
    task_name = "AgentSystem_DailyRun"

    # XML описание задачи
    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-01-01T08:00:00</StartBoundary>
      <Repetition>
        <Interval>P1D</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <ExecutionTimeLimit>PT3H</ExecutionTimeLimit>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>{PYTHON}</Command>
      <Arguments>"{DAILY_SCRIPT}"</Arguments>
      <WorkingDirectory>{PROJECT_DIR}</WorkingDirectory>
    </Exec>
  </Actions>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT3H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
</Task>"""

    xml_path = PROJECT_DIR / "task_schedule.xml"
    xml_path.write_text(xml, encoding="utf-16")

    result = subprocess.run(
        ["schtasks", "/create", "/tn", task_name, "/xml", str(xml_path), "/f"],
        capture_output=True, text=True
    )
    xml_path.unlink()

    if result.returncode == 0:
        print(f"✅ Задача '{task_name}' создана — запуск каждый день в 8:00")
    else:
        print(f"❌ Ошибка создания задачи: {result.stderr}")
        print("   Попробуй запустить от имени администратора.")


def setup_bot_autostart():
    """Создаёт задачу запуска бота при входе в систему."""
    task_name = "AgentSystem_Bot"

    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>{PYTHON}</Command>
      <Arguments>"{BOT_SCRIPT}"</Arguments>
      <WorkingDirectory>{PROJECT_DIR}</WorkingDirectory>
    </Exec>
  </Actions>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
</Task>"""

    xml_path = PROJECT_DIR / "task_bot.xml"
    xml_path.write_text(xml, encoding="utf-16")

    result = subprocess.run(
        ["schtasks", "/create", "/tn", task_name, "/xml", str(xml_path), "/f"],
        capture_output=True, text=True
    )
    xml_path.unlink()

    if result.returncode == 0:
        print(f"✅ Задача '{task_name}' создана — бот запускается при входе в систему")
    else:
        print(f"❌ Ошибка создания задачи бота: {result.stderr}")


if __name__ == "__main__":
    print("=== Настройка автозапуска ===\n")
    print(f"Python:       {PYTHON}")
    print(f"Проект:       {PROJECT_DIR}")
    print(f"daily_run:    {DAILY_SCRIPT}")
    print(f"bot:          {BOT_SCRIPT}")
    print()
    setup_daily_task()
    setup_bot_autostart()
    print()
    print("Готово. Следующие шаги:")
    print("1. Открой config/bot_config.json и вставь токен бота")
    print("2. Запусти бота вручную: python bot/bot.py")
    print("3. Напиши /start своему боту в Telegram")
    print("4. Запусти тест: python daily_run.py")
