#!/usr/bin/env python3
"""
Feed Discovery Module for awesome-rss-feeds integration
Parses OPML files and provides searchable feed database
with advanced health monitoring and quality scoring
"""

import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Any, Optional
import json
import logging
import requests
import feedparser
from datetime import datetime, timedelta
import hashlib

logger = logging.getLogger(__name__)

class FeedDiscovery:
    def __init__(self, awesome_feeds_path: str = "awesome-rss-feeds"):
        self.awesome_feeds_path = Path(awesome_feeds_path)
        self.feeds_cache = {}
        self.repo_available = False
        self._load_all_feeds()
    
    def _load_all_feeds(self):
        """Load and parse all OPML files"""
        if not self.awesome_feeds_path.exists():
            logger.warning(f"awesome-rss-feeds directory not found at {self.awesome_feeds_path}")
            logger.info("Run setup script to automatically clone the feed discovery database")
            self.repo_available = False
            return
        
        self.repo_available = True
        
        # Load recommended feeds by category
        recommended_path = self.awesome_feeds_path / "recommended" / "with_category"
        if recommended_path.exists():
            for opml_file in recommended_path.glob("*.opml"):
                category = opml_file.stem
                feeds = self._parse_opml_file(opml_file)
                if feeds:
                    self.feeds_cache[f"recommended_{category}"] = {
                        "type": "recommended",
                        "category": category,
                        "display_name": f"Recommended: {category}",
                        "feeds": feeds
                    }
        
        # Load country-based feeds
        countries_path = self.awesome_feeds_path / "countries" / "with_category"
        if countries_path.exists():
            for opml_file in countries_path.glob("*.opml"):
                country = opml_file.stem
                feeds = self._parse_opml_file(opml_file)
                if feeds:
                    self.feeds_cache[f"country_{country}"] = {
                        "type": "country",
                        "category": country,
                        "display_name": f"Country: {country}",
                        "feeds": feeds
                    }
        
        logger.info(f"Loaded {len(self.feeds_cache)} feed collections")
    
    def _parse_opml_file(self, file_path: Path) -> List[Dict[str, Any]]:
        """Parse an OPML file and extract feed information"""
        try:
            # Read and preprocess the file to handle unescaped characters
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Try to fix common XML issues in descriptions
            import html
            import re
            
            # Find description attributes and escape their content
            def escape_description(match):
                desc = match.group(1)
                # Unescape any existing HTML entities first, then re-escape properly
                desc = html.unescape(desc)
                desc = html.escape(desc, quote=True)
                return f'description="{desc}"'
            
            # Fix unescaped ampersands and quotes in description attributes
            content = re.sub(r'description="([^"]*)"', escape_description, content)
            
            # Parse the cleaned content
            root = ET.fromstring(content)
            
            feeds = []
            
            # Find all outline elements with xmlUrl (RSS feeds)
            for outline in root.findall(".//outline[@xmlUrl]"):
                feed_info = {
                    "title": outline.get("title", "").strip(),
                    "text": outline.get("text", "").strip(),
                    "description": outline.get("description", "").strip(),
                    "url": outline.get("xmlUrl", "").strip(),
                    "type": outline.get("type", "rss").strip()
                }
                
                # Use title if text is empty, or vice versa
                if not feed_info["title"] and feed_info["text"]:
                    feed_info["title"] = feed_info["text"]
                elif not feed_info["text"] and feed_info["title"]:
                    feed_info["text"] = feed_info["title"]
                
                if feed_info["url"] and feed_info["title"]:
                    feeds.append(feed_info)
            
            return feeds
            
        except ET.ParseError as e:
            logger.warning(f"XML parsing error in {file_path}: {e}")
            # Try alternative parsing method for problematic files
            return self._parse_opml_fallback(file_path)
        except Exception as e:
            logger.error(f"Unexpected error parsing {file_path}: {e}")
            return []
    
    def _parse_opml_fallback(self, file_path: Path) -> List[Dict[str, Any]]:
        """Fallback parser using regex for problematic OPML files"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            import re
            feeds = []
            
            # Use regex to find outline elements with xmlUrl
            pattern = r'<outline[^>]*xmlUrl="([^"]+)"[^>]*(?:text="([^"]*)")?[^>]*(?:title="([^"]*)")?[^>]*/?>'
            matches = re.findall(pattern, content, re.IGNORECASE)
            
            for match in matches:
                url, text, title = match
                
                # Clean up the extracted data
                feed_info = {
                    "title": (title or text or "").strip(),
                    "text": (text or title or "").strip(),
                    "description": "",
                    "url": url.strip(),
                    "type": "rss"
                }
                
                if feed_info["url"] and feed_info["title"]:
                    feeds.append(feed_info)
            
            logger.info(f"Fallback parser found {len(feeds)} feeds in {file_path}")
            return feeds
            
        except Exception as e:
            logger.error(f"Fallback parsing also failed for {file_path}: {e}")
            return []
    
    def get_all_categories(self) -> List[Dict[str, Any]]:
        """Get all available categories"""
        categories = []
        for key, data in self.feeds_cache.items():
            categories.append({
                "key": key,
                "type": data["type"],
                "category": data["category"],
                "display_name": data["display_name"],
                "feed_count": len(data["feeds"])
            })
        
        # Sort by type and then by category name
        categories.sort(key=lambda x: (x["type"], x["category"]))
        return categories
    
    def get_feeds_by_category(self, category_key: str) -> List[Dict[str, Any]]:
        """Get all feeds for a specific category"""
        return self.feeds_cache.get(category_key, {}).get("feeds", [])
    
    def search_feeds(self, query: str, category_filter: str = None) -> List[Dict[str, Any]]:
        """Search feeds by title, description, or URL"""
        query = query.lower().strip()
        results = []
        
        categories_to_search = [category_filter] if category_filter else self.feeds_cache.keys()
        
        for category_key in categories_to_search:
            if category_key not in self.feeds_cache:
                continue
                
            category_data = self.feeds_cache[category_key]
            for feed in category_data["feeds"]:
                # Search in title, description, and URL
                searchable_text = " ".join([
                    feed.get("title", ""),
                    feed.get("description", ""),
                    feed.get("url", ""),
                    feed.get("text", "")
                ]).lower()
                
                if query in searchable_text:
                    result = feed.copy()
                    result["category_key"] = category_key
                    result["category_display"] = category_data["display_name"]
                    results.append(result)
        
        return results
    
    def get_popular_feeds(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get popular/recommended feeds"""
        popular = []
        
        # Get available categories and prioritize them
        available_categories = list(self.feeds_cache.keys())
        
        # Prioritize certain categories that exist
        priority_order = [
            # Look for country-based feeds first
            "country_United States",
            "country_United Kingdom",
            "country_Canada",
            # Then look for any recommended categories
        ]
        
        # Add any available recommended categories
        recommended_cats = [cat for cat in available_categories if cat.startswith("recommended_")]
        priority_order.extend(recommended_cats)
        
        # Add any other country categories
        country_cats = [cat for cat in available_categories if cat.startswith("country_") and cat not in priority_order]
        priority_order.extend(country_cats)
        
        for category_key in priority_order:
            if category_key in self.feeds_cache:
                category_data = self.feeds_cache[category_key]
                feeds_to_take = min(3, len(category_data["feeds"]))  # Take up to 3 from each
                
                for feed in category_data["feeds"][:feeds_to_take]:
                    result = feed.copy()
                    result["category_key"] = category_key
                    result["category_display"] = category_data["display_name"]
                    popular.append(result)
                    
                    if len(popular) >= limit:
                        return popular[:limit]
        
        return popular
    
    def get_english_categories(self) -> List[Dict[str, Any]]:
        """Get categories that are likely to contain English-language feeds"""
        english_countries = [
            "United States", "United Kingdom", "Canada",
            "Australia", "Ireland", "Hong Kong SAR China"
        ]
        
        categories = []
        for key, data in self.feeds_cache.items():
            # Include all recommended categories (usually English)
            if data["type"] == "recommended":
                categories.append({
                    "key": key,
                    "type": data["type"],
                    "category": data["category"],
                    "display_name": data["display_name"],
                    "feed_count": len(data["feeds"])
                })
            # Include English-speaking countries
            elif data["type"] == "country" and any(country in data["category"] for country in english_countries):
                categories.append({
                    "key": key,
                    "type": data["type"],
                    "category": data["category"],
                    "display_name": data["display_name"],
                    "feed_count": len(data["feeds"])
                })
        
        categories.sort(key=lambda x: (x["type"], x["category"]))
        return categories
    
    def get_english_feeds(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get feeds from English-speaking sources"""
        english_feeds = []
        english_categories = self.get_english_categories()
        
        for cat_info in english_categories:
            category_data = self.feeds_cache.get(cat_info["key"], {})
            for feed in category_data.get("feeds", []):
                result = feed.copy()
                result["category_key"] = cat_info["key"]
                result["category_display"] = cat_info["display_name"]
                english_feeds.append(result)
                
                if len(english_feeds) >= limit:
                    return english_feeds[:limit]
        
        return english_feeds

    def is_available(self) -> bool:
        """Check if feed discovery database is available"""
        return self.repo_available and len(self.feeds_cache) > 0

    def get_feed_stats(self) -> Dict[str, Any]:
        """Get statistics about the feed database"""
        if not self.is_available():
            return {
                "total_feeds": 0,
                "total_categories": 0,
                "english_feeds": 0,
                "english_categories": 0,
                "by_type": {},
                "available": False,
                "message": "Feed discovery database not available. Run setup script to enable."
            }
        
        total_feeds = sum(len(data["feeds"]) for data in self.feeds_cache.values())
        
        by_type = {}
        for data in self.feeds_cache.values():
            feed_type = data["type"]
            if feed_type not in by_type:
                by_type[feed_type] = 0
            by_type[feed_type] += len(data["feeds"])
        
        english_categories = self.get_english_categories()
        english_feeds_count = sum(cat["feed_count"] for cat in english_categories)
        
        return {
            "total_feeds": total_feeds,
            "total_categories": len(self.feeds_cache),
            "english_feeds": english_feeds_count,
            "english_categories": len(english_categories),
            "by_type": by_type,
            "available": True
        }

    def check_feed_health(self, feed_url: str, timeout: int = 10) -> Dict[str, Any]:
        """Check feed health and availability"""
        try:
            response = requests.get(feed_url, timeout=timeout)
            if response.status_code == 200:
                # Parse feed to check validity
                feed = feedparser.parse(response.content)
                if feed.bozo and feed.bozo_exception:
                    return {
                        "status": "unhealthy",
                        "last_check": datetime.utcnow().isoformat(),
                        "error": f"Feed parsing error: {feed.bozo_exception}",
                        "status_code": response.status_code,
                        "item_count": 0
                    }
                
                item_count = len(feed.entries)
                return {
                    "status": "healthy",
                    "last_check": datetime.utcnow().isoformat(),
                    "item_count": item_count,
                    "status_code": response.status_code,
                    "error": None
                }
            else:
                return {
                    "status": "unhealthy",
                    "last_check": datetime.utcnow().isoformat(),
                    "error": f"HTTP {response.status_code}",
                    "status_code": response.status_code,
                    "item_count": 0
                }
        except requests.exceptions.Timeout:
            return {
                "status": "unhealthy",
                "last_check": datetime.utcnow().isoformat(),
                "error": "Timeout",
                "status_code": None,
                "item_count": 0
            }
        except requests.exceptions.RequestException as e:
            return {
                "status": "unhealthy",
                "last_check": datetime.utcnow().isoformat(),
                "error": str(e),
                "status_code": None,
                "item_count": 0
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "last_check": datetime.utcnow().isoformat(),
                "error": f"Unexpected error: {str(e)}",
                "status_code": None,
                "item_count": 0
            }

    def calculate_feed_score(self, feed_url: str, timeout: int = 10) -> float:
        """Calculate feed quality score (0-100)"""
        health = self.check_feed_health(feed_url, timeout)
        
        if health["status"] != "healthy":
            return 0.0
        
        score = 100.0
        
        # Deduct for errors
        if health.get("error"):
            score -= 50
        
        # Deduct for low item count
        item_count = health.get("item_count", 0)
        if item_count < 5:
            score -= 20
        elif item_count < 10:
            score -= 10
        
        # Deduct for HTTP errors (non-200 status)
        status_code = health.get("status_code")
        if status_code and status_code != 200:
            score -= 30
        
        return max(0.0, min(100.0, score))

    def batch_check_feeds(self, feed_urls: List[str], timeout: int = 10) -> List[Dict[str, Any]]:
        """Check health of multiple feeds"""
        results = []
        for url in feed_urls:
            health = self.check_feed_health(url, timeout)
            score = self.calculate_feed_score(url, timeout)
            results.append({
                "url": url,
                "health": health,
                "score": score
            })
        return results

    def get_feed_categories(self, feed_url: str) -> List[str]:
        """Get categories for a specific feed based on URL and title"""
        categories = []
        
        # Search through all cached feeds to find this URL
        for category_key, category_data in self.feeds_cache.items():
            for feed in category_data.get("feeds", []):
                if feed.get("url") == feed_url:
                    # Found the feed, extract its category
                    if "category" in category_data:
                        categories.append(category_data["category"])
                    break
        
        return categories

    def add_custom_feed(self, feed_url: str, title: str, description: str = "", category: str = "custom") -> bool:
        """Add a custom feed to the database"""
        try:
            # Create a simple OPML structure for custom feeds
            custom_feeds_path = self.awesome_feeds_path / "custom"
            custom_feeds_path.mkdir(exist_ok=True)
            
            opml_file = custom_feeds_path / f"{category}.opml"
            
            # Read existing content if file exists
            existing_feeds = []
            if opml_file.exists():
                existing_feeds = self._parse_opml_file(opml_file)
            
            # Check if feed already exists
            for existing_feed in existing_feeds:
                if existing_feed.get("url") == feed_url:
                    return False
            
            # Add new feed
            new_feed = {
                "title": title,
                "text": title,
                "description": description,
                "url": feed_url,
                "type": "rss"
            }
            existing_feeds.append(new_feed)
            
            # Write back to OPML file
            self._write_opml_file(opml_file, existing_feeds, category)
            
            # Reload cache
            self._load_all_feeds()
            
            return True
            
        except Exception as e:
            logger.error(f"Error adding custom feed: {e}")
            return False

    def remove_custom_feed(self, feed_url: str, category: str = "custom") -> bool:
        """Remove a custom feed from the database"""
        try:
            custom_feeds_path = self.awesome_feeds_path / "custom"
            opml_file = custom_feeds_path / f"{category}.opml"
            
            if not opml_file.exists():
                return False
            
            # Read existing feeds
            existing_feeds = self._parse_opml_file(opml_file)
            
            # Remove the feed
            filtered_feeds = [feed for feed in existing_feeds if feed.get("url") != feed_url]
            
            if len(filtered_feeds) == len(existing_feeds):
                return False  # Feed not found
            
            # Write back to OPML file
            self._write_opml_file(opml_file, filtered_feeds, category)
            
            # Reload cache
            self._load_all_feeds()
            
            return True
            
        except Exception as e:
            logger.error(f"Error removing custom feed: {e}")
            return False

    def export_feeds(self, format: str = "opml", category: str = None) -> str:
        """Export feeds in specified format"""
        try:
            if format == "opml":
                return self._export_opml(category)
            elif format == "json":
                return self._export_json(category)
            elif format == "csv":
                return self._export_csv(category)
            else:
                raise ValueError(f"Unsupported format: {format}")
        except Exception as e:
            logger.error(f"Error exporting feeds: {e}")
            raise

    def import_feeds(self, content: str, format: str = "opml", category: str = "imported") -> Dict[str, Any]:
        """Import feeds from specified format"""
        try:
            if format == "opml":
                return self._import_opml(content, category)
            elif format == "json":
                return self._import_json(content, category)
            elif format == "csv":
                return self._import_csv(content, category)
            else:
                raise ValueError(f"Unsupported format: {format}")
        except Exception as e:
            logger.error(f"Error importing feeds: {e}")
            raise

    def _write_opml_file(self, file_path: Path, feeds: List[Dict[str, Any]], category: str):
        """Write feeds to OPML file"""
        opml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
        opml_content += '<opml version="2.0">\n'
        opml_content += f'  <head>\n'
        opml_content += f'    <title>{category}</title>\n'
        opml_content += f'  </head>\n'
        opml_content += '  <body>\n'
        
        for feed in feeds:
            opml_content += f'    <outline text="{feed.get("text", "")}" title="{feed.get("title", "")}" description="{feed.get("description", "")}" xmlUrl="{feed.get("url", "")}" type="{feed.get("type", "rss")}"/>\n'
        
        opml_content += '  </body>\n'
        opml_content += '</opml>\n'
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(opml_content)

    def _export_opml(self, category: str = None) -> str:
        """Export feeds as OPML"""
        opml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
        opml_content += '<opml version="2.0">\n'
        opml_content += '  <head>\n'
        opml_content += '    <title>News02 Feeds Export</title>\n'
        opml_content += '  </head>\n'
        opml_content += '  <body>\n'
        
        categories_to_export = []
        if category:
            if category in self.feeds_cache:
                categories_to_export = [category]
        else:
            categories_to_export = list(self.feeds_cache.keys())
        
        for category_key in categories_to_export:
            category_data = self.feeds_cache.get(category_key, {})
            feeds = category_data.get("feeds", [])
            
            if feeds:
                opml_content += f'    <outline text="{category_data.get("display_name", category_key)}">\n'
                for feed in feeds:
                    opml_content += f'      <outline text="{feed.get("text", "")}" title="{feed.get("title", "")}" description="{feed.get("description", "")}" xmlUrl="{feed.get("url", "")}" type="{feed.get("type", "rss")}"/>\n'
                opml_content += '    </outline>\n'
        
        opml_content += '  </body>\n'
        opml_content += '</opml>\n'
        
        return opml_content

    def _export_json(self, category: str = None) -> str:
        """Export feeds as JSON"""
        export_data = {
            "export_date": datetime.utcnow().isoformat(),
            "version": "1.0",
            "feeds": []
        }
        
        categories_to_export = []
        if category:
            if category in self.feeds_cache:
                categories_to_export = [category]
        else:
            categories_to_export = list(self.feeds_cache.keys())
        
        for category_key in categories_to_export:
            category_data = self.feeds_cache.get(category_key, {})
            feeds = category_data.get("feeds", [])
            
            for feed in feeds:
                export_data["feeds"].append({
                    "url": feed.get("url"),
                    "title": feed.get("title"),
                    "description": feed.get("description"),
                    "category": category_data.get("display_name", category_key),
                    "type": feed.get("type", "rss")
                })
        
        return json.dumps(export_data, indent=2)

    def _export_csv(self, category: str = None) -> str:
        """Export feeds as CSV"""
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["URL", "Title", "Description", "Category", "Type"])
        
        categories_to_export = []
        if category:
            if category in self.feeds_cache:
                categories_to_export = [category]
        else:
            categories_to_export = list(self.feeds_cache.keys())
        
        for category_key in categories_to_export:
            category_data = self.feeds_cache.get(category_key, {})
            feeds = category_data.get("feeds", [])
            
            for feed in feeds:
                writer.writerow([
                    feed.get("url", ""),
                    feed.get("title", ""),
                    feed.get("description", ""),
                    category_data.get("display_name", category_key),
                    feed.get("type", "rss")
                ])
        
        return output.getvalue()

    def _import_opml(self, content: str, category: str) -> Dict[str, Any]:
        """Import feeds from OPML"""
        try:
            # Parse OPML content
            root = ET.fromstring(content)
            feeds = []
            
            # Find all outline elements with xmlUrl
            for outline in root.findall(".//outline[@xmlUrl]"):
                feed_info = {
                    "title": outline.get("title", "").strip(),
                    "text": outline.get("text", "").strip(),
                    "description": outline.get("description", "").strip(),
                    "url": outline.get("xmlUrl", "").strip(),
                    "type": outline.get("type", "rss").strip()
                }
                
                if feed_info["url"] and feed_info["title"]:
                    feeds.append(feed_info)
            
            # Save to custom category
            custom_feeds_path = self.awesome_feeds_path / "custom"
            custom_feeds_path.mkdir(exist_ok=True)
            
            opml_file = custom_feeds_path / f"{category}.opml"
            self._write_opml_file(opml_file, feeds, category)
            
            # Reload cache
            self._load_all_feeds()
            
            return {
                "success": True,
                "imported_count": len(feeds),
                "category": category
            }
            
        except ET.ParseError as e:
            return {
                "success": False,
                "error": f"XML parsing error: {str(e)}",
                "imported_count": 0
            }

    def _import_json(self, content: str, category: str) -> Dict[str, Any]:
        """Import feeds from JSON"""
        try:
            data = json.loads(content)
            feeds = []
            
            if "feeds" in data:
                for feed_data in data["feeds"]:
                    feed_info = {
                        "title": feed_data.get("title", ""),
                        "text": feed_data.get("title", ""),
                        "description": feed_data.get("description", ""),
                        "url": feed_data.get("url", ""),
                        "type": feed_data.get("type", "rss")
                    }
                    
                    if feed_info["url"] and feed_info["title"]:
                        feeds.append(feed_info)
            
            # Save to custom category
            custom_feeds_path = self.awesome_feeds_path / "custom"
            custom_feeds_path.mkdir(exist_ok=True)
            
            opml_file = custom_feeds_path / f"{category}.opml"
            self._write_opml_file(opml_file, feeds, category)
            
            # Reload cache
            self._load_all_feeds()
            
            return {
                "success": True,
                "imported_count": len(feeds),
                "category": category
            }
            
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error": f"JSON parsing error: {str(e)}",
                "imported_count": 0
            }

    def _import_csv(self, content: str, category: str) -> Dict[str, Any]:
        """Import feeds from CSV"""
        try:
            import csv
            import io
            
            reader = csv.reader(io.StringIO(content))
            header = next(reader, None)
            
            if not header:
                return {
                    "success": False,
                    "error": "Empty CSV file",
                    "imported_count": 0
                }
            
            # Find column indices
            url_idx = header.index("URL") if "URL" in header else 0
            title_idx = header.index("Title") if "Title" in header else 1
            desc_idx = header.index("Description") if "Description" in header else 2
            
            feeds = []
            for row in reader:
                if len(row) > url_idx:
                    feed_info = {
                        "title": row[title_idx] if len(row) > title_idx else "",
                        "text": row[title_idx] if len(row) > title_idx else "",
                        "description": row[desc_idx] if len(row) > desc_idx else "",
                        "url": row[url_idx],
                        "type": "rss"
                    }
                    
                    if feed_info["url"] and feed_info["title"]:
                        feeds.append(feed_info)
            
            # Save to custom category
            custom_feeds_path = self.awesome_feeds_path / "custom"
            custom_feeds_path.mkdir(exist_ok=True)
            
            opml_file = custom_feeds_path / f"{category}.opml"
            self._write_opml_file(opml_file, feeds, category)
            
            # Reload cache
            self._load_all_feeds()
            
            return {
                "success": True,
                "imported_count": len(feeds),
                "category": category
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"CSV parsing error: {str(e)}",
                "imported_count": 0
            }


# Global instance
feed_discovery = FeedDiscovery()