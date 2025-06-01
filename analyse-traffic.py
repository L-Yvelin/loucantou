#!/usr/bin/env python3
import os
import re
import argparse
import logging
from datetime import datetime, timedelta
import urllib.request
from typing import Optional, List, Tuple, Dict, Any

import pandas as pd
from user_agents import parse as parse_ua
from jinja2 import Template
import geoip2.database
import plotly.express as px
import plotly.graph_objects as go
import pycountry

# Constants
GEO_DB_URL = "https://github.com/P3TERX/GeoLite.mmdb/releases/download/2025.05.28/GeoLite2-Country.mmdb"
LOCAL_GEO_DB = "GeoLite2-Country.mmdb"
LOG_RE = re.compile(
    r'(?P<ip>\S+) - - \[(?P<ts>.*?)\] '
    r'"(?P<method>\w+) (?P<url>\S+) HTTP/\d\.\d" '
    r'(?P<status>\d+) \d+ "(?P<ref>.*?)" "(?P<ua>.*?)"'
)
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>B&amp;B Website Dashboard</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap" rel="stylesheet" />
  <style>
    body {
      font-family: 'Inter', sans-serif;
      max-width: 900px;
      margin: auto;
      padding: 1rem;
      background: #f8f9fa;
      color: #333;
    }
    h1, h2 {
      font-weight: 700;
      color: #2c3e50;
      margin-bottom: 0.5rem;
    }
    .summary {
      display: flex;
      justify-content: space-around;
      flex-wrap: wrap;
      gap: 1.5rem;
      margin-bottom: 2rem;
    }
    .summary .card {
      flex: 1 1 200px;
      background: #fff;
      color: #2c3e50;
      padding: 1.2rem 1.5rem;
      border-radius: 12px;
      box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
      text-align: center;
      min-height: 120px;
    }
    .summary .card .value {
      font-size: 2rem;
      font-weight: 900;
      margin-top: 0.2rem;
    }
    img {
      max-width: 100%;
      border-radius: 8px;
      box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
      margin-bottom: 1.5rem;
    }
    table {
      width: 100%;
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
      margin-bottom: 1.5rem;
      background: #fff;
    }
    th, td {
      padding: 0.75rem 1rem;
      text-align: left;
      border-bottom: 1px solid #e9ecef;
    }
    thead th {
      background: #2c3e50;
      color: white;
      font-weight: 700;
      font-size: 1rem;
    }
    tbody tr:nth-child(even) td {
      background: #f8f9fa;
    }
    tbody tr:hover td {
      background: #e9ecef;
    }
    a {
      color: #3498db;
      text-decoration: none;
    }
    a:hover {
      text-decoration: underline;
    }
    p.small {
      font-size: 0.85rem;
      color: #7f8c8d;
      margin-top: 2rem;
      text-align: center;
    }
    @media (max-width: 576px) {
      .summary {
        flex-direction: column;
      }
      .summary .card {
        flex: unset;
      }
    }
  </style>
</head>
<body>
  <h1 class="mb-4">Website Dashboard <small class="text-muted">({{ generated }})</small></h1>

  <div class="summary">
    <div class="card">
      <div>Total Sessions</div>
      <div class="value">{{ total_visits }}</div>
    </div>
    <div class="card">
      <div>Unique Visitors</div>
      <div class="value">{{ unique_ips }}</div>
    </div>
    <div class="card">
      <div>Avg. Session Duration</div>
      <div class="value">{{ "%.1f"|format(avg_len) }} min</div>
    </div>
  </div>

  <h2>Sessions by Day of Week</h2>
  <img src="{{ base_url }}/sessions_dow.png" alt="Sessions per weekday" loading="lazy" />

  <h2>Top 5 Landing Pages</h2>
  <img src="{{ base_url }}/top5_pages.png" alt="Top landing pages" loading="lazy" />

  <h2>Avg. Session Duration by Day</h2>
  <img src="{{ base_url }}/avg_len_dow.png" alt="Avg session length per weekday" loading="lazy" />

  <h2>Sessions by Hour of Day</h2>
  <img src="{{ base_url }}/sessions_by_hour.png" alt="Sessions by hour" loading="lazy" />

  <h2>Top 5 External Referrers</h2>
  <table class="table">
    <thead><tr><th>Referrer URL</th><th>Sessions</th></tr></thead>
    <tbody>
    {% for ref,sessions in top5_ref %}
      <tr><td><a href="{{ ref }}" target="_blank" rel="noopener">{{ ref }}</a></td><td>{{ sessions }}</td></tr>
    {% endfor %}
    </tbody>
  </table>

  <h2>Top 5 Countries</h2>
  <img src="{{ base_url }}/top5_countries.png" alt="Top countries" loading="lazy" />

  <p class="small">
    * GeoIP via MaxMind GeoLite2 (free).<br />
    * Bots filtered out; your domain "{{ domain }}" excluded from referrers.<br />
    * All metrics are session-based (30-minute timeout).
  </p>
</body>
</html>"""


def setup_logging() -> None:
    """Set up logging configuration with a specific format and level."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("dashboard.log"),
            logging.StreamHandler()
        ]
    )


def download_geodb(path: str) -> None:
    """
    Download the GeoLite2 database from a specified URL if it does not exist locally.

    Args:
        path (str): The local path where the GeoLite2 database will be saved.

    Raises:
        Exception: If there is an error during the download process.
    """
    if not os.path.isfile(path):
        logging.info("Downloading GeoLite2 DB to %s ...", path)
        try:
            urllib.request.urlretrieve(GEO_DB_URL, path)
            logging.info("GeoLite2 DB downloaded successfully.")
        except Exception as e:
            logging.error("Failed to download GeoLite2 DB: %s", e)
            raise


def is_bot_custom(ua: str) -> bool:
    """
    Check if a user agent string indicates a bot based on a list of known bot indicators.

    Args:
        ua (str): The user agent string to check.

    Returns:
        bool: True if the user agent is identified as a bot, False otherwise.
    """
    ua = ua.lower()
    bot_indicators = [
        "bot", "crawler", "spider", "crawl", "slurp", "search",
        "archive", "transcoder", "monitor", "fetch", "loader",
        "python-requests", "httpclient", "java", "wget", "curl",
        "lighthouse", "axios", "scrapy", "httpx", "phantomjs",
        "headless", "libwww", "mechanize", "apachebench"
    ]
    return any(indicator in ua for indicator in bot_indicators)


def is_static_file(url: str) -> bool:
    """
    Check if a URL points to a static file based on common static file extensions.

    Args:
        url (str): The URL to check.

    Returns:
        bool: True if the URL points to a static file, False otherwise.
    """
    static_extensions = ['.jpg', '.png', '.css', '.js',
                         '.svg', '.ico', '.woff', '.woff2', '.ttf']
    return any(url.endswith(ext) for ext in static_extensions)


def is_suspicious_request(url: str, method: str) -> bool:
    """
    Check if a request is suspicious based on URL patterns and HTTP methods.

    Args:
        url (str): The URL to check.
        method (str): The HTTP method used in the request.

    Returns:
        bool: True if the request is suspicious, False otherwise.
    """
    suspicious_patterns = ['/wp-admin/', '/admin/', '/login/', '/phpmyadmin/']
    suspicious_methods = ['POST', 'PUT', 'DELETE']
    return any(pattern in url for pattern in suspicious_patterns) or method in suspicious_methods


def parse_log_line(line: str, domain: str) -> Optional[Dict[str, Any]]:
    """
    Parse a log line and extract relevant information such as IP, timestamp, URL, etc.

    Args:
        line (str): The log line to parse.
        domain (str): The domain to exclude from referrers.

    Returns:
        Optional[Dict[str, Any]]: A dictionary containing the parsed log data if the line is valid, None otherwise.
    """
    m = LOG_RE.match(line)
    if not m:
        return None
    d = m.groupdict()
    try:
        dt = datetime.strptime(d['ts'], '%d/%b/%Y:%H:%M:%S %z')
    except ValueError:
        return None

    ua_str = d['ua']
    ua = parse_ua(ua_str)
    if ua.is_bot or is_bot_custom(ua_str):
        return None

    if d['ref'] == '-' or domain in d['ref'] or is_static_file(d['url']) or d['status'] == '404' or is_suspicious_request(d['url'], d['method']):
        return None

    return {
        'ip': d['ip'],
        'dt': dt,
        'url': d['url'],
        'status': int(d['status']),
        'ref': d['ref']
    }


def load_and_clean(logpath: str, domain: str, start_date: datetime) -> pd.DataFrame:
    """
    Load and clean log data from a log file, filtering out invalid or irrelevant entries.

    Args:
        logpath (str): The path to the log file.
        domain (str): The domain to exclude from referrers.
        start_date (datetime): The start date for filtering log entries.

    Returns:
        pd.DataFrame: A DataFrame containing the cleaned log data.

    Raises:
        Exception: If there is an error reading the log file.
    """
    rows = []
    try:
        with open(logpath, errors='ignore') as f:
            for line in f:
                rec = parse_log_line(line, domain)
                if rec and rec['dt'] >= start_date:
                    rows.append(rec)
    except Exception as e:
        logging.error("Failed to read log file: %s", e)
        raise

    df = pd.DataFrame(rows)
    df.sort_values('dt', inplace=True)
    df['url'] = df['url'].str.replace(r'index\.html$', '', regex=True)
    return df


def identify_sessions(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Identify sessions based on IP addresses and a 30-minute inactivity threshold.

    Args:
        df (pd.DataFrame): The cleaned log data.

    Returns:
        Tuple[pd.DataFrame, pd.DataFrame]: A tuple containing (session_summary, enriched_df)
            - session_summary: DataFrame with session-level aggregations
            - enriched_df: Original df enriched with session information
    """
    df['prev'] = df.groupby('ip')['dt'].shift()
    df['gap_m'] = (df['dt'] - df['prev']).dt.total_seconds().div(60).fillna(31)
    df['new_sess'] = df['gap_m'] > 30
    df['sess_id'] = df.groupby('ip')['new_sess'].cumsum().astype(
        str).radd(df['ip'] + '_')

    # Create session summary
    sess_summary = df.groupby('sess_id').agg({
        'dt': ['min', 'max'],
        'ip': 'first',
        'url': 'first',  # Landing page (first URL in session)
        'ref': 'first'   # Session referrer (first referrer in session)
    }).reset_index()

    # Flatten column names
    sess_summary.columns = ['sess_id', 'start',
                            'end', 'ip', 'landing_page', 'referrer']
    sess_summary['duration'] = (
        sess_summary['end'] - sess_summary['start']).dt.total_seconds().div(60)

    return sess_summary, df


def ensure_dirs(base: str = 'output', period: str = 'w') -> Tuple[str, str, str]:
    """
    Ensure that the necessary directories exist for storing output files, creating them if necessary.

    Args:
        base (str): The base directory for output files.
        period (str): The period for which directories are created (e.g., 'w' for weekly, 'm' for monthly).

    Returns:
        Tuple[str, str, str]: A tuple containing the base directory, folder name, and image directory.
    """
    now = datetime.now()
    if period == 'w':
        fld = f"w-{now:%Y-%m-%d}"
    elif period == 'm':
        fld = f"m-{now:%Y-%m}"
    elif period == 'y':
        fld = f"y-{now:%Y}"
    else:
        fld = now.strftime("%Y-%m-%d")

    img_dir = os.path.join(base, fld, 'images')
    os.makedirs(img_dir, exist_ok=True)
    return base, fld, img_dir


def save_plotly(fig: go.Figure, out_dir: str, fname: str) -> None:
    """
    Save a Plotly figure as an image file with consistent styling.

    Args:
        fig (go.Figure): The Plotly figure to save.
        out_dir (str): The directory where the image file will be saved.
        fname (str): The name of the image file.

    Raises:
        Exception: If there is an error saving the Plotly figure.
    """
    fig.update_layout(
        template='plotly_white',
        margin=dict(t=40, b=20, l=30, r=20),
        font=dict(family="Inter, sans-serif", size=14)
    )
    try:
        fig.write_image(os.path.join(out_dir, fname), engine="kaleido")
    except Exception as e:
        logging.error("Failed to save Plotly figure: %s", e)
        raise


def generate_visualizations(sess: pd.DataFrame, df_enriched: pd.DataFrame, img_dir: str, domain: str) -> Dict[str, Any]:
    """
    Generate session-based visualizations from session data, saving them as image files.

    Args:
        sess (pd.DataFrame): The session summary data.
        df_enriched (pd.DataFrame): The enriched log data with session information.
        img_dir (str): The directory where the generated images will be saved.
        domain (str): The domain to exclude from referrers.

    Returns:
        Dict[str, Any]: A dictionary containing data for the HTML template.
    """
    total_visits = len(sess)
    unique_ips = sess['ip'].nunique()
    avg_len = sess['duration'].mean()

    # Sessions by Day of Week (session-based)
    dow = sess['start'].dt.day_name().value_counts().reindex(
        ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']).fillna(0)
    fig = px.bar(
        x=dow.index, y=dow.values,
        labels={'x': 'Day', 'y': 'Sessions'},
        title="Sessions per Weekday",
        color=dow.values,
        color_continuous_scale=px.colors.sequential.Blues
    )
    save_plotly(fig, img_dir, "sessions_dow.png")

    # Top 5 Landing Pages (session-based)
    # Filter for actual pages (not just any URL)
    landing_pages = sess['landing_page'].copy()
    landing_pages = landing_pages[landing_pages.str.endswith(
        ('/', '.html')) | (landing_pages == '')]
    top5_pages = landing_pages.value_counts().iloc[:5]

    fig = px.bar(
        x=top5_pages.values, y=top5_pages.index,
        orientation='h',
        labels={'x': 'Sessions', 'y': 'Landing Page'},
        title="Top 5 Landing Pages",
        color=top5_pages.values,
        color_continuous_scale=px.colors.sequential.Blues
    )
    save_plotly(fig, img_dir, "top5_pages.png")

    # Avg. Session Duration by Day (session-based)
    avg_by_dow = sess.groupby(sess['start'].dt.day_name())['duration'].mean().reindex(
        ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']).fillna(0)
    fig = px.bar(
        x=avg_by_dow.index, y=avg_by_dow.values,
        labels={'x': 'Day', 'y': 'Avg Duration (min)'},
        title="Avg Session Length by Weekday",
        color=avg_by_dow.values,
        color_continuous_scale=px.colors.sequential.Blues
    )
    save_plotly(fig, img_dir, "avg_len_dow.png")

    # Sessions by Hour of Day (session-based)
    hrs = sess['start'].dt.hour.value_counts().sort_index()
    fig = px.bar(
        x=hrs.index, y=hrs.values,
        labels={'x': 'Hour of Day', 'y': 'Sessions'},
        title="Sessions by Hour of Day",
        color=hrs.values,
        color_continuous_scale=px.colors.sequential.Blues
    )
    save_plotly(fig, img_dir, "sessions_by_hour.png")

    # Top 5 External Referrers (session-based)
    ext_referrers = sess.loc[(sess['referrer'] != '-') &
                             (~sess['referrer'].str.contains(domain, na=False)), 'referrer']
    ext_ref_counts = ext_referrers.value_counts().iloc[:5]
    top5_ref = list(ext_ref_counts.items())

    # Top 5 Countries (session-based, using GeoIP on session IPs)
    reader = geoip2.database.Reader(LOCAL_GEO_DB)

    def lookup_country(ip: str) -> str:
        try:
            return reader.country(ip).country.iso_code or 'Unknown'
        except geoip2.errors.AddressNotFoundError:
            return 'Unknown'

    sess['country'] = sess['ip'].apply(lookup_country)
    reader.close()

    cc = sess['country'].value_counts()
    top5c = cc.iloc[:5]
    fig = px.bar(
        x=top5c.index, y=top5c.values,
        labels={'x': 'Country', 'y': 'Sessions'},
        title="Top 5 Visitor Countries",
        color=top5c.values,
        color_continuous_scale=px.colors.sequential.Blues
    )
    save_plotly(fig, img_dir, "top5_countries.png")

    return {
        'total_visits': total_visits,
        'unique_ips': unique_ips,
        'avg_len': avg_len,
        'top5_ref': top5_ref
    }


def generate_html(template_data: Dict[str, Any], base_url: str, domain: str, output_path: str) -> None:
    """
    Generate an HTML dashboard from the template data and save it to a file.

    Args:
        template_data (Dict[str, Any]): The data to render in the HTML template.
        base_url (str): The base URL for the images.
        domain (str): The domain to exclude from referrers.
        output_path (str): The path where the generated HTML file will be saved.

    Raises:
        Exception: If there is an error generating the HTML file.
    """
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            tpl = Template(HTML_TEMPLATE)
            f.write(tpl.render(
                generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
                base_url=base_url,
                domain=domain,
                **template_data
            ))
    except Exception as e:
        logging.error("Failed to generate HTML: %s", e)
        raise


def main() -> None:
    """
    Main function to analyze website traffic and generate a session-based dashboard.
    This function orchestrates the entire process from log parsing to HTML generation.
    """
    setup_logging()
    parser = argparse.ArgumentParser(
        description="Analyze website traffic (session-based)")
    parser.add_argument('--logpath', required=True, help="Path to access.log")
    parser.add_argument('--domain', required=True,
                        help="Your own domain to exclude")
    parser.add_argument(
        '--period', choices=['w', 'm', 'y'], default='w', help="w=weekly, m=monthly, y=yearly")
    args = parser.parse_args()

    # Calculate start date based on the period
    now = datetime.now()
    if args.period == 'w':
        start_date = now - timedelta(days=7)
    elif args.period == 'm':
        start_date = now - timedelta(days=30)
    elif args.period == 'y':
        start_date = now - timedelta(days=365)
    else:
        start_date = now - timedelta(days=7)

    download_geodb(LOCAL_GEO_DB)

    base, folder, img_dir = ensure_dirs('output', args.period)
    raw_base = "https://raw.githubusercontent.com/L-Yvelin/loucantou/refs/heads/main/output"
    base_url = f"{raw_base}/{folder}/images"

    df = load_and_clean(args.logpath, args.domain, start_date)
    sess, df_enriched = identify_sessions(df)

    logging.info(
        f"Processed {len(df)} log entries into {len(sess)} sessions from {sess['ip'].nunique()} unique IPs")

    template_data = generate_visualizations(
        sess, df_enriched, img_dir, args.domain)

    html_out = os.path.join(base, folder, "dashboard.html")
    generate_html(template_data, base_url, args.domain, html_out)

    logging.info(f"Dashboard generated: {html_out}")


if __name__ == "__main__":
    main()
