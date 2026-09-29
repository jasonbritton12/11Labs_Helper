"""Deterministic text composition candidates for the caption timing stage.

This module only chooses faithful token groups and explicit displayed lines.  It
does not alter times, render files, or claim that its small English break hints
are a general grammatical parser.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, replace
from typing import Iterable

from .models import (
    CaptionContentKind,
    CaptionContext,
    CaptionProfile,
    CaptionSource,
    CaptionSourceToken,
    CaptionTimingMode,
)
from .source import CaptionSourceAnalysis, CaptionSourceFinding


MAX_CHARS_PER_LINE = 32
MAX_LINES_PER_EVENT = 2
MAX_EVENT_CHARS = MAX_CHARS_PER_LINE * MAX_LINES_PER_EVENT
MAX_MERGE_GAP_SECS = 0.25
MAX_GROUP_TOKENS = 24
MAX_HANG_SECS = 1.0

_ARTICLES = frozenset({"a", "an", "the"})
_ADJECTIVES = frozenset({"big", "little", "new", "old", "red", "small", "young"})
_AUXILIARIES = frozenset({"am", "are", "be", "been", "being", "can", "could", "did", "do", "does", "had", "has", "have", "is", "may", "might", "must", "shall", "should", "was", "were", "will", "would"})
_PREPOSITIONS = frozenset({"about", "after", "at", "by", "for", "from", "in", "into", "of", "on", "over", "to", "under", "with"})
_PRONOUNS = frozenset({"he", "her", "hers", "him", "i", "it", "she", "they", "them", "we", "you"})
_COMMON_VERBS = frozenset({"are", "be", "call", "called", "can", "did", "do", "does", "go", "goes", "has", "have", "is", "know", "make", "need", "said", "say", "see", "think", "was", "were", "will", "work"})
_CONJUNCTIONS = frozenset({"and", "as", "because", "but", "or", "so", "though", "while", "yet"})


@dataclass(frozen=True)
class CompositionIssue:
    rule_id: str
    message: str
    source_token_indices: tuple[int, ...] = ()


@dataclass(frozen=True)
class CaptionCompositionCandidate:
    """One faithful event candidate for P05 timing/QC selection."""

    source_token_indices: tuple[int, ...]
    source_cue_indices: tuple[int, ...]
    speaker_id: str | None
    content_kind: CaptionContentKind
    original_speech_start: float | None
    original_speech_end: float | None
    authored_lines: tuple[str, ...]
    displayed_characters: int
    # Kept separately from the rendered lines so the content ledger can remove
    # only notation this composer added.  A literal dash in source text remains
    # source content.
    has_speaker_dash: bool = False
    issues: tuple[CompositionIssue, ...] = ()
    # P05 prepends measured timing costs; P04 supplies deterministic composition
    # components in the same documented lexical order.
    content_integrity_penalty: int = 0
    hard_rule_failures: int = 0
    reading_speed_penalty: int = 0
    linguistic_penalty: int = 0
    orphan_penalty: int = 0
    line_balance_penalty: int = 0
    excessive_hang_penalty: int = 0
    event_count_penalty: int = 1

    @property
    def displayed_text(self) -> str:
        return "\n".join(self.authored_lines)

    @property
    def hard_failure_count(self) -> int:
        return self.hard_rule_failures

    @property
    def penalty(self) -> tuple[int, int, int, int, int, int, int, int]:
        """Stable lexical cost consumed by the bounded house-mode search."""

        return (
            self.content_integrity_penalty,
            self.hard_rule_failures,
            self.reading_speed_penalty,
            self.linguistic_penalty,
            self.orphan_penalty,
            self.line_balance_penalty,
            self.excessive_hang_penalty,
            self.event_count_penalty,
        )


@dataclass(frozen=True)
class CaptionCompositionPlan:
    candidates: tuple[CaptionCompositionCandidate, ...]
    issues: tuple[CompositionIssue, ...]


def _display_count(lines: Iterable[str]) -> int:
    """Count displayed Unicode code points; line separators do not display."""

    return sum(len(line) for line in lines)


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _combining_issue(text: str, source_indices: tuple[int, ...]) -> CompositionIssue | None:
    if any(unicodedata.combining(character) for character in text):
        return CompositionIssue(
            "COUNTING_REVIEW_REQUIRED",
            "Displayed text contains combining code points; its destination counting policy needs review.",
            source_indices,
        )
    return None


def _word(value: str) -> str:
    return value.strip(".,!?;:\"'()[]").casefold()


def _is_name(value: str) -> bool:
    stripped = value.strip(".,!?;:\"'()[]")
    return len(stripped) > 1 and stripped[0].isupper() and stripped[1:].isalpha()


def _break_penalty(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[int, int, tuple[CompositionIssue, ...]]:
    """Small English-only hints; ambiguous layouts are explicitly reviewable."""

    before = _word(left[-1])
    after = _word(right[0])
    linguistic_penalty = 0
    orphan_penalty = 0
    issues: list[CompositionIssue] = []
    if left[-1].rstrip().endswith((".", "?", "!", ";", ":", ",")) or after in _CONJUNCTIONS:
        linguistic_penalty -= 3
    if before in _ARTICLES:
        linguistic_penalty += 30
        issues.append(CompositionIssue("LINE_BREAK_REVIEW_REQUIRED", "The break separates an article from a following phrase."))
    elif before in _ADJECTIVES:
        linguistic_penalty += 20
        issues.append(CompositionIssue("LINE_BREAK_REVIEW_REQUIRED", "The break may separate an adjective from a noun."))
    elif before in _PRONOUNS and after in _COMMON_VERBS:
        linguistic_penalty += 25
        issues.append(CompositionIssue("LINE_BREAK_REVIEW_REQUIRED", "The break may separate a subject from a verb."))
    elif before in _AUXILIARIES:
        linguistic_penalty += 25
        issues.append(CompositionIssue("LINE_BREAK_REVIEW_REQUIRED", "The break may separate an auxiliary from a verb."))
    elif before in _PREPOSITIONS:
        linguistic_penalty += 25
        issues.append(CompositionIssue("LINE_BREAK_REVIEW_REQUIRED", "The break may separate a preposition from its phrase."))
    elif _is_name(left[-1]) and _is_name(right[0]):
        linguistic_penalty += 20
        issues.append(CompositionIssue("LINE_BREAK_REVIEW_REQUIRED", "The break may separate a name pair."))
    if len(right) <= 2 and len(" ".join(right)) <= 12:
        orphan_penalty += 15
        issues.append(CompositionIssue("LINE_BREAK_REVIEW_REQUIRED", "The second line is a short orphan phrase."))
    return linguistic_penalty, orphan_penalty, tuple(issues)


def _line_options(words: tuple[str, ...], prefix: str) -> tuple[tuple[tuple[str, ...], tuple[int, int, int], tuple[CompositionIssue, ...]], ...]:
    """Return feasible line layouts sorted by preference, without changing words."""

    full = prefix + " ".join(words)
    options: list[tuple[tuple[str, ...], tuple[int, int, int], tuple[CompositionIssue, ...]]] = []
    if len(full) <= MAX_CHARS_PER_LINE:
        options.append(((full,), (0, 0, 0), ()))
    for break_at in range(1, len(words)):
        left = prefix + " ".join(words[:break_at])
        right = " ".join(words[break_at:])
        if len(left) > MAX_CHARS_PER_LINE or len(right) > MAX_CHARS_PER_LINE:
            continue
        linguistic_penalty, orphan_penalty, issues = _break_penalty(words[:break_at], words[break_at:])
        # Prefer natural breaks, then balanced lines, then the earlier boundary.
        # Natural/punctuation score is represented in ``linguistic_penalty``.
        # The final field only balances otherwise equivalent layouts.
        options.append(((left, right), (linguistic_penalty, orphan_penalty, abs(len(left) - len(right))), issues))
    return tuple(sorted(options, key=lambda option: (len(option[0]) != 1, option[1], option[0])))


def _fallback_lines(words: tuple[str, ...], prefix: str) -> tuple[str, ...]:
    """Preserve a failed draft using the most balanced source-word boundary."""

    full = prefix + " ".join(words)
    if len(words) == 1:
        return (full,)
    candidates = []
    for break_at in range(1, len(words)):
        left = prefix + " ".join(words[:break_at])
        right = " ".join(words[break_at:])
        candidates.append((max(len(left), len(right)), abs(len(left) - len(right)), break_at, (left, right)))
    return min(candidates)[3]


def _timing(tokens: tuple[CaptionSourceToken, ...]) -> tuple[float | None, float | None]:
    starts = [token.original_start for token in tokens if token.original_start is not None]
    ends = [token.original_end for token in tokens if token.original_end is not None]
    return (starts[0] if starts else None, max(ends) if ends else None)


def _candidate(
    tokens: tuple[CaptionSourceToken, ...],
    *,
    source_cue_indices: tuple[int, ...],
    speaker_id: str | None,
    content_kind: CaptionContentKind,
    prefix_dash: bool,
    fixed_text: str | None = None,
) -> CaptionCompositionCandidate:
    source_indices = tuple(token.source_word_index for token in tokens)
    # A fixed source cue's text is already canonical-normalized.  For a normal
    # token group, each token is an immutable source word/event notation.
    text = fixed_text if fixed_text is not None else " ".join(token.text for token in tokens)
    # House-mode units are source tokens, never pieces inferred by splitting a
    # token's text.  Fixed baseline cues predate source references in legacy
    # data, so their only safe reflow boundary is existing whitespace.
    words = tuple(text.split()) if fixed_text is not None else tuple(token.text for token in tokens)
    prefix = "- " if prefix_dash else ""
    options = _line_options(words, prefix) if words else ()
    issues: list[CompositionIssue] = []
    linguistic_penalty = 0
    orphan_penalty = 0
    balance_penalty = 0
    hard_rule_failures = 0
    content_integrity_penalty = 0
    if fixed_text is not None and tokens and _normalize(" ".join(token.text for token in tokens)) != _normalize(fixed_text):
        content_integrity_penalty = 1
        issues.append(
            CompositionIssue(
                "SOURCE_TEXT_MISMATCH",
                "A fixed baseline cue does not match its referenced source tokens; its text was retained unchanged.",
                source_indices,
            )
        )
    if options:
        lines, line_penalty, line_issues = options[0]
        linguistic_penalty, orphan_penalty, balance_penalty = line_penalty
        issues.extend(
            CompositionIssue(issue.rule_id, issue.message, source_indices)
            for issue in line_issues
        )
    elif not words:
        lines = ()
        hard_rule_failures = 1
        issues.append(
            CompositionIssue(
                "EMPTY_SOURCE_CUE",
                "A fixed source cue has no text to compose; it remains an explicit empty candidate.",
                source_indices,
            )
        )
    else:
        lines = _fallback_lines(words, prefix)
        hard_rule_failures = 1
        issues.append(
            CompositionIssue(
                "LINE_CAPACITY_EXCEEDED",
                "No source-word line layout fits the 32-character, two-line capacity; faithful draft retained.",
                source_indices,
            )
        )
        if any(len((prefix if position == 0 else "") + word) > MAX_CHARS_PER_LINE for position, word in enumerate(words)):
            issues.append(
                CompositionIssue(
                    "SINGLE_WORD_OVERLONG",
                    "A single source word exceeds line capacity and was preserved without splitting.",
                    source_indices,
                )
            )
    combining = _combining_issue("".join(lines), source_indices)
    if combining is not None:
        issues.append(combining)
    start, end = _timing(tokens)
    return CaptionCompositionCandidate(
        source_token_indices=source_indices,
        source_cue_indices=source_cue_indices,
        speaker_id=speaker_id,
        content_kind=content_kind,
        original_speech_start=start,
        original_speech_end=end,
        authored_lines=tuple(lines),
        displayed_characters=_display_count(lines),
        has_speaker_dash=prefix_dash,
        issues=tuple(issues),
        content_integrity_penalty=content_integrity_penalty,
        hard_rule_failures=hard_rule_failures,
        linguistic_penalty=linguistic_penalty,
        orphan_penalty=orphan_penalty,
        line_balance_penalty=balance_penalty,
    )


def _source_candidates(source: CaptionSource) -> tuple[CaptionCompositionCandidate, ...]:
    tokens_by_index = {token.source_word_index: token for token in source.tokens}
    candidates: list[CaptionCompositionCandidate] = []
    previous_speaker: str | None = None
    seen_dialogue = False
    for cue in source.baseline_cues:
        tokens = tuple(tokens_by_index[index] for index in cue.source_word_indices if index in tokens_by_index)
        content_kind = CaptionContentKind.AUDIO_EVENT if cue.is_audio_event else CaptionContentKind.WORD
        prefix_dash = not cue.is_audio_event and seen_dialogue and cue.speaker_id != previous_speaker
        candidate = _candidate(
            tokens,
            source_cue_indices=(cue.index,),
            speaker_id=cue.speaker_id,
            content_kind=content_kind,
            prefix_dash=prefix_dash,
            fixed_text=cue.text,
        )
        missing_refs = tuple(index for index in cue.source_word_indices if index not in tokens_by_index)
        if not cue.source_word_indices:
            candidate = replace(
                candidate,
                content_integrity_penalty=candidate.content_integrity_penalty + 1,
                issues=candidate.issues + (
                    CompositionIssue(
                        "SOURCE_TRACE_UNAVAILABLE",
                        "The fixed source cue has no source-word references; text was not realigned.",
                    ),
                ),
            )
        elif missing_refs:
            candidate = replace(
                candidate,
                content_integrity_penalty=candidate.content_integrity_penalty + 1,
                issues=candidate.issues + (
                    CompositionIssue(
                        "SOURCE_REFERENCE_MISSING",
                        "The fixed source cue references unavailable source tokens; text was not realigned.",
                        missing_refs,
                    ),
                ),
            )
        candidates.append(candidate)
        if not cue.is_audio_event:
            previous_speaker = cue.speaker_id
            seen_dialogue = True
    return tuple(candidates)


def _semantic_blocks(tokens: tuple[CaptionSourceToken, ...]) -> tuple[tuple[CaptionSourceToken, ...], ...]:
    blocks: list[list[CaptionSourceToken]] = []
    for token in tokens:
        if not blocks:
            blocks.append([token])
            continue
        previous = blocks[-1][-1]
        gap = None
        if previous.original_end is not None and token.original_start is not None:
            gap = token.original_start - previous.original_end
        must_split = (
            previous.speaker_id != token.speaker_id
            or previous.content_kind != token.content_kind
            or gap is None
            or gap > MAX_MERGE_GAP_SECS
        )
        if must_split:
            blocks.append([token])
        else:
            blocks[-1].append(token)
    return tuple(tuple(block) for block in blocks)


def _house_block_candidates(
    block: tuple[CaptionSourceToken, ...],
    previous_dialogue_speaker: str | None,
    seen_dialogue: bool,
    profile: CaptionProfile,
    next_block_start: float | None,
    program_end: float | None,
) -> tuple[CaptionCompositionCandidate, ...]:
    """Use bounded DP to minimize hard failures, then layout penalties/events."""

    content_kind = block[0].content_kind
    speaker_id = block[0].speaker_id
    initial_dash = content_kind is CaptionContentKind.WORD and seen_dialogue and speaker_id != previous_dialogue_speaker

    zero_cost = (0, 0, 0, 0, 0, 0, 0, 0)
    costs: list[tuple[int, int, int, int, int, int, int, int] | None] = [
        None
    ] * (len(block) + 1)
    choices: list[tuple[int, CaptionCompositionCandidate] | None] = [
        None
    ] * len(block)
    costs[len(block)] = zero_cost
    for start in range(len(block) - 1, -1, -1):
        best_cost: tuple[int, int, int, int, int, int, int, int] | None = None
        best_choice: tuple[int, CaptionCompositionCandidate] | None = None
        for end in range(start + 1, min(len(block), start + MAX_GROUP_TOKENS) + 1):
            candidate = _candidate(
                block[start:end],
                source_cue_indices=tuple(sorted({token.canonical_cue_index for token in block[start:end] if token.canonical_cue_index is not None})),
                speaker_id=speaker_id,
                content_kind=content_kind,
                prefix_dash=initial_dash and start == 0,
            )
            next_start = (
                block[end].original_start
                if end < len(block)
                else next_block_start
            )
            timing_hard, reading_speed, hang = _house_timing_cost(
                candidate,
                next_start=next_start,
                program_end=program_end,
                profile=profile,
            )
            candidate = replace(
                candidate,
                hard_rule_failures=candidate.hard_rule_failures + timing_hard,
                reading_speed_penalty=reading_speed,
                excessive_hang_penalty=hang,
            )
            tail_cost = costs[end]
            assert tail_cost is not None
            cost = (
                candidate.content_integrity_penalty + tail_cost[0],
                candidate.hard_rule_failures + tail_cost[1],
                candidate.reading_speed_penalty + tail_cost[2],
                candidate.linguistic_penalty + tail_cost[3],
                candidate.orphan_penalty + tail_cost[4],
                candidate.line_balance_penalty + tail_cost[5],
                candidate.excessive_hang_penalty + tail_cost[6],
                candidate.event_count_penalty + tail_cost[7],
            )
            # ``end`` increases from the earliest source boundary. Keeping the
            # first equal-cost choice makes ties stable without storing every
            # tail tuple (which would grow quadratically on long programs).
            if best_cost is None or cost < best_cost:
                best_cost = cost
                best_choice = (end, candidate)
        assert best_cost is not None and best_choice is not None
        costs[start] = best_cost
        choices[start] = best_choice

    selected: list[CaptionCompositionCandidate] = []
    position = 0
    while position < len(block):
        choice = choices[position]
        assert choice is not None
        position, candidate = choice
        selected.append(candidate)
    return tuple(selected)


def _house_timing_cost(
    candidate: CaptionCompositionCandidate,
    *,
    next_start: float | None,
    program_end: float | None,
    profile: CaptionProfile,
) -> tuple[int, int, int]:
    """Score the same bounds P05 will apply, without changing source times.

    This makes house segmentation and timing a joint bounded search: a grouping
    that necessarily exceeds duration, overlap, or 20-CPS limits loses before
    readability and event-count preferences.  P05 still emits the measured
    findings and remains the final timing authority.
    """

    start = candidate.original_speech_start
    speech_end = candidate.original_speech_end
    if start is None or speech_end is None or start < 0 or speech_end <= start:
        return 1, 1, 0

    caps = [start + profile.max_duration_secs, speech_end + MAX_HANG_SECS]
    if next_start is not None:
        caps.append(next_start)
    if program_end is not None and program_end >= 0:
        caps.append(program_end)
    end_cap = min(caps)
    required = max(
        profile.min_duration_secs,
        candidate.displayed_characters / profile.cps_target,
    )
    hard = 0
    if speech_end > end_cap:
        hard += 1
        end = speech_end
    else:
        end = min(max(speech_end, start + required), end_cap)
    duration = end - start
    if duration < profile.min_duration_secs or duration > profile.max_duration_secs:
        hard += 1
    if next_start is not None and end > next_start:
        hard += 1
    cps = candidate.displayed_characters / duration if duration > 0 else float("inf")
    reading_speed = int(cps > profile.cps_target)
    if cps > profile.cps_warning:
        hard += 1
    hang_ms = max(0, int(round((end - speech_end) * 1000)))
    return hard, reading_speed, hang_ms


def _house_candidates(
    source: CaptionSource,
    profile: CaptionProfile,
    context: CaptionContext | None,
) -> tuple[CaptionCompositionCandidate, ...]:
    candidates: list[CaptionCompositionCandidate] = []
    previous_speaker: str | None = None
    seen_dialogue = False
    blocks = _semantic_blocks(source.tokens)
    program_end = (
        context.duration_secs
        if context is not None and context.duration_secs is not None
        else source.duration_secs
    )
    for block_index, block in enumerate(blocks):
        next_block_start = (
            blocks[block_index + 1][0].original_start
            if block_index + 1 < len(blocks)
            else None
        )
        generated = _house_block_candidates(
            block,
            previous_speaker,
            seen_dialogue,
            profile,
            next_block_start,
            program_end,
        )
        candidates.extend(generated)
        if block[0].content_kind is CaptionContentKind.WORD:
            previous_speaker = block[0].speaker_id
            seen_dialogue = True
    return tuple(candidates)


def _analysis_issues(findings: tuple[CaptionSourceFinding, ...]) -> tuple[CompositionIssue, ...]:
    return tuple(
        CompositionIssue(finding.rule_id, finding.message, finding.source_word_indices)
        for finding in findings
    )


def _candidate_content_text(candidate: CaptionCompositionCandidate) -> str:
    """Return candidate wording with only composer-added notation removed.

    The composition ledger must distinguish a speaker dash from a dash that was
    present in a source word.  ``has_speaker_dash`` records that provenance so
    a faithful source string is never accidentally changed during checking.
    """

    lines = list(candidate.authored_lines)
    if candidate.has_speaker_dash and lines:
        assert lines[0].startswith("- ")
        lines[0] = lines[0][2:]
    return _normalize(" ".join(lines))


def compose_caption_plan(
    source: CaptionSource | CaptionSourceAnalysis,
    *,
    timing_mode: CaptionTimingMode,
    profile: CaptionProfile | None = None,
    context: CaptionContext | None = None,
) -> CaptionCompositionPlan:
    """Compose deterministic candidates without changing the source object."""

    if isinstance(source, CaptionSourceAnalysis):
        analysis = source
        caption_source = analysis.source
        issues = list(_analysis_issues(analysis.findings))
    else:
        caption_source = source
        issues = []
    if timing_mode is CaptionTimingMode.SOURCE:
        candidates = _source_candidates(caption_source)
    else:
        if profile is None:
            from .profiles import HOUSE_ENGLISH_V1

            profile = HOUSE_ENGLISH_V1
        candidates = _house_candidates(caption_source, profile, context)
    candidate_indices = tuple(index for candidate in candidates for index in candidate.source_token_indices)
    expected_indices = tuple(token.source_word_index for token in caption_source.tokens)
    candidate_text = _normalize(" ".join(_candidate_content_text(candidate) for candidate in candidates))
    expected_text = _normalize(" ".join(token.text for token in caption_source.tokens))
    if candidate_indices != expected_indices or candidate_text != expected_text:
        issues.append(
            CompositionIssue(
                "SOURCE_CONTENT_LEDGER_INCOMPLETE",
                "Composition could not preserve every source token exactly once in source order and wording.",
                expected_indices,
            )
        )
    return CaptionCompositionPlan(candidates=candidates, issues=tuple(issues))


def compose_caption_candidates(
    source: CaptionSource | CaptionSourceAnalysis,
    *,
    timing_mode: CaptionTimingMode,
    profile: CaptionProfile | None = None,
    context: CaptionContext | None = None,
) -> tuple[CaptionCompositionCandidate, ...]:
    """Compatibility-friendly candidate-only access for the P05 timing stage."""

    return compose_caption_plan(
        source,
        timing_mode=timing_mode,
        profile=profile,
        context=context,
    ).candidates
