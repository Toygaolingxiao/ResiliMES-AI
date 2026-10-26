import time, traceback
from resilimes.config import load_settings
from resilimes.llm.nightshift import build_openai_client
s = load_settings()
c = build_openai_client(base_url=s.meterless_base_url, token=s.meterless_runtime_token, timeout_s=300, app_id=s.meterless_app_id)
long_ctx = "Lot L%d at step %d waited %d min at tool group DIFF_%d.\n"
big = "".join(long_ctx % (i, i % 300, i % 97, i % 40) for i in range(400))
tests = [("tiny_64", [{"role":"user","content":"Reply with the single word OK."}], 64),
         ("tiny_4096", [{"role":"user","content":"Reply with the single word OK."}], 4096),
         ("ctx_4096", [{"role":"user","content":big + "\nWhich tool group appears most often? Answer in one line."}], 4096)]
for name, msgs, mt in tests:
    t = time.time()
    try:
        r = c.chat.completions.create(model=s.nemotron_model, messages=msgs, max_tokens=mt, temperature=0.2)
        u = getattr(r, "usage", None)
        print(name, "OK", round(time.time()-t,1), "s model=", r.model, "usage=", u and (u.prompt_tokens, u.completion_tokens), "text=", repr((r.choices[0].message.content or "")[-80:]))
    except Exception as e:
        print(name, "FAIL", round(time.time()-t,1), "s", type(e).__name__, getattr(e, "status_code", ""), str(e)[:300])
