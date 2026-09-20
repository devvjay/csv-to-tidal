import csv
import json
import re
import time
import unicodedata
import webbrowser
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd
import tidalapi


# ============================================================
# Configuration
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
CSV_DIR = BASE_DIR / "csv-files-go-here"
TOKEN_FILE = BASE_DIR / "tidal_token.json"
REPORT_DIR = BASE_DIR / "reports"

# Matching
MIN_MATCH_SCORE = 0.82
STRONG_MATCH_SCORE = 0.94
SEARCH_RESULTS_PER_QUERY = 50

# TIDAL playlist updates
ADD_RETRIES = 4
RETRY_BASE_DELAY = 1.5

# Small delay to avoid hammering the API.
REQUEST_DELAY = 0.25


# ============================================================
# Text / matching helpers
# ============================================================

def normalize_text(value):
    """Normalize text for Unicode-safe, punctuation-insensitive matching."""
    if value is None:
        return ""

    text = str(value).strip().lower()

    # Unicode normalization: Ciepło -> Cieplo
    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        char for char in text
        if not unicodedata.combining(char)
    )

    text = text.replace("&", " and ")

    # Normalize common apostrophes/dashes.
    text = text.replace("’", "'").replace("–", "-").replace("—", "-")

    # Keep useful words; punctuation becomes a separator.
    text = re.sub(r"[^a-z0-9]+", " ", text)

    return " ".join(text.split())


def base_title(value):
    """
    Return a simplified title for secondary comparison.

    This deliberately does NOT replace the original title comparison.
    That prevents a version such as 'Song (Live)' from automatically
    becoming identical to 'Song'.
    """
    text = normalize_text(value)

    # Remove common version/remix/live annotations for a secondary score.
    text = re.sub(
        r"\b("
        r"remaster(?:ed)?|remix|radio edit|extended|edit|"
        r"live|acoustic|version|mono|stereo|demo|instrumental"
        r")\b",
        " ",
        text,
    )

    return " ".join(text.split())


def token_similarity(a, b):
    """Compare sets of normalized words."""
    a_tokens = set(normalize_text(a).split())
    b_tokens = set(normalize_text(b).split())

    if not a_tokens or not b_tokens:
        return 0.0

    intersection = len(a_tokens & b_tokens)
    return (2.0 * intersection) / (len(a_tokens) + len(b_tokens))


def string_similarity(a, b):
    a = normalize_text(a)
    b = normalize_text(b)

    if not a or not b:
        return 0.0

    if a == b:
        return 1.0

    return SequenceMatcher(None, a, b).ratio()


def artist_similarity(csv_artists, tidal_artists):
    """
    Compare CSV artists against all available TIDAL artists.

    CSV exports commonly contain multiple artists separated by commas.
    """
    csv_names = [
        normalize_text(x)
        for x in re.split(r"\s*,\s*", str(csv_artists))
        if normalize_text(x)
    ]

    tidal_names = [
        normalize_text(x)
        for x in tidal_artists
        if normalize_text(x)
    ]

    if not csv_names or not tidal_names:
        return 0.0

    scores = []

    for csv_artist in csv_names:
        best = 0.0

        for tidal_artist in tidal_names:
            if csv_artist == tidal_artist:
                best = 1.0
                break

            # Handles cases such as a featured artist being included.
            if csv_artist in tidal_artist or tidal_artist in csv_artist:
                best = max(best, 0.95)

            best = max(
                best,
                SequenceMatcher(None, csv_artist, tidal_artist).ratio(),
            )

        scores.append(best)

    # Penalize a result that fails to match one of several CSV artists.
    return sum(scores) / len(scores)


def calculate_match_score(csv_track, csv_artists, tidal_title, tidal_artists):
    """
    Return a 0..1 confidence score.

    Exact normalized title + exact artist match is effectively a perfect match.
    Base-title similarity is only a secondary signal, so 'Dreams' does not
    automatically become 'The Chain' just because the artist matches.
    """
    title = normalize_text(csv_track)
    result_title = normalize_text(tidal_title)

    if not title or not result_title:
        return 0.0

    exact_title = 1.0 if title == result_title else 0.0
    fuzzy_title = string_similarity(title, result_title)
    token_title = token_similarity(title, result_title)

    base_title_score = string_similarity(
        base_title(csv_track),
        base_title(tidal_title),
    )

    artist_score = artist_similarity(csv_artists, tidal_artists)

    # Exact title should dominate.
    if exact_title:
        title_score = 1.0
    else:
        title_score = (
            fuzzy_title * 0.50
            + token_title * 0.25
            + base_title_score * 0.25
        )

    # Title matters more than artist.
    score = title_score * 0.72 + artist_score * 0.28

    # A strong artist mismatch should prevent accidental same-title matches.
    if artist_score < 0.45:
        score *= 0.75

    return max(0.0, min(1.0, score))


# ============================================================
# TIDAL object helpers
# ============================================================

def get_value(obj, name, default=None):
    """Read an attribute from either an object or dictionary."""
    if isinstance(obj, dict):
        return obj.get(name, default)

    return getattr(obj, name, default)


def get_track_id(track):
    return get_value(track, "id")


def get_track_title(track):
    return get_value(track, "name", "") or get_value(track, "title", "")


def get_artist_names(track):
    """
    Return every artist name we can find on a TIDAL track.
    """
    names = []

    artists = get_value(track, "artists", None)

    if artists:
        for artist in artists:
            name = get_value(artist, "name", "")
            if name:
                names.append(str(name))

    primary_artist = get_value(track, "artist", None)

    if primary_artist:
        name = get_value(primary_artist, "name", "")
        if name:
            names.append(str(name))

    # Remove duplicates while preserving order.
    result = []
    seen = set()

    for name in names:
        key = normalize_text(name)
        if key and key not in seen:
            seen.add(key)
            result.append(name)

    return result


def format_track(track):
    title = get_track_title(track)
    artists = get_artist_names(track)

    return f"{title} - {', '.join(artists)}"


# ============================================================
# Authentication
# ============================================================

def datetime_to_timestamp(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()

    return 0


def save_session(session):
    """Save OAuth credentials locally.

    IMPORTANT: tidal_token.json contains credentials and must never be
    committed to GitHub.
    """
    token_data = {
        "token_type": getattr(session, "token_type", None),
        "access_token": getattr(session, "access_token", None),
        "refresh_token": getattr(session, "refresh_token", None),
        "expiry_time": getattr(session, "expiry_time", None),
    }

    with TOKEN_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            token_data,
            file,
            indent=2,
            default=lambda value: (
                value.isoformat()
                if isinstance(value, datetime)
                else str(value)
            ),
        )

    try:
        # Best-effort protection on systems that support chmod.
        TOKEN_FILE.chmod(0o600)
    except OSError:
        pass


def load_session():
    """Load a previously saved OAuth session."""
    if not TOKEN_FILE.exists():
        return None

    try:
        with TOKEN_FILE.open("r", encoding="utf-8") as file:
            token_data = json.load(file)

        required = ("token_type", "access_token", "refresh_token")
        if not all(token_data.get(key) for key in required):
            return None

        expiry = token_data.get("expiry_time")

        if expiry:
            try:
                expiry = datetime.fromisoformat(expiry)
            except (TypeError, ValueError):
                expiry = None

        session = tidalapi.Session()

        # tidalapi versions have used slightly different signatures.
        try:
            session.load_oauth_session(
                token_data["token_type"],
                token_data["access_token"],
                token_data["refresh_token"],
                expiry,
            )
        except TypeError:
            session.load_oauth_session(
                token_data["token_type"],
                token_data["access_token"],
                token_data["refresh_token"],
            )

        if session.check_login():
            print("✓ Loaded saved TIDAL session.")
            return session

        print("Saved TIDAL session is no longer valid.")

    except Exception as error:
        print(f"Could not load saved TIDAL session: {error}")

    return None


def login_to_tidal():
    """Load a saved session or start TIDAL OAuth login."""
    session = load_session()

    if session:
        return session

    print("\nStarting TIDAL OAuth login...")

    try:
        session = tidalapi.Session()
        login, future = session.login_oauth()

        url = login.verification_uri_complete

        print("\nOpen this URL in your browser:")
        print(url)

        try:
            webbrowser.open(url)
        except Exception:
            pass

        print("\nWaiting for TIDAL authorization...")
        future.result()

        if not session.check_login():
            print("✗ TIDAL login failed.")
            return None

        save_session(session)
        print("✓ Logged in successfully.")
        print(f"✓ Session saved to {TOKEN_FILE.name}")

        return session

    except Exception as error:
        print(f"\n✗ TIDAL login error: {error}")
        print(
            "\nIf you see 'invalid_client', update tidalapi first:\n"
            "    python -m pip install --upgrade tidalapi"
        )
        return None


# ============================================================
# CSV handling
# ============================================================

def get_csv_files():
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(CSV_DIR.glob("*.csv"))


def find_column(columns, candidates):
    normalized = {
        normalize_text(column).replace(" ", ""): column
        for column in columns
    }

    for candidate in candidates:
        key = normalize_text(candidate).replace(" ", "")
        if key in normalized:
            return normalized[key]

    return None


def read_csv_file(csv_path):
    """Read a CSV and return clean track/artist records."""
    encodings = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
    last_error = None

    for encoding in encodings:
        try:
            df = pd.read_csv(csv_path, encoding=encoding)
            break
        except UnicodeDecodeError as error:
            last_error = error
    else:
        raise ValueError(
            f"Could not decode {csv_path.name}: {last_error}"
        )

    track_column = find_column(
        df.columns,
        ["Track Name", "Track", "Title", "Song"],
    )

    artist_column = find_column(
        df.columns,
        ["Artist Name(s)", "Artist Names", "Artist", "Artists"],
    )

    if not track_column or not artist_column:
        raise ValueError(
            f"{csv_path.name} must contain track and artist columns. "
            f"Found: {list(df.columns)}"
        )

    songs = []

    for _, row in df.iterrows():
        track = str(row.get(track_column, "")).strip()
        artist = str(row.get(artist_column, "")).strip()

        if not track or track.lower() == "nan":
            continue

        if not artist or artist.lower() == "nan":
            artist = ""

        songs.append(
            {
                "track": track,
                "artist": artist,
            }
        )

    return songs


# ============================================================
# TIDAL searching
# ============================================================

def search_tracks(session, query):
    """Search TIDAL and return track results."""
    if not query.strip():
        return []

    try:
        # Prefer an explicit Track-only search.
        try:
            result = session.search(
                query,
                models=[tidalapi.media.Track],
            )
        except (TypeError, AttributeError):
            result = session.search(query)

        tracks = get_value(result, "tracks", [])

        if tracks is None:
            return []

        return list(tracks)[:SEARCH_RESULTS_PER_QUERY]

    except Exception as error:
        print(f"  Search error for '{query}': {error}")
        return []


def build_search_queries(track, artists):
    """Generate a small set of useful search queries."""
    track = str(track).strip()
    artists = str(artists).strip()

    queries = [
        f"{track} {artists}".strip(),
        f"{artists} {track}".strip(),
        track,
    ]

    # For very long titles, also search the first part.
    words = track.split()

    if len(words) > 5:
        queries.append(
            f"{' '.join(words[:5])} {artists}".strip()
        )

    # Deduplicate while preserving order.
    result = []
    seen = set()

    for query in queries:
        key = normalize_text(query)

        if key and key not in seen:
            seen.add(key)
            result.append(query)

    return result


def find_best_match(session, song):
    """Search TIDAL and return (track, score)."""
    candidates = {}

    queries = build_search_queries(
        song["track"],
        song["artist"],
    )

    for query in queries:
        for track in search_tracks(session, query):
            track_id = get_track_id(track)

            if track_id is not None:
                candidates[track_id] = track

        time.sleep(REQUEST_DELAY)

    best_track = None
    best_score = 0.0

    for track in candidates.values():
        title = get_track_title(track)
        artists = get_artist_names(track)

        if not title:
            continue

        score = calculate_match_score(
            song["track"],
            song["artist"],
            title,
            artists,
        )

        if score > best_score:
            best_score = score
            best_track = track

    return best_track, best_score


# ============================================================
# Playlist handling
# ============================================================

def is_retryable_error(error):
    text = str(error).lower()

    return any(
        marker in text
        for marker in (
            "412",
            "precondition",
            "revision",
            "429",
            "too many requests",
            "rate limit",
        )
    )


def get_fresh_playlist(session, playlist_id, fallback):
    """Refresh the playlist object before a write."""
    try:
        return session.playlist(playlist_id)
    except Exception:
        return fallback


def add_track_with_retry(session, playlist, playlist_id, track_id):
    """
    Add one track, refreshing the playlist and retrying transient errors.

    This specifically addresses stale playlist revision errors such as HTTP 412.
    """
    last_error = None

    for attempt in range(1, ADD_RETRIES + 1):
        try:
            fresh_playlist = get_fresh_playlist(
                session,
                playlist_id,
                playlist,
            )

            fresh_playlist.add([track_id])

            return fresh_playlist, True, None

        except Exception as error:
            last_error = error

            if not is_retryable_error(error) or attempt == ADD_RETRIES:
                break

            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))

            print(
                f"  Retry {attempt}/{ADD_RETRIES - 1} after "
                f"playlist/API error: {error}"
            )
            time.sleep(delay)

    return playlist, False, last_error


def create_playlist(session, playlist_name, songs):
    """Create a TIDAL playlist and import songs."""
    playlist = session.user.create_playlist(
        playlist_name,
        "Imported from CSV",
    )

    playlist_id = playlist.id

    print(f"✓ Created playlist: {playlist_name}")
    print(f"✓ Playlist ID: {playlist_id}\n")

    successful_adds = 0
    skipped_duplicates = 0
    low_confidence = []
    failed_adds = []
    added_tidal_ids = set()

    total_songs = len(songs)

    for index, song in enumerate(songs, start=1):
        print(
            f"[{index}/{total_songs}] "
            f"{song['track']} - {song['artist']}"
        )

        try:
            best_match, score = find_best_match(session, song)

            if best_match is None:
                print("  ✗ No TIDAL result found.")
                low_confidence.append(
                    {
                        "track": song["track"],
                        "artist": song["artist"],
                        "score": 0.0,
                        "matched_track": "",
                        "matched_artist": "",
                        "status": "not_found",
                    }
                )
                continue

            matched_id = get_track_id(best_match)
            matched_title = get_track_title(best_match)
            matched_artists = get_artist_names(best_match)

            print(
                f"  → Best match: {matched_title} - "
                f"{', '.join(matched_artists)}"
            )
            print(f"  → Confidence: {score:.0%}")

            if score < MIN_MATCH_SCORE:
                print(
                    f"  ⚠ Skipped: confidence below "
                    f"{MIN_MATCH_SCORE:.0%}"
                )

                low_confidence.append(
                    {
                        "track": song["track"],
                        "artist": song["artist"],
                        "score": score,
                        "matched_track": matched_title,
                        "matched_artist": ", ".join(matched_artists),
                        "status": "low_confidence",
                    }
                )
                continue

            if matched_id in added_tidal_ids:
                print("  ⚠ Skipped: this TIDAL track was already added.")
                skipped_duplicates += 1
                continue

            playlist, added, error = add_track_with_retry(
                session,
                playlist,
                playlist_id,
                matched_id,
            )

            if not added:
                print(f"  ✗ Could not add track: {error}")

                failed_adds.append(
                    {
                        "track": song["track"],
                        "artist": song["artist"],
                        "score": score,
                        "matched_track": matched_title,
                        "matched_artist": ", ".join(matched_artists),
                        "status": "add_failed",
                        "error": str(error),
                    }
                )
                continue

            added_tidal_ids.add(matched_id)
            successful_adds += 1

            print(
                f"  ✓ Added "
                f"({successful_adds}/{total_songs})"
            )

        except Exception as error:
            print(f"  ✗ Error processing song: {error}")

            failed_adds.append(
                {
                    "track": song["track"],
                    "artist": song["artist"],
                    "score": 0.0,
                    "matched_track": "",
                    "matched_artist": "",
                    "status": "processing_error",
                    "error": str(error),
                }
            )

        print()
        time.sleep(REQUEST_DELAY)

    # Save an import report.
    report_path = save_report(
        playlist_name,
        songs,
        successful_adds,
        skipped_duplicates,
        low_confidence,
        failed_adds,
    )

    print("=" * 60)
    print("IMPORT COMPLETE")
    print("=" * 60)
    print(f"Playlist:          {playlist_name}")
    print(f"CSV songs:         {total_songs}")
    print(f"Successfully added:{successful_adds}")
    print(f"Duplicates skipped:{skipped_duplicates}")
    print(f"Low confidence:    {len(low_confidence)}")
    print(f"Add failures:      {len(failed_adds)}")

    if report_path:
        print(f"Report:            {report_path}")

    return playlist


# ============================================================
# Reports
# ============================================================

def save_report(
    playlist_name,
    songs,
    successful_adds,
    skipped_duplicates,
    low_confidence,
    failed_adds,
):
    """Write a CSV report so failed/uncertain imports are recoverable."""
    try:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)

        safe_name = re.sub(
            r"[^a-zA-Z0-9._-]+",
            "_",
            playlist_name,
        ).strip("_")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = REPORT_DIR / f"{safe_name}_{timestamp}.csv"

        rows = []

        for item in low_confidence:
            rows.append(item)

        for item in failed_adds:
            rows.append(item)

        if not rows:
            rows.append(
                {
                    "track": "",
                    "artist": "",
                    "score": "",
                    "matched_track": "",
                    "matched_artist": "",
                    "status": "complete",
                    "error": "",
                }
            )

        pd.DataFrame(rows).to_csv(
            report_path,
            index=False,
            encoding="utf-8-sig",
        )

        return report_path

    except Exception as error:
        print(f"Could not save report: {error}")
        return None


# ============================================================
# Main program
# ============================================================

def select_csv_file(csv_files):
    print("\nAvailable CSV playlists:")

    for index, file in enumerate(csv_files, start=1):
        print(f"{index}. {file.stem}")

    while True:
        try:
            selection = input(
                "\nSelect a playlist number "
                "(or 0 to exit): "
            ).strip()

            number = int(selection)

            if number == 0:
                return None

            if 1 <= number <= len(csv_files):
                return csv_files[number - 1]

            print("Invalid selection.")

        except ValueError:
            print("Please enter a number.")


def main():
    print("=" * 60)
    print("CSV → TIDAL PLAYLIST IMPORTER")
    print("=" * 60)

    print("\nLogging in to TIDAL...")
    session = login_to_tidal()

    if not session:
        return

    try:
        if not session.check_login():
            print("✗ TIDAL session is not authenticated.")
            return
    except Exception as error:
        print(f"✗ Could not verify TIDAL session: {error}")
        return

    csv_files = get_csv_files()

    if not csv_files:
        print(
            "\nNo CSV files found.\n"
            f"Put your CSV files in:\n{CSV_DIR}"
        )
        return

    csv_file = select_csv_file(csv_files)

    if csv_file is None:
        print("Exiting.")
        return

    default_name = csv_file.stem

    playlist_name = input(
        f"\nEnter playlist name "
        f"(press Enter for '{default_name}'): "
    ).strip()

    if not playlist_name:
        playlist_name = default_name

    try:
        songs = read_csv_file(csv_file)
    except Exception as error:
        print(f"\n✗ Could not read CSV: {error}")
        return

    if not songs:
        print("\n✗ The CSV contains no usable tracks.")
        return

    print(f"\n✓ Loaded {len(songs)} songs from {csv_file.name}")

    confirm = input(
        f"\nCreate TIDAL playlist '{playlist_name}' "
        f"and import {len(songs)} tracks? [Y/n]: "
    ).strip().lower()

    if confirm and confirm not in ("y", "yes"):
        print("Cancelled.")
        return

    print("\nCreating playlist and importing tracks...\n")

    create_playlist(
        session,
        playlist_name,
        songs,
    )

    print("\nDone.")


if __name__ == "__main__":
    main()
