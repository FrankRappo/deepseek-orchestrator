# Агент DeepSeek на базе Codex

`/work/deepseek` запускает обычный Codex CLI с моделями DeepSeek через
Responses API. По устройству это отдельный оркестратор, похожий на `/work/glm`:
DeepSeek может сам составить `tasks/T*.md`, а затем Codex с моделью DeepSeek
выполнит их по очереди в tmux. Можно также подготовить задачи обычным Codex
или вручную. У каждого пользователя отдельный `CODEX_HOME` в
`~/.local/share/deepseek-codex`, поэтому настройки обычного `~/.codex`
не меняются и сеансы `root`/`hgff` не конфликтуют.

## 1. Проверить установку

В WSL Ubuntu:

```bash
cd /work/deepseek
bin/orchestrate doctor
bin/balance
```

Нужны Codex CLI версии 0.144.0 или новее, Python 3 и tmux. Ключ читается из
`DEEPSEEK_API_KEY` либо из `/home/hgff/api deepseek.txt`; он не копируется в
этот проект. `doctor` проверяет CLI и доступ к ключу, `balance` делает запрос
к API DeepSeek. Баланс первого запроса запоминается как база 100%.

## 2. Модели, качество, токены и цена

Доступны две актуальные модели API:

| ID | Версия | Контекст / максимум ответа | Изображения | Качество по данным DeepSeek |
| --- | --- | --- | --- | --- |
| `deepseek-flash` | V4.1 Flash | 1 048 576 / 393 216 токенов | Да | В новом релизе заявлены результаты выше V4 Pro на ряде тестов; обычно лучший старт по цене. |
| `deepseek-v4-pro` | V4 Pro | 1 048 576 / 393 216 токенов | Нет | Остаётся доступным и описан как сильная модель для agent-задач; сравнение качества с нынешним Flash неоднозначно. |

Для ориентира: в опубликованных DeepSeek результатах Terminal-Bench 2.1
у V4.1 Flash — 90.6, у V4 Pro — 87.9. Эти цифры опубликованы для разных
релизов и не гарантируют результат на вашем репозитории.
[Источник: журнал выпусков DeepSeek](https://api-docs.deepseek.com/updates/).

Число **израсходованных** токенов не закреплено за моделью: оно зависит от
задачи, длины контекста, числа ходов и кэша. Фактический расход после задачи
показывают `orchestrate usage` и исторические средние в `orchestrate models
--project ...`. У обеих моделей есть уровни рассуждения `low`, `high`, `max`;
текущая конфигурация Codex использует `high`.

Тарифы DeepSeek на **24.09.2026**, USD за 1 млн токенов:

| Тип токенов | Flash вне пика / пик | Pro вне пика / пик |
| --- | ---: | ---: |
| Вход, попавший в кэш | $0.003 / $0.006 | $0.022 / $0.044 |
| Вход, не попавший в кэш | $0.15 / $0.30 | $0.66 / $1.32 |
| Выход | $0.60 / $1.20 | $1.98 / $3.96 |

При одинаковом объёме Pro стоит примерно в 4.4 раза дороже для входа без
кэша и в 3.3 раза дороже для выхода. Разный объём токенов в реальной задаче
может изменить итоговое соотношение.

Пик: 01:00–04:00 и 06:00–10:00 UTC по будням, кроме государственных
праздников Китая. Цены могут измениться: перед важными расчётами сверяйте
[текущий прайс DeepSeek](https://api-docs.deepseek.com/quick_start/pricing/).
`usage` считает **оценочный диапазон** стоимости по этим тарифам; точный
списанный остаток показывает `balance`.

### Как оркестратор выбирает модель

В файле задачи ставьте `Model: auto` и `Complexity: low`, `medium` или
`high`. При `--model auto` действуют режимы `--routing`:

| Режим | low | medium | high |
| --- | --- | --- | --- |
| `economy` (по умолчанию) | Flash | Flash | Flash |
| `balanced` | Flash | Flash | Pro |
| `quality` | Flash | Pro | Pro |

Это **эвристика выбора**, а не гарантия, что Pro окажется лучше для конкретной
задачи: актуальные материалы DeepSeek дают противоречивые сигналы о сравнении
качества. `economy` использует новый Flash и самый низкий тариф. Явный
`Model: deepseek-v4-pro`/`deepseek-flash` в задаче имеет приоритет. Явный
`--model deepseek-v4-pro`/`deepseek-flash` задаёт модель для всех задач с
`Model: auto`; `--model auto` даёт выбор политике. Посмотреть действующие
правила и цены можно командой `bin/orchestrate models --project /work/my-project`.

`--controller-model` отдельно выбирает модель **планировщика**, который пишет
задачи из `GOAL.md`. Когда он не указан и `--model auto`, режим `economy`
запускает планировщик на Flash, а `balanced`/`quality` — на Pro.

## 3A. DeepSeek сам планирует и выполняет

Создайте файл `/work/my-project/GOAL.md` с целью, ограничениями и командами
проверки. Затем запустите:

```bash
/work/deepseek/bin/orchestrate start \
  --project /work/my-project \
  --controller deepseek \
  --goal /work/my-project/GOAL.md \
  --controller-model deepseek-v4-pro \
  --model auto --routing economy \
  --idle-exit
```

Планировщик запускается, только когда в `tasks/` ещё нет файлов `T*.md`.
Он создаёт задачи, затем оркестратор выполняет их последовательно.
`--idle-exit` завершает tmux-сессию после очереди. Без него оркестратор
продолжает ожидать новые задачи.

## 3B. Codex или человек готовит задачи

Создайте `/work/my-project/tasks/T01_name.md` по образцу
[`TASK_TEMPLATE.md`](TASK_TEMPLATE.md). После этого:

```bash
/work/deepseek/bin/orchestrate start \
  --project /work/my-project \
  --controller codex \
  --model auto --routing balanced \
  --idle-exit
```

`--controller codex` означает, что задачи создал Codex, а выполняет их
DeepSeek через Codex CLI. Для задач, созданных вручную, используйте
`--controller manual`.

## 4. Следить за задачами, токенами и балансом

```bash
/work/deepseek/bin/orchestrate status --project /work/my-project
/work/deepseek/bin/orchestrate usage --project /work/my-project
/work/deepseek/bin/orchestrate usage --project /work/my-project --json
/work/deepseek/bin/orchestrate models --project /work/my-project
/work/deepseek/bin/balance
/work/deepseek/bin/balance --json
```

`usage` суммирует реальные токены завершённых ходов Codex, показывает
итоги по моделям и оценку стоимости; если API не вернул usage, число не
выдумывается. Учёт
охватывает задачи, запущенные через `orchestrate`. `balance` показывает
текущий денежный остаток по каждой валюте и процент от локально сохранённой
базы. API DeepSeek не возвращает общий лимит токенов или готовый процент
остатка. После пополнения процент может превысить 100%; новая база задаётся
командой `bin/balance --reset-baseline`.

Результат задачи: `reports/report_T01_name.md` с последней строкой
`STATUS: SUCCESS`, `FAIL`, `BLOCKED` или `PARTIAL`. Подробности запуска:
`logs/T01_name.log`, сводка токенов: `logs/deepseek_usage.jsonl`. Перед
принятием результата проверьте diff и команды проверки из задачи.

## Прямой запуск, очередь и разрешения

Актуальная краткая инструкция для запуска DeepSeek Flash или Pro в прямом
интерактивном режиме и через очередь задач:
[`INTERACTIVE_START.txt`](INTERACTIVE_START.txt).

Для короткой команды из любого каталога один раз создайте ссылку в PATH:

```bash
sudo ln -s /work/deepseek/bin/deepseek /usr/local/bin/deepseek
```

Для интерактивной работы без очереди:

```bash
deepseek                                    # Pro в текущем каталоге
deepseek --project /work/my-project --model deepseek-flash

# Запуск с моделью Pro:
deepseek --project /work/my-project --model deepseek-v4-pro

# Позже продолжить последний диалог того же проекта:
deepseek resume --project /work/my-project --last
```

По умолчанию Codex использует `workspace-write` и запрос подтверждения.
Добавьте `--dangerous` к `deepseek` или `orchestrate start`, когда нужен
запуск без sandbox и запросов разрешений:

```bash
/work/deepseek/bin/orchestrate start \
  --project /work/my-project --controller codex \
  --model deepseek-v4-pro --dangerous --idle-exit
```

Этот флаг передаёт Codex
`--dangerously-bypass-approvals-and-sandbox` только для нового запуска.
Остановить ожидающую очередь: `bin/orchestrate stop --project /work/my-project`.
Подключиться к её tmux-сессии: `bin/orchestrate attach --project /work/my-project`.
После прерванной задачи автоматического повтора нет: она могла уже изменить
файлы. Исправьте причину и создайте новую задачу.

## Технические источники

`.codex/models.json` извлечён из официального скрипта DeepSeek для Codex
версии 1.4.0. Конфигурация использует `env_key`, поэтому ключ не хранится в
TOML. Документация:
[подключение Codex](https://api-docs.deepseek.com/quick_start/agent_integrations/codex/),
[Responses API](https://api-docs.deepseek.com/guides/responses_api/),
[баланс](https://api-docs.deepseek.com/api/get-user-balance/),
[модели API](https://api-docs.deepseek.com/api/list-models/),
[публикация V4.1 Flash](https://api-docs.deepseek.com/news/news260910/),
[настройки Codex](https://developers.openai.com/codex/config-reference/).
