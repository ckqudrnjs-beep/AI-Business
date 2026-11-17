"""마케팅 자동화 파이프라인: 생성 → (휴대폰) 승인 → 발행. 표준 라이브러리만 사용.

  python3 automation/pipeline.py generate   # 초안 생성 → queue/pending
  python3 automation/pipeline.py notify     # 대기 초안을 텔레그램으로 전송(승인/반려 버튼)
  python3 automation/pipeline.py poll       # 버튼 응답 수집 → approved/rejected 이동
  python3 automation/pipeline.py publish    # 승인된 것만 발행(기본 DRY-RUN)
  python3 automation/pipeline.py report     # 큐 현황 요약
원칙: 승인(approved) 없이는 어떤 채널에도 발행하지 않는다. 결제·환불·광고비 집행은 자동화 범위 밖.
환경변수: ANTHROPIC_API_KEY(없으면 템플릿 초안), TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, PUBLISH_LIVE=1
"""
import json, os, sys, time, uuid, urllib.request, urllib.parse
from pathlib import Path

ROOT = Path(__file__).parent
Q = {s: ROOT / "queue" / s for s in ("pending", "sent", "approved", "rejected", "published")}
for d in Q.values(): d.mkdir(parents=True, exist_ok=True)
CFG = json.loads((ROOT / "config.json").read_text())
LOG = ROOT / "logs" / "events.jsonl"
DISCLOSURE = "\n\n※ 이 글은 AI의 도움을 받아 작성되었으며 운영자가 검수했습니다."

def log(ev, **kw):
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a") as f: f.write(json.dumps({"t": time.time(), "ev": ev, **kw}, ensure_ascii=False) + "\n")

def http(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=60) as r: return json.loads(r.read())

def llm(prompt):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key: return None
    body = json.dumps({"model": CFG["llm_model"], "max_tokens": 1200,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    out = http("https://api.anthropic.com/v1/messages", body,
               {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    return out["content"][0]["text"]

def tg(method, **params):
    tok = os.environ["TELEGRAM_BOT_TOKEN"]
    return http(f"https://api.telegram.org/bot{tok}/{method}", json.dumps(params).encode(),
                {"content-type": "application/json"})

def save(state, item): (Q[state] / f"{item['id']}.json").write_text(json.dumps(item, ensure_ascii=False, indent=1))
def load(state): return [json.loads(p.read_text()) for p in sorted(Q[state].glob("*.json"))]
def move(item, a, b): (Q[a] / f"{item['id']}.json").unlink(missing_ok=True); save(b, item)

def generate():
    topics_file = ROOT / "content" / "topics.txt"
    topics = [t.strip() for t in topics_file.read_text().splitlines() if t.strip()] if topics_file.exists() else []
    done = {i["topic"] for s in Q for i in load(s)}
    todo = [t for t in topics if t not in done][: CFG["daily_posts"]]
    for t in todo:
        prompt = (f"브랜드 '{CFG['brand']}' / 분야: {CFG['niche']} / 독자: {CFG['audience']} / 톤: {CFG['tone']}.\n"
                  f"주제 '{t}'로 블로그 초안을 한국어로 작성(제목, 3~4개 소제목, 실습 예시 1개, 마지막에 구독 안내 1문장). "
                  "수익 보장·과장·확인 안 된 통계는 금지. 모르는 사실은 쓰지 말 것.")
        body = llm(prompt) or f"# {t}\n\n(DRY: API 키 없음 — 템플릿 초안)\n- 핵심 3가지\n- 실습 예시\n- 구독 안내"
        if CFG["require_ai_disclosure"]: body += DISCLOSURE
        item = {"id": uuid.uuid4().hex[:8], "topic": t, "channels": CFG["channels"], "body": body, "created": time.time()}
        save("pending", item); log("generated", id=item["id"], topic=t)
        print("생성:", item["id"], t)
    if not todo: print("새 주제 없음 (content/topics.txt에 주제를 추가하세요)")

def notify():
    for it in load("pending"):
        preview = f"[{it['id']}] {it['topic']}\n채널: {', '.join(it['channels'])}\n\n{it['body'][:900]}"
        if not os.environ.get("TELEGRAM_BOT_TOKEN"):
            print("DRY(텔레그램 미설정):\n", preview[:300]); continue
        kb = {"inline_keyboard": [[{"text": "✅ 승인", "callback_data": f"ok:{it['id']}"},
                                   {"text": "❌ 반려", "callback_data": f"no:{it['id']}"}]]}
        tg("sendMessage", chat_id=os.environ["TELEGRAM_CHAT_ID"], text=preview, reply_markup=kb)
        move(it, "pending", "sent"); log("sent", id=it["id"])

def poll():
    if not os.environ.get("TELEGRAM_BOT_TOKEN"): print("텔레그램 미설정"); return
    offs = ROOT / "logs" / "offset"; off = int(offs.read_text()) if offs.exists() else 0
    for u in tg("getUpdates", offset=off, timeout=0)["result"]:
        off = u["update_id"] + 1
        cb = u.get("callback_query")
        if not cb or str(cb["message"]["chat"]["id"]) != os.environ["TELEGRAM_CHAT_ID"]: continue  # 본인 채팅만
        act, iid = cb["data"].split(":")
        it = next((i for i in load("sent") if i["id"] == iid), None)
        if it: move(it, "sent", "approved" if act == "ok" else "rejected"); log(act, id=iid)
        tg("answerCallbackQuery", callback_query_id=cb["id"], text="처리됨")
    offs.write_text(str(off))

def publish():
    live = os.environ.get("PUBLISH_LIVE") == "1"
    for it in load("approved"):
        for ch in it["channels"]:
            # TODO: 채널별 어댑터(블로그 API/인스타 Graph API/메일 발송). 지금은 기록만.
            print(("발행" if live else "DRY-RUN"), ch, it["id"], it["topic"]); log("publish", id=it["id"], ch=ch, live=live)
        if live: move(it, "approved", "published")

def report():
    print({s: len(list(Q[s].glob('*.json'))) for s in Q})

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    {"generate": generate, "notify": notify, "poll": poll, "publish": publish, "report": report}[cmd]()
