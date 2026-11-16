# Prop Comp

NBA player prop lines for the 2026-27 season, graded against what the player actually did.

The board stores every DraftKings player prop ESPN still publishes: points, rebounds, assists, threes, PRA and the other combos, steals, blocks, double-doubles, triple-doubles, first basket, first field goal, and milestone alternates. Games already played come back with the open number and the last current number. Upcoming games include the full alternate ladder, and that ladder is kept after tip even if the feed later drops it. Today and the next two days are fetched again on each sync. Finished games already stored are not requested again.

## Look at it

- Interactive board: `docs/index.html`
- Static snapshot: `docs/snapshot.html`

The interactive board loads one slate at a time, plus a precomputed season map. That is what keeps it quick as the season gets long.

## Refresh

From this folder:

```bash
python3 -m propcomp
```

Python 3.11 or newer. No packages to install. The database is `data/propcomp.sqlite`. The site files are rewritten into `docs/`.

A finished game is frozen after its lines and box score are stored. Run the same command tomorrow and it only walks today, tomorrow, and the day after, then freezes anything that has ended.

## How a line is graded

- Totals: actual above the current number is over, below is under, equal is a push.
- Milestones: the player has to reach the posted threshold.
- Double-double and triple-double use points, rebounds, assists, steals, and blocks.
- First basket is the first made field goal of the game. First team field goal, including the Exact market, is the first made field goal for that player's team.
- Quarter milestones are counted from the play-by-play.
- A player who did not play is void.

The two American prices on a total are the two sides of the number. The feed does not say which one is the over, so the board shows both and does not guess.

## Daily update

`.github/workflows/sync.yml` runs the same sync every hour from 9:00am through 1:00am Eastern. That covers the window when the books post and move lines, and the window when games finish and can be graded. A run that finds nothing new does not commit. Finished games already stored are left alone. The workflow can also be started by hand from the Actions tab.
