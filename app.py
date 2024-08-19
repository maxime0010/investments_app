from flask import Flask, render_template, request, redirect, url_for, flash
import mysql.connector
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Database connection configuration
db_config = {
    'user': 'doadmin',
    'password': os.getenv('MYSQL_MDP'),
    'host': 'db-mysql-nyc3-03005-do-user-4526552-0.h.db.ondigitalocean.com',
    'database': 'defaultdb',
    'port': 25060
}

def fetch_stock_prices(ticker):
    api_key = "KG8F3YBYGVL0HFFU"
    url = f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY_ADJUSTED&symbol={ticker}&outputsize=compact&apikey={api_key}"
    response = requests.get(url)
    data = response.json()
    
    # Process the API response
    prices = []
    if 'Time Series (Daily)' in data:
        time_series = data['Time Series (Daily)']
        for date, values in time_series.items():
            prices.append({
                'date': date,
                'close': float(values['5. adjusted close'])
            })
    
    return prices

def get_latest_portfolio_date():
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(date) FROM portfolio")
    latest_date = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return latest_date

def get_logo_url(ticker):
    # Using Logo.dev to get the logo based on the ticker
    url = f"https://logo.clearbit.com/{ticker}.logo.dev"
    
    response = requests.get(url)
    
    if response.status_code == 200:
        return url
    return None

def get_top_stocks(latest_date):
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT p.ticker, MAX(r.name) as name, a.last_closing_price AS last_price, 
               a.expected_return, a.num_analysts, MAX(p.ranking) as ranking, 
               MAX(a.average_price_target) as target_price
        FROM portfolio p
        JOIN analysis a ON p.ticker = a.ticker
        JOIN ratings r ON r.ticker = p.ticker
        WHERE p.date = %s
        GROUP BY p.ticker, a.last_closing_price, a.expected_return, a.num_analysts
        ORDER BY ranking
        LIMIT 10
    """
    cursor.execute(query, (latest_date,))
    top_stocks = cursor.fetchall()

    for stock in top_stocks:
        stock['logo_url'] = get_logo_url(stock['ticker'])

    cursor.close()
    conn.close()
    return top_stocks





@app.route('/portfolio')
def portfolio():
    latest_date = get_latest_portfolio_date()
    top_stocks = get_top_stocks(latest_date)
    return render_template('portfolio.html', stocks=top_stocks, last_updated=latest_date)

@app.route('/stock/<ticker>')
def stock_detail(ticker):
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT r.name AS stock_name, a.last_closing_price, a.expected_return, 
               a.num_analysts, p.date, p.total_value
        FROM analysis a
        JOIN portfolio p ON a.ticker = p.ticker
        JOIN ratings r ON a.ticker = r.ticker
        WHERE a.ticker = %s
        ORDER BY p.date DESC
    """
    cursor.execute(query, (ticker,))
    stock_details = cursor.fetchall()

    # Fetch stock prices from Alpha Vantage API
    stock_prices = fetch_stock_prices(ticker)

    cursor.execute("""
        SELECT analyst_name, analyst, adjusted_pt_current, action_company
        FROM ratings
        WHERE ticker = %s
        ORDER BY date DESC
    """, (ticker,))
    analysts = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('stock_detail.html', stock=stock_details, prices=stock_prices, analysts=analysts)


@app.route('/performance')
def performance():
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT date, SUM(total_value) as total_portfolio_value
        FROM portfolio
        GROUP BY date
        ORDER BY date
    """
    cursor.execute(query)
    performance_data = cursor.fetchall()

    dates = [entry['date'].strftime('%Y-%m-%d') for entry in performance_data if entry['date'] is not None]
    values = [entry['total_portfolio_value'] for entry in performance_data if entry['total_portfolio_value'] is not None]

    if not dates:
        dates = ["No data"]
    if not values:
        values = [0]

    if len(values) >= 30:
        return_30_days = round(((values[-1] - values[-30]) / values[-30]) * 100, 2)
    else:
        return_30_days = None
    
    if len(values) >= 365:
        return_12_months = round(((values[-1] - values[-365]) / values[-365]) * 100, 2)
    else:
        return_12_months = None

    cursor.close()
    conn.close()

    return render_template('performance.html', dates=dates, values=values, 
                           return_30_days=return_30_days, return_12_months=return_12_months)

@app.route('/subscribe', methods=['POST'])
def subscribe():
    email = request.form['email']

    # Save the email to the database
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()

    try:
        cursor.execute("INSERT INTO subscriptions (email) VALUES (%s)", (email,))
        conn.commit()
        flash('Thank you for subscribing to our newsletter!', 'success')
    except mysql.connector.Error as err:
        flash(f"An error occurred: {err}", 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('portfolio'))

@app.route('/investment-strategy')
def investment_strategy():
    return render_template('investment_strategy.html')


if __name__ == '__main__':
    app.debug = True
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
