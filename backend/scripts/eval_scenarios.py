"""Agent quality metrics (task "Метрики качества агента"): runs scripted dialogues against a RUNNING app.

    cd backend && python scripts/eval_scenarios.py [--base http://localhost:8080] [--out ../docs/metrics.md]

It needs a configured LLM (GIGACHAT_AUTH_KEY), because it exercises the real agents. Per scenario it measures:
completed (plan ready/partial/booked at the end), clarification turns, time to the first recommendation,
verifier errors left in the final plan. Unseen-query behaviour is what the jury tests, so extend SCENARIOS.
"""
import argparse
import statistics
import sys
import time
import uuid

import httpx

SCENARIOS = [
    ("Москва: полный запрос, только отели", ["Найди отели в Москве на 6-9 ноября для двух взрослых. Завтрак и бесплатная отмена, до 30 000 рублей за всё проживание."]),
    ("Питер: неполный запрос", ["Хочу в Питер на выходные", "Из Москвы, нас двое, 14-16 ноября"]),
    ("Питер: поездка с изменениями", ["Поездка в Санкт-Петербург из Москвы с 14 по 16 ноября, нас двое", "Сделай дешевле", "А если на два дня позже?", "С нами едет собака"]),
    ("Россия: несколько городов", ["Москва, Казань, Нижний Новгород на неделю с 1 ноября, нас двое, поездом или самолётом", "Принимаю даты"]),
    ("Размытый запрос про море", ["Хочу куда-нибудь к тёплому морю в ноябре, недорого, с ребёнком 7 лет, без долгих перелётов", "Из Москвы, нас двое взрослых"]),
    ("Япония: Токио и Осака", ["Из Москвы в Токио и Осаку на 8 ночей с 12 ноября, двое взрослых, бюджет 450 000"]),
    ("Море: от размытого запроса до плана", ["Хочу куда-нибудь к тёплому морю в ноябре, недорого, с ребёнком 7 лет, без долгих перелётов", "Из Москвы, нас двое взрослых", "Сочи", "С 14 по 21 ноября"]),
    ("Бали на неделю", ["Хочу на Бали на неделю с 7 ноября, из Москвы с билетами, нас двое, бюджет 400 000 за всё", "Принимаю даты"]),
    ("Только поезд", ["Только билеты на поезд из Москвы в Казань 14 ноября, обратно 16 ноября, нас двое"]),
    ("Семья с собакой в Сочи", ["Сочи с 20 по 27 декабря, трое взрослых и дети 3 и 9 лет, едем с собакой, из Москвы, до 300 000"]),
    ("Однодневная поездка «завтра»", ["Завтра утром из Москвы в Нижний Новгород, вечером обратно, еду один"]),
    ("Автобусом, без самолётов", ["Из Москвы в Нижний Новгород автобусом на выходные, нас двое"]),
    ("Пересборка: четверо, без завтрака", ["Отель в Москве с 6 по 9 ноября, двое взрослых, с завтраком", "Нас будет четверо", "Убери завтрак"]),
]


def run(base: str, messages: list[str], timeout: float = 240) -> dict:
    """One scripted dialogue as a fresh guest: send each message, wait until the agents are idle, read the result."""
    with httpx.Client(base_url=base, timeout=30) as c:
        auth = c.post("/api/v1/auth/guest")
        auth.raise_for_status()
        h = {"Authorization": f"Bearer {auth.json()['token']}"}
        chat = c.get("/api/v1/chats/active", headers=h).json()["id"]
        t0, first_rec, view, timed_out = time.time(), None, None, False
        for text in messages:
            c.post(f"/api/v1/chats/{chat}/messages", json={"text": text, "client_message_id": str(uuid.uuid4())}, headers=h).raise_for_status()
            deadline = time.time() + timeout
            finished = False
            while time.time() < deadline:
                time.sleep(1.0)
                r = c.get(f"/api/v1/chats/{chat}/plan", headers=h)
                view = r.json()["view"] if r.status_code == 200 else None  # 404: no plan yet (e.g. the agents asked a question)
                if first_rec is None and view and any(n.get("selected_offer_ref") for n in view["nodes"].values()):
                    first_rec = time.time() - t0
                if not c.get(f"/api/v1/chats/{chat}/status", headers=h).json()["busy"]:
                    finished = True
                    break
            timed_out = timed_out or not finished
        msgs = c.get(f"/api/v1/chats/{chat}/messages", headers=h).json()
        questions = sum(1 for m in msgs if m["role"] == "assistant" and (m.get("turn") or {}).get("kind") == "question")
        status = view["status"] if view else "no plan"
        errors = [x["code"] for x in (view or {}).get("checks", []) if x["severity"] == "error"]
        complete = bool(view) and (view.get("pricing") or {}).get("is_complete") is True
        # success = a COMPLETE plan (every priced part has a chosen option) without verifier errors; a partial plan, a
        # timeout and an error are different outcomes and are counted apart, never as success
        outcome = ("timeout" if timed_out else "directions" if status == "choosing_destination" else "ok" if status in ("ready", "booked", "in_cart") and complete and not errors
                   else "partial" if status == "partial" or (view and not complete) else "errors" if errors else "no plan")
        return {"completed": outcome == "ok", "outcome": outcome, "status": status, "questions": questions,
                "ttfr": first_rec, "errors": errors, "messages": len(messages)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    ap.add_argument("--out")
    a = ap.parse_args()
    rows = []
    for name, msgs in SCENARIOS:
        print(f"... {name}", flush=True)
        try:
            rows.append((name, run(a.base, msgs)))
        except Exception as e:  # noqa: BLE001
            rows.append((name, {"completed": False, "outcome": "error", "status": f"error: {e}", "questions": 0, "ttfr": None, "errors": [], "messages": len(msgs)}))
    lines = ["| Сценарий | Полный план без ошибок | Итог | Уточнений | До первой рекомендации, с | Ошибки состыковок |", "|---|---|---|---:|---:|---|"]
    for name, r in rows:
        lines.append(f"| {name} | {'да' if r['completed'] else 'нет'} | {r.get('outcome', r['status'])} | {r['questions']} | {r['ttfr'] and round(r['ttfr'], 1) or '—'} | {', '.join(r['errors']) or '—'} |")
    done = [r for _, r in rows if r["completed"]]
    ttfr = [r["ttfr"] for r in done if r["ttfr"]]
    shown = [r for _, r in rows if r.get("outcome") == "directions"]
    lines += ["", f"Полный план без ошибок: {len(done)} из {len(rows)}; ещё {len(shown)} сценариев остановились на выборе направления (так и задумано: ждут выбора пользователя). Частичные, таймауты и ошибки считаются отдельно, см. столбец «Итог». Уточнений в среднем: {statistics.mean(r['questions'] for _, r in rows):.1f}. "
              + (f"Медиана времени до первой рекомендации: {statistics.median(ttfr):.1f} с." if ttfr else "")]
    out = "\n".join(lines)
    print("\n" + out)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(out + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
