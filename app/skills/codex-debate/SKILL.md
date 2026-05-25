---
name: codex-debate
description: "Cross-LLM ревью через Codex CLI (GPT-5.5). Codex ревьюит план/код/diff, пишет результат в codex_<slug>.md в папке фичи. Авто-итерация до консенсуса. Conventional Comments. Персистентные сессии для debate. Триггеры: 'спроси кодекса', 'кодекс ревью', 'ревьюй через кодекса', 'второе мнение', 'cross-review', 'adversarial review', 'переспроси кодекса', 'уточни у кодекса', 'продолжи с кодексом', '/codex', '/codex-debate'. НЕ юзать на тривиальных задачах (трата токенов)."
roles: [all]
integrations: []
---

# Codex Debate — cross-LLM ревью через GPT-5.5

## Purpose
Adversarial review плана/кода/решения через Codex CLI (другая модель — GPT-5.5). Codex исследует код через shell, пишет результат в `<feature_dir>/codex_<slug>.md`. Claude Code итерирует с ним до консенсуса. Юзеру показывается финал.

**Кейс 24.04.2026:** Codex нашёл 5 блокеров в плане (scope creep, неверные пути, противоречие), переписал план вдвое короче. 4 итерации = план прошёл фильтр качества.

## ⚠️ Главный принцип — ВТОРОЕ МНЕНИЕ, НЕ ИСТИНА

Codex — другая модель с другими bias'ами. Часто прав, но **не всегда**. Claude Code должен:
- **Прислушиваться** к каждому замечанию
- **Проверять** все blocking-замечания через код (`ls`, `grep`, `cat`, Serena) **перед** тем как принять
- **Спорить** если не согласен — через resume сессии с контраргументами из кода
- **Эскалировать юзеру** если Codex просит удалить существующий функционал, поменять архитектуру существующих компонентов, или сделать что-то с непонятными последствиями
- **Не соглашаться слепо** — это обесценивает весь cross-LLM review

При расхождении формат для юзера: "Codex говорит X. Я проверил — [согласен / не согласен потому что Y]. Хочешь чтобы я вступил в дебаты с ним?"

## When to Invoke

- "спроси кодекса", "кодекс ревью", "ревьюй через кодекса"
- "второе мнение", "cross-review", "adversarial review"
- "переспроси кодекса", "уточни у кодекса", "продолжи с кодексом" → **resume сессии, НЕ новая**
- `/codex` или `/codex-debate`
- Claude сам предлагает review когда видит спорное архитектурное решение или большой план — но **только с явного "да" юзера**
- **После значимого фикса/изменения кода** — предложить юзеру пройти Codex review до push'а (но не делать автоматически без явного запроса)

**НЕ юзать** на мелких вопросах ("кодекс, что такое grep") — трата токенов и лимитов.

## Главные правила

1. **OUTPUT В FEATURE_DIR** — Codex пишет в `<feature_dir>/codex_<slug>.md`. Каждый раунд = секция `## Round N` (append). НЕ в корень cwd, НЕ в `/tmp`.
2. **CONVENTIONAL COMMENTS** — формат замечаний (см. ниже)
3. **RESUME НЕ НОВАЯ СЕССИЯ** — follow-up через `codex exec resume`, иначе Codex теряет контекст
4. **ОДИН SLUG ВЕЗДЕ** — slug определяется один раз и используется для: имени файла, ключа в codex_sessions.json, resume. Не придумывать новый slug при resume.

## Формат замечаний (Conventional Comments)

Codex должен использовать эти префиксы в каждом замечании:

| Префикс | Что значит |
|---|---|
| `blocking:` | must fix, мерж невозможен. Баги, security, data loss, поломка тестов |
| `suggestion:` | рекомендация. Улучшит код, но не блокирует |
| `question:` | нужен ответ автора, не однозначное замечание |
| `thought:` | мысль вслух, не требует действия |
| `nit:` | мелочь (стиль/нейминг). Можно скипнуть |

Каждое замечание: `<префикс>: file:line — суть проблемы → конкретное предложение`.

## Pre-Flight Check

1. `command -v codex >/dev/null 2>&1` — иначе "codex CLI не установлен" и стоп.
2. Определить **feature_dir** — папку текущей фичи в `docs_work/<месяц_день>/<feature_name>/`:
   - Если cwd внутри `docs_work/<...>/<feature>/` или ниже — это и есть `feature_dir`
   - Если юзер передал путь к фиче явно — берём его
   - Если фичи нет (общий вопрос вне процесса) → **ephemeral-режим** (см. Шаг 3)
3. Определить **slug** для этой темы внутри фичи:
   - Короткий kebab-case: `plan-review`, `code-review`, `architecture`, `tests-review`
   - Sanitize к `[a-z0-9-]`, max 50 chars
   - Если юзер не сказал — спросить **только при первом вызове** для этой темы. На resume slug определяется по контексту follow-up.
4. **project_root** — корень проекта (где лежит код для ревью). По умолчанию = текущая cwd, если в репо. Codex запускается **с этим cwd**, чтобы видеть код. Output-файл по абсолютному пути в feature_dir.

## Process Flow

### Шаг 0 — Подготовить codex_sessions.json

```bash
FEATURE_DIR="<feature_dir>"           # абсолютный путь
SESSIONS_JSON="$FEATURE_DIR/codex_sessions.json"
SLUG="<slug>"
OUTPUT_FILE="$FEATURE_DIR/codex_${SLUG}.md"
PROJECT_ROOT="<project_root>"         # cwd для codex

mkdir -p "$FEATURE_DIR"
[ -f "$SESSIONS_JSON" ] || echo '{"sessions": {}}' > "$SESSIONS_JSON"
```

### Шаг 1 — Определить: новая сессия или resume?

```bash
UUID=$(jq -r --arg slug "$SLUG" '.sessions[$slug].uuid // empty' "$SESSIONS_JSON")
```

- `$UUID` пустой → **новая сессия** (Шаг 2а)
- `$UUID` есть и юзер просит продолжить → **resume** (Шаг 2б)
- Юзер явно сказал "с нуля" → новая сессия (старый UUID перезаписать)

### Шаг 2а — Новая сессия (Codex пишет файл сам)

Промпт собирается через temp-файл с переменными — так не нужно эскапить:

```bash
cat > /tmp/codex-prompt-$$.txt <<EOF
$(cat <<'INSTRUCTIONS'
Ты adversarial code reviewer. Проводи review по правилам ниже.
INSTRUCTIONS
)

OUTPUT FILE: $OUTPUT_FILE

ЗАДАЧА: <конкретная задача — read PLAN.md, review diff, etc.>

$(cat <<'PROJECT_CONTEXT'
PROJECT CONTEXT (calibrate severity):
- Stack: <вписать стек проекта>
- Stage: <prototype / MVP / production>
- Scale: <что важно — correctness/security/data integrity или perf at scale>
- Phase: <что НЕ важно сейчас — enterprise patterns, монитор-инфраструктура, 100% coverage>
- Severity calibration:
  * "blocking" = crash / data corruption / security hole
  * "suggestion" = real improvement worth doing
  * "nit" = можно пропустить, мы не оптимизируем под идеальный стиль
PROJECT_CONTEXT
)

ИНСТРУКЦИИ ДЛЯ OUTPUT:
1. Создай файл $OUTPUT_FILE с frontmatter:
   ---
   slug: $SLUG
   topic: <тема одной строкой>
   created: <ISO timestamp>
   model: gpt-5.5
   ---
2. Структура файла:
   ## Tests
   <вывод тестов или "не применимо">

   ## Round 1 — <ISO>
   ### Summary
   <3-5 предложений>

   ### Замечания
   <Conventional Comments — blocking/suggestion/question/thought/nit>
   Каждое: file:line — проблема → фикс.

   ### Вердикт
   <одна фраза: рабочий / требует доработки / выкинуть>

3. Не модифицируй другие файлы. Только $OUTPUT_FILE.
4. Напиши на русском языке.
EOF

cd "$PROJECT_ROOT"
codex exec \
  -s workspace-write \
  -c model_reasoning_effort="high" \
  --skip-git-repo-check \
  --json \
  -o /tmp/codex-last-msg.txt \
  - < /tmp/codex-prompt-$$.txt 2>&1 | tee /tmp/codex-last.jsonl

rm /tmp/codex-prompt-$$.txt
```

Зачем флаги:
- `-s workspace-write` — codex может писать в cwd (нужно чтобы записать output-файл). На VPS требует kernel-фикс sysctl (см. Error Handling).
- `-c model_reasoning_effort="high"` — для review лучше high. Override дефолта `medium` из config.toml.
- `--skip-git-repo-check` — не падает в /tmp или вне git
- `--json` — нужен для извлечения thread_id
- `-o /tmp/codex-last-msg.txt` — итоговое сообщение Codex (что он сделал, краткий summary)
- `- < file` — промпт через stdin, безопасный quoting

После завершения извлечь UUID и обновить реестр:

```bash
UUID=$(jq -r 'select(.type=="thread.started") | .thread_id' /tmp/codex-last.jsonl | head -1)
[ -z "$UUID" ] && UUID=$(jq -r 'select(.type=="session_meta") | .payload.id' /tmp/codex-last.jsonl | head -1)

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
jq --arg slug "$SLUG" --arg uuid "$UUID" --arg topic "<topic>" --arg now "$NOW" \
  '.sessions[$slug] = {uuid: $uuid, topic: $topic, started: $now, last_used: $now, turns: 1}' \
  "$SESSIONS_JSON" > "$SESSIONS_JSON.tmp" && mv "$SESSIONS_JSON.tmp" "$SESSIONS_JSON"

# Sanity: убедиться, что Codex реально записал файл
test -s "$OUTPUT_FILE" || echo "ВНИМАНИЕ: $OUTPUT_FILE пустой или не создан"

# Sanity: убедиться, что Codex не тронул ничего лишнего
git -C "$PROJECT_ROOT" status --porcelain | grep -v "$(realpath --relative-to="$PROJECT_ROOT" "$OUTPUT_FILE")" \
  | grep -v "$(realpath --relative-to="$PROJECT_ROOT" "$SESSIONS_JSON")" \
  && echo "ВНИМАНИЕ: codex изменил что-то кроме output-файла"
```

### Шаг 2б — Resume сессии (Codex дописывает Round N)

```bash
UUID=$(jq -r --arg slug "$SLUG" '.sessions[$slug].uuid' "$SESSIONS_JSON")
TURN=$(($(jq -r --arg slug "$SLUG" '.sessions[$slug].turns' "$SESSIONS_JSON") + 1))

cat > /tmp/codex-prompt-$$.txt <<EOF
ЗАДАЧА: <follow-up — "I fixed N issues, re-review", или "Claude не согласен с замечанием X, вот его аргументы: ..." >

OUTPUT: допиши секцию ## Round $TURN в файл $OUTPUT_FILE (он уже существует с Round 1..N-1, не перезаписывай предыдущие раунды).

Формат секции:
## Round $TURN — <ISO>
### Re-review
<статус каждого предыдущего blocking: FIXED / STILL BROKEN / NEW BUG INTRODUCED>
### Новые замечания
<если появились — Conventional Comments>
### Вердикт раунда
<APPROVED / требует ещё фиксов>

Напиши на русском.
EOF

cd "$PROJECT_ROOT"
codex exec resume "$UUID" \
  -c model_reasoning_effort="high" \
  --skip-git-repo-check \
  --json \
  -o /tmp/codex-last-msg.txt \
  - < /tmp/codex-prompt-$$.txt 2>&1 | tee -a /tmp/codex-last.jsonl

rm /tmp/codex-prompt-$$.txt

# Обновить реестр
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
jq --arg slug "$SLUG" --arg now "$NOW" \
  '.sessions[$slug].last_used = $now | .sessions[$slug].turns += 1' \
  "$SESSIONS_JSON" > "$SESSIONS_JSON.tmp" && mv "$SESSIONS_JSON.tmp" "$SESSIONS_JSON"
```

**КРИТИЧНО:** у `codex exec resume` флаг `-s` НЕ работает — sandbox наследуется от исходной сессии. Поэтому при создании новой сессии сразу выбирай правильный sandbox.

### Шаг 3 — Эфемерный режим (нет фичи)

Для one-off вопросов вне процесса фичи:

```bash
codex exec \
  -s read-only \
  --skip-git-repo-check \
  --ephemeral \
  -c model_reasoning_effort="medium" \
  -o /tmp/codex-last-msg.txt \
  "<вопрос юзера>"

cat /tmp/codex-last-msg.txt  # показать юзеру
```

`--ephemeral` — не сохраняет сессию даже на стороне Codex. Resume невозможен.

### Шаг 4 — Авто-итерация до консенсуса

**После завершения Round 1 — НЕ дёргать юзера, итерировать самому.**

1. Прочитать `<feature_dir>/codex_<slug>.md`, разобрать замечания
2. По каждому **blocking** замечанию — **проверить через код** (ls/grep/cat/Serena). Решить ACK / DISAGREE / PARTIAL с фактом из кода
3. **Эскалация юзеру** если:
   - Codex просит **удалить существующий функционал**
   - Codex просит **существенно поменять архитектуру** уже работающих компонентов
   - Замечание непонятное / последствия неочевидные
4. Применить ACK замечания к коду/плану (Edit)
5. Resume сессию с changelog'ом — Шаг 2б
6. Codex дописывает Round 2 в файл
7. Цикл 1-6 пока не наступит одно из:
   - Codex написал "APPROVED" / "merge-ready" / "no remaining blockers"
   - 5+ раундов без прогресса (diminishing returns) → решай сам, показывай юзеру
   - В каком-то раунде появился пункт под эскалацию (см. п.3) → стоп, к юзеру

### Шаг 5 — Показать юзеру финальный результат

```
🤖 **Codex review завершён** (slug: `<slug>`, раундов: N)

**Вердикт:** <APPROVED / требует доработки / выкинуть>

**Кратко по замечаниям:**
- blocking: X найдено, Y пофикшено, Z отклонено (с обоснованием)
- suggestion: M найдено, K принято
- nit: пропущено

**Где почитать:** `<feature_dir>/codex_<slug>.md`

**Что делать дальше:**
- Если ок — продолжаем работу / пушим
- Если хочешь дебатить ещё — "переспроси кодекса про <X>"
```

## Project Context — добавлять в каждый промпт

Без контекста Codex ревьюит MVP-фикс на 50 строк как enterprise — выдаёт 15 suggestions про circuit breakers и observability, всё верно для Netflix, бесполезно тут.

**Шаблон** (адаптировать под проект):

```
PROJECT CONTEXT (calibrate severity):
- Stack: <FastAPI+PostgreSQL / Hyprland config / etc>
- Stage: <prototype / MVP / production>
- Scale: <что важно — correctness/security или perf at scale>
- Phase: <что НЕ важно сейчас — enterprise patterns, monitoring infra, 100% coverage>
- Severity calibration:
  * "blocking" = crash / data corruption / security hole
  * "suggestion" = real improvement worth doing
  * "nit" = пропустить, мы не оптимизируем стиль
```

Если Claude **не знает** контекст проекта — **спросить юзера** перед первым вызовом Codex'а в новой фиче. Контекст можно сохранить в `<feature_dir>/.codex_context.md` для последующих вызовов.

## Run in Background

- **Sync (дефолт)** для review длиной до 2 минут — простые планы, мелкие diff'ы
- **`run_in_background: true`** для крупных review (>2 мин) — большой план, тесты, сложный код. Claude параллельно работает над другими подзадачами, по уведомлению о завершении читает результат

В Bash tool ставить `timeout: 300000` (5 мин) для sync вызовов с большими промптами.

## Язык

Codex по дефолту думает и пишет на английском. Если юзер общается на русском — **в каждом промпте** добавлять "Напиши на русском языке". Codex может думать на любом, но output должен соответствовать языку юзера.

## Промпт-шаблоны

### Review плана/ТЗ

```
Ты adversarial code reviewer. Сейчас в cwd — <project_root> (<стек>).

Шаг 1: Прочитай файл $PLAN_FILE (план/ТЗ).
Шаг 2: Исследуй живой код — ls/grep/cat — проверь все ссылки из плана. Файлы существуют? Функции есть? Сигнатуры совпадают?
Шаг 3: Если проект Python и есть pytest — запусти. Если не Python или тестов нет — напиши "тесты не применимы".
Шаг 4: Запиши review в $OUTPUT_FILE по формату из основной инструкции.

Ищи в плане:
1. Scope creep — что выкинуть не теряя сути
2. Неверные ссылки на код (проверяй ls/grep, не угадывай)
3. Внутренние противоречия
4. Security / архитектурные блокеры (race conditions, потеря данных)
5. Нарушения бизнес-правил из CLAUDE.md проекта (если есть)

Не больше 10 замечаний. Конкретика. Без воды.

[+ PROJECT CONTEXT block]
```

### Review кода (diff / uncommitted)

```
Ты adversarial code reviewer. cwd — <project_root>.

Шаг 1: Найди тест-раннер: pyproject.toml/package.json/Makefile/etc. Запусти если есть.
Шаг 2: Посмотри diff: `git diff` или `git diff <base>...HEAD`.
Шаг 3: Прочитай новые/изменённые файлы.
Шаг 4: Найди баги, security holes, breaking changes, race conditions, null safety.
Шаг 5: Запиши review в $OUTPUT_FILE.

Не предлагай рефакторинг если старый код работает. Не выдумывай замечания если их нет — пиши "ACK".

[+ PROJECT CONTEXT block]
```

### Debate (при несогласии Claude в авто-итерации)

```
Claude Code не согласен с твоими замечаниями <ID-список>. Аргументы:

<аргументы Claude с фактами из кода>

Проверь каждый пункт:
- ACK — принимаю, Claude прав
- Контраргумент — не согласен, обоснование с фактами из кода (не "мне кажется")
- Частично — что принято, что нет

Допиши секцию ## Round N в $OUTPUT_FILE.
```

### Re-review после фикса

```
Я применил твои замечания: <changelog>

Re-review — для каждого предыдущего замечания: FIXED / STILL BROKEN / NEW BUG INTRODUCED.
Если все blocking закрыты и нет новых — вердикт APPROVED.

Допиши ## Round N в $OUTPUT_FILE.
```

## Error Handling

| Ошибка | Что делать |
|---|---|
| `codex not found` | "Codex CLI не установлен. Установи `npm i -g @openai/codex` и повтори." |
| `402 Payment Required: deactivated_workspace` | **НЕ sandbox-проблема**. ChatGPT подписка/billing — юзеру: "проверь chatgpt.com → Settings → Billing, потом `codex logout && codex login`" |
| `bwrap: ... Operation not permitted` | **Kernel-уровень**, не codex. На Ubuntu 22.04+: `sudo sysctl kernel.apparmor_restrict_unprivileged_userns=0` (+ закрепить в `/etc/sysctl.d/99-codex-bwrap.conf`). Без перезагрузки. На VPS ris уже сделано. |
| `resume` с несуществующим UUID | Удалить запись из `codex_sessions.json` по slug, сказать юзеру "сессия протухла, начинаю новую" |
| `tee` упал — output не записан | Проверить `$OUTPUT_FILE` существует и не пустой (`test -s`). Если пустой — посмотреть `/tmp/codex-last.jsonl` последние 30 строк. |
| Codex изменил **не тот** файл | После Codex проверять `git status` — изменено должно быть только `<feature_dir>/codex_<slug>.md`. Если что-то ещё — флагить юзеру. |
| Rate limit | Стоп, не ретраить. Показать юзеру. |
| Таймаут (>5 мин) | В Bash: `timeout: 300000`. Если всё равно — сократить промпт или `run_in_background: true`. |

## Технические детали

- **Модель и reasoning:** `gpt-5.5` + `model_reasoning_effort="high"` для review (`-c` override). Эфемерный one-off — `medium` из config.toml
- **Sandbox:** `workspace-write` для review (нужно записать файл) / `read-only` для эфемерного
- **Approval:** `codex exec --ask-for-approval=never` дефолт (автономно)
- **Pointers:** `<feature_dir>/codex_sessions.json` — `{slug: {uuid, topic, started, last_used, turns}}`. **НЕ в /tmp** (теряются на reboot)
- **Сырьё сессий:** `~/.codex/sessions/<год>/<месяц>/<UUID>.jsonl` — Codex ведёт сам
- **JSONL last call:** `/tmp/codex-last.jsonl` — временный, для извлечения thread_id
- **Final message:** `/tmp/codex-last-msg.txt` — что Codex сказал в конце (короткий summary, не сам review)
- **Security:** при `workspace-write` Codex читает любые файлы в cwd. **НЕ запускать в директориях с `.env`/credentials** без проверки `ls -a` на секреты. В промпте явно говорить "пиши только в `$OUTPUT_FILE`, не трогай другие файлы"
- **MCP:** Codex поддерживает MCP-сервера (Serena LSP) — можно подключить отдельно через `codex mcp` для лучшей навигации в больших кодовых базах. Не обязательно

## Что НЕ делать

- ❌ Не показывать сырой JSONL юзеру — только путь к review-файлу + краткий пересказ
- ❌ Не создавать новую сессию на follow-up — `resume`
- ❌ Не забывать в промпте "пиши на русском" если юзер на русском
- ❌ Не забывать `OUTPUT FILE` и `PROJECT CONTEXT` в промпте
- ❌ Не **соглашаться слепо** с blocking-замечаниями — проверять через код
- ❌ Не использовать `-s danger-full-access` или `--dangerously-bypass-approvals-and-sandbox` без явного "да" юзера
- ❌ Не запускать `workspace-write` в директориях с секретами
- ❌ Не дёргать юзера на каждый Round — итерировать до консенсуса (с эскалацией для удаления функционала)
- ❌ Не сохранять pointer'ы в `/tmp` — теряются при reboot на tmpfs
- ❌ Не вызывать Codex на тривиальщине — трата лимитов
