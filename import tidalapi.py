import tidalapi
import pandas as pd
import time
import os
from pathlib import Path

def login_to_tidal():
    """Login to Tidal using OAuth"""
    session = tidalapi.Session()
    session.login_oauth()
    return session

def get_csv_files():
    """Get list of CSV files from the csv-files-go-here directory"""
    csv_folder = Path(__file__).parent / 'csv-files-go-here'
    return list(csv_folder.glob('*.csv'))

def read_csv_file(csv_path):
    """Read a CSV file and extract track and artist information"""
    df = pd.read_csv(csv_path)
    songs = []
    for _, row in df.iterrows():
        # Extract artist name(s) from the Artist Name(s) column
        artist_names = row['Artist Name(s)'].split(', ')[0]  # Take first artist if multiple
        songs.append({
            'track': row['Track Name'],
            'artist': artist_names
        })
    return songs

def create_playlist(session, playlist_name, songs):
    """Create a Tidal playlist and add songs"""
    # Create new playlist
    playlist = session.user.create_playlist(playlist_name, "Imported from CSV")
    
    # Add each song
    for song in songs:
        try:
            # Search for the song
            search_query = f"{song['track']} {song['artist']}"
            results = session.search(search_query, models=[tidalapi.media.Track])
            
            if results.tracks and len(results.tracks) > 0:
                track = results.tracks[0]
                playlist.add([track.id])
                print(f"Added: {song['track']} - {song['artist']}")
            else:
                print(f"Not found: {song['track']} - {song['artist']}")
            
            # Add delay to avoid rate limiting
            time.sleep(1)
            
        except Exception as e:
            print(f"Error adding {song['track']}: {str(e)}")
    
    return playlist

def main():
    # Login to Tidal
    print("Logging in to Tidal...")
    session = login_to_tidal()
    
    # Get available CSV files
    csv_files = get_csv_files()
    if not csv_files:
        print("No CSV files found in the csv-files-go-here folder!")
        return
    
    # Display available playlists
    print("\nAvailable playlists:")
    for i, file in enumerate(csv_files, 1):
        print(f"{i}. {file.stem}")
    
    # Get user selection
    while True:
        try:
            selection = int(input("\nSelect a playlist number to import (or 0 to exit): ")) - 1
            if selection == -1:
                return
            if 0 <= selection < len(csv_files):
                break
            print("Invalid selection. Please try again.")
        except ValueError:
            print("Please enter a valid number.")
    
    # Get playlist name
    default_name = csv_files[selection].stem
    playlist_name = input(f"\nEnter playlist name (press Enter to use '{default_name}'): ")
    if not playlist_name:
        playlist_name = default_name
    
    # Read and process the selected CSV file
    print(f"\nProcessing {csv_files[selection].name}...")
    songs = read_csv_file(csv_files[selection])
    
    # Create the playlist
    print(f"\nCreating Tidal playlist '{playlist_name}'...")
    playlist = create_playlist(session, playlist_name, songs)
    
    print(f"\nPlaylist '{playlist_name}' has been created successfully!")

if __name__ == "__main__":
    main()