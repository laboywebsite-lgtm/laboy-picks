# Laboy NBA Sports Betting Analytics Tool

A complete Python 3 sports betting analytics tool for the NBA, modeled after the MLB version. This tool provides model-based game predictions, odds comparison, pick tracking, and comprehensive performance analytics.

## Installation

```bash
# Required
pip install tabulate requests

# Optional (for enhanced features)
pip install beautifulsoup4 playwright anthropic

# For Playwright screenshot support
playwright install chromium
```

## Quick Start

### Fetch Today's Games
```bash
python3 nba.py
```

### Fetch & Cache Fresh Stats
```bash
python3 nba.py --refresh
```

### Show All Team Stats
```bash
python3 nba.py --stats
```

### Generate Model Picks
```bash
python3 nba.py --picks
```

### Export to HTML + JPG
```bash
python3 nba.py --export-html
```

## Core Features

### Model & Analysis
- **Fetch NBA.com Advanced Stats**: ORTG, DRTG, PACE per team
- **Game Model**: Pythagorean expectation with home court advantage
- **Market Odds**: Integration with The Odds API
- **EV+ Identification**: Picks with positive expected value vs market
- **Matchup Reports**: Detailed analysis for any two teams

### Pick Tracking
- **Log Picks**: Interactively log your personal picks
- **Grade Results**: Mark as W/L/P with automatic P&L calculation
- **Record Tracking**: Win-loss-push record with running balance
- **CSV Export/Import**: Backup and restore pick history

### Advanced Analytics
- **Streak Analysis**: Current and max winning/losing streaks
- **Variance by Odds**: Performance breakdown by favorite/dog ranges
- **Sportsbook Performance**: Compare results by book
- **Season Summary**: Monthly aggregation and trends
- **AI Feedback**: Claude analysis of loss patterns (requires API key)

### Publishing
- **HTML Export**: Professional pick cards with team logos
- **JPG Screenshots**: Automated conversion via Playwright
- **GitHub Pages**: Push picks to your Pages site

## All Commands

### Basic Usage
```
python3 nba.py                          # Today's games with model lines
python3 nba.py 2026-04-15               # Specific date
python3 nba.py --help                   # Show all commands
```

### Model & Stats
```
python3 nba.py --refresh                # Fetch fresh NBA.com stats
python3 nba.py --stats                  # Show all team stats
python3 nba.py --lines                  # Detailed model lines
python3 nba.py --picks                  # EV+ picks vs market
python3 nba.py --set-stats TEAM ORTG DRTG PACE  # Manual override
```

### Analysis
```
python3 nba.py --matchup BOS MIL        # Detailed matchup report
python3 nba.py --trends BOS             # Team win/loss trends
python3 nba.py --compare                # Model vs market comparison
python3 nba.py --summary                # Season summary by month
python3 nba.py --validate               # Check stats integrity
```

### Pick Tracking
```
python3 nba.py --log                    # Log a new pick
python3 nba.py --grade 1 W              # Grade pick #1 as Win
python3 nba.py --remove 1               # Remove pick #1
python3 nba.py --record                 # Show record with balance
python3 nba.py --feedback               # Performance analysis + AI
```

### Export & Publishing
```
python3 nba.py --export-html            # Generate pick card HTML+JPG
python3 nba.py --export-record          # Export record card
python3 nba.py --grade-picks [FILE]     # Grade HTML picks
python3 nba.py --export-csv             # Export picks to CSV
python3 nba.py --import-csv FILE        # Import picks from CSV
python3 nba.py --publish [FILES...]     # Push to GitHub Pages
```

## Environment Variables

```bash
# Required for market odds
export ODDS_API_KEY="your-key-here"

# Optional for AI feedback
export ANTHROPIC_API_KEY="your-key-here"
```

## Data Files

- `nba_stats_cache.json` - Cached team stats (ORTG/DRTG/PACE)
- `nba_picks_log.json` - Personal pick tracking history
- `nba_model_picks.json` - Model picks by date
- `nba_picks_export.csv` - CSV backup of picks

## Model Details

### Scoring Projection
```
Expected Points = (ORTG_team + DRTG_opponent) / 2 × PACE_avg / 100
```

### Win Probability
```
Win% = Team_Score^13.91 / (Team_Score^13.91 + Opponent_Score^13.91)
```

### Home Court Advantage
- +2.5 points for home team

### League Averages (2024-25)
- ORTG: 115.0
- DRTG: 115.0
- PACE: 99.0

## Pick Data Format

Each pick includes:
- `date`: YYYY-MM-DD
- `game`: "BOS @ MIL"
- `pick`: Team abbreviation
- `odds`: American format (-110, +150, etc.)
- `book`: Sportsbook (DK, FD, BET, etc.)
- `stake`: Amount wagered
- `result`: W/L/P or null
- `pnl`: Profit/loss or null
- `analysis`: Notes on the pick

## Team Abbreviations

ATL, BOS, BKN, CHA, CHI, CLE, DAL, DEN, DET, GSW, HOU, IND, LAC, LAL, MEM, MIA, MIL, MIN, NOP, NYK, OKC, ORL, PHI, PHX, POR, SAC, SAS, TOR, UTA, WAS

## Performance Metrics

- **Record**: W-L-P format
- **Win Rate**: Wins / (Wins + Losses)
- **P&L**: Total profit/loss in dollars
- **ROI**: (P&L / Total Risk) × 100%
- **Streaks**: Current and max consecutive results
- **Odds Analysis**: Performance by odds range and sportsbook

## Tips

1. **Start with --refresh**: Always get fresh stats before analyzing
2. **Use --validate**: Check for unusual stats before betting
3. **Track everything**: Log all picks for accurate analysis
4. **Export regularly**: Use CSV export for backups
5. **Monitor streaks**: Watch for hot/cold periods
6. **Book comparison**: See which book offers best value

## Requirements

- Python 3.7+
- tabulate (for tables)
- requests (for HTTP)
- Optional: beautifulsoup4, playwright, anthropic

## License

Personal use only.
