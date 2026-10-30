"""Lexical fact search core (design §九): tokenizing, safe FTS queries, RRF + rerank, and the
synthetic 20k-row benchmark from the prototype."""

from __future__ import annotations

import random
import sqlite3
import time

import pytest

from agent.fact_search import cjk_expand, fts_phrase, query_terms, rrf_fuse
from agent.memory_db import MemoryDB
from agent.room_ledger import Ledger

DAY = 86400.0


# ── tokenizing ──────────────────────────────────────────────────────────────────


def test_cjk_expand_writes_bigrams_and_single_chars():
    assert cjk_expand("健康判据").split() == ["健康", "康判", "判据", "健", "康", "判", "据"]
    assert cjk_expand("gateway 健康 ok").split() == ["gateway", "健康", "健", "康", "ok"]
    assert cjk_expand("围").split() == ["围"]
    assert cjk_expand("plain text only").split() == ["plain", "text", "only"]
    assert "テス" in cjk_expand("テスト").split()
    assert "한국" in cjk_expand("한국어").split()
    # A CJK run glued to latin text is still split off.
    assert cjk_expand("phi网关").split() == ["phi", "网关", "网", "关"]


def test_query_terms_latin_words_and_cjk_bigrams():
    assert query_terms("Gateway LOG a 7 网关健康判据 围") == [
        "gateway", "log", "网关", "关健", "健康", "康判", "判据", "围"]
    assert query_terms("busy_router") == ["busy", "router"]
    assert query_terms("health Health HEALTH") == ["health"]
    assert query_terms('"*" - NEAR( OR') == ["near", "or"]
    assert query_terms("") == []


def test_fts_phrase_quotes_and_escapes():
    assert fts_phrase("abc") == '"abc"'
    assert fts_phrase('a"b') == '"a""b"'


def test_rrf_fuse_uses_k60_reciprocal_ranks():
    fused = rrf_fuse([[1, 2], [2, 3]])
    assert fused[2] == pytest.approx(1 / 62 + 1 / 61)
    assert fused[1] == pytest.approx(1 / 61)
    assert fused[3] == pytest.approx(1 / 62)


# ── small-store behaviour ───────────────────────────────────────────────────────


def test_typo_term_is_rescued_by_trigram_index(tmp_path):
    led = Ledger(tmp_path / "room")
    want = led.add("gateway restarted cleanly", kind="fact")
    led.add("unrelated deploy note", kind="note")
    assert [h["id"] for h in led.search("gatway")] == [want]
    assert [h["id"] for h in led.search("gateway")] == [want]
    led.close()


def test_recency_breaks_ties_with_14_day_half_life(tmp_path):
    led = Ledger(tmp_path / "room")
    now = time.time()
    new = led.add("router timeout raised", kind="fact", ts=now)
    old = led.add("router timeout raised", kind="fact", ts=now - 14 * DAY)  # newer id: wins a plain bm25 tie
    hits = led.search("router timeout")
    assert [h["id"] for h in hits] == [new, old]
    led.close()


def test_kind_weight_ranks_decision_above_step(tmp_path):
    led = Ledger(tmp_path / "room")
    now = time.time()
    decision = led.add("proxy port changed", kind="decision", ts=now)
    step = led.add("proxy port changed", kind="step", ts=now)  # newer id: wins a plain bm25 tie
    assert [h["id"] for h in led.search("proxy port")] == [decision, step]
    led.close()


INJECTIONS = ['"', "*", "NEAR(", "OR", "-", "NOT", "AND", "^", ":", "(", ")", "body:x", '"unterminated',
              "* OR *", "x* -y", 'alpha" OR "', "NEAR(alpha beta, 5)"]


@pytest.fixture(params=["ledger", "memory"])
def small_store(request, tmp_path):
    if request.param == "ledger":
        store = Ledger(tmp_path / "room")
        for text in ("alpha beta release", "gamma delta deploy", "epsilon zeta rollback"):
            store.add(text, kind="fact")
        search = store.search
    else:
        store = MemoryDB(tmp_path / "memory.db")
        for text in ("alpha beta release", "gamma delta deploy", "epsilon zeta rollback"):
            store.add("memory", "soft", text, kind="fact")
        search = store.search
    yield store, search
    store.close()


@pytest.mark.parametrize("raw", [s for s in INJECTIONS if "alpha" not in s])
def test_fts_operator_strings_neither_raise_nor_match_everything(small_store, raw):
    _store, search = small_store
    assert search(raw) == []


def test_fts_operator_words_are_plain_words(small_store):
    store, search = small_store
    if isinstance(store, Ledger):
        near = store.add("the build waits near the proxy", kind="note")
    else:
        near = store.add("memory", "soft", "the build waits near the proxy", kind="note")
    assert [h["id"] for h in search("NEAR(")] == [near]
    # A quoted-phrase break-out attempt only finds rows that contain its words.
    assert {h["text"] for h in search('alpha" OR "')} == {"alpha beta release"}
    found = {h["text"] for h in search("NEAR(alpha beta, 5)")}
    assert "alpha beta release" in found
    assert not found & {"gamma delta deploy", "epsilon zeta rollback"}


def test_raw_user_text_in_match_would_raise(tmp_path):
    """Deliberately-wrong variant: passing user text straight to MATCH breaks; the safe builder must not."""
    led = Ledger(tmp_path / "room")
    led.add("alpha beta", kind="fact")
    conn = sqlite3.connect(led.path)
    try:
        for raw in ("NEAR(", '"', "*"):
            with pytest.raises(sqlite3.OperationalError):
                conn.execute("SELECT rowid FROM entries_words WHERE entries_words MATCH ?", (raw,)).fetchall()
    finally:
        conn.close()
        led.close()


# ── benchmark (design §九 prototype): 20k filler rows, 5 hidden facts, 12 queries ──────────────────

SEEDS = {
    "s1": ("decision", 3, "BusyRouter keeps the primary model's reasoning effort when it falls back to the "
                          "secondary model.", "busy router fallback reasoning effort"),
    "s2": ("fact", 2, "Gateway health criterion: after a restart the gateway log must show 'platform connected' "
                      "within 60 s; a running process alone does not count.", "网关健康判据 health criteria"),
    "s3": ("decision", 1, "Room fence: use Landlock when the kernel supports it, otherwise fall back to bwrap; "
                          "without any fence the session refuses to start.", "围栏 sandbox 沙箱 bubblewrap"),
    "s4": ("result", 4, "Test containers carry the label phi.test=1 and are removed after every run; cleanup "
                        "check passed 9/9.", "容器清理 cleanup"),
    "s5": ("fact", 5, "Upstream sync takes only stable releases (newest non-prerelease tag vX.Y.Z); commits on "
                      "main outside a stable release are never ported.", "上游稳定版 stable release tag"),
}

QUERIES = [
    ("busyruoter reasoning", "s1"),
    ("busy router fallback", "s1"),
    ("gatway log", "s2"),
    ("网关健康判据", "s2"),
    ("gateway health criteria", "s2"),
    ("landlok bwrap", "s3"),
    ("围栏", "s3"),
    ("sandbox kernel", "s3"),
    ("test container label", "s4"),
    ("容器清理", "s4"),
    ("stable release tag", "s5"),
    ("上游稳定版", "s5"),
]

# Every row matching two or more query words is planted on purpose: a seed, a partial decoy (some of a
# query's words, any kind and age) or a full decoy (all of them, but an old step/note that recency and kind
# weight must rank below the seed). Filler rows are background noise carrying at most one query word.
PARTIAL_DECOYS = [
    "busy loop in router fixed", "reasoning tokens counted in usage", "router fallback retried twice",
    "gateway restarted after update", "log rotation enabled", "gateway health ok",
    "health check criteria draft for workers", "bwrap missing on the build image", "landing page copy updated",
    "test container started", "container label added to compose file", "tagged release candidate",
    "stable branch release notes", "网关日志轮转", "健康检查通过", "容器测试通过", "清理临时文件", "上游分支同步完成",
]
FULL_DECOYS = ["检查围栏日志", "kernel sandbox module loaded"]

QUERY_WORDS = """gateway log logs health criteria busy router reasoning fallback kernel sandbox test tests container
label release tag stable""".split()
QUERY_CJK = ["网关", "健康", "容器", "清理", "上游", "稳定"]

BACKGROUND_WORDS = """check model session restart deploy config build error timeout retry branch commit push merge
upstream matrix room space memory token cache disk cpu gpu latency api key rotate provider profile plugin skill
tool prompt context summary voice audio file preview upload terminal browser display screen mobile theme font logo
brand version patch script docker image volume network port proxy dns cert queue worker thread lock sqlite index
search query rank score agent user admin chat message reply stream the and after with for on in to of from was is
not fixed added removed updated failed passed started stopped draft review plan task step note todo result
decision blocker run runs ran service process host path env secret backup restore migrate schema table column row
field value limit budget quota usage cost price billing""".split()

BACKGROUND_CJK = """日志 检查 测试 标签 发布 版本 分支 提交 推送 合并 路由 推理 回退 内核 模型 会话 重启 部署 配置 构建 错误 超时
重试 缓存 磁盘 延迟 密钥 插件 技能 工具 上下文 摘要 语音 文件 预览 上传 终端 浏览器 屏幕 手机 主题 字体 品牌 补丁 脚本
镜像 网络 端口 代理 证书 队列 线程 索引 搜索 用户 消息 范围 完成 失败 通过 开始 结束""".split()

KIND_MIX = ["step"] * 35 + ["note"] * 25 + ["result"] * 10 + ["todo"] * 10 + ["fact"] * 8 + ["decision"] * 7 + \
    ["blocker"] * 5


def _filler_rows(rng: random.Random, now: float, count: int) -> list[dict]:
    # Synthetic words skip b, g, l and t, so they never contain a 3-gram of the typo queries by accident;
    # background words still do ("after", "note", "and", "plan").
    synthetic = sorted({"".join(rng.choice("dfkmnprsvz") + rng.choice("aeiou") for _ in range(rng.randint(2, 4)))
                        for _ in range(4000)})
    rows = []
    for i, text in enumerate(PARTIAL_DECOYS * 6):
        rows.append({"text": text, "kind": ("step", "note", "todo", "fact")[i % 4],
                     "ts": now - rng.uniform(10, 200) * DAY})
    for i, text in enumerate(FULL_DECOYS * 6):
        rows.append({"text": text, "kind": ("step", "note")[i % 2], "ts": now - rng.uniform(60, 200) * DAY})
    while len(rows) < count:
        parts: list[str] = []
        for _ in range(rng.randint(12, 40)):
            r = rng.random()
            if r < 0.30:
                parts.append(rng.choice(BACKGROUND_WORDS))
            elif r < 0.42:
                word = rng.choice(BACKGROUND_CJK)
                if parts and "\u4e00" <= parts[-1][-1] <= "\u9fff":
                    parts[-1] += word  # Chinese runs carry no spaces
                else:
                    parts.append(word)
            else:
                parts.append(rng.choice(synthetic))
        if rng.random() < 0.25:
            parts.insert(rng.randrange(len(parts) + 1), rng.choice(QUERY_WORDS + QUERY_CJK))
        rows.append({"text": " ".join(parts), "kind": rng.choice(KIND_MIX), "ts": now - rng.uniform(0, 365) * DAY})
    return rows


@pytest.fixture(scope="module")
def bench(tmp_path_factory):
    rng = random.Random(20261025)
    now = time.time()
    led = Ledger(tmp_path_factory.mktemp("bench") / "room")
    led.add_many(_filler_rows(rng, now, 20000))
    seed_ids = {}
    for name, (kind, age, text, keywords) in SEEDS.items():
        seed_ids[name] = led.add(text, kind=kind, keywords=keywords, ts=now - age * DAY)
    yield led, seed_ids
    led.close()


def _misses(led, seed_ids, *, rerank):
    report = []
    for query, want in QUERIES:
        hits = led.search(query, k=3, rerank=rerank)
        if not hits or hits[0]["id"] != seed_ids[want]:
            report.append((query, want, [(h["id"], round(h["score"], 6), round(h["coverage"], 2), h["kind"],
                                          h["text"][:60]) for h in hits]))
    return report


def test_benchmark_has_20k_filler_rows(bench):
    led, _ = bench
    conn = sqlite3.connect(led.path)
    try:
        assert conn.execute("SELECT count(*) FROM entries").fetchone()[0] == 20005
        assert conn.execute("SELECT count(*) FROM entries_words").fetchone()[0] == 20005
        assert conn.execute("SELECT count(*) FROM entries_tri").fetchone()[0] == 20005
    finally:
        conn.close()


def test_benchmark_all_12_queries_top1_with_rerank(bench):
    led, seed_ids = bench
    assert _misses(led, seed_ids, rerank=True) == []


def test_benchmark_plain_rrf_misses_at_least_one(bench):
    """Negative control: without the rerank the same benchmark must fail somewhere, otherwise it proves nothing."""
    led, seed_ids = bench
    assert _misses(led, seed_ids, rerank=False), "plain RRF found all 12 — benchmark does not discriminate"


def test_benchmark_latency_p95_under_50ms(bench):
    led, _ = bench
    for query, _want in QUERIES:  # warm the page cache
        led.search(query)
    samples = []
    for _ in range(5):
        for query, _want in QUERIES:
            start = time.perf_counter()
            led.search(query)
            samples.append(time.perf_counter() - start)
    samples.sort()
    p95 = samples[int(len(samples) * 0.95) - 1]
    assert p95 < 0.050, f"p95 {p95 * 1000:.1f} ms, max {samples[-1] * 1000:.1f} ms"
