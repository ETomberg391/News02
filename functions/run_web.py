#!/usr/bin/env python3
"""
News02 Web Interface Launcher
Easy way to start the web dashboard
"""

import os
import sys
import subprocess
import webbrowser
import time
import threading

# Add the root directory to Python path to make 'functions' package accessible
# This is needed when running from the root directory
sys.path.insert(0, os.getcwd())

def check_dependencies():
    """Check if all required dependencies are installed"""
    print("🔍 Checking dependencies...")
    
    try:
        import flask
        import yaml
        import feedparser
        from newspaper import Article
        import edge_tts
        print("✅ All web dependencies are installed")
        return True
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        print("Please run: pip install -r requirements.txt")
        return False

def check_configuration():
    """Check if basic configuration files exist"""
    print("⚙️ Checking configuration...")
    
    required_files = ['.env', 'settings/feeds/feeds.yaml', 'settings/llm_settings/ai_models.yml']
    missing_files = []
    
    for file in required_files:
        if not os.path.exists(file):
            missing_files.append(file)
    
    if missing_files:
        print(f"⚠️ Missing configuration files: {', '.join(missing_files)}")
        print("Run setup.py to create missing files")
        return False
    
    print("✅ Configuration files found")
    return True

def open_browser_delayed(url, delay=2):
    """Open browser after a delay"""
    time.sleep(delay)
    try:
        webbrowser.open(url)
    except:
        pass

def main():
    """Main launcher function"""
    print("🚀 News02 Web Interface Launcher")
    print("=" * 40)
    
    # Check dependencies
    if not check_dependencies():
        sys.exit(1)
    
    # Check configuration
    if not check_configuration():
        response = input("Would you like to run setup now? (y/n): ").lower().strip()
        if response in ['y', 'yes']:
            try:
                subprocess.run([sys.executable, 'setup.py'], check=True)
            except subprocess.CalledProcessError:
                print("❌ Setup failed")
                sys.exit(1)
        else:
            print("❌ Cannot start without proper configuration")
            sys.exit(1)
    
    # Set environment variables
    os.environ.setdefault('FLASK_ENV', 'development')
    os.environ.setdefault('FLASK_SECRET_KEY', 'news02-dev-key')
    
    # Get configuration
    host = os.getenv('WEB_HOST', '127.0.0.1')
    port = int(os.getenv('WEB_PORT', '5000'))
    debug = os.getenv('WEB_DEBUG', 'true').lower() == 'true'
    
    url = f"http://{host}:{port}"
    
    print(f"🌐 Starting web server at {url}")
    print("📊 Dashboard will open automatically")
    print("⏹️ Press Ctrl+C to stop")
    print("-" * 40)
    
    # Open browser in background thread
    # Open browser in background thread only if not in debug mode (to avoid opening twice)
    # Open browser in background thread, ensuring it only opens once even in debug mode
    if host in ['127.0.0.1', 'localhost', '0.0.0.0'] and os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        browser_thread = threading.Thread(
            target=open_browser_delayed,
            args=(f"http://127.0.0.1:{port}",)
        )
        browser_thread.daemon = True
        browser_thread.start()
    
    # Start Flask app
    try:
        from functions.web_server import app
        app.run(host=host, port=port, debug=debug)
    except KeyboardInterrupt:
        print("\n👋 Web server stopped")
    except Exception as e:
        print(f"❌ Error starting web server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()