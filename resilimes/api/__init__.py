"""HTTP API for the ResiliMES console."""

# The seed domain shared by the timeline API and the explain report
# endpoints: a Gantt "why?" deep link carries the timeline seed, so the
# two sides must accept the same range. Defined once, here, so the two
# cannot drift apart again.
SEED_MAX = 9
