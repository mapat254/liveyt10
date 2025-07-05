import sys
import subprocess
import threading
import time
import os
import json
import streamlit.components.v1 as components
from datetime import datetime, timedelta
import urllib.parse
import sqlite3
from pathlib import Path

# Install required packages if not available
def install_package(package):
    try:
        __import__(package.split('==')[0].replace('-', '_'))
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

# Install streamlit first
try:
    import streamlit as st
except ImportError:
    install_package("streamlit>=1.28.0")
    import streamlit as st

# Install other packages
packages = [
    "google-auth>=2.17.0",
    "google-auth-oauthlib>=1.0.0", 
    "google-api-python-client>=2.88.0",
    "requests>=2.31.0"
]

for package in packages:
    try:
        if 'google-auth' in package:
            import google.auth
        elif 'google-api' in package:
            from googleapiclient.discovery import build
        elif 'requests' in package:
            import requests
    except ImportError:
        install_package(package)

# Now import all required modules
try:
    import google.auth
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from google_auth_oauthlib.flow import Flow
    import requests
except ImportError as e:
    st.error(f"Error importing required modules: {e}")
    st.stop()

# Initialize database for persistent logs
def init_database():
    """Initialize SQLite database for persistent logs"""
    try:
        db_path = Path("streaming_logs.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Create logs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS streaming_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                session_id TEXT NOT NULL,
                log_type TEXT NOT NULL,
                message TEXT NOT NULL,
                video_file TEXT,
                stream_key TEXT,
                channel_name TEXT
            )
        ''')
        
        # Create streaming_sessions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS streaming_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                video_file TEXT,
                stream_title TEXT,
                stream_description TEXT,
                tags TEXT,
                category TEXT,
                privacy_status TEXT,
                made_for_kids BOOLEAN,
                channel_name TEXT,
                status TEXT DEFAULT 'active'
            )
        ''')
        
        # Create auth_credentials table for persistent authentication
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS auth_credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT UNIQUE NOT NULL,
                channel_name TEXT NOT NULL,
                access_token TEXT NOT NULL,
                refresh_token TEXT,
                token_uri TEXT NOT NULL,
                client_id TEXT NOT NULL,
                client_secret TEXT NOT NULL,
                expires_at TEXT,
                created_at TEXT NOT NULL,
                last_used TEXT NOT NULL,
                is_active BOOLEAN DEFAULT 1
            )
        ''')
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Database initialization error: {e}")
        return False

def log_to_database(session_id, log_type, message, video_file=None, stream_key=None, channel_name=None):
    """Log message to database"""
    try:
        conn = sqlite3.connect("streaming_logs.db")
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO streaming_logs 
            (timestamp, session_id, log_type, message, video_file, stream_key, channel_name)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(),
            session_id,
            log_type,
            message,
            video_file,
            stream_key,
            channel_name
        ))
        
        conn.commit()
        conn.close()
    except Exception as e:
        st.error(f"Error logging to database: {e}")

def get_logs_from_database(session_id=None, limit=100):
    """Get logs from database"""
    try:
        conn = sqlite3.connect("streaming_logs.db")
        cursor = conn.cursor()
        
        if session_id:
            cursor.execute('''
                SELECT timestamp, log_type, message, video_file, channel_name
                FROM streaming_logs 
                WHERE session_id = ?
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (session_id, limit))
        else:
            cursor.execute('''
                SELECT timestamp, log_type, message, video_file, channel_name
                FROM streaming_logs 
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (limit,))
        
        logs = cursor.fetchall()
        conn.close()
        return logs
    except Exception as e:
        st.error(f"Error getting logs from database: {e}")
        return []

def save_auth_credentials(channel_id, channel_name, credentials_dict):
    """Save authentication credentials to database"""
    try:
        conn = sqlite3.connect("streaming_logs.db")
        cursor = conn.cursor()
        
        # Calculate expiry time (1 hour from now as default)
        expires_at = (datetime.now() + timedelta(hours=1)).isoformat()
        current_time = datetime.now().isoformat()
        
        cursor.execute('''
            INSERT OR REPLACE INTO auth_credentials 
            (channel_id, channel_name, access_token, refresh_token, token_uri, client_id, client_secret, expires_at, created_at, last_used, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            channel_id,
            channel_name,
            credentials_dict.get('access_token'),
            credentials_dict.get('refresh_token'),
            credentials_dict.get('token_uri', 'https://oauth2.googleapis.com/token'),
            credentials_dict.get('client_id'),
            credentials_dict.get('client_secret'),
            expires_at,
            current_time,
            current_time,
            True
        ))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error saving auth credentials: {e}")
        return False

def load_auth_credentials():
    """Load all active authentication credentials from database"""
    try:
        conn = sqlite3.connect("streaming_logs.db")
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT channel_id, channel_name, access_token, refresh_token, token_uri, client_id, client_secret, expires_at
            FROM auth_credentials 
            WHERE is_active = 1
            ORDER BY last_used DESC
        ''')
        
        credentials = cursor.fetchall()
        conn.close()
        
        result = []
        for cred in credentials:
            channel_id, channel_name, access_token, refresh_token, token_uri, client_id, client_secret, expires_at = cred
            result.append({
                'channel_id': channel_id,
                'channel_name': channel_name,
                'access_token': access_token,
                'refresh_token': refresh_token,
                'token_uri': token_uri,
                'client_id': client_id,
                'client_secret': client_secret,
                'expires_at': expires_at
            })
        
        return result
    except Exception as e:
        st.error(f"Error loading auth credentials: {e}")
        return []

def update_last_used(channel_id):
    """Update last used timestamp for channel"""
    try:
        conn = sqlite3.connect("streaming_logs.db")
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE auth_credentials 
            SET last_used = ?
            WHERE channel_id = ?
        ''', (datetime.now().isoformat(), channel_id))
        
        conn.commit()
        conn.close()
    except Exception as e:
        st.error(f"Error updating last used: {e}")

def delete_auth_credentials(channel_id):
    """Delete authentication credentials from database"""
    try:
        conn = sqlite3.connect("streaming_logs.db")
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE auth_credentials 
            SET is_active = 0
            WHERE channel_id = ?
        ''', (channel_id,))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error deleting auth credentials: {e}")
        return False

def refresh_access_token(credentials_dict):
    """Refresh access token using refresh token"""
    try:
        if not credentials_dict.get('refresh_token'):
            return None
            
        token_data = {
            'client_id': credentials_dict['client_id'],
            'client_secret': credentials_dict['client_secret'],
            'refresh_token': credentials_dict['refresh_token'],
            'grant_type': 'refresh_token'
        }
        
        response = requests.post(credentials_dict['token_uri'], data=token_data)
        
        if response.status_code == 200:
            tokens = response.json()
            # Update the credentials dict with new access token
            credentials_dict['access_token'] = tokens['access_token']
            return credentials_dict
        else:
            st.error(f"Token refresh failed: {response.text}")
            return None
    except Exception as e:
        st.error(f"Error refreshing token: {e}")
        return None
def save_streaming_session(session_id, video_file, stream_title, stream_description, tags, category, privacy_status, made_for_kids, channel_name):
    """Save streaming session to database"""
    try:
        conn = sqlite3.connect("streaming_logs.db")
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO streaming_sessions 
            (session_id, start_time, video_file, stream_title, stream_description, tags, category, privacy_status, made_for_kids, channel_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            session_id,
            datetime.now().isoformat(),
            video_file,
            stream_title,
            stream_description,
            tags,
            category,
            privacy_status,
            made_for_kids,
            channel_name
        ))
        
        conn.commit()
        conn.close()
    except Exception as e:
        st.error(f"Error saving streaming session: {e}")

def load_google_oauth_config(json_file):
    """Load Google OAuth configuration from downloaded JSON file"""
    try:
        config = json.load(json_file)
        if 'web' in config:
            return config['web']
        elif 'installed' in config:
            return config['installed']
        else:
            st.error("Invalid Google OAuth JSON format")
            return None
    except Exception as e:
        st.error(f"Error loading Google OAuth JSON: {e}")
        return None

def generate_auth_url(client_config):
    """Generate OAuth authorization URL"""
    try:
        scopes = ['https://www.googleapis.com/auth/youtube.force-ssl']
        
        # Create authorization URL
        auth_url = (
            f"{client_config['auth_uri']}?"
            f"client_id={client_config['client_id']}&"
            f"redirect_uri={urllib.parse.quote(client_config['redirect_uris'][0])}&"
            f"scope={urllib.parse.quote(' '.join(scopes))}&"
            f"response_type=code&"
            f"access_type=offline&"
            f"prompt=consent"
        )
        return auth_url
    except Exception as e:
        st.error(f"Error generating auth URL: {e}")
        return None

def exchange_code_for_tokens(client_config, auth_code):
    """Exchange authorization code for access and refresh tokens"""
    try:
        token_data = {
            'client_id': client_config['client_id'],
            'client_secret': client_config['client_secret'],
            'code': auth_code,
            'grant_type': 'authorization_code',
            'redirect_uri': client_config['redirect_uris'][0]
        }
        
        response = requests.post(client_config['token_uri'], data=token_data)
        
        if response.status_code == 200:
            tokens = response.json()
            return tokens
        else:
            st.error(f"Token exchange failed: {response.text}")
            return None
    except Exception as e:
        st.error(f"Error exchanging code for tokens: {e}")
        return None

def create_youtube_service(credentials_dict):
    """Create YouTube API service from credentials"""
    try:
        if 'token' in credentials_dict:
            credentials = Credentials.from_authorized_user_info(credentials_dict)
        else:
            credentials = Credentials(
                token=credentials_dict.get('access_token'),
                refresh_token=credentials_dict.get('refresh_token'),
                token_uri=credentials_dict.get('token_uri', 'https://oauth2.googleapis.com/token'),
                client_id=credentials_dict.get('client_id'),
                client_secret=credentials_dict.get('client_secret'),
                scopes=['https://www.googleapis.com/auth/youtube.force-ssl']
            )
        service = build('youtube', 'v3', credentials=credentials)
        return service
    except Exception as e:
        st.error(f"Error creating YouTube service: {e}")
        return None

def get_stream_key_only(service):
    """Get stream key without creating broadcast"""
    try:
        # Create a simple live stream to get stream key
        stream_request = service.liveStreams().insert(
            part="snippet,cdn",
            body={
                "snippet": {
                    "title": f"Stream Key Generator - {datetime.now().strftime('%Y%m%d_%H%M%S')}"
                },
                "cdn": {
                    "resolution": "1080p",
                    "frameRate": "30fps",
                    "ingestionType": "rtmp"
                }
            }
        )
        stream_response = stream_request.execute()
        
        return {
            "stream_key": stream_response['cdn']['ingestionInfo']['streamName'],
            "stream_url": stream_response['cdn']['ingestionInfo']['ingestionAddress'],
            "stream_id": stream_response['id']
        }
    except Exception as e:
        st.error(f"Error getting stream key: {e}")
        return None

def get_channel_info(service, channel_id=None):
    """Get channel information from YouTube API"""
    try:
        if channel_id:
            request = service.channels().list(
                part="snippet,statistics",
                id=channel_id
            )
        else:
            request = service.channels().list(
                part="snippet,statistics",
                mine=True
            )
        
        response = request.execute()
        return response.get('items', [])
    except Exception as e:
        st.error(f"Error fetching channel info: {e}")
        return []

def create_live_stream(service, title, description, scheduled_start_time, tags=None, category_id="20", privacy_status="public", made_for_kids=False):
    """Create a live stream on YouTube with complete settings"""
    try:
        # Create live stream
        stream_request = service.liveStreams().insert(
            part="snippet,cdn",
            body={
                "snippet": {
                    "title": f"{title} - Stream",
                    "description": description
                },
                "cdn": {
                    "resolution": "1080p",
                    "frameRate": "30fps",
                    "ingestionType": "rtmp"
                }
            }
        )
        stream_response = stream_request.execute()
        
        # Prepare broadcast body
        broadcast_body = {
            "snippet": {
                "title": title,
                "description": description,
                "scheduledStartTime": scheduled_start_time.isoformat()
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": made_for_kids
            },
            "contentDetails": {
                "enableAutoStart": True,
                "enableAutoStop": True
            }
        }
        
        # Add tags if provided
        if tags:
            broadcast_body["snippet"]["tags"] = tags
            
        # Add category if provided
        if category_id:
            broadcast_body["snippet"]["categoryId"] = category_id
        
        # Create live broadcast
        broadcast_request = service.liveBroadcasts().insert(
            part="snippet,status,contentDetails",
            body=broadcast_body
        )
        broadcast_response = broadcast_request.execute()
        
        # Bind stream to broadcast
        bind_request = service.liveBroadcasts().bind(
            part="id,contentDetails",
            id=broadcast_response['id'],
            streamId=stream_response['id']
        )
        bind_response = bind_request.execute()
        
        return {
            "stream_key": stream_response['cdn']['ingestionInfo']['streamName'],
            "stream_url": stream_response['cdn']['ingestionInfo']['ingestionAddress'],
            "broadcast_id": broadcast_response['id'],
            "stream_id": stream_response['id'],
            "watch_url": f"https://www.youtube.com/watch?v={broadcast_response['id']}",
            "broadcast_response": broadcast_response
        }
    except Exception as e:
        st.error(f"Error creating live stream: {e}")
        return None

def run_ffmpeg(video_path, stream_key, is_shorts, log_callback, rtmp_url=None, session_id=None):
    """Run FFmpeg for streaming with enhanced logging"""
    output_url = rtmp_url or f"rtmp://a.rtmp.youtube.com/live2/{stream_key}"
    scale = "-vf scale=720:1280" if is_shorts else ""
    cmd = [
        "ffmpeg", "-re", "-stream_loop", "-1", "-i", video_path,
        "-c:v", "libx264", "-preset", "veryfast", "-b:v", "2500k",
        "-maxrate", "2500k", "-bufsize", "5000k",
        "-g", "60", "-keyint_min", "60",
        "-c:a", "aac", "-b:a", "128k",
        "-f", "flv"
    ]
    if scale:
        cmd += scale.split()
    cmd.append(output_url)
    
    start_msg = f"🚀 Starting FFmpeg streaming to YouTube"
    log_callback(start_msg)
    if session_id:
        log_to_database(session_id, "INFO", start_msg, video_path)
    
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            log_callback(line.strip())
            if session_id:
                log_to_database(session_id, "FFMPEG", line.strip(), video_path)
        process.wait()
        
        end_msg = "✅ Streaming completed successfully"
        log_callback(end_msg)
        if session_id:
            log_to_database(session_id, "INFO", end_msg, video_path)
            
    except Exception as e:
        error_msg = f"❌ FFmpeg Error: {e}"
        log_callback(error_msg)
        if session_id:
            log_to_database(session_id, "ERROR", error_msg, video_path)
    finally:
        final_msg = "⏹️ Streaming session ended"
        log_callback(final_msg)
        if session_id:
            log_to_database(session_id, "INFO", final_msg, video_path)

def auto_process_auth_code():
    """Automatically process authorization code from URL"""
    # Check URL parameters
    query_params = st.query_params
    
    if 'code' in query_params:
        auth_code = query_params['code']
        
        # Check if this code has been processed
        if 'processed_codes' not in st.session_state:
            st.session_state['processed_codes'] = set()
        
        if auth_code not in st.session_state['processed_codes']:
            st.info("🔄 Processing authorization code from URL...")
            
            if 'oauth_config' in st.session_state:
                with st.spinner("Exchanging code for tokens..."):
                    tokens = exchange_code_for_tokens(st.session_state['oauth_config'], auth_code)
                    
                    if tokens:
                        st.session_state['youtube_tokens'] = tokens
                        st.session_state['processed_codes'].add(auth_code)
                        
                        # Create credentials for YouTube service
                        oauth_config = st.session_state['oauth_config']
                        creds_dict = {
                            'access_token': tokens['access_token'],
                            'refresh_token': tokens.get('refresh_token'),
                            'token_uri': oauth_config['token_uri'],
                            'client_id': oauth_config['client_id'],
                            'client_secret': oauth_config['client_secret']
                        }
                        
                        # Test the connection
                        service = create_youtube_service(creds_dict)
                        if service:
                            channels = get_channel_info(service)
                            if channels:
                                channel = channels[0]
                                st.session_state['youtube_service'] = service
                                st.session_state['channel_info'] = channel
                                
                                # Save credentials to database for persistence
                                save_auth_credentials(
                                    channel['id'],
                                    channel['snippet']['title'],
                                    creds_dict
                                )
                                
                                st.success(f"✅ Successfully connected to: {channel['snippet']['title']}")
                                
                                # Clear URL parameters
                                st.query_params.clear()
                                st.rerun()
                        else:
                            st.error("❌ Failed to create YouTube service")
                    else:
                        st.error("❌ Failed to exchange code for tokens")
            else:
                st.error("❌ OAuth configuration not found. Please upload OAuth JSON first.")

def get_youtube_categories():
    """Get YouTube video categories"""
    return {
        "1": "Film & Animation",
        "2": "Autos & Vehicles", 
        "10": "Music",
        "15": "Pets & Animals",
        "17": "Sports",
        "19": "Travel & Events",
        "20": "Gaming",
        "22": "People & Blogs",
        "23": "Comedy",
        "24": "Entertainment",
        "25": "News & Politics",
        "26": "Howto & Style",
        "27": "Education",
        "28": "Science & Technology"
    }

def main():
    # Page configuration must be the first Streamlit command
    st.set_page_config(
        page_title="YouTube Live Streaming Platform",
        page_icon="📺",
        layout="wide"
    )
    
    # Initialize database
    if not init_database():
        st.error("Failed to initialize database. Some features may not work.")
        return
    
    # Initialize session state
    if 'session_id' not in st.session_state:
        st.session_state['session_id'] = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    if 'live_logs' not in st.session_state:
        st.session_state['live_logs'] = []
    
    # Load saved authentication credentials on startup
    if 'auth_loaded' not in st.session_state:
        saved_credentials = load_auth_credentials()
        if saved_credentials:
            # Use the most recently used credentials
            latest_cred = saved_credentials[0]
            
            # Try to create YouTube service with saved credentials
            service = create_youtube_service(latest_cred)
            if service:
                try:
                    channels = get_channel_info(service)
                    if channels:
                        channel = channels[0]
                        st.session_state['youtube_service'] = service
                        st.session_state['channel_info'] = channel
                        st.session_state['saved_auth'] = latest_cred
                        
                        # Update last used timestamp
                        update_last_used(latest_cred['channel_id'])
                        
                        log_to_database(st.session_state['session_id'], "INFO", f"Auto-loaded saved authentication for: {channel['snippet']['title']}")
                except Exception as e:
                    # Try to refresh token if access failed
                    refreshed_cred = refresh_access_token(latest_cred)
                    if refreshed_cred:
                        # Update database with new token
                        save_auth_credentials(
                            latest_cred['channel_id'],
                            latest_cred['channel_name'],
                            refreshed_cred
                        )
                        
                        # Try again with refreshed token
                        service = create_youtube_service(refreshed_cred)
                        if service:
                            channels = get_channel_info(service)
                            if channels:
                                channel = channels[0]
                                st.session_state['youtube_service'] = service
                                st.session_state['channel_info'] = channel
                                st.session_state['saved_auth'] = refreshed_cred
                                
                                log_to_database(st.session_state['session_id'], "INFO", f"Auto-loaded refreshed authentication for: {channel['snippet']['title']}")
        
        st.session_state['auth_loaded'] = True
    
    st.title("🎥 YouTube Live Streaming Platform")
    st.markdown("---")
    
    # Auto-process authorization code if present
    auto_process_auth_code()
    
    # Sidebar for configuration
    with st.sidebar:
        st.header("📋 Configuration")
        
        # Session info
        st.info(f"🆔 Session: {st.session_state['session_id']}")
        
        # Google OAuth Configuration
        st.subheader("🔐 Google OAuth Setup")
        oauth_file = st.file_uploader("Upload Google OAuth JSON", type=['json'], key="oauth_upload")
        
        if oauth_file:
            oauth_config = load_google_oauth_config(oauth_file)
            if oauth_config:
                st.success("✅ Google OAuth config loaded")
                st.session_state['oauth_config'] = oauth_config
                
                # Generate authorization URL
                auth_url = generate_auth_url(oauth_config)
                if auth_url:
                    st.markdown("### Step 1: Authorize Access")
                    st.markdown(f"[🔗 Click here to authorize]({auth_url})")
                    
                    # Instructions
                    with st.expander("💡 Instructions"):
                        st.write("1. Click the authorization link above")
                        st.write("2. Grant permissions to your YouTube account")
                        st.write("3. You'll be redirected back automatically")
                        st.write("4. Or copy the code from the URL and paste below")
                    
                    # Manual authorization code input (fallback)
                    st.markdown("### Manual Code Input (if needed)")
                    auth_code = st.text_input("Authorization Code (optional)", type="password")
                    
                    if st.button("Exchange Code for Tokens"):
                        if auth_code:
                            with st.spinner("Exchanging code for tokens..."):
                                tokens = exchange_code_for_tokens(oauth_config, auth_code)
                                if tokens:
                                    st.success("✅ Tokens obtained successfully!")
                                    st.session_state['youtube_tokens'] = tokens
                                    
                                    # Create credentials for YouTube service
                                    creds_dict = {
                                        'access_token': tokens['access_token'],
                                        'refresh_token': tokens.get('refresh_token'),
                                        'token_uri': oauth_config['token_uri'],
                                        'client_id': oauth_config['client_id'],
                                        'client_secret': oauth_config['client_secret']
                                    }
                                    
                                    # Test the connection
                                    service = create_youtube_service(creds_dict)
                                    if service:
                                        channels = get_channel_info(service)
                                        if channels:
                                            channel = channels[0]
                                            st.success(f"🎉 Connected to: {channel['snippet']['title']}")
                                            st.session_state['youtube_service'] = service
                                            st.session_state['channel_info'] = channel
                                            
                                            # Save credentials to database for persistence
                                            save_auth_credentials(
                                                channel['id'],
                                                channel['snippet']['title'],
                                                creds_dict
                                            )
                        else:
                            st.error("Please enter the authorization code")
        
        # Log Management
        st.markdown("---")
        st.subheader("📊 Log Management")
        
        # Saved Channels Management
        saved_credentials = load_auth_credentials()
        if saved_credentials:
            st.markdown("---")
            st.subheader("💾 Saved Channels")
            
            for i, cred in enumerate(saved_credentials):
                col_ch1, col_ch2, col_ch3 = st.columns([3, 1, 1])
                
                with col_ch1:
                    st.write(f"**{cred['channel_name']}**")
                    st.caption(f"Last used: {cred['expires_at'][:16]}")
                
                with col_ch2:
                    if st.button("🔄 Use", key=f"use_channel_{i}"):
                        # Load this channel
                        service = create_youtube_service(cred)
                        if service:
                            try:
                                channels = get_channel_info(service)
                                if channels:
                                    channel = channels[0]
                                    st.session_state['youtube_service'] = service
                                    st.session_state['channel_info'] = channel
                                    st.session_state['saved_auth'] = cred
                                    
                                    # Update last used
                                    update_last_used(cred['channel_id'])
                                    
                                    st.success(f"✅ Switched to: {channel['snippet']['title']}")
                                    st.rerun()
                            except Exception as e:
                                # Try to refresh token
                                refreshed_cred = refresh_access_token(cred)
                                if refreshed_cred:
                                    save_auth_credentials(
                                        cred['channel_id'],
                                        cred['channel_name'],
                                        refreshed_cred
                                    )
                                    st.success("🔄 Token refreshed, try again")
                                    st.rerun()
                                else:
                                    st.error("❌ Authentication expired, please re-authorize")
                        else:
                            st.error("❌ Failed to create service")
                
                with col_ch3:
                    if st.button("🗑️", key=f"delete_channel_{i}", help="Remove saved channel"):
                        if delete_auth_credentials(cred['channel_id']):
                            st.success("✅ Channel removed")
                            st.rerun()
        
        col_log1, col_log2 = st.columns(2)
        with col_log1:
            if st.button("🔄 Refresh Logs"):
                st.rerun()
        
        with col_log2:
            if st.button("🗑️ Clear Session Logs"):
                st.session_state['live_logs'] = []
                st.success("Logs cleared!")
        
        # Export logs
        if st.button("📥 Export All Logs"):
            all_logs = get_logs_from_database(limit=1000)
            if all_logs:
                logs_text = "\n".join([f"[{log[0]}] {log[1]}: {log[2]}" for log in all_logs])
                st.download_button(
                    label="💾 Download Logs",
                    data=logs_text,
                    file_name=f"streaming_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                    mime="text/plain"
                )
    
    # Main content area
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.header("🎥 Video & Streaming Setup")
        
        # Video selection
        video_files = [f for f in os.listdir('.') if f.endswith(('.mp4', '.flv', '.avi', '.mov', '.mkv'))]
        
        if video_files:
            st.write("📁 Available videos:")
            selected_video = st.selectbox("Select video", video_files)
        else:
            selected_video = None
            st.info("No video files found in current directory")
        
        # Video upload
        uploaded_file = st.file_uploader("Or upload new video", type=['mp4', 'flv', 'avi', 'mov', 'mkv'])
        
        if uploaded_file:
            with open(uploaded_file.name, "wb") as f:
                f.write(uploaded_file.read())
            st.success("✅ Video uploaded successfully!")
            video_path = uploaded_file.name
            log_to_database(st.session_state['session_id'], "INFO", f"Video uploaded: {uploaded_file.name}")
        elif selected_video:
            video_path = selected_video
        else:
            video_path = None
        
        # YouTube Authentication Status
        if 'youtube_service' in st.session_state and 'channel_info' in st.session_state:
            st.subheader("📺 YouTube Channel")
            channel = st.session_state['channel_info']
            col_ch1, col_ch2 = st.columns(2)
            
            with col_ch1:
                st.write(f"**Channel:** {channel['snippet']['title']}")
                st.write(f"**Subscribers:** {channel['statistics'].get('subscriberCount', 'Hidden')}")
                
                # Show if this is from saved auth
                if 'saved_auth' in st.session_state:
                    st.caption("🔒 Using saved authentication")
            
            with col_ch2:
                st.write(f"**Views:** {channel['statistics'].get('viewCount', '0')}")
                st.write(f"**Videos:** {channel['statistics'].get('videoCount', '0')}")
                
                # Logout button
                if st.button("🚪 Logout"):
                    # Clear session state
                    if 'youtube_service' in st.session_state:
                        del st.session_state['youtube_service']
                    if 'channel_info' in st.session_state:
                        del st.session_state['channel_info']
                    if 'saved_auth' in st.session_state:
                        del st.session_state['saved_auth']
                    if 'current_stream_key' in st.session_state:
                        del st.session_state['current_stream_key']
                    
                    st.success("✅ Logged out successfully")
                    st.rerun()
            
            # Get stream key from YouTube
            if st.button("🔑 Get Stream Key"):
                try:
                    service = st.session_state['youtube_service']
                    with st.spinner("Getting stream key..."):
                        stream_info = get_stream_key_only(service)
                        if stream_info:
                            stream_key = stream_info['stream_key']
                            st.session_state['current_stream_key'] = stream_key
                            st.session_state['current_stream_info'] = stream_info
                            st.success("✅ Stream key obtained!")
                            log_to_database(st.session_state['session_id'], "INFO", "Stream key generated successfully")
                            
                            # Display stream information
                            col_sk1, col_sk2 = st.columns(2)
                            with col_sk1:
                                st.text_input("Stream Key", value=stream_key, type="password")
                            with col_sk2:
                                st.text_input("RTMP URL", value=stream_info['stream_url'])
                            
                            st.info("💡 Use these credentials in your streaming software (OBS, etc.)")
                except Exception as e:
                    error_msg = f"Error getting stream key: {e}"
                    st.error(error_msg)
                    log_to_database(st.session_state['session_id'], "ERROR", error_msg)
        else:
            st.subheader("🔑 Manual Stream Key")
            
            # Check if we have a current stream key
            current_key = st.session_state.get('current_stream_key', '')
            manual_stream_key = st.text_input("Stream Key", 
                                     value=current_key, 
                                     type="password",
                                     help="Enter your YouTube stream key or get one using OAuth above")
            
            # Update session state with manual input
            if manual_stream_key:
                st.session_state['current_stream_key'] = manual_stream_key
            
            if current_key:
                st.success("✅ Stream key ready")
            else:
                st.info("💡 Upload OAuth JSON and authorize for automatic key generation")
        
        # Enhanced Live Stream Settings
        st.subheader("📝 Live Stream Settings")
        
        # Basic settings
        col_basic1, col_basic2 = st.columns(2)
        
        with col_basic1:
            stream_title = st.text_input("🎬 Stream Title", value="Live Stream", max_chars=100)
            privacy_status = st.selectbox("🔒 Privacy", ["public", "unlisted", "private"])
            made_for_kids = st.checkbox("👶 Made for Kids")
        
        with col_basic2:
            categories = get_youtube_categories()
            category_names = list(categories.values())
            selected_category_name = st.selectbox("📂 Category", category_names, index=category_names.index("Gaming"))
            category_id = [k for k, v in categories.items() if v == selected_category_name][0]
            
            date = st.date_input("📅 Streaming Date")
            time_val = st.time_input("⏰ Streaming Time")
        
        # Description
        stream_description = st.text_area("📄 Stream Description", 
                                        value="Live streaming session", 
                                        max_chars=5000,
                                        height=100)
        
        # Tags
        tags_input = st.text_input("🏷️ Tags (comma separated)", 
                                 placeholder="gaming, live, stream, youtube")
        tags = [tag.strip() for tag in tags_input.split(",") if tag.strip()] if tags_input else []
        
        if tags:
            st.write("**Tags:**", ", ".join(tags))
        
        # Technical settings
        with st.expander("🔧 Technical Settings"):
            col_tech1, col_tech2 = st.columns(2)
            
            with col_tech1:
                is_shorts = st.checkbox("📱 Shorts Mode (720x1280)")
                auto_create = st.checkbox("🤖 Auto-create YouTube Live")
                enable_chat = st.checkbox("💬 Enable Live Chat", value=True)
            
            with col_tech2:
                bitrate = st.selectbox("📊 Bitrate", ["1500k", "2500k", "4000k", "6000k"], index=1)
                framerate = st.selectbox("🎞️ Frame Rate", ["24", "30", "60"], index=1)
                resolution = st.selectbox("📺 Resolution", ["720p", "1080p", "1440p"], index=1)
        
        # Advanced settings
        with st.expander("⚙️ Advanced Settings"):
            custom_rtmp = st.text_input("🌐 Custom RTMP URL (optional)")
            enable_dvr = st.checkbox("📹 Enable DVR", value=True)
            enable_content_encryption = st.checkbox("🔐 Enable Content Encryption")
            
            # Monetization settings
            st.subheader("💰 Monetization")
            enable_monetization = st.checkbox("💵 Enable Monetization")
            if enable_monetization:
                ad_breaks = st.checkbox("📺 Enable Ad Breaks")
                super_chat = st.checkbox("💬 Enable Super Chat", value=True)
    
    with col2:
        st.header("📊 Status & Controls")
        
        # Streaming status
        streaming = st.session_state.get('streaming', False)
        if streaming:
            st.error("🔴 LIVE")
            
            # Live stats
            if 'stream_start_time' in st.session_state:
                duration = datetime.now() - st.session_state['stream_start_time']
                st.metric("⏱️ Duration", str(duration).split('.')[0])
        else:
            st.success("⚫ OFFLINE")
        
        # Control buttons
        if st.button("▶️ Start Streaming", type="primary"):
            # Get the current stream key
            stream_key = st.session_state.get('current_stream_key', '')
            
            if not video_path:
                st.error("❌ Please select or upload a video!")
            elif not stream_key:
                st.error("❌ Stream key is required!")
            else:
                # Save streaming session
                save_streaming_session(
                    st.session_state['session_id'],
                    video_path,
                    stream_title,
                    stream_description,
                    ", ".join(tags),
                    category_id,
                    privacy_status,
                    made_for_kids,
                    st.session_state.get('channel_info', {}).get('snippet', {}).get('title', 'Unknown')
                )
                
                # Create YouTube live stream if requested
                if auto_create and 'youtube_service' in st.session_state:
                    service = st.session_state['youtube_service']
                    if service:
                        scheduled_time = datetime.combine(date, time_val)
                        live_info = create_live_stream(
                            service, 
                            stream_title, 
                            stream_description, 
                            scheduled_time,
                            tags,
                            category_id,
                            privacy_status,
                            made_for_kids
                        )
                        if live_info:
                            st.success(f"✅ Live stream created!")
                            st.info(f"Watch URL: {live_info['watch_url']}")
                            st.session_state['current_stream_key'] = live_info['stream_key']
                            st.session_state['live_broadcast_info'] = live_info
                            stream_key = live_info['stream_key']
                            log_to_database(st.session_state['session_id'], "INFO", f"YouTube Live created: {live_info['watch_url']}")
                
                # Start streaming
                st.session_state['streaming'] = True
                st.session_state['stream_start_time'] = datetime.now()
                st.session_state['live_logs'] = []
                
                def log_callback(msg):
                    if 'live_logs' not in st.session_state:
                        st.session_state['live_logs'] = []
                    st.session_state['live_logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
                    # Keep only last 100 logs in memory
                    if len(st.session_state['live_logs']) > 100:
                        st.session_state['live_logs'] = st.session_state['live_logs'][-100:]
                
                st.session_state['ffmpeg_thread'] = threading.Thread(
                    target=run_ffmpeg, 
                    args=(video_path, stream_key, is_shorts, log_callback, custom_rtmp or None, st.session_state['session_id']), 
                    daemon=True
                )
                st.session_state['ffmpeg_thread'].start()
                st.success("🚀 Streaming started!")
                log_to_database(st.session_state['session_id'], "INFO", f"Streaming started: {video_path}")
                st.rerun()
        
        if st.button("⏹️ Stop Streaming", type="secondary"):
            st.session_state['streaming'] = False
            if 'stream_start_time' in st.session_state:
                del st.session_state['stream_start_time']
            os.system("pkill ffmpeg")
            st.warning("⏸️ Streaming stopped!")
            log_to_database(st.session_state['session_id'], "INFO", "Streaming stopped by user")
            st.rerun()
        
        # Live broadcast info
        if 'live_broadcast_info' in st.session_state:
            st.subheader("📺 Live Broadcast")
            broadcast_info = st.session_state['live_broadcast_info']
            st.write(f"**Watch URL:** [Open Stream]({broadcast_info['watch_url']})")
            st.write(f"**Broadcast ID:** {broadcast_info['broadcast_id']}")
        
        # Statistics
        st.subheader("📈 Statistics")
        
        # Session stats
        session_logs = get_logs_from_database(st.session_state['session_id'], 50)
        st.metric("Session Logs", len(session_logs))
        
        if 'live_logs' in st.session_state:
            st.metric("Live Log Entries", len(st.session_state['live_logs']))
        
        # Quick actions
        st.subheader("⚡ Quick Actions")
        
        if st.button("📋 Copy Stream Key"):
            if 'current_stream_key' in st.session_state:
                st.code(st.session_state['current_stream_key'])
                st.success("Stream key displayed above!")
        
        if st.button("🔄 Refresh Status"):
            st.rerun()
    
    # Live Logs Section
    st.markdown("---")
    st.header("📝 Live Streaming Logs")
    
    # Log tabs
    tab1, tab2, tab3 = st.tabs(["🔴 Live Logs", "📊 Session History", "🗂️ All Logs"])
    
    with tab1:
        st.subheader("Real-time Streaming Logs")
        
        # Live logs container
        log_container = st.container()
        with log_container:
            if 'live_logs' in st.session_state and st.session_state['live_logs']:
                # Show last 50 live logs
                recent_logs = st.session_state['live_logs'][-50:]
                logs_text = "\n".join(recent_logs)
                st.text_area("Live Logs", logs_text, height=300, disabled=True, key="live_logs_display")
            else:
                st.info("No live logs available. Start streaming to see real-time logs.")
        
        # Auto-refresh toggle
        auto_refresh = st.checkbox("🔄 Auto-refresh logs", value=streaming)
        
        if auto_refresh and streaming:
            time.sleep(2)
            st.rerun()
    
    with tab2:
        st.subheader("Current Session History")
        
        session_logs = get_logs_from_database(st.session_state['session_id'], 100)
        if session_logs:
            # Create a formatted display
            for log in session_logs[:20]:  # Show last 20 session logs
                timestamp, log_type, message, video_file, channel_name = log
                
                # Color code by log type
                if log_type == "ERROR":
                    st.error(f"**{timestamp}** - {message}")
                elif log_type == "INFO":
                    st.info(f"**{timestamp}** - {message}")
                elif log_type == "FFMPEG":
                    st.text(f"{timestamp} - {message}")
                else:
                    st.write(f"**{timestamp}** - {message}")
        else:
            st.info("No session logs available yet.")
    
    with tab3:
        st.subheader("All Historical Logs")
        
        # Filter options
        col_filter1, col_filter2 = st.columns(2)
        
        with col_filter1:
            log_limit = st.selectbox("Show logs", [50, 100, 200, 500], index=1)
        
        with col_filter2:
            log_type_filter = st.selectbox("Filter by type", ["All", "INFO", "ERROR", "FFMPEG"])
        
        all_logs = get_logs_from_database(limit=log_limit)
        
        if all_logs:
            # Filter by type if selected
            if log_type_filter != "All":
                all_logs = [log for log in all_logs if log[1] == log_type_filter]
            
            # Display in expandable sections
            for i, log in enumerate(all_logs[:50]):  # Limit display to 50 for performance
                timestamp, log_type, message, video_file, channel_name = log
                
                with st.expander(f"{log_type} - {timestamp} - {message[:50]}..."):
                    st.write(f"**Timestamp:** {timestamp}")
                    st.write(f"**Type:** {log_type}")
                    st.write(f"**Message:** {message}")
                    if video_file:
                        st.write(f"**Video File:** {video_file}")
                    if channel_name:
                        st.write(f"**Channel:** {channel_name}")
        else:
            st.info("No historical logs available.")

if __name__ == '__main__':
    main()
