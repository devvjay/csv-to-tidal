import tidalapi
import pandas as pd
import time
import os
import json
from pathlib import Path
from datetime import datetime

def datetime_handler(obj):
    """Handle datetime serialization"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

def load_session():
    """Load existing session from file"""
    token_file = Path(__file__).parent / 'tidal_token.json'
    if token_file.exists():
        try:
            with open(token_file, 'r') as f:
                token_data = json.load(f)
                # Convert ISO format string back to datetime
                token_data['expiry_time'] = datetime.fromisoformat(token_data['expiry_time'])
                
            session = tidalapi.Session()
            session.load_oauth_session(
                token_data['token_type'],
                token_data['access_token'],
                token_data['refresh_token'],
                token_data['expiry_time']
            )
            
            if session.check_login():
                print("Successfully loaded existing session!")
                return session
        except Exception as e:
            print(f"Error loading saved session: {str(e)}")
    
    return None

def save_session(session):
    """Save session token information to file"""
    token_file = Path(__file__).parent / 'tidal_token.json'
    token_data = {
        'token_type': session.token_type,
        'access_token': session.access_token,
        'refresh_token': session.refresh_token,
        'expiry_time': session.expiry_time
    }
    
    with open(token_file, 'w') as f:
        json.dump(token_data, f, default=datetime_handler)

def login_to_tidal():
    """Login to Tidal using OAuth"""
    # Try to load existing session first
    session = load_session()
    if session:
        return session
    
    # If no valid session exists, create new one
    session = tidalapi.Session()
    try:
        # Start OAuth login process
        login, future = session.login_oauth()
        
        # Print instructions for user
        print("\nPlease visit this URL to authorize the app:")
        print(login.verification_uri_complete)
        print("\nWaiting for authorization...")
        
        # Wait for the login to complete
        future.result()
        
        if session.check_login():
            print("Successfully logged in!")
            # Save the session for future use
            save_session(session)
            return session
        else:
            print("Login failed. Please try again.")
            return None
    except Exception as e:
        print(f"Error during login: {str(e)}")
        return None

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
    successful_adds = 0
    total_songs = len(songs)
    not_found_songs = []
    
    for song in songs:
        try:
            # Clean up search terms even more aggressively
            track_name = (song['track']
                        .replace('(', '')
                        .replace(')', '')
                        .replace('[', '')
                        .replace(']', '')
                        .replace('FT.', '')
                        .replace('FT', '')
                        .replace('FEAT.', '')
                        .replace('FEAT', '')
                        .replace('feat.', '')
                        .replace('with', '')
                        .replace('&', '')
                        .replace('-', ' ')
                        .replace('!', '')
                        .replace('?', '')
                        .replace('\'', '')
                        .replace('"', '')
                        .strip())
            artist_name = song['artist'].strip()
            
            # Try different search combinations
            search_attempts = [
                f"{track_name} {artist_name}",  # Full search
                track_name,  # Just track name
                f"{artist_name} {track_name}",  # Artist first, then track
                ' '.join(track_name.split()[:3]) + " " + artist_name,  # First three words + artist
                artist_name + " " + ' '.join(track_name.split()[:3])  # Artist + first three words
            ]
            
            best_match = None
            highest_match_ratio = 0
            
            for search_query in search_attempts:
                if not search_query.strip():
                    continue
                
                try:
                    search_result = session.search(search_query)
                    
                    # Check if search_result is a dictionary and has 'tracks' key
                    if isinstance(search_result, dict) and 'tracks' in search_result:
                        tracks = search_result['tracks']
                    # If search_result has tracks attribute
                    elif hasattr(search_result, 'tracks') and search_result.tracks:
                        tracks = search_result.tracks
                    else:
                        continue
                    
                    # Process tracks
                    for track in tracks[:15]:
                        # Handle both dictionary and object cases
                        track_name_result = track.name if hasattr(track, 'name') else track.get('name', '')
                        track_artist = track.artist.name if hasattr(track, 'artist') else track.get('artist', {}).get('name', '')
                        track_id = track.id if hasattr(track, 'id') else track.get('id', None)
                        
                        if not (track_name_result and track_artist and track_id):
                            continue
                        
                        # Clean up the track name for comparison
                        track_title = (track_name_result.lower()
                                     .replace('(', '')
                                     .replace(')', '')
                                     .replace('[', '')
                                     .replace(']', '')
                                     .replace('feat.', '')
                                     .replace('ft.', '')
                                     .replace('featuring', '')
                                     .replace('\'', '')
                                     .replace('"', '')
                                     .strip())
                        
                        # More flexible artist matching
                        artist_match = (
                            artist_name.lower() in track_artist.lower() or 
                            track_artist.lower() in artist_name.lower()
                        )
                        
                        # More flexible title matching
                        words_in_track = set(track_name.lower().split())
                        words_in_result = set(track_title.split())
                        word_match_ratio = len(words_in_track & words_in_result) / max(len(words_in_track), len(words_in_result))
                        
                        if artist_match and word_match_ratio > highest_match_ratio:
                            highest_match_ratio = word_match_ratio
                            best_match = track
                            
                            if word_match_ratio > 0.8:
                                break
                    
                    if best_match and highest_match_ratio > 0.8:
                        break
                        
                except Exception as search_error:
                    print(f"Search error for {search_query}: {str(search_error)}")
                    continue
                
                time.sleep(0.3)
            
            if best_match:
                try:
                    track_id = best_match.id if hasattr(best_match, 'id') else best_match.get('id')
                    playlist.add([track_id])
                    successful_adds += 1
                    print(f"Added ({successful_adds}/{total_songs}): {song['track']} - {song['artist']}")
                    print(f"  → Matched as: {best_match.name if hasattr(best_match, 'name') else best_match.get('name')} - {best_match.artist.name if hasattr(best_match, 'artist') else best_match.get('artist', {}).get('name')}")
                except Exception as add_error:
                    print(f"Error adding track to playlist: {str(add_error)}")
                    not_found_songs.append(f"{song['track']} - {song['artist']}")
            else:
                not_found_songs.append(f"{song['track']} - {song['artist']}")
                print(f"Not found: {song['track']} - {song['artist']}")
            
            time.sleep(0.3)
            
        except Exception as e:
            print(f"Error processing {song['track']}: {str(e)}")
            not_found_songs.append(f"{song['track']} - {song['artist']}")
    
    # Print summary
    print(f"\nSummary:")
    print(f"Successfully added {successful_adds} out of {total_songs} songs")
    if not_found_songs:
        print("\nSongs that couldn't be found:")
        for song in not_found_songs:
            print(f"- {song}")
    
    return playlist

def main():
    # Login to Tidal
    print("Logging in to Tidal...")
    session = login_to_tidal()
    
    # Check if login was successful
    if not session or not session.check_login():
        print("Failed to login to Tidal. Please try again.")
        return
    
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