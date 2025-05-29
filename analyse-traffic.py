import argparse
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
import markdown
import base64
import subprocess
import logging
import xml.etree.ElementTree as ET
from markdown.treeprocessors import Treeprocessor
from markdown.extensions import Extension

# Configure logging settings
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('log_analysis.log'),  # Log to a file
        logging.StreamHandler()  # Log to console
    ]
)

def create_timestamped_subfolder(base_dir, period=None):
    now = datetime.now()
    if period == 'w':
        folder_name = f"w-{now.strftime('%Y-%m-%d')}"
    elif period == 'm':
        folder_name = f"m-{now.strftime('%Y-%m')}"
    elif period == 'y':
        folder_name = f"y-{now.strftime('%Y')}"
    else:
        folder_name = now.strftime('%Y-%m-%d')

    output_dir = os.path.join(base_dir, folder_name)
    os.makedirs(output_dir, exist_ok=True)
    logging.info("Created directory: %s", output_dir)
    return output_dir

base_output_dir = 'output'
if not os.path.exists(base_output_dir):
    os.makedirs(base_output_dir, exist_ok=True)
    logging.info("Created base output directory: %s", base_output_dir)

parser = argparse.ArgumentParser(description='Analyze log files.')
parser.add_argument('--period', type=str, choices=['w', 'm', 'y'], default='w',
                    help='Period for the cron job: w (weekly), m (monthly), y (yearly)')
parser.add_argument('--logpath', type=str, default=None,
                    help='Path to the log file to analyze (required)')
args = parser.parse_args()

if not args.logpath:
    logging.error("Log path argument is missing.")
    raise ValueError("You must provide --logpath argument pointing to the log file")

output_dir = create_timestamped_subfolder(base_output_dir, period=args.period)

def parse_log_line(line):
    match = re.match(
        r'(?P<ip>\d+\.\d+\.\d+\.\d+) - - \[(?P<timestamp>.*?)\] "(?:GET|POST) (?P<url>\S+) HTTP/\d\.\d" \d+ \d+ "(?P<referrer>.*?)" "(?P<user_agent>.*?)"',
        line
    )
    if not match:
        return None

    data = match.groupdict()
    data['datetime'] = datetime.strptime(
        data['timestamp'], '%d/%b/%Y:%H:%M:%S %z')
    data['is_bot'], data['bot_name'] = detect_bot(data['user_agent'])
    return data

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

def analyze_log(file_path, period='w'):
    logging.info("Analyzing log file: %s", file_path)
    records = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            if 'api_key' in line.lower():
                continue
            parsed = parse_log_line(line)
            if parsed:
                records.append(parsed)

    df = pd.DataFrame(records)
    if df.empty:
        logging.warning("No valid records found in log file.")
        return {}

    now = datetime.now(pytz.UTC)
    if period == 'w':
        cutoff_date = now - timedelta(weeks=1)
    elif period == 'm':
        cutoff_date = now - timedelta(days=30)
    elif period == 'y':
        cutoff_date = now - timedelta(days=365)
    else:
        raise ValueError("Invalid period. Must be one of 'w', 'm', or 'y'.")

    df = df[df['datetime'] >= cutoff_date]

    df = enrich_user_agent(df)
    df['visit_id'] = df['ip'].astype(
        str) + df['datetime'].dt.floor('1H').astype(str)
    unique_visits = df.drop_duplicates(subset=['visit_id'])

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

    session_durations = defaultdict(list)
    for ip, group in unique_visits.groupby('ip'):
        group = group.sort_values('datetime')
        durations = group['datetime'].diff().dt.total_seconds() / 60
        session_durations[ip].extend(durations.dropna().tolist())

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
    plot_path = os.path.join(output_dir, filename)
    fig.savefig(plot_path)
    plt.close(fig)
    logging.info("Saved plot: %s", plot_path)

results = analyze_log(args.logpath, period=args.period)

visits_per_day_df = results['visits_per_day'].reset_index()
visits_per_day_df.columns = ['date', 'visits']
fig, ax = plt.subplots(figsize=(12, 6))
sns.lineplot(data=visits_per_day_df, x='date', y='visits', ax=ax)
ax.set_title('Visits per Day')
ax.set_xlabel('Date')
ax.set_ylabel('Visits')
save_plot(fig, 'visits_per_day.png')

visits_per_hour_df = results['visits_per_hour'].reset_index()
visits_per_hour_df.columns = ['hour', 'visits']
fig, ax = plt.subplots(figsize=(12, 6))
sns.lineplot(data=visits_per_hour_df, x='hour', y='visits', ax=ax)
ax.set_title('Visits per Hour')
ax.set_xlabel('Hour')
ax.set_ylabel('Visits')
save_plot(fig, 'visits_per_hour.png')

fig, ax = plt.subplots(figsize=(12, 6))
sns.barplot(x=results['bots_per_name'].index,
            y=results['bots_per_name'].values, ax=ax)
ax.set_title('Top Bots')
ax.set_xlabel('Bot Name')
ax.set_ylabel('Visits')
ax.set_xticklabels(ax.get_xticklabels(), rotation=45)
save_plot(fig, 'top_bots.png')

fig, ax = plt.subplots(figsize=(12, 6))
results['device_distribution'].plot(kind='pie', autopct='%1.1f%%', ax=ax)
ax.set_title('Device Distribution')
save_plot(fig, 'device_distribution.png')

fig, ax = plt.subplots(figsize=(12, 6))
results['browser_distribution'].plot(kind='pie', autopct='%1.1f%%', ax=ax)
ax.set_title('Browser Distribution')
save_plot(fig, 'browser_distribution.png')

fig, ax = plt.subplots(figsize=(12, 6))
results['os_distribution'].plot(kind='pie', autopct='%1.1f%%', ax=ax)
ax.set_title('OS Distribution')
save_plot(fig, 'os_distribution.png')

fig, ax = plt.subplots(figsize=(12, 6))
sns.barplot(x=results['top_referrers'].index,
            y=results['top_referrers'].values, ax=ax)
ax.set_title('Top Referrers')
ax.set_xlabel('Referrer')
ax.set_ylabel('Visits')
ax.set_xticklabels(ax.get_xticklabels(), rotation=45)
save_plot(fig, 'top_referrers.png')

fig, ax = plt.subplots(figsize=(12, 6))
sns.barplot(x=results['top_urls'].index, y=results['top_urls'].values, ax=ax)
ax.set_title('Top URLs')
ax.set_xlabel('URL')
ax.set_ylabel('Visits')
ax.set_xticklabels(ax.get_xticklabels(), rotation=45)
save_plot(fig, 'top_urls.png')

session_durations = [duration for durations in results['session_durations'].values()
                     for duration in durations]
fig, ax = plt.subplots(figsize=(12, 6))
sns.histplot(session_durations, bins=30, ax=ax)
ax.set_title('Session Durations (minutes)')
ax.set_xlabel('Duration (minutes)')
ax.set_ylabel('Frequency')
save_plot(fig, 'session_durations.png')

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
{results['visits_per_day'].to_frame().to_markdown()}

### Visits per Hour
{results['visits_per_hour'].to_frame().to_markdown()}

### Top Bots
{results['bots_per_name'].to_frame().to_markdown()}

### Top Referrers
{results['top_referrers'].to_frame().to_markdown()}

### Top URLs
{results['top_urls'].to_frame().to_markdown()}

### Device Distribution
{results['device_distribution'].to_frame().to_markdown()}

### Browser Distribution
{results['browser_distribution'].to_frame().to_markdown()}

### OS Distribution
{results['os_distribution'].to_frame().to_markdown()}

### Error Rates
{results['error_rates']}
"""
    report_path = os.path.join(output_dir, 'log_analysis_report.md')
    with open(report_path, 'w') as f:
        f.write(markdown_content)
    logging.info("Generated markdown report: %s", report_path)

generate_markdown_report(results)

class InlineImageProcessor(Treeprocessor):
    def run(self, root):
        base_url = f"https://raw.githubusercontent.com/L-Yvelin/loucantou/refs/heads/main/output/{os.path.basename(output_dir)}/"
        for img in root.iter('img'):
            src = img.get('src')
            clean_src = src.lstrip('./').lstrip('/')
            img.set('src', base_url + clean_src)

class Base64ImageExtension(Extension):
    def extendMarkdown(self, md):
        md.treeprocessors.register(
            InlineImageProcessor(md), 'inline_image', 15)

def generate_html_report():
    markdown_path = os.path.join(output_dir, 'log_analysis_report.md')
    with open(markdown_path, 'r') as f:
        md_text = f.read()

    md = markdown.Markdown(extensions=[Base64ImageExtension(), 'markdown.extensions.tables'])
    html = md.convert(md_text)

    html_report_path = os.path.join(output_dir, 'log_analysis_report.html')
    with open(html_report_path, 'w') as f:
        f.write(html)
    logging.info("Generated HTML report: %s", html_report_path)

generate_html_report()

# Log the list of files in the new directory
logging.info("Listing files in the directory: %s", output_dir)
result = subprocess.run(['ls', output_dir], capture_output=True, text=True)
logging.info("Files in directory:\n%s", result.stdout)
