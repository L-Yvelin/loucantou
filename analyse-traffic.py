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
from collections import Counter

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
  <title>Loucantou traffic recap</title>
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
  <h1 class="mb-4">Loucantou traffic recap <small class="text-muted">({{ generated }})</small></h1>

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

  <h2>Most visited days</h2>
  <img src="{{ base_url }}/sessions_dow.png" alt="Most visited days" loading="lazy" />

  <h2>At what hour do people visit</h2>
  <img src="{{ base_url }}/sessions_by_hour.png" alt="At what hour do people visit" loading="lazy" />

  <h2>People come from these websites</h2>
  <table class="table">
    <thead><tr><th>Referrer URL</th><th>Sessions</th></tr></thead>
    <tbody>
    {% for ref,sessions in top5_ref %}
      <tr><td><a href="{{ ref }}" target="_blank" rel="noopener">{{ ref }}</a></td><td>{{ sessions }}</td></tr>
    {% endfor %}
    </tbody>
  </table>

  <h2>Countries Distribution</h2>
  <h3 class="value">France represents {{ "%.1f"|format(france_percentage) }}% of the visits</h3>
  <p>The remaining is:</p>
  <img src="{{ base_url }}/countries_pie_excluding_france.png" alt="Countries Distribution" loading="lazy" />

  <p class="small">
    * GeoIP via MaxMind GeoLite2 (free).<br />
    * Bots filtered out; your domain "{{ domain }}" excluded from referrers.<br />
    * All metrics are session-based (30-minute timeout).
  </p>
</body>
</html>"""


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("dashboard.log"),
            logging.StreamHandler()
        ]
    )


def download_geodb(path):
    if not os.path.isfile(path):
        logging.info("Downloading GeoLite2 DB to %s ...", path)
        try:
            urllib.request.urlretrieve(GEO_DB_URL, path)
            logging.info("GeoLite2 DB downloaded successfully.")
        except Exception as e:
            logging.error("Failed to download GeoLite2 DB: %s", e)
            raise


def load_and_process_sessions(logpath, domain, start_date):
    sessions = {}

    with open(logpath, errors='ignore') as f:
        for raw_line in f:
            match = log_pattern.match(raw_line)
            if not match:
                continue

            data = match.groupdict()
            data['url'] = data['url'].split('?', 1)[0]
            data['referrer'] = data['referrer'].split('?', 1)[0]

            if '/logs/' in data['url'] or '/logs/' in data['referrer']:
                continue

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


def ensure_dirs(base='output', period='w'):
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


def save_plotly(fig, out_dir, fname):
    fig.update_layout(
        template='plotly_white',
        margin=dict(t=40, b=20, l=30, r=20),
        font=dict(family="Inter, sans-serif", size=14),
        showlegend=False
    )
    try:
        fig.write_image(os.path.join(out_dir, fname), engine="kaleido")
    except Exception as e:
        logging.error("Failed to save Plotly figure: %s", e)
        raise


def generate_visualizations(user_sessions, img_dir, domain):
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
        color=dow.values,
        color_continuous_scale=px.colors.sequential.Blues
    )
    save_plotly(fig, img_dir, "sessions_dow.png")

    session_hours = [session[0]['timestamp'].hour for _,
                     session in user_sessions]
    hrs = pd.Series(session_hours).value_counts().sort_index()

    fig = px.line(
        x=hrs.index, y=hrs.values,
        labels={'x': 'Hour of Day', 'y': 'Sessions'},
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

    def lookup_country(ip):
        try:
            response = reader.country(ip)
            if response.country.iso_code:
                country = pycountry.countries.get(
                    alpha_2=response.country.iso_code)
                return country.name if country else 'Unknown'
            return 'Unknown'
        except (geoip2.errors.AddressNotFoundError, AttributeError):
            return 'Unknown'

    countries = [lookup_country(ip) for ip, _ in user_sessions]
    reader.close()

    cc = pd.Series(countries).value_counts()
    france_count = cc.get('France', 0)
    other_countries = cc.drop('France', errors='ignore')

    fig = px.pie(
        names=other_countries.index,
        values=other_countries.values,
        hole=0.3,
        labels={'names': 'Country', 'values': 'Visits'},
    )

    fig.update_traces(
        textposition='inside',
        textinfo='label+percent',
        hovertemplate="<b>%{label}</b><br>%{percent:.1%} (%{value} visits)<extra></extra>",
        texttemplate='%{label}<br>%{percent:.1%}'
    )

    fig.update_layout(
        uniformtext_minsize=12,
        uniformtext_mode='hide',
        margin=dict(t=0, b=0, l=0, r=0)
    )

    save_plotly(fig, img_dir, "countries_pie_excluding_france.png")

    france_percentage = (france_count / total_visits) * 100

    return {
        'total_visits': total_visits,
        'unique_ips': unique_ips,
        'avg_len': avg_len,
        'top5_ref': top5_ref,
        'france_percentage': france_percentage
    }


def generate_html(template_data, base_url, domain, output_path):
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


def main():
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
