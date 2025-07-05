import sys
import subprocess
import threading
import time
import os
import json
import streamlit.components.v1 as components
from datetime import datetime, timedelta
import urllib.parse
import requests

# Install required packages
try:
    import streamlit as st
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "streamlit"])
    import streamlit as st

try:
    import google.auth
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from google_auth_oauthlib.flow import Flow
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "google-auth", "google-auth-oauthlib", "google-api-python-client"])
    import google.auth
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from google_auth_oauthlib.flow import Flow

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

def load_channel_config(json_file):
    """Load channel configuration from JSON file"""
    try:
        config = json.load(json_file)
        return config
    except Exception as e:
        st.error(f"Error loading JSON file: {e}")
        return None

def validate_channel_config(config):
    """Validate channel configuration structure"""
    required_fields = ['channels']
    for field in required_fields:
        if field not in config:
            return False, f"Missing required field: {field}"
    
    if not isinstance(config['channels'], list):
        return False, "Channels must be a list"
    
    for i, channel in enumerate(config['channels']):
        required_channel_fields = ['name', 'stream_key']
        for field in required_channel_fields:
            if field not in channel:
                return False, f"Channel {i+1} missing required field: {field}"
    
    return True, "Valid configuration"

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

def create_live_stream(service, title, description, scheduled_start_time):
    """Create a live stream on YouTube"""
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
        
        # Create live broadcast
        broadcast_request = service.liveBroadcasts().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": title,
                    "description": description,
                    "scheduledStartTime": scheduled_start_time.isoformat()
                },
                "status": {
                    "privacyStatus": "public"
                }
            }
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
            "watch_url": f"https://www.youtube.com/watch?v={broadcast_response['id']}"
        }
    except Exception as e:
        st.error(f"Error creating live stream: {e}")
        return None

def run_ffmpeg(video_path, stream_key, is_shorts, log_callback, rtmp_url=None):
    """Run FFmpeg for streaming"""
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
    log_callback(f"Menjalankan: {' '.join(cmd)}")
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            log_callback(line.strip())
        process.wait()
    except Exception as e:
        log_callback(f"Error: {e}")
    finally:
        log_callback("Streaming selesai atau dihentikan.")

def get_url_params():
    """Get URL parameters using JavaScript"""
    js_code = """
    <script>
        const urlParams = new URLSearchParams(window.location.search);
        const code = urlParams.get('code');
        const scope = urlParams.get('scope');
        
        if (code) {
            // Send code to Streamlit
            window.parent.postMessage({
                type: 'streamlit:setComponentValue',
                value: {
                    code: code,
                    scope: scope
                }
            }, '*');
        }
    </script>
    """
    return components.html(js_code, height=0)

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
                                
                                # Create JSON config
                                json_config = {
                                    "channels": [
                                        {
                                            "name": channel['snippet']['title'],
                                            "stream_key": "will-be-generated",
                                            "description": channel['snippet'].get('description', ''),
                                            "auth": creds_dict
                                        }
                                    ],
                                    "default_settings": {
                                        "quality": "1080p",
                                        "privacy": "public",
                                        "auto_start": False
                                    }
                                }
                                
                                st.session_state['auto_generated_config'] = json_config
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

def main():
    # Page configuration must be the first Streamlit command
    st.set_page_config(
        page_title="Streaming YT by didinchy",
        page_icon="📈",
        layout="wide"
    )
    
    st.title("Live Streaming Loss Doll")
    st.markdown("---")
    
    # Auto-process authorization code if present
    auto_process_auth_code()
    
    # Sidebar for configuration
    with st.sidebar:
        st.header("📋 Configuration")
        
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
                                            
                                            # Create JSON config
                                            json_config = {
                                                "channels": [
                                                    {
                                                        "name": channel['snippet']['title'],
                                                        "stream_key": "will-be-generated",
                                                        "description": channel['snippet'].get('description', ''),
                                                        "auth": creds_dict
                                                    }
                                                ],
                                                "default_settings": {
                                                    "quality": "1080p",
                                                    "privacy": "public",
                                                    "auto_start": False
                                                }
                                            }
                                            
                                            st.session_state['auto_generated_config'] = json_config
                        else:
                            st.error("Please enter the authorization code")
        
        # Show auto-generated config download
        if 'auto_generated_config' in st.session_state:
            st.markdown("---")
            st.subheader("📥 Download Generated Config")
            config_json = json.dumps(st.session_state['auto_generated_config'], indent=2)
            st.download_button(
                label="📄 Download JSON Config",
                data=config_json,
                file_name="youtube_config.json",
                mime="application/json"
            )
            st.info("💡 Save this file for future use!")
        
        # JSON Configuration Upload
        st.subheader("Channel Configuration")
        json_file = st.file_uploader("Upload JSON Configuration", type=['json'])
        
        if json_file:
            config = load_channel_config(json_file)
            if config:
                is_valid, message = validate_channel_config(config)
                if is_valid:
                    st.success("✅ Valid configuration loaded")
                    st.session_state['channel_config'] = config
                else:
                    st.error(f"❌ Invalid configuration: {message}")
        
        # Sample JSON format
        with st.expander("📄 Sample JSON Format"):
            sample_config = {
                "channels": [
                    {
                        "name": "Channel 1",
                        "stream_key": "your-stream-key-1",
                        "description": "Channel description",
                        "auth": {
                            "client_id": "your-client-id",
                            "client_secret": "your-client-secret",
                            "refresh_token": "your-refresh-token",
                            "token": "your-access-token"
                        }
                    }
                ],
                "default_settings": {
                    "quality": "1080p",
                    "privacy": "public",
                    "auto_start": False
                }
            }
            st.json(sample_config)
        
        # Google OAuth JSON format example
        with st.expander("🔐 Google OAuth JSON Format"):
            st.write("This is the format you get when downloading OAuth credentials from Google Cloud Console:")
            oauth_sample = {
                "web": {
                    "client_id": "your-client-id.apps.googleusercontent.com",
                    "project_id": "your-project-id",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                    "client_secret": "your-client-secret",
                    "redirect_uris": ["https://your-app.streamlit.app"]
                }
            }
            st.json(oauth_sample)
    
    # Main content area
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.header("🎥 Video & Streaming Setup")
        
        # Video selection
        video_files = [f for f in os.listdir('.') if f.endswith(('.mp4', '.flv'))]
        
        if video_files:
            st.write("📁 Available videos:")
            selected_video = st.selectbox("Select video", video_files)
        else:
            selected_video = None
            st.info("No video files found in current directory")
        
        # Video upload
        uploaded_file = st.file_uploader("Or upload new video (mp4/flv - H264/AAC codec)", type=['mp4', '.flv'])
        
        if uploaded_file:
            with open(uploaded_file.name, "wb") as f:
                f.write(uploaded_file.read())
            st.success("✅ Video uploaded successfully!")
            video_path = uploaded_file.name
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
            
            with col_ch2:
                st.write(f"**Views:** {channel['statistics'].get('viewCount', '0')}")
                st.write(f"**Videos:** {channel['statistics'].get('videoCount', '0')}")
            
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
                            
                            # Display stream information
                            col_sk1, col_sk2 = st.columns(2)
                            with col_sk1:
                                st.text_input("Stream Key", value=stream_key, type="password")
                            with col_sk2:
                                st.text_input("RTMP URL", value=stream_info['stream_url'])
                            
                            st.info("💡 Use these credentials in your streaming software (OBS, etc.)")
                except Exception as e:
                    st.error(f"Error getting stream key: {e}")
        
        # Channel selection from JSON config
        elif 'channel_config' in st.session_state:
            st.subheader("📺 Channel Selection")
            config = st.session_state['channel_config']
            channel_options = [ch['name'] for ch in config['channels']]
            selected_channel_name = st.selectbox("Select channel", channel_options)
            
            # Find selected channel
            selected_channel = next((ch for ch in config['channels'] if ch['name'] == selected_channel_name), None)
            
            if selected_channel:
                stream_key = selected_channel['stream_key']
                st.info(f"Using stream key from: {selected_channel_name}")
                
                # Display channel info if auth is available
                if 'auth' in selected_channel:
                    st.subheader("🔐 Channel Authentication")
                    if st.button("Verify Authentication"):
                        service = create_youtube_service(selected_channel['auth'])
                        if service:
                            channels = get_channel_info(service)
                            if channels:
                                channel = channels[0]
                                st.success(f"✅ Authenticated as: {channel['snippet']['title']}")
                                st.write(f"Subscribers: {channel['statistics'].get('subscriberCount', 'Hidden')}")
                                st.write(f"Total Views: {channel['statistics'].get('viewCount', '0')}")
                            else:
                                st.error("❌ Could not fetch channel information")
        else:
            st.subheader("🔑 Manual Stream Key")
            
            # Check if we have a current stream key
            current_key = st.session_state.get('current_stream_key', '')
            stream_key = st.text_input("Stream Key", 
                                     value=current_key, 
                                     type="password",
                                     help="Enter your YouTube stream key or get one using the button above")
            
            if current_key:
                st.success("✅ Using generated stream key")
            else:
                st.info("💡 Upload OAuth JSON and click 'Get Stream Key' for automatic key generation")
        
        # Streaming settings
        st.subheader("⚙️ Streaming Settings")
        col_a, col_b = st.columns(2)
        
        with col_a:
            date = st.date_input("📅 Streaming Date")
            is_shorts = st.checkbox("📱 Shorts Mode (720x1280)")
        
        with col_b:
            time_val = st.time_input("⏰ Streaming Time")
            auto_create = st.checkbox("🤖 Auto-create YouTube Live")
        
        # Advanced settings
        with st.expander("🔧 Advanced Settings"):
            custom_rtmp = st.text_input("Custom RTMP URL (optional)")
            stream_title = st.text_input("Stream Title", value="Live Stream")
            stream_description = st.text_area("Stream Description", value="Live streaming session")
    
    with col2:
        st.header("📊 Status & Controls")
        
        # Streaming status
        streaming = st.session_state.get('streaming', False)
        if streaming:
            st.error("🔴 LIVE")
        else:
            st.success("⚫ OFFLINE")
        
        # Control buttons
        if st.button("▶️ Start Streaming", type="primary"):
            if not video_path:
                st.error("❌ Please select or upload a video!")
            elif not stream_key:
                st.error("❌ Stream key is required!")
            else:
                # Create YouTube live stream if requested
                if auto_create and 'youtube_service' in st.session_state:
                    service = st.session_state['youtube_service']
                    if service:
                        scheduled_time = datetime.combine(date, time_val)
                        live_info = create_live_stream(service, stream_title, stream_description, scheduled_time)
                        if live_info:
                            st.success(f"✅ Live stream created!")
                            st.info(f"Watch URL: {live_info['watch_url']}")
                            stream_key = live_info['stream_key']
                elif auto_create and 'channel_config' in st.session_state and selected_channel and 'auth' in selected_channel:
                    service = create_youtube_service(selected_channel['auth'])
                    if service:
                        scheduled_time = datetime.combine(date, time_val)
                        live_info = create_live_stream(service, stream_title, stream_description, scheduled_time)
                        if live_info:
                            st.success(f"✅ Live stream created!")
                            st.info(f"Watch URL: {live_info['watch_url']}")
                            stream_key = live_info['stream_key']
                
                # Start streaming
                st.session_state['streaming'] = True
                st.session_state['logs'] = []
                
                def log_callback(msg):
                    if 'logs' not in st.session_state:
                        st.session_state['logs'] = []
                    st.session_state['logs'].append(msg)
                
                st.session_state['ffmpeg_thread'] = threading.Thread(
                    target=run_ffmpeg, 
                    args=(video_path, stream_key, is_shorts, log_callback, custom_rtmp or None), 
                    daemon=True
                )
                st.session_state['ffmpeg_thread'].start()
                st.success("🚀 Streaming started!")
                st.rerun()
        
        if st.button("⏹️ Stop Streaming", type="secondary"):
            st.session_state['streaming'] = False
            os.system("pkill ffmpeg")
            if os.path.exists("temp_video.mp4"):
                os.remove("temp_video.mp4")
            st.warning("⏸️ Streaming stopped!")
            st.rerun()
        
        # Statistics
        st.subheader("📈 Statistics")
        if 'logs' in st.session_state:
            st.metric("Log Entries", len(st.session_state['logs']))
        
        # Channel info display
        if 'channel_config' in st.session_state:
            config = st.session_state['channel_config']
            st.metric("Configured Channels", len(config['channels']))
    
    # Ads section
    st.markdown("---")
    show_ads = st.checkbox("📢 Show Ads", value=True)
    if show_ads:
        st.subheader("🎯 Sponsored Content")
        components.html(
            """
            <div style="background:#f0f2f6;padding:20px;border-radius:10px;text-align:center;margin:20px 0;">
                <script type='text/javascript' 
                        src='//pl26562103.profitableratecpm.com/28/f9/95/28f9954a1d5bbf4924abe123c76a68d2.js'>
                </script>
                <p style="color:#888;font-style:italic;">Advertisement space</p>
            </div>
            """,
            height=300
        )
    
    # Logs section
    st.markdown("---")
    st.header("📝 Streaming Logs")
    
    log_container = st.container()
    with log_container:
        if 'logs' in st.session_state and st.session_state['logs']:
            logs_text = "\n".join(st.session_state['logs'][-50:])  # Show last 50 logs
            st.text_area("Logs", logs_text, height=200, disabled=True)
        else:
            st.info("No logs available. Start streaming to see logs.")
    
    # Auto-refresh logs if streaming
    if streaming:
        time.sleep(2)
        st.rerun()

if __name__ == '__main__':
    main()
