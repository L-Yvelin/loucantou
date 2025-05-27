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
import shutil

# Ensure the output directory exists and is empty
output_dir = 'output'
if os.path.exists(output_dir):
    shutil.rmtree(output_dir)
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

def save_plot(fig, filename):
    fig.savefig(os.path.join(output_dir, filename))
    plt.close(fig)

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
save_plot(fig, 'visits_per_day.png')

# Plot visits per hour
visits_per_hour_df = results['visits_per_hour'].reset_index()
visits_per_hour_df.columns = ['hour', 'visits']
fig, ax = plt.subplots(figsize=(12, 6))
sns.lineplot(data=visits_per_hour_df, x='hour', y='visits', ax=ax)
ax.set_title('Visits per Hour')
ax.set_xlabel('Hour')
ax.set_ylabel('Visits')
save_plot(fig, 'visits_per_hour.png')

# Plot top bots
fig, ax = plt.subplots(figsize=(12, 6))
sns.barplot(x=results['bots_per_name'].index,
            y=results['bots_per_name'].values, ax=ax)
ax.set_title('Top Bots')
ax.set_xlabel('Bot Name')
ax.set_ylabel('Visits')
ax.set_xticklabels(ax.get_xticklabels(), rotation=45)
save_plot(fig, 'top_bots.png')

# Plot device distribution
fig, ax = plt.subplots(figsize=(12, 6))
results['device_distribution'].plot(kind='pie', autopct='%1.1f%%', ax=ax)
ax.set_title('Device Distribution')
save_plot(fig, 'device_distribution.png')

# Plot browser distribution
fig, ax = plt.subplots(figsize=(12, 6))
results['browser_distribution'].plot(kind='pie', autopct='%1.1f%%', ax=ax)
ax.set_title('Browser Distribution')
save_plot(fig, 'browser_distribution.png')

# Plot OS distribution
fig, ax = plt.subplots(figsize=(12, 6))
results['os_distribution'].plot(kind='pie', autopct='%1.1f%%', ax=ax)
ax.set_title('OS Distribution')
save_plot(fig, 'os_distribution.png')

# Plot top referrers
fig, ax = plt.subplots(figsize=(12, 6))
sns.barplot(x=results['top_referrers'].index,
            y=results['top_referrers'].values, ax=ax)
ax.set_title('Top Referrers')
ax.set_xlabel('Referrer')
ax.set_ylabel('Visits')
ax.set_xticklabels(ax.get_xticklabels(), rotation=45)
save_plot(fig, 'top_referrers.png')

# Plot top URLs
fig, ax = plt.subplots(figsize=(12, 6))
sns.barplot(x=results['top_urls'].index, y=results['top_urls'].values, ax=ax)
ax.set_title('Top URLs')
ax.set_xlabel('URL')
ax.set_ylabel('Visits')
ax.set_xticklabels(ax.get_xticklabels(), rotation=45)
save_plot(fig, 'top_urls.png')

# Plot session durations
session_durations = [duration for durations in results['session_durations'].values()
                     for duration in durations]
fig, ax = plt.subplots(figsize=(12, 6))
sns.histplot(session_durations, bins=30, ax=ax)
ax.set_title('Session Durations (minutes)')
ax.set_xlabel('Duration (minutes)')
ax.set_ylabel('Frequency')
save_plot(fig, 'session_durations.png')

# Generate Markdown report
def generate_markdown_report(results):
    markdown_content = f"""
# Log Analysis Report

## Visits per Day
![Visits per Day](./visits_per_day.png)

## Visits per Hour
![Visits per Hour](./visits_per_hour.png)

## Top Bots
![Top Bots](./top_bots.png)

## Device Distribution
![Device Distribution](./device_distribution.png)

## Browser Distribution
![Browser Distribution](./browser_distribution.png)

## OS Distribution
![OS Distribution](./os_distribution.png)

## Top Referrers
![Top Referrers](./top_referrers.png)

## Top URLs
![Top URLs](./top_urls.png)

## Session Durations
![Session Durations](./session_durations.png)

## Summary

### Visits per Day
```
{results['visits_per_day']}
```

### Visits per Hour
```
{results['visits_per_hour']}
```

### Top Bots
```
{results['bots_per_name']}
```

### Top Referrers
```
{results['top_referrers']}
```

### Top URLs
```
{results['top_urls']}
```

### Device Distribution
```
{results['device_distribution']}
```

### Browser Distribution
```
{results['browser_distribution']}
```

### OS Distribution
```
{results['os_distribution']}
```

### Error Rates
```
{results['error_rates']}
```
    """
    with open(os.path.join(output_dir, 'log_analysis_report.md'), 'w') as f:
        f.write(markdown_content)

generate_markdown_report(results)
