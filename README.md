# CSV to TIDAL

A Python tool to import Spotify playlist CSV files into TIDAL playlists.

I created this project for personal use to transfer playlists exported from Spotify using [Exportify](https://exportify.app/) to TIDAL.

## Features

* 🔐 TIDAL OAuth login with session persistence
* 🎵 Smart track and artist matching
* 📊 Confidence scoring to reduce incorrect matches
* 📁 Supports multiple CSV files
* 🔄 Retries temporary TIDAL/API errors
* 🧹 Prevents duplicate tracks
* 📈 Shows import statistics
* 📄 Generates CSV reports for unmatched and failed tracks
* 🔤 Supports common CSV encodings and column names

## Requirements

* Python 3.x
* A TIDAL account
* Spotify playlist CSV files exported using Exportify
* Internet connection

## Installation

```bash
git clone https://github.com/devvjay/csv-to-tidal.git
cd csv-to-tidal
python -m pip install tidalapi pandas
```

## Usage

1. Put your CSV files inside:

```text
csv-files-go-here/
```

2. Run:

```bash
python main.py
```

3. Authenticate with TIDAL on the first run.
4. Select your CSV playlist.
5. Enter a playlist name and confirm the import.

The program searches TIDAL, matches tracks using title and artist similarity, and only adds matches above the confidence threshold.

## Import Reports

After an import, a report is automatically saved in:

```text
reports/
```

The report contains tracks that were not found, had low confidence, failed to add, or encountered an error.

## CSV Format

Example:

```csv
Track Name,Artist Name(s)
"Die For You","The Weeknd"
"Blinding Lights","The Weeknd"
```

The importer automatically detects common track and artist column names.

## Exportify

CSV files can be exported from [Exportify](https://exportify.app/).

GitHub repository: [watsonbox/exportify](https://github.com/watsonbox/exportify)

Props to the creator of Exportify!

## Troubleshooting

If TIDAL authentication stops working, delete:

```text
tidal_token.json
```

and run the program again.

For login issues, update `tidalapi`:

```bash
python -m pip install --upgrade tidalapi
```

## License

MIT License

## Acknowledgments

* [tidalapi](https://github.com/tamland/python-tidal)
* [pandas](https://pandas.pydata.org/)
* [Exportify](https://exportify.app/)

## Disclaimer

This project is not affiliated with or endorsed by Spotify or TIDAL.
