import pytz
import re
import pandas as pd
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import seaborn as sns
from user_agents import parse
import os
import numpy as np
from collections import defaultdict
import base64
from io import BytesIO
import html2text

# Ensure the output directory exists
output_dir = 'output'
os.makedirs(output_dir, exist_ok=True)

# Efficient log parser for large files


def parse_log_line(line):
    match = re.match(
        r'(?P<ip>\d+\.\d+\.\d+\.\d+) - - \[(?P<timestamp>.*?)\] "(?:GET|POST) (?P<url>\S+) HTTP/\d\.\d" \d+ \d+ "(?P<referrer>.*?)" "(?P<user_agent>.*?)"',
        line
    )
    if not match:
        return None

    data = match.groupdict()
    # Convert timestamp to datetime, including timezone offset
    data['datetime'] = datetime.strptime(
        data['timestamp'], '%d/%b/%Y:%H:%M:%S %z')
    data['is_bot'], data['bot_name'] = detect_bot(data['user_agent'])
    return data

# Basic bot detection (can be expanded)


def detect_bot(user_agent):
    bot_signatures = {
        'Googlebot': 'Googlebot',
        'Bingbot': 'bingbot',
        'DuckDuckBot': 'DuckDuckBot',
        'Baiduspider': 'Baiduspider',
        'YandexBot': 'YandexBot',
        'Facebot': 'Facebot',
        'facebookexternalhit': 'facebook',
        'Twitterbot': 'Twitterbot',
        'Applebot': 'Applebot',
        'Slackbot': 'Slackbot',
        'GPTBot': 'ChatGPT',
        'OAI-SearchBot': 'OpenAI SearchBot',
        'ChatGPT-User': 'ChatGPT',
        'bot': 'generic-bot',
        'crawl': 'crawler',
        'spider': 'spider',
        'robot': 'robot'
    }

    ua_lower = user_agent.lower()
    for name, signature in bot_signatures.items():
        if signature.lower() in ua_lower:
            return True, name
    return False, None

# Main logic


def analyze_log(file_path, max_lines=None, months=None):
    records = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f):
            if max_lines and i >= max_lines:
                break
            parsed = parse_log_line(line)
            if parsed:
                records.append(parsed)

    df = pd.DataFrame(records)

    # Filter for the past X months if specified
    if months is not None:
        # Create a timezone-aware cutoff date
        cutoff_date = datetime.now(pytz.UTC) - timedelta(days=30 * months)
        df = df[df['datetime'] >= cutoff_date]

    # Enrich data with user agent details
    df = enrich_user_agent(df)

    # Group by IP and time window to count unique visits
    df['visit_id'] = df['ip'].astype(
        str) + df['datetime'].dt.floor('1H').astype(str)
    unique_visits = df.drop_duplicates(subset=['visit_id'])

    # Summary
    visits_per_day = unique_visits.groupby(
        unique_visits['datetime'].dt.date).size().rename('visits')
    visits_per_hour = unique_visits.groupby(
        unique_visits['datetime'].dt.hour).size().rename('visits')
    visits_per_ip = unique_visits.groupby('ip').size().rename('visits')
    bots = unique_visits[unique_visits['is_bot']]
    bots_per_name = bots['bot_name'].value_counts()
    bots_per_day = bots.groupby(bots['datetime'].dt.date).size()
    top_referrers = unique_visits['referrer'].value_counts().head(10)
    top_urls = unique_visits['url'].value_counts().head(10)
    device_distribution = unique_visits['device_type'].value_counts()
    browser_distribution = unique_visits['browser'].value_counts()
    os_distribution = unique_visits['os'].value_counts()

    # Session duration analysis
    session_durations = defaultdict(list)
    for ip, group in unique_visits.groupby('ip'):
        group = group.sort_values('datetime')
        durations = group['datetime'].diff().dt.total_seconds() / 60
        session_durations[ip].extend(durations.dropna().tolist())

    # Error rate analysis (assuming error codes are logged)
    error_rates = unique_visits['url'].apply(
        lambda x: 1 if '404' in x or '500' in x else 0).sum()

    return {
        'visits_per_day': visits_per_day,
        'visits_per_hour': visits_per_hour,
        'visits_per_ip': visits_per_ip,
        'bots': bots,
        'bots_per_name': bots_per_name,
        'bots_per_day': bots_per_day,
        'top_referrers': top_referrers,
        'top_urls': top_urls,
        'device_distribution': device_distribution,
        'browser_distribution': browser_distribution,
        'os_distribution': os_distribution,
        'session_durations': session_durations,
        'error_rates': error_rates
    }


def enrich_user_agent(df):
    df['device_type'] = df['user_agent'].apply(
        lambda ua: parse(ua).device.family)
    df['browser'] = df['user_agent'].apply(lambda ua: parse(ua).browser.family)
    df['os'] = df['user_agent'].apply(lambda ua: parse(ua).os.family)
    return df


def plot_to_base64(fig):
    buf = BytesIO()
    fig.savefig(buf, format="png")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


# Example usage with filtering for the past 3 months
results = analyze_log(
    "/var/www/html/loucantou.yvelin.net/logs/loucantou-access.log", max_lines=50000000, months=3)

# Plot visits per day
visits_per_day_df = results['visits_per_day'].reset_index()
visits_per_day_df.columns = ['date', 'visits']
fig, ax = plt.subplots(figsize=(12, 6))
sns.lineplot(data=visits_per_day_df, x='date', y='visits', ax=ax)
ax.set_title('Visits per Day')
ax.set_xlabel('Date')
ax.set_ylabel('Visits')
visits_per_day_img = plot_to_base64(fig)
plt.close(fig)

# Plot visits per hour
visits_per_hour_df = results['visits_per_hour'].reset_index()
visits_per_hour_df.columns = ['hour', 'visits']
fig, ax = plt.subplots(figsize=(12, 6))
sns.lineplot(data=visits_per_hour_df, x='hour', y='visits', ax=ax)
ax.set_title('Visits per Hour')
ax.set_xlabel('Hour')
ax.set_ylabel('Visits')
visits_per_hour_img = plot_to_base64(fig)
plt.close(fig)

# Plot top bots
fig, ax = plt.subplots(figsize=(12, 6))
sns.barplot(x=results['bots_per_name'].index,
            y=results['bots_per_name'].values, ax=ax)
ax.set_title('Top Bots')
ax.set_xlabel('Bot Name')
ax.set_ylabel('Visits')
ax.set_xticklabels(ax.get_xticklabels(), rotation=45)
top_bots_img = plot_to_base64(fig)
plt.close(fig)

# Plot device distribution
fig, ax = plt.subplots(figsize=(12, 6))
results['device_distribution'].plot(kind='pie', autopct='%1.1f%%', ax=ax)
ax.set_title('Device Distribution')
device_distribution_img = plot_to_base64(fig)
plt.close(fig)

# Plot browser distribution
fig, ax = plt.subplots(figsize=(12, 6))
results['browser_distribution'].plot(kind='pie', autopct='%1.1f%%', ax=ax)
ax.set_title('Browser Distribution')
browser_distribution_img = plot_to_base64(fig)
plt.close(fig)

# Plot OS distribution
fig, ax = plt.subplots(figsize=(12, 6))
results['os_distribution'].plot(kind='pie', autopct='%1.1f%%', ax=ax)
ax.set_title('OS Distribution')
os_distribution_img = plot_to_base64(fig)
plt.close(fig)

# Plot top referrers
fig, ax = plt.subplots(figsize=(12, 6))
sns.barplot(x=results['top_referrers'].index,
            y=results['top_referrers'].values, ax=ax)
ax.set_title('Top Referrers')
ax.set_xlabel('Referrer')
ax.set_ylabel('Visits')
ax.set_xticklabels(ax.get_xticklabels(), rotation=45)
top_referrers_img = plot_to_base64(fig)
plt.close(fig)

# Plot top URLs
fig, ax = plt.subplots(figsize=(12, 6))
sns.barplot(x=results['top_urls'].index, y=results['top_urls'].values, ax=ax)
ax.set_title('Top URLs')
ax.set_xlabel('URL')
ax.set_ylabel('Visits')
ax.set_xticklabels(ax.get_xticklabels(), rotation=45)
top_urls_img = plot_to_base64(fig)
plt.close(fig)

# Plot session durations
session_durations = [duration for durations in results['session_durations'].values()
                     for duration in durations]
fig, ax = plt.subplots(figsize=(12, 6))
sns.histplot(session_durations, bins=30, ax=ax)
ax.set_title('Session Durations (minutes)')
ax.set_xlabel('Duration (minutes)')
ax.set_ylabel('Frequency')
session_durations_img = plot_to_base64(fig)
plt.close(fig)

# Generate HTML report


def generate_html_report(results):
    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Log Analysis Report</title>
    <link href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    <div class="container mt-5">
        <h1 class="text-center mb-4">Log Analysis Report</h1>

        <div class="row mb-4">
            <div class="col-md-6">
                <h2>Visits per Day</h2>
                <img src="data:image/png;base64,{visits_per_day_img}" class="img-fluid" alt="Visits per Day">
            </div>
            <div class="col-md-6">
                <h2>Visits per Hour</h2>
                <img src="data:image/png;base64,{visits_per_hour_img}" class="img-fluid" alt="Visits per Hour">
            </div>
        </div>

        <div class="row mb-4">
            <div class="col-md-6">
                <h2>Top Bots</h2>
                <img src="data:image/png;base64,{top_bots_img}" class="img-fluid" alt="Top Bots">
            </div>
            <div class="col-md-6">
                <h2>Device Distribution</h2>
                <img src="data:image/png;base64,{device_distribution_img}" class="img-fluid" alt="Device Distribution">
            </div>
        </div>

        <div class="row mb-4">
            <div class="col-md-6">
                <h2>Browser Distribution</h2>
                <img src="data:image/png;base64,{browser_distribution_img}" class="img-fluid" alt="Browser Distribution">
            </div>
            <div class="col-md-6">
                <h2>OS Distribution</h2>
                <img src="data:image/png;base64,{os_distribution_img}" class="img-fluid" alt="OS Distribution">
            </div>
        </div>

        <div class="row mb-4">
            <div class="col-md-6">
                <h2>Top Referrers</h2>
                <img src="data:image/png;base64,{top_referrers_img}" class="img-fluid" alt="Top Referrers">
            </div>
            <div class="col-md-6">
                <h2>Top URLs</h2>
                <img src="data:image/png;base64,{top_urls_img}" class="img-fluid" alt="Top URLs">
            </div>
        </div>

        <div class="row mb-4">
            <div class="col-md-12">
                <h2>Session Durations</h2>
                <img src="data:image/png;base64,{session_durations_img}" class="img-fluid" alt="Session Durations">
            </div>
        </div>

        <div class="row mb-4">
            <div class="col-md-12">
                <h2>Summary</h2>
                <p><strong>Visits per Day:</strong></p>
                <pre>{results['visits_per_day']}</pre>
                <p><strong>Visits per Hour:</strong></p>
                <pre>{results['visits_per_hour']}</pre>
                <p><strong>Top Bots:</strong></p>
                <pre>{results['bots_per_name']}</pre>
                <p><strong>Top Referrers:</strong></p>
                <pre>{results['top_referrers']}</pre>
                <p><strong>Top URLs:</strong></p>
                <pre>{results['top_urls']}</pre>
                <p><strong>Device Distribution:</strong></p>
                <pre>{results['device_distribution']}</pre>
                <p><strong>Browser Distribution:</strong></p>
                <pre>{results['browser_distribution']}</pre>
                <p><strong>OS Distribution:</strong></p>
                <pre>{results['os_distribution']}</pre>
                <p><strong>Error Rates:</strong> {results['error_rates']}</p>
            </div>
        </div>
    </div>
</body>
</html>
    """
    with open(os.path.join(output_dir, 'log_analysis_report.html'), 'w') as f:
        f.write(html_content)

    # Convert HTML to Markdown
    h = html2text.HTML2Text()
    h.ignore_links = False
    markdown_content = h.handle(html_content)

    with open(os.path.join(output_dir, 'log_analysis_report.md'), 'w') as f:
        f.write(markdown_content)


generate_html_report(results)
