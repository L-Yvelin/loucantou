#!/usr/bin/env python3
import os
import re
import argparse
import logging
import statistics
import math
from datetime import datetime, timedelta, timezone
import urllib.request
from typing import Optional, List, Tuple, Dict, Any

import pandas as pd
from user_agents import parse as parse_ua
from jinja2 import Template
import geoip2.database
import plotly.express as px
import plotly.graph_objects as go
import pycountry

GEO_DB_URL = "https://github.com/P3TERX/GeoLite.mmdb/releases/latest/download/GeoLite2-Country.mmdb"
LOCAL_GEO_DB = "GeoLite2-Country.mmdb"

log_pattern = re.compile(
    r'(?P<ip>\d+\.\d+\.\d+\.\d+)\s+-\s+-\s+'
    r'\[(?P<timestamp>[^\]]+)\]\s+'
    r'"(?P<method>[A-Z]+)\s(?P<url>\S+)\s(?P<protocol>[^"]+)"\s+'
    r'(?P<status>\d{3})\s+'
    r'(?P<size>\d+|-)\s+'
    r'"(?P<referrer>[^"]*)"\s+'
    r'"(?P<user_agent>[^"]+)"'
)
referrer_regex = re.compile(r"^(-|.*loucantou\.yvelin\.net.*)?$")

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
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("dashboard.log"),
            logging.StreamHandler()
        ]
    )


def download_geodb(path: str) -> None:
    if not os.path.isfile(path):
        logging.info("Downloading GeoLite2 DB to %s ...", path)
        try:
            urllib.request.urlretrieve(GEO_DB_URL, path)
            logging.info("GeoLite2 DB downloaded successfully.")
        except Exception as e:
            logging.error("Failed to download GeoLite2 DB: %s", e)
            raise


def load_and_process_sessions(logpath: str, domain: str, start_date: datetime) -> List[Tuple[str, List[Dict]]]:
    sessions = {}

    with open(logpath, errors='ignore') as f:
        for raw_line in f:
            match = log_pattern.match(raw_line)
            if not match:
                continue

            data = match.groupdict()
            try:
                dt = datetime.strptime(
                    data['timestamp'], '%d/%b/%Y:%H:%M:%S %z')
                data['timestamp'] = dt
            except ValueError:
                continue

            if dt < start_date:
                continue

            ip = data['ip']

            if ip not in sessions:
                sessions[ip] = [[data]]
            else:
                last_session = sessions[ip][-1]
                last_dt = last_session[-1]['timestamp']
                if (dt - last_dt).total_seconds() > 1800:
                    sessions[ip].append([data])
                else:
                    last_session.append(data)

    user_sessions = []
    for ip, session_list in sessions.items():
        for session in session_list:
            if all(
                all(
                    referrer_regex.match(ref)
                    for ref in (line.get('referrer') for line in session)
                )
                for session in session_list
            ):
                continue
            user_sessions.append((ip, session))

    return user_sessions


def ensure_dirs(base: str = 'output', period: str = 'w') -> Tuple[str, str, str]:
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


def generate_visualizations(user_sessions: List[Tuple[str, List[Dict]]], img_dir: str, domain: str) -> Dict[str, Any]:
    total_visits = len(user_sessions)
    unique_ips = len(set(ip for ip, _ in user_sessions))

    session_durations = [
        (session[-1]['timestamp'] - session[0]
         ['timestamp']).total_seconds() / 60
        for _, session in user_sessions
    ]
    avg_len = statistics.mean(session_durations) if session_durations else 0

    session_starts = [session[0]['timestamp'] for _, session in user_sessions]
    session_start_df = pd.DataFrame({'start': session_starts})

    dow = session_start_df['start'].dt.day_name().value_counts().reindex(
        ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']).fillna(0)
    fig = px.bar(
        x=dow.index, y=dow.values,
        labels={'x': 'Day', 'y': 'Sessions'},
        title="Sessions per Weekday",
        color=dow.values,
        color_continuous_scale=px.colors.sequential.Blues
    )
    save_plotly(fig, img_dir, "sessions_dow.png")

    # Count top 5 most visited pages (not just landing pages)
    all_pages = [line['url'] for _, session in user_sessions for line in session]
    all_pages = [url.replace('index.html', '') for url in all_pages if "api" not in url]
    all_pages_series = pd.Series(all_pages)
    top5_pages = all_pages_series.value_counts().iloc[:5]

    fig = px.bar(
        x=top5_pages.values, y=top5_pages.index,
        orientation='h',
        labels={'x': 'Sessions', 'y': 'Landing Page'},
        title="Top 5 Landing Pages",
        color=top5_pages.values,
        color_continuous_scale=px.colors.sequential.Blues
    )
    save_plotly(fig, img_dir, "top5_pages.png")

    durations_by_dow = {}
    for _, session in user_sessions:
        day_name = session[0]['timestamp'].strftime('%A')
        duration = (session[-1]['timestamp'] - session[0]
                    ['timestamp']).total_seconds() / 60
        if day_name not in durations_by_dow:
            durations_by_dow[day_name] = []
        durations_by_dow[day_name].append(duration)

    avg_by_dow = {day: statistics.mean(durations)
                  for day, durations in durations_by_dow.items()}
    dow_order = ['Monday', 'Tuesday', 'Wednesday',
                 'Thursday', 'Friday', 'Saturday', 'Sunday']
    avg_by_dow_ordered = [avg_by_dow.get(day, 0) for day in dow_order]

    fig = px.bar(
        x=dow_order, y=avg_by_dow_ordered,
        labels={'x': 'Day', 'y': 'Avg Duration (min)'},
        title="Avg Session Length by Weekday",
        color=avg_by_dow_ordered,
        color_continuous_scale=px.colors.sequential.Blues
    )
    save_plotly(fig, img_dir, "avg_len_dow.png")

    session_hours = [session[0]['timestamp'].hour for _,
                     session in user_sessions]
    hrs = pd.Series(session_hours).value_counts().sort_index()
    fig = px.bar(
        x=hrs.index, y=hrs.values,
        labels={'x': 'Hour of Day', 'y': 'Sessions'},
        title="Sessions by Hour of Day",
        color=hrs.values,
        color_continuous_scale=px.colors.sequential.Blues
    )
    save_plotly(fig, img_dir, "sessions_by_hour.png")

    ext_referrers = []
    for _, session in user_sessions:
        referrer = session[0]['referrer']
        if referrer != '-' and domain not in referrer:
            ext_referrers.append(referrer)

    ext_ref_counts = pd.Series(ext_referrers).value_counts().iloc[:5]
    top5_ref = list(ext_ref_counts.items()) if not ext_ref_counts.empty else []

    reader = geoip2.database.Reader(LOCAL_GEO_DB)

    def lookup_country(ip: str) -> str:
        try:
            return reader.country(ip).country.iso_code or 'Unknown'
        except geoip2.errors.AddressNotFoundError:
            return 'Unknown'

    countries = [lookup_country(ip) for ip, _ in user_sessions]
    reader.close()

    cc = pd.Series(countries).value_counts()
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
    setup_logging()
    parser = argparse.ArgumentParser(
        description="Analyze website traffic (session-based)")
    parser.add_argument('--logpath', required=True, help="Path to access.log")
    parser.add_argument('--domain', required=True,
                        help="Your own domain to exclude")
    parser.add_argument(
        '--period', choices=['w', 'm', 'y'], default='w', help="w=weekly, m=monthly, y=yearly")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
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

    user_sessions = load_and_process_sessions(
        args.logpath, args.domain, start_date)

    logging.info(
        f"Found {len(user_sessions)} sessions from {len(set(ip for ip, _ in user_sessions))} unique IPs")

    template_data = generate_visualizations(
        user_sessions, img_dir, args.domain)

    html_out = os.path.join(base, folder, "dashboard.html")
    generate_html(template_data, base_url, args.domain, html_out)

    logging.info(f"Dashboard generated: {html_out}")


if __name__ == "__main__":
    main()
