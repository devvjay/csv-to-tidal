# csv-to-tidal
I, created this project for personal use so that i could transfer .csv(s) i got from spotify using Exportify to Tidal.  
Any future contributions are Welcome

# Exportify  
it is a tool which i used to dump the playlist data into .csv
it can be found at 
https://exportify.app/  

https://github.com/watsonbox/exportify  

Props to him as well.


          
# CSV to Tidal Playlist Converter

A Python tool that converts CSV playlist files into Tidal playlists.

## Features
- OAuth-based Tidal authentication with session persistence
- Smart song matching algorithm
- Support for multiple CSV files
- Progress tracking and detailed feedback

## Prerequisites
- Python 3.x
- Tidal account
- CSV files with playlists

## Installation
```bash
git clone https://github.com/devvjay/csv-to-tidal
cd csv-tidal
pip install tidalapi pandas
```

## CSV Format
Place your files in `csv-files-go-here` directory:
```csv
Track Name,Artist Name(s)
"Die For You","The Weeknd"
```
i have provided a sample .csv for the format

## Usage  
1. Create a folder named `csv-files-go-here`
2. Place CSV files in `csv-files-go-here`
3. Run:
```bash
python main.py
```
4. First time: Follow OAuth link to authorize
5. Select CSV and enter playlist name
6. Wait for completion

## Troubleshooting
- Authentication: Delete `tidal_token.json` to re-authenticate
- Check CSV format and encoding (UTF-8)
- Review console for unmatched songs

## License
MIT License

## Acknowledgments
- [tidalapi](https://github.com/tamland/python-tidal)
- [pandas](https://pandas.pydata.org/)        
