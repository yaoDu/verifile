"""BM25 index over evidence chunks.

Deliberately lexical rather than embedding-based. Filing questions turn on exact
terminology — "capital expenditure", "Item 1A", "finance leases", concept names
and dollar figures — where BM25 with metadata filters is more predictable than
a dense retriever, needs no model download, and is fully reproducible offline.
The trade-off (weak paraphrase recall) is documented in the README and
mitigated by hand-written query-term expansions in the topic catalogue.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from ..models import EvidenceChunk, RetrievedEvidence

K1 = 1.5
B = 0.75

_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-\.']*")

# Common English function words. Kept small on purpose: filing vocabulary such as
# "may", "will" and "could" is load-bearing in risk factors, so an aggressive
# stopword list would hurt recall on exactly the queries analysts care about.
STOPWORDS = frozenset(
    (
        "a an and are as at be been but by can could did do does for from had has have how i if in "
        "into is it its may might of on or our ours she he they them their this that these those to "
        "was we were what when where which while who will with would you your not no nor"
    ).split()
)


# Words that describe the *act of asking*, not the subject being asked about.
# Filings never contain them, so they must not count against query coverage.
QUESTION_WORDS = frozenset(
    (
        "what which who whom whose when why how did does do is are was were describe description "
        "say said tell explain discuss mention state stated indicate identify identified factors "
        "factor drove driver drivers cause caused change changed changes about regarding concerning "
        "give provide show list summarize summarise compare comparison happened occur occurred "
        "appear appeared prominent new old any some many much more most between versus vs"
    ).split()
)


def tokenize(text: str) -> list[str]:
    toks = _TOKEN.findall(text.lower())
    return [t.strip(".-'") for t in toks if t.strip(".-'") and t not in STOPWORDS]


@dataclass
class _Doc:
    chunk: EvidenceChunk
    tf: Counter = field(default_factory=Counter)
    length: int = 0


class Bm25Index:
    """Small in-memory BM25 index with metadata filtering."""

    def __init__(self, chunks: list[EvidenceChunk]) -> None:
        self.docs: list[_Doc] = []
        self.df: Counter = Counter()
        for c in chunks:
            toks = tokenize(f"{c.heading} {c.text}")
            d = _Doc(chunk=c, tf=Counter(toks), length=len(toks))
            self.docs.append(d)
            self.df.update(d.tf.keys())
        self.n = len(self.docs)
        self.avg_len = (sum(d.length for d in self.docs) / self.n) if self.n else 0.0

    def _idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def search(
        self,
        query: str,
        *,
        period: str | None = None,
        section_ids: tuple[str, ...] | None = None,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> list[RetrievedEvidence]:
        terms = tokenize(query)
        if not terms or not self.n:
            return []
        results: list[RetrievedEvidence] = []
        for d in self.docs:
            if period and d.chunk.period != period:
                continue
            if section_ids and d.chunk.section_id not in section_ids:
                continue
            score = 0.0
            matched: list[str] = []
            for t in terms:
                f = d.tf.get(t, 0)
                if not f:
                    continue
                matched.append(t)
                denom = f + K1 * (1 - B + B * (d.length / self.avg_len if self.avg_len else 1))
                score += self._idf(t) * (f * (K1 + 1)) / denom
            if score > min_score:
                results.append(
                    RetrievedEvidence(
                        chunk=d.chunk, score=round(score, 4), matched_terms=sorted(set(matched))
                    )
                )
        results.sort(key=lambda r: (-r.score, r.chunk.chunk_id))
        return results[:top_k]

    def phrase_frequency(
        self, phrases: list[str], *, period: str, section_ids: tuple[str, ...] | None = None
    ) -> dict[str, int]:
        """Word-boundary occurrences of each phrase in one period.

        Phrase counting (rather than summing per-token frequencies) is what keeps
        the emphasis measure honest: "artificial intelligence" is one mention,
        not two, and a phrase list containing both "ai" and "generative ai" does
        not double-count the same sentence.
        """
        # Longest phrase first so that "generative ai" consumes the span before
        # the bare "ai" pattern can count it again.
        ordered = sorted(phrases, key=lambda p: (-len(p), p))
        patterns = [
            (p, re.compile(r"\b" + r"\s+".join(re.escape(w) for w in p.lower().split()) + r"\b"))
            for p in ordered
        ]
        counts = dict.fromkeys(phrases, 0)
        for d in self.docs:
            if d.chunk.period != period:
                continue
            if section_ids and d.chunk.section_id not in section_ids:
                continue
            body = f"{d.chunk.heading} {d.chunk.text}".lower()
            consumed: list[tuple[int, int]] = []
            for phrase, pat in patterns:
                for m in pat.finditer(body):
                    if any(m.start() < ce and cs < m.end() for cs, ce in consumed):
                        continue
                    consumed.append((m.start(), m.end()))
                    counts[phrase] += 1
        return counts

    @staticmethod
    def content_terms(query: str) -> list[str]:
        """Query terms that name *subject matter*, not the act of asking.

        A filing never contains "describe", "drove" or "tell", so leaving those
        in a coverage calculation makes a perfectly answerable question look
        unanswerable purely because of how it was phrased.
        """
        return [t for t in dict.fromkeys(tokenize(query)) if t not in QUESTION_WORDS]

    def query_coverage(
        self, query: str, *, section_ids: tuple[str, ...] | None = None
    ) -> tuple[float, list[str]]:
        """IDF-weighted share of the query's terms that exist in the corpus.

        A raw BM25 score is not a usable "did we actually answer this?" signal:
        an off-topic question still scores well if it happens to share common
        words with the filing ("chief executive officer's favourite colour"
        matches on *chief*, *executive* and *officer*). Coverage asks a
        different question — are the *distinctive* words of the query present at
        all? Terms absent from the corpus carry their full (maximum) IDF into
        the denominator, so a question hinging on undisclosed terminology scores
        near zero however many common words it shares.

        Returns ``(coverage, missing_terms)``.
        """
        terms = self.content_terms(query)
        if not terms or not self.n:
            return 0.0, terms
        if section_ids:
            present = set()
            for d in self.docs:
                if d.chunk.section_id in section_ids:
                    present |= d.tf.keys()
        else:
            present = set(self.df)

        total = matched = 0.0
        missing: list[str] = []
        for t in terms:
            weight = self._idf(t)
            total += weight
            if t in present:
                matched += weight
            else:
                missing.append(t)
        return (matched / total if total else 0.0), missing

    def token_count(self, *, period: str, section_ids: tuple[str, ...] | None = None) -> int:
        return sum(
            d.length
            for d in self.docs
            if d.chunk.period == period and (not section_ids or d.chunk.section_id in section_ids)
        )

    def chunk_ids(self) -> set[str]:
        return {d.chunk.chunk_id for d in self.docs}
