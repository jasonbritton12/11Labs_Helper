# P04 composition contract

This note freezes the deterministic candidate search consumed by P05. It applies
to the house English v1 profile; it does not claim a general grammar parser.

## Fixed source-mode candidates

Source mode emits exactly one candidate for every baseline cue, in baseline cue
order. It may add line breaks only at whitespace inside that cue. It never changes
the cue's source identity, count, or timing. A cue with missing or absent source
references remains a fixed candidate with its normalized baseline wording and a
source-linked diagnostic; it is never realigned by matching words or timestamps.

Speaker notation is authored before capacity/counting. The first dialogue cue
after a dialogue-speaker change receives `- `; pure audio events neither receive
the dash nor update the previous dialogue speaker. Display count is the sum of
Unicode code points in authored lines, including spaces, punctuation, sound
notation, and the speaker dash. Newline separators do not count.

The composition ledger requires candidate token indices to equal the source token
indices exactly once and in source order. It also compares normalized displayed
wording after removing only a composer-recorded speaker dash. A mismatch is
`SOURCE_CONTENT_LEDGER_INCOMPLETE`; wording and source data stay intact.

## House-mode search bounds

House candidates are built from source-order semantic blocks. A block ends at a
speaker or content-kind change, unavailable timestamps, or a source gap greater
than `max_merge_gap_secs = 0.25`. It never merges dialogue with an audio event.

The dynamic program considers at most `max_group_tokens = 24` source tokens for
each event boundary. It has one cached state per token offset and evaluates
boundaries in ascending source order, so ties choose the earliest boundary. This
is a bounded linear-state search with at most 24 transitions per state, rather
than a whole-program exponential segmentation search.

Candidate costs compare lexicographically in this order:

1. content/synchronization integrity
2. hard-rule failures
3. reading-speed target violations (reserved for P05 timing evaluation)
4. linguistic break penalty
5. orphan second-line penalty
6. line-balance penalty
7. excessive-hang penalty (reserved for P05 timing evaluation)
8. event count

Within an event, one line wins whenever it fits 32 characters. Two-line layouts
must keep each line at or below 32 characters. They rank reviewed punctuation and
conjunction opportunities before balanced length, while penalizing article/noun,
adjective/noun, name-pair, subject/verb, auxiliary/verb, and preposition/phrase
breaks. A short one- or two-word second line is an orphan and carries
`LINE_BREAK_REVIEW_REQUIRED`. If no source-word layout fits the 32-by-2 capacity,
the best balanced faithful draft is returned with `LINE_CAPACITY_EXCEEDED`; a
single overlong word is retained whole and also receives `SINGLE_WORD_OVERLONG`.
